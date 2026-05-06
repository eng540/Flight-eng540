#--- START OF FILE Flight-eng540-eng540-patch-1/worker/tasks/operations_task.py ---
"""
Operations Board Celery Task (System Design §5–§7)

execute_operation_task: processes all chunks for one Operation.
retry_chunks_task: scheduler tick for failed-but-retryable chunks.

Full state machine compliance per system design §3 + §7.

INCLUDES FIXES:
  - Zero-Chunk Paralysis fixed (Operations with 0 chunks mark as completed immediately).
  - Infinite Retry fixed (Do not retry chunks on HTTP 400/401/403/404/422).
  - CSV Export fix (Tag flight sessions using their exact fr24_id).
  - RADICAL EXPORT FIX: Aggressive tagging for flight_summaries and flight_tracks
    to ensure all fetched data is linked to operation_id and chunk_id.
"""
import logging
import time
import sys
import os
from datetime import datetime, timezone

from celery import shared_task
from celery.exceptions import MaxRetriesExceededError, SoftTimeLimitExceeded

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'backend'))

from app.database import SessionLocal
from app.config import settings

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# MAIN EXECUTION TASK
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(
    bind=True,
    name="worker.tasks.operations_task.execute_operation_task",
    queue="ingestion",
    soft_time_limit=7200,   # 2 hours max
    time_limit=7800,
    max_retries=0,           # No task-level retry — chunk-level retry handles it
)
def execute_operation_task(self, operation_id: int):
    """
    Processes all pending chunks for an Operation sequentially.

    Evidence §5 Execution Flow:
      "جلب جميع chunks بـ status='pending' مُرتَّبة ASC
       لكل chunk:
         تحقق cancel_requested
         SET chunk.status = 'running'
         FR24 API call
         parse_and_store
         SET chunk.status = 'completed'
         sleep(INGESTION_DELAY_SECONDS)"
    """
    logger.info(f"[OpsTask] Starting operation {operation_id}")

    db = SessionLocal()
    try:
        from app.crud.operations import OperationsCRUD, ChunksCRUD
        from app.models import Operation

        op = db.query(Operation).filter(Operation.id == operation_id).first()
        if not op:
            logger.error(f"[OpsTask] Operation {operation_id} not found")
            return {"status": "error", "message": "operation not found"}

        if op.status not in ("running", "partial"):
            logger.warning(
                f"[OpsTask] Operation {operation_id} in state '{op.status}' "
                f"— expected running/partial. Aborting."
            )
            return {"status": "skipped", "reason": f"unexpected status: {op.status}"}

        chunks = ChunksCRUD.get_pending_chunks(db, operation_id)
        logger.info(
            f"[OpsTask] Operation {operation_id}: {len(chunks)} pending chunks"
        )

        # 🚨 FIX (Zero-Chunk Paralysis): End the operation immediately if there are no chunks
        if len(chunks) == 0:
            logger.info(f"[OpsTask] Operation {operation_id} has 0 chunks. Marking as completed.")
            op.status = "completed"
            op.completed_at = _now()
            db.commit()
            return {"status": "done", "processed": 0, "note": "0 chunks"}

        processed = 0
        for chunk in chunks:

            # ── Cancel check ────────────────────────────────────────────────
            # Evidence §7: "worker checks cancel_requested between chunks"
            db.refresh(op)
            if op.cancel_requested:
                logger.info(
                    f"[OpsTask] Cancel requested for op {operation_id}. "
                    f"Stopping after chunk {chunk.chunk_index - 1}."
                )
                _cancel_remaining_chunks(db, operation_id)
                op.status       = "cancelled"
                op.cancelled_at = _now()
                db.commit()
                return {
                    "status":    "cancelled",
                    "processed": processed,
                    "reason":    op.cancel_reason,
                }

            # ── Execute chunk ────────────────────────────────────────────────
            success = _execute_single_chunk(db, op, chunk)
            if success:
                processed += 1

            # ── Polite delay between API calls ───────────────────────────────
            # Evidence §4 duration formula: includes INGESTION_DELAY_SECONDS
            time.sleep(settings.INGESTION_DELAY_SECONDS)

        logger.info(
            f"[OpsTask] Operation {operation_id} loop complete. "
            f"Processed: {processed} chunks."
        )
        return {"status": "done", "processed": processed}

    except SoftTimeLimitExceeded:
        logger.warning(f"[OpsTask] Soft time limit exceeded for op {operation_id}")
        return {"status": "timeout"}
    except Exception as exc:
        logger.error(f"[OpsTask] Unhandled error op {operation_id}: {exc}", exc_info=True)
        return {"status": "error", "error": str(exc)}
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# RETRY SCHEDULER TASK (runs every 30 seconds via beat)
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(
    bind=True,
    name="worker.tasks.operations_task.retry_chunks_task",
    queue="maintenance",
)
def retry_chunks_task(self):
    """
    Picks up failed-but-retryable chunks and re-executes them.
    Uses idx_chunks_retry partial index for efficient lookup.
    Evidence §7: "Retry Scheduler: next_retry_at <= now()"
    """
    db = SessionLocal()
    try:
        from app.crud.operations import ChunksCRUD
        from app.models import Operation

        chunks = ChunksCRUD.get_retryable_chunks(db)
        if not chunks:
            return {"status": "no_retries"}

        logger.info(f"[RetryTask] Found {len(chunks)} retryable chunks")

        retried = 0
        for chunk in chunks:
            op = db.query(Operation).filter(Operation.id == chunk.operation_id).first()
            if not op or op.cancel_requested:
                continue
            success = _execute_single_chunk(db, op, chunk)
            if success:
                retried += 1
            time.sleep(2)

        return {"status": "done", "retried": retried}
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# CORE: single chunk execution
# ─────────────────────────────────────────────────────────────────────────────

