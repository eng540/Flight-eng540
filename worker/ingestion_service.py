"""
Enterprise Ingestion Service (v6.2 — STRICT OPENAPI COMPLIANCE)
Strictly compliant with FR24 OpenAPI v1 Specification.

INCLUDES FIXES FROM ARCHITECT AUDIT:
  - enrich_flight_details: chunk_size strictly limited to 15 (P0-V3).
  - enrich_flight_details: param corrected to 'flight_ids' (P0-V2).
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

_HISTORIC_CHUNK_HOURS = 1
_HISTORIC_STEP_SECONDS = 3600

class FlightIngestionService:

    def __init__(self):
        self._db = None
        self.fr24_api_key = settings.FR24_API_KEY
        self.fr24_base_url = settings.FR24_BASE_URL
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

    def _safe_request(self, endpoint: str, params: dict) -> Optional[dict]:
        if not self.fr24_api_key:
            logger.error("[FR24 Auth] FR24_API_KEY is not set in settings.")
            return None

        if time.time() < self.pause_until:
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
                if isinstance(data, list):
                    return data[0] if len(data) > 0 else {}
                return data

            if response.status_code == 429:
                time.sleep(15)
                return None

            if response.status_code == 401:
                self.pause_until = time.time() + 600
                return None

            if response.status_code == 402:
                self.pause_until = time.time() + 3600
                return None

            self.consecutive_failures += 1
            if self.consecutive_failures >= 3:
                self.pause_until = time.time() + 120
            return None

        except requests.exceptions.RequestException:
            return None

    def ingest_live_radar_from_fr24(self, regions) -> Dict[str, int]:
        totals = {"new_aircrafts": 0, "new_sessions": 0, "tracks_recorded": 0, "events": 0, "rejected": 0, "errors": 0}
        db = self._new_db()
        now_ts = int(time.time())
        try:
            for region in regions:
                bounds = f"{region.lamax},{region.lamin},{region.lomin},{region.lomax}"
                data = self._safe_request("/api/live/flight-positions/full", {"bounds": bounds, "limit": 1500})
                if not data: continue
                flights = data.get("data",[])
                payloads =[p for f in flights if (p := self._parse_fr24_position(f, now_ts, region.key))]
                if payloads:
                    batch = EnterpriseDataRouter.process_telemetry_batch(db, payloads)
                    for k in totals: totals[k] += batch.get(k, 0)
        finally:
            db.close()
        return totals

    def ingest_date_range_for_region(self, begin_ts: int, end_ts: int, region, force_reingest: bool = False) -> Dict[str, int]:
        from app.database import SessionLocal
        from app.models import IngestionJob
        from sqlalchemy import and_

        db = SessionLocal()
        totals = {"jobs_processed": 0, "jobs_skipped": 0, "flights_created": 0, "flights_updated": 0}
        bounds = f"{region.lamax},{region.lamin},{region.lomin},{region.lomax}"
        current_ts = begin_ts

        try:
            while current_ts <= end_ts:
                date_str = datetime.utcfromtimestamp(current_ts).strftime("%Y-%m-%d")
                if not force_reingest:
                    if db.query(IngestionJob).filter(and_(IngestionJob.region_key == region.key, IngestionJob.date_str == date_str, IngestionJob.status == "completed")).first():
                        totals["jobs_skipped"] += 1
                        current_ts += _HISTORIC_STEP_SECONDS
                        continue

                job = db.query(IngestionJob).filter(and_(IngestionJob.region_key == region.key, IngestionJob.date_str == date_str)).first()
                if not job:
                    job = IngestionJob(job_type="historic", region_key=region.key, date_str=date_str, lamin=region.lamin, lomin=region.lomin, lamax=region.lamax, lomax=region.lomax, begin_ts=begin_ts, end_ts=end_ts, status="running", started_at=datetime.now(timezone.utc))
                    db.add(job)
                else:
                    job.status = "running"
                db.commit()

                data = self._safe_request("/api/historic/flight-positions/full", {"bounds": bounds, "timestamp": current_ts, "limit": 1500})
                if not data:
                    job.status = "failed"
                    db.commit()
                    current_ts += _HISTORIC_STEP_SECONDS
                    continue

                payloads = [p for f in data.get("data",[]) if (p := self._parse_fr24_position(f, current_ts, region.key))]
                ingested = 0
                if payloads:
                    ingest_db = self._new_db()
                    try:
                        batch = EnterpriseDataRouter.process_telemetry_batch(ingest_db, payloads)
                        ingested = batch.get("new_sessions", 0) + batch.get("tracks_recorded", 0)
                    finally:
                        ingest_db.close()

                job.status = "completed"
                job.flights_ingested = (job.flights_ingested or 0) + ingested
                job.completed_at = datetime.now(timezone.utc)
                db.commit()
                totals["jobs_processed"] += 1
                current_ts += _HISTORIC_STEP_SECONDS
                time.sleep(settings.INGESTION_DELAY_SECONDS)
        finally:
            db.close()
        return totals

    def enrich_flight_details(self, fr24_ids: List[str]) -> Dict[str, Any]:
        if not fr24_ids: return {"enriched": 0, "errors": 0}
        from app.database import SessionLocal
        from app.models import FactFlightSession, DimGeography

        # 🚨 FIX P0-V3: Chunk size strictly limited to 15 (OpenAPI Spec limit)
        chunk_size = 15
        enriched = 0
        errors = 0
        db = SessionLocal()

        try:
            for i in range(0, len(fr24_ids), chunk_size):
                chunk = fr24_ids[i : i + chunk_size]
                ids_param = ",".join(chunk)

                # 🚨 FIX P0-V2: Parameter must be flight_ids (plural)
                data = self._safe_request(
                    "/api/flight-summary/full",
                    {"flight_ids": ids_param, "limit": len(chunk)},
                )
                if not data:
                    errors += len(chunk)
                    continue

                for summary in data.get("data",[]):
                    fr24_id = summary.get("fr24_id")
                    if not fr24_id: continue
                    session = db.query(FactFlightSession).filter(FactFlightSession.fr24_id == fr24_id).first()
                    if not session: continue

                    if summary.get("orig_icao"):
                        if dep := db.query(DimGeography).filter(DimGeography.icao_code == summary["orig_icao"]).first():
                            session.dep_airport_id = dep.id
                    if summary.get("dest_icao_actual") or summary.get("dest_icao"):
                        if arr := db.query(DimGeography).filter(DimGeography.icao_code == (summary.get("dest_icao_actual") or summary.get("dest_icao"))).first():
                            session.arr_airport_id = arr.id
                    if summary.get("datetime_takeoff"):
                        try: session.actual_takeoff_ts = datetime.fromisoformat(summary["datetime_takeoff"].replace("Z", "+00:00"))
                        except ValueError: pass
                    if summary.get("datetime_landed"):
                        try: session.actual_landing_ts = datetime.fromisoformat(summary["datetime_landed"].replace("Z", "+00:00"))
                        except ValueError: pass
                    if summary.get("actual_distance"):
                        session.total_distance_km = float(summary["actual_distance"])
                    if summary.get("flight_ended"):
                        session.flight_status = "landed"
                    enriched += 1
                db.commit()
                time.sleep(1)
        finally:
            db.close()
        return {"enriched": enriched, "errors": errors}

    def fetch_historical_track(self, fr24_id: str) -> Optional[List[Dict]]:
        data = self._safe_request("/api/flight-tracks", {"flight_id": fr24_id})
        if not data: return None
        tracks_raw = data.get("tracks",[]) if isinstance(data, dict) else []
        result =[]
        for point in tracks_raw:
            ts_str = point.get("timestamp")
            if not ts_str: continue
            try: dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except ValueError: continue
            result.append({
                "timestamp": dt, "lat": point.get("lat"), "lon": point.get("lon"),
                "alt_ft": point.get("alt"), "gspeed_kts": point.get("gspeed"),
                "vspeed_fpm": point.get("vspeed"), "heading_deg": point.get("track"),
            })
        return result

    def cleanup_old_data(self, days: int) -> int:
        if days <= 0: return 0
        from app.database import SessionLocal
        from app.models import FactFlightSession, CurrentAircraftState, IngestionJob
        from sqlalchemy import and_

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        stale_cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
        job_cutoff = datetime.now(timezone.utc) - timedelta(days=days * 2)

        db = SessionLocal()
        deleted = 0
        try:
            for s in db.query(FactFlightSession).filter(and_(FactFlightSession.last_seen_ts < cutoff, FactFlightSession.flight_status.in_(["landed", "completed"]))).all():
                db.delete(s)
                deleted += 1
            for e in db.query(CurrentAircraftState).filter(CurrentAircraftState.last_updated < stale_cutoff).all():
                db.delete(e)
                deleted += 1
            for j in db.query(IngestionJob).filter(and_(IngestionJob.completed_at < job_cutoff, IngestionJob.status == "completed")).all():
                db.delete(j)
                deleted += 1
            db.commit()
        finally:
            db.close()
        return deleted

    def _parse_fr24_position(self, f: dict, fallback_ts: int, region_key: str) -> Optional[RawIngestionPayload]:
        icao24 = f.get("hex")
        if not icao24: return None
        try: flight_ts = int(datetime.fromisoformat(f.get("timestamp", "").replace("Z", "+00:00")).timestamp())
        except (ValueError, AttributeError, TypeError): flight_ts = fallback_ts

        alt_ft, gspeed, vspeed = f.get("alt"), f.get("gspeed"), f.get("vspeed")
        on_ground = (alt_ft is not None and alt_ft < 100 and gspeed is not None and gspeed < 30)

        return RawIngestionPayload(
            icao24=str(icao24).lower()[:6],
            fr24_id=f.get("fr24_id"),
            callsign=f.get("callsign"),
            flight_number=f.get("flight"),
            registration=f.get("reg"),
            aircraft_type=f.get("type"),
            operator_icao=f.get("operating_as"),
            timestamp=flight_ts,
            longitude=float(f.get("lon", 0)),
            latitude=float(f.get("lat", 0)),
            altitude=float(alt_ft) * 0.3048 if alt_ft is not None else 0.0,
            velocity=float(gspeed) * 1.852 if gspeed is not None else 0.0,
            heading=float(f.get("track", 0)) if f.get("track") is not None else None,
            vspeed_fpm=float(vspeed) if vspeed is not None else None,
            on_ground=on_ground,
            est_departure_airport=f.get("orig_icao"),
            est_arrival_airport=f.get("dest_icao"),
            squawk=f.get("squawk"),
            region_key=region_key,
        )