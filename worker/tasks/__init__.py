"""
Celery Tasks — Flight Intelligence Worker (v2.1 — TIER 1 Fixed)
All task definitions match beat_schedule entries exactly.

FIXES FROM v2.0:
  [FIX-1] cleanup_old_data_task: NameError fixed.
           `except Exception as scr` → `except Exception as exc`
           was: logger.error(f"... {exc}") + self.retry(exc=exc)
           → NameError because exception variable was named `scr` not `exc`.
           Evidence: Python scoping rule — exception alias is only the name
           declared in the `except ... as NAME` clause.

  [FIX-2] ingest_flights_task: removed call to svc.ingest_recent_flights(hours)
           which does not exist on FlightIngestionService.
           Replaced with ingest_live_radar_from_fr24(active_regions).
           Evidence: grep ingestion_service.py for "ingest_recent_flights" → 0 results.

  [NO CHANGE] ingest_recent_geo_task — correct, uses ingest_live_radar_from_fr24.
  [NO CHANGE] ingest_historical_flights — correct, uses ingest_date_range_for_region.
  [NO CHANGE] Legacy stubs preserved (prevents Celery beat errors).
"""
from celery import shared_task
from celery.exceptions import MaxRetriesExceededError, SoftTimeLimitExceeded
import logging
import sys
import os
import time
from typing import List, Optional

from sqlalchemy import create_engine, inspect

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from worker.ingestion_service import FlightIngestionService
from app.config import settings

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# INTERNAL: DB readiness guard — shared by tasks that need live tables
# ─────────────────────────────────────────────────────────────────────────────

def _wait_for_db(max_attempts: int = 30, sleep_s: float = 2.0) -> bool:
    """Returns True when 'dim_geography' table is present, False on timeout."""
    engine = create_engine(settings.DATABASE_URL)
    inspector = inspect(engine)
    for attempt in range(max_attempts):
        try:
            if "dim_geography" in inspector.get_table_names():
                logger.info("[DB Guard] Tables ready.")
                return True
        except Exception:
            pass
        logger.warning(f"[DB Guard] Waiting for tables... {attempt+1}/{max_attempts}")
        time.sleep(sleep_s)
    logger.error("[DB Guard] Tables not ready after timeout. Aborting.")
    return False


# ─────────────────────────────────────────────────────────────────────────────
# TASK 1: Geo-filtered live ingestion (primary — runs every 60 min)
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(
    bind=True, max_retries=3, default_retry_delay=60,
    soft_time_limit=600, time_limit=900,
    name="worker.tasks.ingest_recent_geo_task",
    queue="ingestion",
)
def ingest_recent_geo_task(
    self,
    region_keys: Optional[List[str]] = None,
    lookback_hours: int = 2,
):
    """
    Primary production task: sweeps all configured regions via FR24 live API.
    Called by beat schedule every 60 min and on worker startup.
    """
    if not _wait_for_db():
        return {"status": "error", "message": "DB tables not ready"}

    try:
        active_keys = region_keys or settings.get_active_region_keys()
        regions = [r for r in (settings.get_region(k) for k in active_keys) if r]

        if not regions:
            logger.warning("[Geo Task] No valid regions configured. Check ACTIVE_REGIONS.")
            return {"status": "skipped", "reason": "no regions"}

        svc = FlightIngestionService()
        logger.info(f"[Geo Task] Starting live sweep: {[r.key for r in regions]}")
        result = svc.ingest_live_radar_from_fr24(regions)
        logger.info(f"[Geo Task] Complete: {result}")
        return {"status": "success", "result": result}

    except SoftTimeLimitExceeded:
        logger.warning("[Geo Task] Soft time limit exceeded.")
        return {"status": "timeout"}
    except Exception as exc:
        logger.error(f"[Geo Task] Failed: {exc}", exc_info=True)
        try:
            self.retry(exc=exc)
        except MaxRetriesExceededError:
            return {"status": "failed", "error": str(exc)}