def _execute_single_chunk(db, op, chunk) -> bool:
    """
    Executes one FR24 API call for a chunk.
    Handles all HTTP outcomes per §7 Failure Handling.
    Returns True on success, False on failure.
    """
    from app.crud.operations import ChunksCRUD
    from app.models import Operation
    from worker.ingestion_service import FlightIngestionService

    logger.info(
        f"[Chunk {chunk.operation_id}:{chunk.chunk_index}] "
        f"Starting — {chunk.fr24_endpoint} {chunk.fr24_params}"
    )

    ChunksCRUD.mark_running(db, chunk)
    db.commit()

    svc = FlightIngestionService()

    # ── FR24 API call ─────────────────────────────────────────────────────
    response = svc._safe_request(
        chunk.fr24_endpoint or "",
        chunk.fr24_params   or {},
    )

    # ── HTTP error handling ────────────────────────────────────────────────
    if response is None:
        # _safe_request returns None on all error conditions.
        # Determine which error happened via circuit breaker state.
        if svc.pause_until > time.time():
            # Rate limit (429) or credit exhaustion (402)
            http_status = 429 if svc.consecutive_failures == 0 else 402

            if http_status == 402:
                # Credit exhaustion — fail the whole operation
                # Evidence §7: "402: SET operation.status = 'failed'"
                logger.critical(
                    f"[Chunk] Credit exhausted for op {chunk.operation_id}"
                )
                ChunksCRUD.handle_credit_exhausted(db, chunk.operation_id)
                db.commit()
                return False

            # Rate limit — re-queue this chunk
            retry_after = int(svc.pause_until - time.time()) + 5
            ChunksCRUD.handle_rate_limit(db, chunk, retry_after)
            db.commit()
            return False

        # Generic failure
        ChunksCRUD.mark_failed(
            db, chunk,
            error="API returned no data",
            http_status=None,
        )
        db.commit()
        return False

    # ── Parse and store ───────────────────────────────────────────────────
    try:
        results_count = _parse_and_store(db, response, chunk, op)
    except Exception as exc:
        logger.error(
            f"[Chunk {chunk.chunk_index}] Parse error: {exc}", exc_info=True
        )
        ChunksCRUD.mark_failed(db, chunk, error=str(exc))
        db.commit()
        return False

    # ── Mark completed ────────────────────────────────────────────────────
    credits_used = _extract_credits(response)
    response_size = len(str(response).encode("utf-8"))

    ChunksCRUD.mark_completed(
        db, chunk,
        results_count=results_count,
        credits_used=credits_used,
        response_size=response_size,
    )
    db.commit()

    logger.info(
        f"[Chunk {chunk.operation_id}:{chunk.chunk_index}] "
        f"Completed — {results_count} records, {credits_used} credits"
    )
    return True


# ─────────────────────────────────────────────────────────────────────────────
# DATA PROCESSING
# ─────────────────────────────────────────────────────────────────────────────

