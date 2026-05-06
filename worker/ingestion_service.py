"""
Enterprise Ingestion Service (v7.0 — Multi-Source Hybrid Engine)
Strictly compliant with FR24 OpenAPI v1, OpenSky Network, and AirLabs v9.

UPGRADES:
  [NEW] ingest_live_radar_from_opensky: Primary free source (1 min interval).
        Uses OpenSkyClient with curl fallback to bypass Cloud IP blocks.
  [NEW] ingest_live_radar_from_airlabs: Secondary free source (1 hour interval).
        Provides highly accurate routing data.
  [UPDATED] FR24 Ingestion: Now tags payloads with data_source="FR24".
  
All sources map to a unified `RawIngestionPayload` and are routed through
`EnterpriseDataRouter` which inherently deduplicates based on `icao24`.
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

        # SRE: Circuit Breaker state for FR24
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
    # SRE: Resilient HTTP layer + Circuit Breaker (FR24)
    # ─────────────────────────────────────────────────────────────────────────

    def _safe_request(self, endpoint: str, params: dict) -> Optional[dict]:
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
                if isinstance(data, list):
                    return data[0] if len(data) > 0 else {}
                return data

            if response.status_code == 429:
                logger.warning("[FR24] 429 Rate limit. Sleeping 15s.")
                time.sleep(15)
                return None

            if response.status_code in (401, 403):
                logger.error(f"[FR24] {response.status_code} Unauthorized. Pausing 10 min.")
                self.pause_until = time.time() + 600
                return None

            if response.status_code == 402:
                logger.critical("[FR24] 402 Credit limit reached. Pausing 1 hour.")
                self.pause_until = time.time() + 3600
                return None

            logger.error(f"[FR24] HTTP {response.status_code}: {response.text[:200]}")
            self.consecutive_failures += 1
            if self.consecutive_failures >= 3:
                self.pause_until = time.time() + 120
            return None

        except requests.exceptions.RequestException as exc:
            logger.error(f"[FR24 Network] {exc}")
            return None

    # ─────────────────────────────────────────────────────────────────────────
    # SOURCE 1: OPENSKY NETWORK (Primary Free Source - High Frequency)
    # ─────────────────────────────────────────────────────────────────────────

    def ingest_live_radar_from_opensky(self, regions) -> Dict[str, int]:
        """
        Fetches live state vectors from OpenSky.
        Uses OpenSkyClient to bypass Cloud IP blocks via curl fallback.
        """
        from worker.opensky_client import OpenSkyClient
        client = OpenSkyClient()
        db = self._new_db()
        now_ts = int(time.time())
        totals = {"new_aircrafts": 0, "new_sessions": 0, "tracks_recorded": 0, "events": 0, "rejected": 0, "errors": 0}

        if client.circuit_is_open:
            logger.warning("[OpenSky] Circuit is OPEN. Skipping ingestion to prevent ban.")
            return totals

        try:
            for region in regions:
                logger.info(f"[OpenSky] Scanning {region.name_ar} ({region.key})")
                raw_data = client.get_state_vectors(
                    lamin=region.lamin, lomin=region.lomin,
                    lamax=region.lamax, lomax=region.lomax
                )
                
                if not raw_data or "states" not in raw_data or not raw_data["states"]:
                    logger.info(f"[OpenSky] [{region.key}] No data or blocked.")
                    continue

                payloads = []
                for state in raw_data["states"]:
                    # OpenSky format: [icao24, callsign, origin_country, time_position, last_contact, lon, lat, baro_alt, on_ground, vel, true_track, vertical_rate, sensors, geo_alt, squawk, spi, position_source]
                    if not state[0] or state[5] is None or state[6] is None:
                        continue 
                    
                    alt_m = float(state[7]) if state[7] is not None else 0.0
                    vel_kmh = float(state[9]) * 3.6 if state[9] is not None else 0.0
                    vspeed_fpm = float(state[11]) * 196.85 if state[11] is not None else None
                    
                    payload = RawIngestionPayload(
                        icao24=str(state[0]).lower()[:6],
                        callsign=str(state[1]).strip() if state[1] else None,
                        origin_country=state[2],
                        timestamp=state[3] or state[4] or now_ts,
                        longitude=float(state[5]),
                        latitude=float(state[6]),
                        altitude=alt_m,
                        velocity=vel_kmh,
                        heading=float(state[10]) if state[10] is not None else None,
                        vspeed_fpm=vspeed_fpm,
                        on_ground=bool(state[8]),
                        squawk=state[14],
                        data_source="OPENSKY",
                        region_key=region.key
                    )
                    payloads.append(payload)

                if payloads:
                    batch = EnterpriseDataRouter.process_telemetry_batch(db, payloads)
                    for k in totals: totals[k] += batch.get(k, 0)
                    logger.info(f"[OpenSky] [{region.key}] Processed {len(payloads)} flights. Stats: {batch}")
                    
                time.sleep(settings.INGESTION_DELAY_SECONDS)
        except Exception as exc:
            logger.error(f"[OpenSky] Error: {exc}", exc_info=True)
            totals["errors"] += 1
        finally:
            db.close()
            
        return totals

    # ─────────────────────────────────────────────────────────────────────────
    # SOURCE 2: AIRLABS (Secondary Free Source - Low Frequency)
    # ─────────────────────────────────────────────────────────────────────────

    def ingest_live_radar_from_airlabs(self, regions) -> Dict[str, int]:
        """
        Fetches live flights from AirLabs.
        Provides highly accurate routing (dep_icao, arr_icao).
        """
        api_key = os.getenv("AIRLABS_API_KEY")
        if not api_key:
            logger.warning("[AirLabs] AIRLABS_API_KEY not set in environment. Skipping.")
            return {}

        db = self._new_db()
        now_ts = int(time.time())
        totals = {"new_aircrafts": 0, "new_sessions": 0, "tracks_recorded": 0, "events": 0, "rejected": 0, "errors": 0}

        try:
            for region in regions:
                logger.info(f"[AirLabs] Scanning {region.name_ar} ({region.key})")
                bbox = f"{region.lamin},{region.lomin},{region.lamax},{region.lomax}"
                url = f"https://airlabs.co/api/v9/flights?api_key={api_key}&bbox={bbox}"
                
                resp = requests.get(url, timeout=15)
                if resp.status_code != 200:
                    logger.error(f"[AirLabs] HTTP {resp.status_code}: {resp.text}")
                    continue
                    
                data = resp.json()
                flights = data.get("response", [])
                if not flights:
                    logger.info(f"[AirLabs] [{region.key}] No data.")
                    continue

                payloads = []
                for f in flights:
                    icao24 = f.get("hex")
                    if not icao24 or f.get("lat") is None or f.get("lng") is None:
                        continue
                        
                    payload = RawIngestionPayload(
                        icao24=str(icao24).lower()[:6],
                        callsign=f.get("flight_iata") or f.get("flight_icao") or f.get("reg_number"),
                        flight_number=f.get("flight_number"),
                        registration=f.get("reg_number"),
                        operator_icao=f.get("airline_icao"),
                        origin_country=f.get("flag"),
                        timestamp=now_ts,
                        longitude=float(f.get("lng")),
                        latitude=float(f.get("lat")),
                        altitude=float(f.get("alt", 0)),
                        velocity=float(f.get("speed", 0)),
                        heading=float(f.get("dir")) if f.get("dir") is not None else None,
                        vspeed_fpm=float(f.get("v_speed", 0)) * 196.85 if f.get("v_speed") is not None else None,
                        on_ground=bool(f.get("alt", 1000) == 0),
                        est_departure_airport=f.get("dep_icao"),
                        est_arrival_airport=f.get("arr_icao"),
                        squawk=f.get("squawk"),
                        data_source="AIRLABS",
                        region_key=region.key
                    )
                    payloads.append(payload)

                if payloads:
                    batch = EnterpriseDataRouter.process_telemetry_batch(db, payloads)
                    for k in totals: totals[k] += batch.get(k, 0)
                    logger.info(f"[AirLabs] [{region.key}] Processed {len(payloads)} flights. Stats: {batch}")
                    
                time.sleep(2) # AirLabs rate limit protection
        except Exception as exc:
            logger.error(f"[AirLabs] Error: {exc}", exc_info=True)
            totals["errors"] += 1
        finally:
            db.close()
            
        return totals

    # ─────────────────────────────────────────────────────────────────────────
    # SOURCE 3: FLIGHTRADAR24 (Fallback/Premium Source)
    # ─────────────────────────────────────────────────────────────────────────

    def ingest_live_radar_from_fr24(self, regions) -> Dict[str, int]:
        """
        Sweep all configured regions via FR24 live positions.
        """
        totals = {"new_aircrafts": 0, "new_sessions": 0, "tracks_recorded": 0, "events": 0, "rejected": 0, "errors": 0}
        db = self._new_db()
        now_ts = int(time.time())

        try:
            for region in regions:
                logger.info(f"[FR24] Scanning {region.name_ar} ({region.key})")
                bounds = f"{region.lamax},{region.lamin},{region.lomin},{region.lomax}"
                data = self._safe_request("/api/live/flight-positions/full", {"bounds": bounds, "limit": 1500})
                if not data:
                    continue

                flights = data.get("data",[])
                if not flights:
                    continue

                payloads =[]
                for f in flights:
                    payload = self._parse_fr24_position(f, now_ts, region.key)
                    if payload:
                        payloads.append(payload)

                if payloads:
                    batch = EnterpriseDataRouter.process_telemetry_batch(db, payloads)
                    for k in totals: totals[k] += batch.get(k, 0)
                    logger.info(f"[FR24] [{region.key}] Processed {len(payloads)} flights. Stats: {batch}")

        except Exception as exc:
            logger.error(f"[FR24] Critical error: {exc}", exc_info=True)
            totals["errors"] += 1
        finally:
            db.close()

        return totals

    # ─────────────────────────────────────────────────────────────────────────
    # HISTORIC INGESTION (FR24)
    # ─────────────────────────────────────────────────────────────────────────

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
                    existing = db.query(IngestionJob).filter(and_(IngestionJob.region_key == region.key, IngestionJob.date_str == date_str, IngestionJob.status == "completed")).first()
                    if existing:
                        totals["jobs_skipped"] += 1
                        current_ts += _HISTORIC_STEP_SECONDS
                        continue

                job = db.query(IngestionJob).filter(and_(IngestionJob.region_key == region.key, IngestionJob.date_str == date_str)).first()
                if not job:
                    job = IngestionJob(job_type="historic", region_key=region.key, date_str=date_str, lamin=region.lamin, lomin=region.lomin, lamax=region.lamax, lomax=region.lomax, begin_ts=begin_ts, end_ts=end_ts, status="running", started_at=datetime.now(timezone.utc))
                    db.add(job)
                else:
                    job.status = "running"
                    job.started_at = datetime.now(timezone.utc)
                db.commit()
                db.refresh(job)

                data = self._safe_request("/api/historic/flight-positions/full", {"bounds": bounds, "timestamp": current_ts, "limit": 1500})

                if not data:
                    job.status = "failed"
                    job.error_message = "API returned no data"
                    db.commit()
                    current_ts += _HISTORIC_STEP_SECONDS
                    continue

                flights = data.get("data",[])
                payloads =[]
                for f in flights:
                    payload = self._parse_fr24_position(f, current_ts, region.key)
                    if payload: payloads.append(payload)

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

                job.status = "completed"
                job.flights_ingested = (job.flights_ingested or 0) + ingested
                job.records_processed = (job.records_processed or 0) + len(payloads)
                job.completed_at = datetime.now(timezone.utc)
                db.commit()

                totals["jobs_processed"] += 1
                current_ts += _HISTORIC_STEP_SECONDS
                time.sleep(settings.INGESTION_DELAY_SECONDS)

        except Exception as exc:
            logger.error(f"[Historic] Unhandled error: {exc}", exc_info=True)
        finally:
            db.close()

        return totals

    # ─────────────────────────────────────────────────────────────────────────
    # ENRICHMENT & TRACKS (FR24)
    # ─────────────────────────────────────────────────────────────────────────

    def enrich_flight_details(self, fr24_ids: List[str]) -> Dict[str, Any]:
        if not fr24_ids: return {"enriched": 0, "errors": 0}
        from app.database import SessionLocal
        from app.models import FactFlightSession, DimGeography

        chunk_size = 15
        enriched = 0
        errors = 0
        db = SessionLocal()
        
        try:
            for i in range(0, len(fr24_ids), chunk_size):
                chunk = fr24_ids[i : i + chunk_size]
                data = self._safe_request("/api/flight-summary/full", {"flight_ids": ",".join(chunk), "limit": len(chunk)})
                if not data:
                    errors += len(chunk)
                    continue

                for summary in data.get("data",[]):
                    fr24_id = summary.get("fr24_id")
                    if not fr24_id: continue
                    session = db.query(FactFlightSession).filter(FactFlightSession.fr24_id == fr24_id).first()
                    if not session: continue

                    if summary.get("orig_icao"):
                        dep = db.query(DimGeography).filter(DimGeography.icao_code == summary["orig_icao"]).first()
                        if dep: session.dep_airport_id = dep.id

                    if summary.get("dest_icao") or summary.get("dest_icao_actual"):
                        arr_icao = summary.get("dest_icao_actual") or summary.get("dest_icao")
                        arr = db.query(DimGeography).filter(DimGeography.icao_code == arr_icao).first()
                        if arr: session.arr_airport_id = arr.id

                    if summary.get("datetime_takeoff"):
                        try: session.actual_takeoff_ts = datetime.fromisoformat(summary["datetime_takeoff"].replace("Z", "+00:00"))
                        except: pass

                    if summary.get("datetime_landed"):
                        try: session.actual_landing_ts = datetime.fromisoformat(summary["datetime_landed"].replace("Z", "+00:00"))
                        except: pass

                    if summary.get("actual_distance"): session.total_distance_km = float(summary["actual_distance"])
                    if summary.get("flight_ended"): session.flight_status = "landed"
                    enriched += 1

                db.commit()
                time.sleep(1)
        except Exception as exc:
            logger.error(f"[Enrich] Error: {exc}", exc_info=True)
            errors += 1
        finally:
            db.close()

        return {"enriched": enriched, "errors": errors}

    def fetch_historical_track(self, fr24_id: str) -> Optional[List[Dict]]:
        data = self._safe_request("/api/flight-tracks", {"flight_id": fr24_id})
        if not data: return None
        tracks_raw = data.get("tracks",[])
        if not tracks_raw: return []

        result =[]
        for point in tracks_raw:
            ts_str = point.get("timestamp")
            if not ts_str: continue
            try: dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except: continue

            result.append({
                "timestamp": dt,
                "lat": point.get("lat"),
                "lon": point.get("lon"),
                "alt_ft": point.get("alt"),
                "gspeed_kts": point.get("gspeed"),
                "vspeed_fpm": point.get("vspeed"),
                "heading_deg": point.get("track"),
            })
        return result

    # ─────────────────────────────────────────────────────────────────────────
    # CLEANUP
    # ─────────────────────────────────────────────────────────────────────────

    def cleanup_old_data(self, days: int) -> int:
        if days <= 0: return 0
        from app.database import SessionLocal
        from app.models import FactFlightSession, CurrentAircraftState, IngestionJob
        from sqlalchemy import and_

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        stale_state_cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
        job_cutoff = datetime.now(timezone.utc) - timedelta(days=days * 2)

        db = SessionLocal()
        deleted_total = 0

        try:
            old_sessions = db.query(FactFlightSession).filter(and_(FactFlightSession.last_seen_ts < cutoff, FactFlightSession.flight_status.in_(["landed", "completed"]))).all()
            count = len(old_sessions)
            for session in old_sessions: db.delete(session)
            db.flush()
            deleted_total += count

            stale = db.query(CurrentAircraftState).filter(CurrentAircraftState.last_updated < stale_state_cutoff).all()
            stale_count = len(stale)
            for entry in stale: db.delete(entry)
            db.flush()
            deleted_total += stale_count

            old_jobs = db.query(IngestionJob).filter(and_(IngestionJob.completed_at < job_cutoff, IngestionJob.status == "completed")).all()
            job_count = len(old_jobs)
            for job in old_jobs: db.delete(job)
            db.flush()
            deleted_total += job_count

            db.commit()
        except Exception as exc:
            db.rollback()
            logger.error(f"[Cleanup] Error: {exc}", exc_info=True)
        finally:
            db.close()

        return deleted_total

    # ─────────────────────────────────────────────────────────────────────────
    # INTERNAL: FR24 position parser
    # ─────────────────────────────────────────────────────────────────────────

    def _parse_fr24_position(self, f: dict, fallback_ts: int, region_key: str) -> Optional[RawIngestionPayload]:
        icao24 = f.get("hex")
        if not icao24: return None

        ts_str = f.get("timestamp")
        try:
            dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            flight_ts = int(dt.timestamp())
        except:
            flight_ts = fallback_ts

        alt_ft   = f.get("alt")
        gspeed   = f.get("gspeed")
        vspeed   = f.get("vspeed")

        on_ground = (alt_ft is not None and alt_ft < 100 and gspeed is not None and gspeed < 30)

        altitude_m  = float(alt_ft)  * 0.3048 if alt_ft  is not None else None
        velocity_kmh = float(gspeed) * 1.852  if gspeed  is not None else None

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
            altitude=altitude_m or 0.0,
            velocity=velocity_kmh or 0.0,
            heading=float(f.get("track", 0)) if f.get("track") is not None else None,
            vspeed_fpm=float(vspeed) if vspeed is not None else None,
            on_ground=on_ground,
            est_departure_airport=f.get("orig_icao"),
            est_arrival_airport=f.get("dest_icao"),
            squawk=f.get("squawk"),
            data_source="FR24", # <--- TAGGED
            region_key=region_key,
        )