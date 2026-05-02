"""
Enterprise Ingestion Service (v6.1 — FR24 Termux-Proof)
Strictly compliant with FR24 OpenAPI v1 Specification.

INCLUDES ALL FIXES:
  - fr24_id, flight_number, vspeed_fpm, aircraft_type extraction.
  - on_ground logical physics fix (alt_ft < 100 AND gspeed < 30).
  - operating_as ONLY for airline matching.
  - Real DB cleanup cascade (30-day retention).
  - OpenAPI sync: 'flight_ids' (plural) for summaries.
  - 🛡️ NEW (v6.1): Array-to-Dict Shield for erratic endpoints like /api/flight-tracks
    (discovered via manual curl/termux audit).
"""
import logging
import sys
import os
import time
import requests
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from app.config import settings
from app.schemas import RawIngestionPayload
from app.crud import EnterpriseDataRouter

logger = logging.getLogger(__name__)

# Hours per historic chunk — limits each API call to one-hour window.
# FR24 historic endpoint accepts a single `timestamp` (not a range),
# so we query the midpoint of each hour-sized chunk.
_HISTORIC_CHUNK_HOURS = 1

# FR24 historic endpoint: one snapshot per timestamp.
# We step through the range every N seconds to get coverage.
_HISTORIC_STEP_SECONDS = 3600  # 1 snapshot/hour is enough for analytics