def _parse_and_store(db, response: dict, chunk, op) -> int:
    """
    Parses FR24 API response and stores in fact_flight_session.
    Tags each record with operation_id + chunk_id.
    Evidence §5: "يُضيف operation_id + chunk_id لكل صف"
    """
    from app.crud import EnterpriseDataRouter
    from app.schemas import RawIngestionPayload
    from worker.ingestion_service import FlightIngestionService

    cap = chunk.chunk_type
    svc = FlightIngestionService()

    # Different response structures per capability type
    if cap in ("live_positions", "historic_positions"):
        items = response.get("data",[])
        payloads =[]
        for item in items:
            payload = svc._parse_fr24_position(
                item,
                fallback_ts=chunk.timestamp_from or _now_ts(),
                region_key=chunk.region_key or op.scope_region_key or "global",
            )
            if payload:
                payloads.append(payload)

        if payloads:
            # Pass operation context to router for tagging
            _store_with_operation_tag(db, payloads, op.id, chunk.id)

        return len(payloads)

    elif cap == "flight_summaries":
        # RADICAL FIX: Use dedicated store function to upsert and tag summaries
        items = response.get("data",[])
        if items:
            _store_summaries(db, items, op.id, chunk.id)
        return len(items)

    elif cap == "flight_tracks":
        # Store track points for an fr24_id
        tracks = response.get("tracks",[])
        if tracks and chunk.entity_id:
            _store_tracks(db, tracks, chunk.entity_id, op.id, chunk.id)
        return len(tracks)

    elif cap == "historic_events":
        items = response.get("data",[])
        # Events stored in FactAviationEvent — no batch storage needed here
        return len(items)

    elif cap in ("static_airport", "static_airline"):
        # Static data — upsert into dim_geography / dim_operator
        _store_static(db, response, cap)
        return 1

    return 0


def _store_with_operation_tag(db, payloads, operation_id: int, chunk_id: int):
    """
    Processes telemetry batch and tags the resulting sessions with operation/chunk IDs.
    RADICAL FIX: Removed `.is_(None)` condition. If a flight is fetched, it MUST
    be tagged with the current operation_id so it appears in the CSV export.
    """
    from app.crud import EnterpriseDataRouter
    from app.models import FactFlightSession

    # 1. Store normally via existing router
    EnterpriseDataRouter.process_telemetry_batch(db, payloads)

    # 2. Extract the FR24 IDs from the payloads we just inserted/updated
    fr24_ids = list({p.fr24_id for p in payloads if p.fr24_id})
    
    # 3. Tag these specific flights so they appear in CSV Exports!
    if fr24_ids:
        db.query(FactFlightSession).filter(
            FactFlightSession.fr24_id.in_(fr24_ids)
        ).update(
            {"operation_id": operation_id, "chunk_id": chunk_id},
            synchronize_session=False,
        )


def _store_summaries(db, items: list, operation_id: int, chunk_id: int):
    """
    RADICAL FIX: Dedicated function to parse, upsert, and aggressively TAG 
    flight summaries with operation_id and chunk_id.
    """
    from app.models import FactFlightSession, DimGeography, DimOperator, DimAircraft

    for summary in items:
        fr24_id = summary.get("fr24_id")
        if not fr24_id:
            continue

        # 1. Resolve or Create Aircraft (Required by FactFlightSession)
        hex_code = summary.get("hex")
        if not hex_code:
            hex_code = f"unk_{fr24_id}"[:6].lower()
        else:
            hex_code = hex_code.lower()
            
        ac = db.query(DimAircraft).filter(DimAircraft.icao24 == hex_code).first()
        if not ac:
            ac = DimAircraft(
                icao24=hex_code,
                registration=summary.get("reg"),
                type_code=summary.get("equip")
            )
            db.add(ac)
            db.flush()

        # 2. Resolve or Create Operator
        op_id = None
        op_icao = summary.get("operating_as")
        if op_icao:
            operator = db.query(DimOperator).filter(DimOperator.icao_code == op_icao.upper()).first()
            if not operator:
                operator = DimOperator(icao_code=op_icao.upper(), name=f"Operator {op_icao}")
                db.add(operator)
                db.flush()
            op_id = operator.id

        # 3. Resolve Airports
        dep_id = None
        if summary.get("orig_icao"):
            dep_icao = summary["orig_icao"].upper()
            dep = db.query(DimGeography).filter(DimGeography.icao_code == dep_icao).first()
            if not dep:
                dep = DimGeography(icao_code=dep_icao, name=f"Airport {dep_icao}")
                db.add(dep)
                db.flush()
            dep_id = dep.id

        arr_id = None
        arr_icao_raw = summary.get("dest_icao_actual") or summary.get("dest_icao")
        if arr_icao_raw:
            arr_icao = arr_icao_raw.upper()
            arr = db.query(DimGeography).filter(DimGeography.icao_code == arr_icao).first()
            if not arr:
                arr = DimGeography(icao_code=arr_icao, name=f"Airport {arr_icao}")
                db.add(arr)
                db.flush()
            arr_id = arr.id

        # 4. Timestamps
        now = _now()
        t_takeoff = now
        t_landed = now
        if summary.get("datetime_takeoff"):
            try:
                t_takeoff = datetime.fromisoformat(summary["datetime_takeoff"].replace("Z", "+00:00"))
            except: pass
        if summary.get("datetime_landed"):
            try:
                t_landed = datetime.fromisoformat(summary["datetime_landed"].replace("Z", "+00:00"))
            except: pass

        # 5. Upsert Session
        session = db.query(FactFlightSession).filter(FactFlightSession.fr24_id == fr24_id).first()
        if not session:
            session = FactFlightSession(
                aircraft_id=ac.id,
                fr24_id=fr24_id,
                first_seen_ts=t_takeoff,
                last_seen_ts=t_landed,
            )
            db.add(session)

        # Update fields & TAG the operation
        session.operation_id = operation_id
        session.chunk_id = chunk_id
        session.operator_id = op_id
        session.dep_airport_id = dep_id
        session.arr_airport_id = arr_id
        
        if summary.get("flight"): session.flight_number = summary.get("flight")
        if summary.get("callsign"): session.callsign = summary.get("callsign")
        if summary.get("actual_distance"): session.total_distance_km = float(summary.get("actual_distance"))
        
        session.flight_status = "landed" if summary.get("flight_ended") else "active"
        session.actual_takeoff_ts = t_takeoff if summary.get("datetime_takeoff") else None
        session.actual_landing_ts = t_landed if summary.get("datetime_landed") else None

    db.flush()