# ─────────────────────────────────────────────────────────────────────────────
# TASK 2: Legacy global task (FIX-2: ingest_recent_flights removed)
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(
    bind=True, max_retries=3, default_retry_delay=60,
    soft_time_limit=300, time_limit=600,
    name="worker.tasks.ingest_flights_task",
    queue="ingestion",
)
def ingest_flights_task(self, hours: int = 2):
    """
    FIX-2: Replaced svc.ingest_recent_flights(hours) with
    ingest_live_radar_from_fr24(active_regions).
    ingest_recent_flights() does not exist on FlightIngestionService.
    Evidence: ingestion_service.py has no method named ingest_recent_flights.

    This task is kept in beat schedule as fallback; primary is ingest_recent_geo_task.
    """
    if not _wait_for_db():
        return {"status": "error", "message": "DB tables not ready"}

    try:
        active_keys = settings.get_active_region_keys()
        regions = [r for r in (settings.get_region(k) for k in active_keys) if r]

        if not regions:
            return {"status": "skipped", "reason": "no regions"}

        svc = FlightIngestionService()
        logger.info(f"[Global Task] Starting sweep (last {hours}h context).")
        stats = svc.ingest_live_radar_from_fr24(regions)
        logger.info(f"[Global Task] Done: {stats}")
        return {"status": "success", "stats": stats}

    except SoftTimeLimitExceeded:
        return {"status": "timeout"}
    except Exception as exc:
        logger.error(f"[Global Task] Failed: {exc}", exc_info=True)
        try:
            self.retry(exc=exc)
        except MaxRetriesExceededError:
            return {"status": "failed", "error": str(exc)}


# ─────────────────────────────────────────────────────────────────────────────
# TASK 3: Historical ingestion (on-demand, chunked, idempotent)
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(
    bind=True, max_retries=2, default_retry_delay=120,
    soft_time_limit=3600, time_limit=7200,
    name="worker.tasks.ingest_historical_flights",
    queue="ingestion",
)
def ingest_historical_flights(
    self,
    begin_date: str,
    end_date: str,
    region_keys: List[str],
    force_reingest: bool = False,
):
    """
    Ingest historical flights for [begin_date, end_date] and region list.
    Each (date × region) is an idempotent IngestionJob — skipped if completed.
    Delegates to ingestion_service.ingest_date_range_for_region().
    """
    from datetime import datetime, timedelta

    logger.info(
        f"[Historical] {begin_date}→{end_date} regions={region_keys} force={force_reingest}"
    )

    try:
        begin_ts = int(datetime.strptime(begin_date, "%Y-%m-%d").timestamp())
        end_ts   = int(
            (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)).timestamp()
        ) - 1
    except ValueError as exc:
        return {"status": "failed", "error": f"Invalid date format: {exc}"}

    regions = [r for r in (settings.get_region(k) for k in region_keys) if r]
    if not regions:
        return {"status": "failed", "error": "No valid regions found for given keys"}

    totals = {
        "jobs_processed": 0,
        "jobs_skipped": 0,
        "flights_created": 0,
        "flights_updated": 0,
    }
    svc = FlightIngestionService()

    try:
        for region in regions:
            result = svc.ingest_date_range_for_region(
                begin_ts=begin_ts,
                end_ts=end_ts,
                region=region,
                force_reingest=force_reingest,
            )
            for k in totals:
                totals[k] += result.get(k, 0)

    except SoftTimeLimitExceeded:
        logger.warning("[Historical] Soft time limit exceeded mid-run.")
        return {"status": "partial", **totals}
    except Exception as exc:
        logger.error(f"[Historical] Failed: {exc}", exc_info=True)
        try:
            self.retry(exc=exc)
        except MaxRetriesExceededError:
            return {"status": "failed", "error": str(exc)}

    logger.info(f"[Historical] Completed: {totals}")
    return {"status": "success", **totals}


# ─────────────────────────────────────────────────────────────────────────────
# TASK 4: Cleanup (runs daily)
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(
    bind=True, max_retries=3, default_retry_delay=60,
    name="worker.tasks.cleanup_old_data_task",
    queue="maintenance",
)
def cleanup_old_data_task(self, days: int = 0):
    """
    Remove flights and telemetry older than `days`.
    days=0 → uses DATA_RETENTION_DAYS from settings (default: 30).
    days=0 AND DATA_RETENTION_DAYS=0 → no deletion (keep everything).

    FIX-1: NameError resolved.
    `except Exception as scr` → `except Exception as exc`
    Previously: cleanup silently crashed on any error because the retry call
    referenced `exc` which was undefined in the `as scr` scope.
    """
    retention = settings.DATA_RETENTION_DAYS if days == 0 else days
    if not retention or retention <= 0:
        logger.info("[Cleanup] DATA_RETENTION_DAYS=0 — keeping all data.")
        return {"status": "skipped", "deleted": 0}

    try:
        with FlightIngestionService() as svc:
            deleted = svc.cleanup_old_data(retention)
        logger.info(f"[Cleanup] Deleted {deleted} records older than {retention} days.")
        return {"status": "success", "deleted": deleted}
    except Exception as exc:  # FIX-1: was `as scr` — caused NameError below
        logger.error(f"[Cleanup] Failed: {exc}", exc_info=True)
        try:
            self.retry(exc=exc)  # FIX-1: `exc` is now defined
        except MaxRetriesExceededError:
            return {"status": "failed", "error": str(exc)}