class FlightIngestionService:

    def __init__(self):
        self._db = None
        self.fr24_api_key = settings.FR24_API_KEY
        self.fr24_base_url = settings.FR24_BASE_URL

        # SRE: Circuit Breaker state
        self.consecutive_failures = 0
        self.pause_until = 0.0

    def __enter__(self):
        from app.database import SessionLocal
        self._db = SessionLocal()
        return self

    def __exit__(self, *_):
        if self._db:
            self._db.close()
            self._db = None

    def _new_db(self):
        from app.database import SessionLocal
        return SessionLocal()

    # ─────────────────────────────────────────────────────────────────────────
    # SRE: Resilient HTTP layer + Circuit Breaker
    # ─────────────────────────────────────────────────────────────────────────

    def _safe_request(self, endpoint: str, params: dict) -> Optional[dict]:
        """
        SRE: Resilient HTTP requester — FR24 OpenAPI spec compliant.
        Handles 429 / 401 / 402 with appropriate backpressure.
        Includes Array-to-Dict shield for endpoints like /api/flight-tracks.
        """
        if not self.fr24_api_key:
            logger.error("[FR24 Auth] FR24_API_KEY is not set in settings.")
            return None

        if time.time() < self.pause_until:
            remaining = int(self.pause_until - time.time())
            logger.warning(f"[Circuit Breaker] API paused for {remaining}s. Skipping.")
            return None

        headers = {
            "Accept": "application/json",
            "Accept-Version": "v1",
            "Authorization": f"Bearer {self.fr24_api_key}",
        }
        url = f"{self.fr24_base_url}{endpoint}"

        try:
            response = requests.get(url, headers=headers, params=params, timeout=20)

            if response.status_code == 200:
                self.consecutive_failures = 0
                data = response.json()
                
                # 🛡️ درع الحماية الذي اكتشفناه: 
                # بعض مسارات FR24 (مثل flight-tracks) تعيد مصفوفة بدلاً من كائن.
                # هذا الدرع يحولها لكائن لكي لا ينهار الكود عند استخدام .get()
                if isinstance(data, list):
                    return data[0] if len(data) > 0 else {}
                    
                return data

            if response.status_code == 429:
                logger.warning("[FR24] 429 Rate limit. Sleeping 15s.")
                time.sleep(15)
                return None

            if response.status_code == 401:
                logger.error("[FR24] 401 Unauthorized — invalid token. Pausing 10 min.")
                self.pause_until = time.time() + 600
                return None

            if response.status_code == 402:
                logger.critical("[FR24] 402 Credit limit reached. Pausing 1 hour.")
                self.pause_until = time.time() + 3600
                return None

            logger.error(f"[FR24] HTTP {response.status_code}: {response.text[:200]}")
            self.consecutive_failures += 1
            if self.consecutive_failures >= 3:
                logger.error("[Circuit Breaker] 3 consecutive errors. Pausing 2 min.")
                self.pause_until = time.time() + 120
            return None

        except requests.exceptions.Timeout:
            logger.error(f"[FR24] Request timed out: {url}")
            self.consecutive_failures += 1
            return None
        except requests.exceptions.RequestException as exc:
            logger.error(f"[FR24 Network] {exc}")
            return None

    # ─────────────────────────────────────────────────────────────────────────
    # LIVE INGESTION — /api/live/flight-positions/full
    # ─────────────────────────────────────────────────────────────────────────

    def ingest_live_radar_from_fr24(self, regions) -> Dict[str, int]:
        """
        Sweep all configured regions via FR24 live positions.
        One API call per region → batch-processed via EnterpriseDataRouter.
        """
        totals = {
            "new_aircrafts": 0, "new_sessions": 0,
            "tracks_recorded": 0, "events": 0,
            "rejected": 0, "errors": 0,
        }
        db = self._new_db()
        now_ts = int(time.time())

        try:
            for region in regions:
                logger.info(f"[Live] Scanning {region.name_ar} ({region.key})")

                # FR24 bounds format: "lamax,lamin,lomin,lomax"
                bounds = f"{region.lamax},{region.lamin},{region.lomin},{region.lomax}"
                data = self._safe_request(
                    "/api/live/flight-positions/full",
                    {"bounds": bounds, "limit": 1500},
                )
                if not data:
                    continue

                flights = data.get("data",[])
                if not flights:
                    logger.info(f"[{region.key}] Empty airspace.")
                    continue

                payloads =[]
                for f in flights:
                    payload = self._parse_fr24_position(f, now_ts, region.key)
                    if payload:
                        payloads.append(payload)

                if payloads:
                    batch = EnterpriseDataRouter.process_telemetry_batch(db, payloads)
                    for k in totals:
                        totals[k] += batch.get(k, 0)
                    logger.info(
                        f"[{region.key}] Processed {len(payloads)} flights. Stats: {batch}"
                    )

        except Exception as exc:
            logger.error(f"[Live Radar] Critical error: {exc}", exc_info=True)
            totals["errors"] += 1
        finally:
            db.close()

        return totals

    # ─────────────────────────────────────────────────────────────────────────
    # HISTORIC INGESTION — /api/historic/flight-positions/full
    # ─────────────────────────────────────────────────────────────────────────

    def ingest_date_range_for_region(
        self,
        begin_ts: int,
        end_ts: int,
        region,
        force_reingest: bool = False,
    ) -> Dict[str, int]:
        """
        Ingest historic flight positions for a Unix timestamp range and region.
        """
        from app.database import SessionLocal
        from app.models import IngestionJob
        from sqlalchemy import and_

        db = SessionLocal()
        totals = {
            "jobs_processed": 0,
            "jobs_skipped": 0,
            "flights_created": 0,
            "flights_updated": 0,
        }

        bounds = f"{region.lamax},{region.lamin},{region.lomin},{region.lomax}"
        current_ts = begin_ts

        try:
            while current_ts <= end_ts:
                date_str = datetime.utcfromtimestamp(current_ts).strftime("%Y-%m-%d")

                # Idempotency check — skip completed jobs unless forced
                if not force_reingest:
                    existing = (
                        db.query(IngestionJob)
                        .filter(
                            and_(
                                IngestionJob.region_key == region.key,
                                IngestionJob.date_str == date_str,
                                IngestionJob.status == "completed",
                            )
                        )
                        .first()
                    )
                    if existing:
                        logger.debug(f"[Historic] Skip {date_str}/{region.key} (already done)")
                        totals["jobs_skipped"] += 1
                        current_ts += _HISTORIC_STEP_SECONDS
                        continue

                # Create / update IngestionJob record
                job = (
                    db.query(IngestionJob)
                    .filter(
                        and_(
                            IngestionJob.region_key == region.key,
                            IngestionJob.date_str == date_str,
                        )
                    )
                    .first()
                )
                if not job:
                    job = IngestionJob(
                        job_type="historic",
                        region_key=region.key,
                        date_str=date_str,
                        lamin=region.lamin,
                        lomin=region.lomin,
                        lamax=region.lamax,
                        lomax=region.lomax,
                        begin_ts=begin_ts,
                        end_ts=end_ts,
                        status="running",
                        started_at=datetime.now(timezone.utc),
                    )
                    db.add(job)
                else:
                    job.status = "running"
                    job.started_at = datetime.now(timezone.utc)
                db.commit()
                db.refresh(job)

                logger.info(f"[Historic] Fetching {date_str} @ {region.key} ts={current_ts}")

                data = self._safe_request(
                    "/api/historic/flight-positions/full",
                    {"bounds": bounds, "timestamp": current_ts, "limit": 1500},
                )

                if not data:
                    job.status = "failed"
                    job.error_message = "API returned no data (circuit breaker or quota)"
                    db.commit()
                    current_ts += _HISTORIC_STEP_SECONDS
                    continue

                flights = data.get("data",[])
                payloads =[]
                for f in flights:
                    payload = self._parse_fr24_position(f, current_ts, region.key)
                    if payload:
                        payloads.append(payload)

                ingested = 0
                if payloads:
                    ingest_db = self._new_db()
                    try:
                        batch = EnterpriseDataRouter.process_telemetry_batch(ingest_db, payloads)
                        ingested = batch.get("new_sessions", 0) + batch.get("tracks_recorded", 0)
                        totals["flights_created"] += batch.get("new_sessions", 0)
                        totals["flights_updated"] += batch.get("tracks_recorded", 0)
                    finally:
                        ingest_db.close()

                # Mark job done
                job.status = "completed"
                job.flights_ingested = (job.flights_ingested or 0) + ingested
                job.records_processed = (job.records_processed or 0) + len(payloads)
                job.completed_at = datetime.now(timezone.utc)
                db.commit()

                totals["jobs_processed"] += 1
                logger.info(
                    f"[Historic] {date_str}/{region.key} — {len(payloads)} positions ingested"
                )

                current_ts += _HISTORIC_STEP_SECONDS
                # Polite delay between historic API calls
                time.sleep(settings.INGESTION_DELAY_SECONDS)

        except Exception as exc:
            logger.error(f"[Historic] Unhandled error: {exc}", exc_info=True)
        finally:
            db.close()

        return totals

    # ─────────────────────────────────────────────────────────────────────────
    # ENRICHMENT — /api/flight-summary/full
    # ─────────────────────────────────────────────────────────────────────────

    def enrich_flight_details(self, fr24_ids: List[str]) -> Dict[str, Any]:
        """
        Fetch full flight summary for a list of fr24_ids.
        Uses /api/flight-summary/full → FlightSummaryFull schema.
        """
        if not fr24_ids:
            return {"enriched": 0, "errors": 0}

        from app.database import SessionLocal
        from app.models import FactFlightSession, DimGeography
        from sqlalchemy import and_

        # FR24 accepts up to 100 IDs per call
        chunk_size = 100
        enriched = 0
        errors = 0

        db = SessionLocal()
        try:
            for i in range(0, len(fr24_ids), chunk_size):
                chunk = fr24_ids[i : i + chunk_size]
                ids_param = ",".join(chunk)

                # ✅ هنا تم إصلاح flight_id لتصبح flight_ids (للجمع)
                data = self._safe_request(
                    "/api/flight-summary/full",
                    {"flight_ids": ids_param, "limit": len(chunk)},
                )
                if not data:
                    errors += len(chunk)
                    continue

                for summary in data.get("data",[]):
                    fr24_id = summary.get("fr24_id")
                    if not fr24_id:
                        continue

                    session = (
                        db.query(FactFlightSession)
                        .filter(FactFlightSession.fr24_id == fr24_id)
                        .first()
                    )
                    if not session:
                        continue

                    # Enrich with summary data (FlightSummaryFull fields)
                    if summary.get("orig_icao"):
                        dep = (
                            db.query(DimGeography)
                            .filter(DimGeography.icao_code == summary["orig_icao"])
                            .first()
                        )
                        if dep:
                            session.dep_airport_id = dep.id

                    if summary.get("dest_icao") or summary.get("dest_icao_actual"):
                        arr_icao = summary.get("dest_icao_actual") or summary.get("dest_icao")
                        arr = (
                            db.query(DimGeography)
                            .filter(DimGeography.icao_code == arr_icao)
                            .first()
                        )
                        if arr:
                            session.arr_airport_id = arr.id

                    # Actual takeoff / landing timestamps
                    if summary.get("datetime_takeoff"):
                        try:
                            session.actual_takeoff_ts = datetime.fromisoformat(
                                summary["datetime_takeoff"].replace("Z", "+00:00")
                            )
                        except (ValueError, AttributeError):
                            pass

                    if summary.get("datetime_landed"):
                        try:
                            session.actual_landing_ts = datetime.fromisoformat(
                                summary["datetime_landed"].replace("Z", "+00:00")
                            )
                        except (ValueError, AttributeError):
                            pass

                    if summary.get("actual_distance"):
                        session.total_distance_km = float(summary["actual_distance"])

                    if summary.get("flight_ended"):
                        session.flight_status = "landed"

                    enriched += 1

                db.commit()
                time.sleep(1)  # polite delay between enrichment chunks

        except Exception as exc:
            logger.error(f"[Enrich] Error: {exc}", exc_info=True)
            errors += 1
        finally:
            db.close()

        logger.info(f"[Enrich] Enriched {enriched} sessions, errors={errors}")
        return {"enriched": enriched, "errors": errors}

    # ─────────────────────────────────────────────────────────────────────────
    # TRACK FETCHING — /api/flight-tracks
    # ─────────────────────────────────────────────────────────────────────────

    def fetch_historical_track(self, fr24_id: str) -> Optional[List[Dict]]:
        """
        Fetch full trajectory for a given fr24_id.
        """
        # مسار مسارات الرحلة يستخدم flight_id بصيغة المفرد حسب OpenAPI
        data = self._safe_request("/api/flight-tracks", {"flight_id": fr24_id})
        if not data:
            return None

        # FR24 FlightTracks: {"fr24_id": ..., "tracks": [{timestamp, lat, ...}]}
        tracks_raw = data.get("tracks",[]) if isinstance(data, dict) else []
        if not tracks_raw:
            return []

        result =[]
        for point in tracks_raw:
            ts_str = point.get("timestamp")
            if not ts_str:
                continue
            try:
                dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                continue

            result.append({
                "timestamp": dt,
                "lat": point.get("lat"),
                "lon": point.get("lon"),
                "alt_ft": point.get("alt"),
                "gspeed_kts": point.get("gspeed"),
                "vspeed_fpm": point.get("vspeed"),
                "heading_deg": point.get("track"),
            })

        logger.info(f"[Track] Fetched {len(result)} points for fr24_id={fr24_id}")
        return result

    # ─────────────────────────────────────────────────────────────────────────
    # CLEANUP — 30-day data retention
    # ─────────────────────────────────────────────────────────────────────────

    def cleanup_old_data(self, days: int) -> int:
        """
        Actual deletion of data older than `days`.
        Deletes in dependency order using cascading.
        """
        if days <= 0:
            logger.info("[Cleanup] days=0 — retention disabled, nothing deleted.")
            return 0

        from app.database import SessionLocal
        from app.models import FactFlightSession, CurrentAircraftState, IngestionJob
        from sqlalchemy import and_

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        stale_state_cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
        job_cutoff = datetime.now(timezone.utc) - timedelta(days=days * 2)

        db = SessionLocal()
        deleted_total = 0

        try:
            # 1. Delete old completed flight sessions (TrackTelemetry CASCADE)
            old_sessions = (
                db.query(FactFlightSession)
                .filter(
                    and_(
                        FactFlightSession.last_seen_ts < cutoff,
                        FactFlightSession.flight_status.in_(["landed", "completed"]),
                    )
                )
                .all()
            )
            count = len(old_sessions)
            for session in old_sessions:
                db.delete(session)
            db.flush()
            logger.info(f"[Cleanup] Deleted {count} old flight sessions (+ cascaded tracks)")
            deleted_total += count

            # 2. Remove stale live-state entries (aircraft not seen in 10 min)
            stale = (
                db.query(CurrentAircraftState)
                .filter(CurrentAircraftState.last_updated < stale_state_cutoff)
                .all()
            )
            stale_count = len(stale)
            for entry in stale:
                db.delete(entry)
            db.flush()
            logger.info(f"[Cleanup] Removed {stale_count} stale CurrentAircraftState entries")
            deleted_total += stale_count

            # 3. Remove old completed ingestion job records
            old_jobs = (
                db.query(IngestionJob)
                .filter(
                    and_(
                        IngestionJob.completed_at < job_cutoff,
                        IngestionJob.status == "completed",
                    )
                )
                .all()
            )
            job_count = len(old_jobs)
            for job in old_jobs:
                db.delete(job)
            db.flush()
            logger.info(f"[Cleanup] Purged {job_count} old IngestionJob records")
            deleted_total += job_count

            db.commit()
            logger.info(f"[Cleanup] Total deleted: {deleted_total} rows (cutoff={cutoff.date()})")

        except Exception as exc:
            db.rollback()
            logger.error(f"[Cleanup] Error during cleanup: {exc}", exc_info=True)
        finally:
            db.close()

        return deleted_total

    # ─────────────────────────────────────────────────────────────────────────
    # INTERNAL: FR24 position parser (shared by live + historic)
    # ─────────────────────────────────────────────────────────────────────────

    def _parse_fr24_position(
        self, f: dict, fallback_ts: int, region_key: str
    ) -> Optional[RawIngestionPayload]:
        """
        Parse a single FR24 FlightPositionsFull dict into RawIngestionPayload.
        All field names are exactly as specified in FR24 OpenAPI.
        """
        # FR24 field: hex = ICAO 24-bit transponder address
        icao24 = f.get("hex")
        if not icao24:
            return None

        # ── Timestamp ────────────────────────────────────────────────────────
        ts_str = f.get("timestamp")
        try:
            dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            flight_ts = int(dt.timestamp())
        except (ValueError, AttributeError, TypeError):
            flight_ts = fallback_ts

        # ── Altitude & Speed (FR24 native units) ─────────────────────────────
        alt_ft   = f.get("alt")    # feet AMSL
        gspeed   = f.get("gspeed") # knots
        vspeed   = f.get("vspeed") # ft/min (store as-is)

        # Logic Fix: on_ground = (alt < 100 ft) AND (gspeed < 30 kts)
        on_ground = (
            alt_ft  is not None and alt_ft  < 100 and
            gspeed  is not None and gspeed  < 30
        )

        # Convert to metric for storage
        altitude_m  = float(alt_ft)  * 0.3048 if alt_ft  is not None else None
        velocity_kmh = float(gspeed) * 1.852  if gspeed  is not None else None

        # Business rule: operating_as ONLY
        operator_icao = f.get("operating_as")

        return RawIngestionPayload(
            icao24=str(icao24).lower()[:6],
            fr24_id=f.get("fr24_id"),
            callsign=f.get("callsign"),
            flight_number=f.get("flight"),
            registration=f.get("reg"),
            aircraft_type=f.get("type"),
            operator_icao=operator_icao,
            timestamp=flight_ts,
            longitude=float(f.get("lon", 0)),
            latitude=float(f.get("lat", 0)),
            altitude=altitude_m or 0.0,
            velocity=velocity_kmh or 0.0,
            heading=float(f.get("track", 0)) if f.get("track") is not None else None,
            vspeed_fpm=float(vspeed) if vspeed is not None else None,
            on_ground=on_ground,
            est_departure_airport=f.get("orig_icao"),
            est_arrival_airport=f.get("dest_icao"),
            squawk=f.get("squawk"),
            region_key=region_key,
        )