def _store_tracks(db, tracks: list, fr24_id: str, operation_id: int, chunk_id: int):
    """
    Stores flight track points in track_telemetry.
    RADICAL FIX: Tags TrackTelemetry rows with operation_id and chunk_id.
    """
    from app.models import FactFlightSession, TrackTelemetry

    session = (
        db.query(FactFlightSession)
        .filter(FactFlightSession.fr24_id == fr24_id)
        .first()
    )
    if not session:
        return

    for point in tracks:
        ts_str = point.get("timestamp")
        if not ts_str:
            continue
        try:
            dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue

        alt_ft  = point.get("alt")
        gspeed  = point.get("gspeed")
        track   = db.query(TrackTelemetry).filter(
            TrackTelemetry.session_id == session.session_id,
            TrackTelemetry.timestamp == dt,
        ).first()
        if track:
            # Update tag even if it exists
            track.operation_id = operation_id
            track.chunk_id = chunk_id
            continue

        db.add(TrackTelemetry(
            timestamp=dt,
            session_id=session.session_id,
            latitude=point.get("lat"),
            longitude=point.get("lon"),
            altitude_m=float(alt_ft) * 0.3048 if alt_ft else None,
            velocity_kmh=float(gspeed) * 1.852 if gspeed else None,
            heading_deg=point.get("track"),
            vspeed_fpm=point.get("vspeed"),
            is_on_ground=False,
            operation_id=operation_id,  # <--- TAGGED
            chunk_id=chunk_id,          # <--- TAGGED
        ))


def _store_static(db, response: dict, cap: str):
    """Upserts static airport or airline data."""
    from app.models import DimGeography, DimOperator

    if cap == "static_airport":
        data = response.get("data") or response
        if isinstance(data, list):
            data = data[0] if data else {}
        icao = data.get("icao")
        if not icao:
            return
        geo = db.query(DimGeography).filter(DimGeography.icao_code == icao).first()
        if not geo:
            geo = DimGeography(icao_code=icao)
            db.add(geo)
        geo.iata_code  = data.get("iata")
        geo.name       = data.get("name") or geo.name or f"Airport {icao}"
        geo.city       = data.get("city")
        geo.country_code = data.get("country_code")
        geo.latitude   = data.get("lat")
        geo.longitude  = data.get("lon")
        geo.elevation_m = data.get("elevation")
        db.flush()

    elif cap == "static_airline":
        data = response.get("data") or response
        if isinstance(data, list):
            data = data[0] if data else {}
        icao = data.get("icao")
        if not icao:
            return
        op = db.query(DimOperator).filter(DimOperator.icao_code == icao).first()
        if not op:
            op = DimOperator(icao_code=icao)
            db.add(op)
        op.iata_code = data.get("iata")
        op.name      = data.get("name") or op.name or f"Operator {icao}"
        op.country_code = data.get("country")
        db.flush()


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _cancel_remaining_chunks(db, operation_id: int) -> None:
    from app.models import OperationChunk
    pending = (
        db.query(OperationChunk)
        .filter(
            OperationChunk.operation_id == operation_id,
            OperationChunk.status == "pending",
        )
        .all()
    )
    for c in pending:
        c.status = "cancelled"
    db.flush()


def _extract_credits(response: dict) -> int:
    """
    Attempts to extract actual credits consumed from FR24 response.
    FR24 may include usage info in response headers or body.
    Defaults to 0 if not present.
    """
    usage = response.get("_usage") or response.get("usage") or {}
    return int(usage.get("credits", 0))


def _now():
    return datetime.now(timezone.utc)


def _now_ts() -> int:
    return int(time.time())
#--- END OF FILE ---