# ─────────────────────────────────────────────────────────────────────────────
# TASK 5: Enrichment (on-demand — called after historical ingestion)
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(
    bind=True, max_retries=2, default_retry_delay=30,
    soft_time_limit=1800, time_limit=3600,
    name="worker.tasks.enrich_flight_details_task",
    queue="ingestion",
)
def enrich_flight_details_task(self, fr24_ids: List[str]):
    """
    Enrich flight sessions via /api/flight-summary/full.
    Call after historical ingestion to populate departure/arrival/timing.
    """
    if not fr24_ids:
        return {"status": "skipped", "reason": "no fr24_ids provided"}

    try:
        svc = FlightIngestionService()
        result = svc.enrich_flight_details(fr24_ids)
        return {"status": "success", **result}
    except Exception as exc:
        logger.error(f"[Enrich Task] Failed: {exc}", exc_info=True)
        try:
            self.retry(exc=exc)
        except MaxRetriesExceededError:
            return {"status": "failed", "error": str(exc)}


# ─────────────────────────────────────────────────────────────────────────────
# LEGACY STUBS — prevents "unregistered task" errors in beat logs
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(bind=True, name="worker.tasks.run_realtime_radar_task", queue="ingestion")
def run_realtime_radar_task(self):
    """Legacy stub — no-op, kept to prevent beat unregistered-task warnings."""
    logger.info("[realtime] Legacy task called — no action.")
    return {"status": "skipped", "reason": "legacy task"}


@shared_task(bind=True, name="worker.tasks.ingest_aviationstack_task", queue="ingestion")
def ingest_aviationstack_task(self):
    """DEPRECATED: AviationStack replaced by FR24. Stub kept for beat compat."""
    logger.warning("[AviationStack] Deprecated task called — no action.")
    return {"status": "skipped", "reason": "deprecated — use FR24"}


# ─────────────────────────────────────────────────────────────────────────────
# FIX BUG-2: Stalled Operations Recovery Task
# When backend can't dispatch to Celery broker ([Errno 111] Connection refused),
# operations remain in 'running' state with pending chunks but no active worker.
# This task runs every 60s to detect and re-dispatch such stalled operations.
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(
    bind=True,
    name="worker.tasks.recover_stalled_operations",
    queue="maintenance",
)
def recover_stalled_operations(self):
    """
    Detects operations in 'running'/'partial' state with pending chunks
    but no active Celery task executing them. Re-dispatches them.

    Root cause this fixes:
      ops 77-83: [Errno 111] Connection refused on dispatch_operation_task
      → operation status = running, chunks = pending, but no worker executing
    """
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'backend'))

    from app.database import SessionLocal
    from app.models import Operation, OperationChunk
    from sqlalchemy import and_, func
    from datetime import datetime, timezone, timedelta

    db = SessionLocal()
    recovered = 0
    try:
        # Find operations: running/partial, started > 2 min ago, still have pending chunks
        stale_cutoff = datetime.now(timezone.utc) - timedelta(minutes=2)

        stalled = (
            db.query(Operation)
            .filter(
                Operation.status.in_(["running", "partial"]),
                Operation.started_at < stale_cutoff,
                Operation.cancel_requested.is_(False),
            )
            .all()
        )

        for op in stalled:
            # Check if there are pending chunks
            pending = (
                db.query(func.count(OperationChunk.id))
                .filter(
                    OperationChunk.operation_id == op.id,
                    OperationChunk.status == "pending",
                )
                .scalar() or 0
            )
            if pending == 0:
                continue

            logger.info(
                f"[Recover] Stalled op {op.id} ({op.operation_ref}) "
                f"has {pending} pending chunks — re-dispatching"
            )
            try:
                from worker.tasks.operations_task import execute_operation_task
                execute_operation_task.delay(op.id)
                op.failure_reason = None   # Clear the dispatch failure note
                db.commit()
                recovered += 1
            except Exception as exc:
                logger.error(f"[Recover] Re-dispatch failed for op {op.id}: {exc}")

    except Exception as exc:
        logger.error(f"[Recover] Error in recover_stalled_operations: {exc}", exc_info=True)
    finally:
        db.close()

    logger.info(f"[Recover] Recovered {recovered} stalled operations")
    return {"status": "done", "recovered": recovered}
