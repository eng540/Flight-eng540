"""
Enterprise CRUD Operations (v6.0 — Distributed Write-Safe & Concurrency Optimized)
Compliant with Aviation Physics, State Machines, and FR24 OpenAPI spec.

CHANGES FROM v5.1:
  [FIX] EnterpriseDataRouter.process_telemetry_batch:
        - Implemented Atomic Upsert (ON CONFLICT DO UPDATE) for CurrentAircraftState.
        - Implemented Lexicographical Sorting to mathematically prevent Deadlocks.
        - Implemented Micro-batching with Savepoints (begin_nested) for failure-safe ingestion.
        - Implemented Timestamp-based LWW and Source Priority conflict resolution.
        - Eliminated N+1 queries via Bulk Pre-fetching.
"""
from sqlalchemy.orm import Session, joinedload, aliased
from sqlalchemy import func, and_, or_, desc, case
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, timezone, timedelta
import logging
import math

from app import models, schemas

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═════════════════════════════════════════════════════════════════════════════

class AviationMath:
    """Physical calculations for aviation data quality."""

    @staticmethod
    def haversine_distance(lat1: float, lon1: float,
                           lat2: float, lon2: float) -> float:
        R = 6371.0
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (math.sin(dlat / 2) ** 2
             + math.cos(math.radians(lat1))
             * math.cos(math.radians(lat2))
             * math.sin(dlon / 2) ** 2)
        return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class DataQualityValidator:
    """SRE: Data quality pipeline — rejects physically impossible telemetry."""

    @staticmethod
    def validate_physics(
        payload: schemas.RawIngestionPayload,
        current_state: Optional[models.CurrentAircraftState],
    ) -> bool:
        if payload.velocity and payload.velocity > 1200:
            return False
        if payload.altitude and payload.altitude > 18500:
            return False

        if current_state and current_state.last_updated and current_state.latitude is not None:
            state_ts  = current_state.last_updated.timestamp()
            time_diff = payload.timestamp - state_ts

            # Exact duplicate
            if (abs(time_diff) < 1
                    and abs(payload.latitude  - current_state.latitude)  < 0.0001
                    and abs(payload.longitude - current_state.longitude) < 0.0001):
                return False

            # Ghost jump: >50 km in <30 s
            if 0 < time_diff < 30:
                dist_km = AviationMath.haversine_distance(
                    current_state.latitude, current_state.longitude,
                    payload.latitude, payload.longitude,
                )
                if dist_km > 50:
                    logger.warning(
                        f"[QA] Ghost jump {payload.icao24}: {dist_km:.1f}km/{time_diff:.0f}s"
                    )
                    return False

            # Impossible altitude spike
            if (payload.altitude is not None
                    and current_state.altitude_m is not None
                    and abs(payload.altitude - current_state.altitude_m) > 1000
                    and time_diff < 10):
                return False

        return True


# ═════════════════════════════════════════════════════════════════════════════
# ENTERPRISE DATA ROUTER — Telemetry State Machine
# ═════════════════════════════════════════════════════════════════════════════

class EnterpriseDataRouter:
    """Routes telemetry through state machine and event sourcing."""

    @staticmethod
    def process_telemetry_batch(
        db: Session,
        payloads: List[schemas.RawIngestionPayload],
    ) -> Dict[str, int]:

        stats = {
            "new_aircrafts": 0, "new_sessions": 0,
            "tracks_recorded": 0, "events": 0,
            "rejected": 0, "errors": 0,
        }
        if not payloads:
            return stats

        # ── Step 1: Bulk Pre-fetch & Cache (Eliminate N+1) ───────────────────
        icao24s = list({p.icao24 for p in payloads})
        
        # Pre-fetch Current States for Validation
        current_states = {
            s.icao24: s for s in db.query(models.CurrentAircraftState)
            .filter(models.CurrentAircraftState.icao24.in_(icao24s)).all()
        }

        # Pre-fetch Aircraft
        aircraft_cache = {
            a.icao24: a for a in db.query(models.DimAircraft)
            .filter(models.DimAircraft.icao24.in_(icao24s), models.DimAircraft.valid_to.is_(None)).all()
        }

        # Pre-fetch Active Sessions
        active_sessions = {
            s.aircraft.icao24: s for s in db.query(models.FactFlightSession)
            .join(models.DimAircraft)
            .filter(
                models.DimAircraft.icao24.in_(icao24s),
                models.FactFlightSession.flight_status == "active"
            ).all()
        }

        geo_cache: Dict[str, int] = {}
        operator_cache: Dict[str, Dict[str, Any]] = {}

        # ── Step 2: Process each radar ping (In-Memory) ───────────────────────
        valid_payloads = []
        state_upsert_dicts = []

        for payload in payloads:
            try:
                current_state = current_states.get(payload.icao24)

                if not DataQualityValidator.validate_physics(payload, current_state):
                    stats["rejected"] += 1
                    continue

                # Resolve Dimensions (with failure-safe nested transactions)
                dep_id = EnterpriseDataRouter._ensure_geo_safe(db, geo_cache, payload.est_departure_airport)
                arr_id = EnterpriseDataRouter._ensure_geo_safe(db, geo_cache, payload.est_arrival_airport)
                op_entry = EnterpriseDataRouter._ensure_operator_safe(db, operator_cache, payload.operator_icao)
                
                op_id    = op_entry["id"]   if op_entry else None
                op_name  = op_entry["name"] if op_entry else None

                # Aircraft Resolution
                aircraft = aircraft_cache.get(payload.icao24)
                if not aircraft:
                    try:
                        with db.begin_nested():
                            aircraft = models.DimAircraft(
                                icao24=payload.icao24,
                                registration=payload.registration,
                                type_code=payload.aircraft_type,
                                country_code=(payload.origin_country[:2].upper() if payload.origin_country else None),
                                operator_id=op_id,
                            )
                            db.add(aircraft)
                            db.flush()
                            stats["new_aircrafts"] += 1
                            aircraft_cache[payload.icao24] = aircraft
                    except IntegrityError:
                        # Handled concurrent insert by another worker
                        aircraft = db.query(models.DimAircraft).filter_by(icao24=payload.icao24, valid_to=None).first()
                        aircraft_cache[payload.icao24] = aircraft

                if not aircraft:
                    continue # Skip if resolution completely failed

                dt_timestamp = datetime.fromtimestamp(payload.timestamp, tz=timezone.utc)

                # Session State Machine
                session = active_sessions.get(payload.icao24)
                last_on_ground  = current_state.on_ground if current_state else payload.on_ground
                is_moving       = payload.velocity and payload.velocity > 50
                should_open     = False

                if not session:
                    if not payload.on_ground or is_moving:
                        should_open = True
                else:
                    secs_since = (dt_timestamp - session.last_seen_ts).total_seconds()
                    should_close   = False
                    close_reason   = ""

                    if secs_since > 1200:
                        should_close = True
                        close_reason = "lost_signal"
                    elif payload.on_ground and not is_moving and last_on_ground:
                        if secs_since > 300:
                            should_close = True
                            close_reason = "landed"

                    if should_close:
                        session.flight_status    = close_reason
                        session.actual_landing_ts = session.last_seen_ts if close_reason == "landed" else None
                        db.flush()
                        if close_reason == "lost_signal":
                            db.add(models.FactAviationEvent(
                                timestamp=dt_timestamp, aircraft_id=aircraft.id,
                                session_id=session.session_id,
                                event_category="SYSTEM", event_type="SIGNAL_LOST",
                            ))
                            stats["events"] += 1
                        
                        del active_sessions[payload.icao24] # Remove from active cache
                        
                        if not payload.on_ground or is_moving:
                            should_open = True

                if should_open:
                    session = models.FactFlightSession(
                        aircraft_id=aircraft.id, operator_id=op_id,
                        callsign=payload.callsign, fr24_id=payload.fr24_id,
                        flight_number=payload.flight_number,
                        dep_airport_id=dep_id, arr_airport_id=arr_id,
                        first_seen_ts=dt_timestamp, last_seen_ts=dt_timestamp,
                        flight_status="active",
                    )
                    db.add(session)
                    db.flush()
                    active_sessions[payload.icao24] = session
                    stats["new_sessions"] += 1
                    
                    if not payload.on_ground:
                        db.add(models.FactAviationEvent(
                            timestamp=dt_timestamp, aircraft_id=aircraft.id,
                            session_id=session.session_id,
                            event_category="FLIGHT", event_type="TAKEOFF",
                        ))
                        stats["events"] += 1

                # Update active session & Add Track
                if session and session.flight_status == "active":
                    session.last_seen_ts = dt_timestamp
                    if payload.altitude and (session.max_altitude_m is None or payload.altitude > session.max_altitude_m):
                        session.max_altitude_m = payload.altitude

                    if payload.fr24_id and not session.fr24_id: session.fr24_id = payload.fr24_id
                    if payload.flight_number and not session.flight_number: session.flight_number = payload.flight_number
                    if dep_id and not session.dep_airport_id: session.dep_airport_id = dep_id
                    if arr_id and not session.arr_airport_id: session.arr_airport_id = arr_id
                    if op_id  and not session.operator_id: session.operator_id = op_id

                    db.add(models.TrackTelemetry(
                        timestamp=dt_timestamp, session_id=session.session_id,
                        latitude=payload.latitude, longitude=payload.longitude,
                        altitude_m=payload.altitude, velocity_kmh=payload.velocity,
                        heading_deg=payload.heading, vspeed_fpm=payload.vspeed_fpm,
                        is_on_ground=payload.on_ground, squawk=payload.squawk,
                        data_source=payload.data_source,
                    ))
                    stats["tracks_recorded"] += 1

                # Emergency squawk
                if payload.squawk in ("7500", "7600", "7700"):
                    last_sq = current_state.squawk if current_state else None
                    if payload.squawk != last_sq and session:
                        db.add(models.FactAviationEvent(
                            timestamp=dt_timestamp, aircraft_id=aircraft.id,
                            session_id=session.session_id,
                            event_category="EMERGENCY", event_type=f"SQUAWK_{payload.squawk}",
                        ))
                        stats["events"] += 1

                # Prepare dict for Atomic Upsert
                state_upsert_dicts.append({
                    "icao24": payload.icao24,
                    "aircraft_id": aircraft.id,
                    "session_id": session.session_id if session else None,
                    "fr24_id": payload.fr24_id,
                    "callsign": payload.callsign,
                    "flight_number": payload.flight_number,
                    "operator_name": op_name,
                    "aircraft_type": payload.aircraft_type,
                    "aircraft_model": aircraft.model,
                    "dep_airport_iata": payload.est_departure_airport,
                    "arr_airport_iata": payload.est_arrival_airport,
                    "latitude": payload.latitude,
                    "longitude": payload.longitude,
                    "altitude_m": payload.altitude,
                    "velocity_kmh": payload.velocity,
                    "heading_deg": payload.heading,
                    "vspeed_fpm": payload.vspeed_fpm,
                    "on_ground": payload.on_ground,
                    "squawk": payload.squawk,
                    "region_key": payload.region_key,
                    "data_source": payload.data_source,
                    "last_updated": dt_timestamp
                })

            except Exception as exc:
                logger.error(f"[Router] Error processing {payload.icao24}: {exc}", exc_info=True)
                stats["errors"] += 1

        # Flush Sessions and Tracks before Upserting State
        try:
            db.flush()
        except Exception as exc:
            logger.error(f"[Router] Pre-upsert flush failed: {exc}")
            db.rollback()
            return stats

        # ── Step 3: Atomic Upsert for CurrentAircraftState ───────────────────
        if state_upsert_dicts:
            # 1. Lexicographical Sorting (Prevents Deadlocks)
            state_upsert_dicts.sort(key=lambda x: x["icao24"])

            # 2. Micro-batching
            batch_size = 50
            for i in range(0, len(state_upsert_dicts), batch_size):
                batch = state_upsert_dicts[i:i+batch_size]
                
                stmt = pg_insert(models.CurrentAircraftState).values(batch)
                
                # 3. Source Priority Logic (FR24 > AIRLABS > OPENSKY)
                priority_sql = case(
                    (stmt.excluded.data_source == 'FR24', 3),
                    (stmt.excluded.data_source == 'AIRLABS', 2),
                    (stmt.excluded.data_source == 'OPENSKY', 1),
                    else_=0
                )
                current_priority_sql = case(
                    (models.CurrentAircraftState.data_source == 'FR24', 3),
                    (models.CurrentAircraftState.data_source == 'AIRLABS', 2),
                    (models.CurrentAircraftState.data_source == 'OPENSKY', 1),
                    else_=0
                )

                update_dict = {c.name: c for c in stmt.excluded if c.name != 'icao24'}

                # 4. Timestamp-based conflict resolution & Stale write protection
                update_stmt = stmt.on_conflict_do_update(
                    index_elements=['icao24'],
                    set_=update_dict,
                    where=or_(
                        stmt.excluded.last_updated > models.CurrentAircraftState.last_updated,
                        and_(
                            stmt.excluded.last_updated == models.CurrentAircraftState.last_updated,
                            priority_sql > current_priority_sql
                        )
                    )
                )

                # 5. Failure-safe execution
                try:
                    with db.begin_nested():
                        db.execute(update_stmt)
                except Exception as exc:
                    logger.error(f"[Router] Atomic Upsert batch failed: {exc}")
                    stats["errors"] += len(batch)

        try:
            db.commit()
        except Exception as exc:
            logger.error(f"[Router] Final commit failed: {exc}", exc_info=True)
            db.rollback()
            stats["errors"] += 1

        return stats

    # ── Safe FK helpers (Handles Concurrent Inserts) ───────────────────────

    @staticmethod
    def _ensure_geo_safe(db: Session, cache: Dict[str, int], icao: Optional[str]) -> Optional[int]:
        if not icao: return None
        key = icao.upper()
        if key in cache: return cache[key]
        
        geo = db.query(models.DimGeography).filter_by(icao_code=key).first()
        if not geo:
            try:
                with db.begin_nested():
                    geo = models.DimGeography(icao_code=key, name=f"Airport {key}")
                    db.add(geo)
                    db.flush()
            except IntegrityError:
                geo = db.query(models.DimGeography).filter_by(icao_code=key).first()
        
        if geo:
            cache[key] = geo.id
            return geo.id
        return None

    @staticmethod
    def _ensure_operator_safe(db: Session, cache: Dict[str, Dict[str, Any]], icao: Optional[str]) -> Optional[Dict[str, Any]]:
        if not icao: return None
        key = icao.upper()
        if key in cache: return cache[key]
        
        op = db.query(models.DimOperator).filter_by(icao_code=key).first()
        if not op:
            try:
                with db.begin_nested():
                    op = models.DimOperator(icao_code=key, name=f"Operator {key}")
                    db.add(op)
                    db.flush()
            except IntegrityError:
                op = db.query(models.DimOperator).filter_by(icao_code=key).first()
                
        if op:
            cache[key] = {"id": op.id, "name": op.name}
            return cache[key]
        return None


# ═════════════════════════════════════════════════════════════════════════════
# FLIGHT QUERY CRUD
# ═════════════════════════════════════════════════════════════════════════════

class FlightQueryCRUD:

    @staticmethod
    def get_live_positions(
        db: Session,
        region_key: Optional[str] = None,
        on_ground:  Optional[bool] = None,
        limit: int = 1000,
        page:  int = 1,
    ) -> Tuple[List[models.CurrentAircraftState], int]:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)
        q = db.query(models.CurrentAircraftState).filter(
            models.CurrentAircraftState.last_updated >= cutoff,
            models.CurrentAircraftState.latitude.isnot(None),
            models.CurrentAircraftState.longitude.isnot(None),
        )
        if region_key:
            q = q.filter(models.CurrentAircraftState.region_key == region_key)
        if on_ground is not None:
            q = q.filter(models.CurrentAircraftState.on_ground == on_ground)
        total  = q.count()
        offset = (page - 1) * limit
        return q.order_by(desc(models.CurrentAircraftState.last_updated)).offset(offset).limit(limit).all(), total

    @staticmethod
    def get_flight_by_session_id(
        db: Session, session_id: int
    ) -> Optional[models.FactFlightSession]:
        return (
            db.query(models.FactFlightSession)
            .options(
                joinedload(models.FactFlightSession.aircraft).joinedload(models.DimAircraft.operator),
                joinedload(models.FactFlightSession.operator),
                joinedload(models.FactFlightSession.dep_airport),
                joinedload(models.FactFlightSession.arr_airport),
            )
            .filter(models.FactFlightSession.session_id == session_id)
            .first()
        )

    @staticmethod
    def get_trajectory(db: Session, session_id: int) -> List[models.TrackTelemetry]:
        return (
            db.query(models.TrackTelemetry)
            .filter(models.TrackTelemetry.session_id == session_id)
            .order_by(models.TrackTelemetry.timestamp.asc())
            .all()
        )

    @staticmethod
    def search_flights(
        db: Session,
        callsign:      Optional[str] = None,
        icao24:        Optional[str] = None,
        fr24_id:       Optional[str] = None,
        flight_number: Optional[str] = None,
        operator_icao: Optional[str] = None,
        dep_icao:      Optional[str] = None,
        arr_icao:      Optional[str] = None,
        status:        Optional[str] = None,
        date_from:     Optional[str] = None,
        date_to:       Optional[str] = None,
        page:      int = 1,
        page_size: int = 50,
    ) -> Tuple[List[models.FactFlightSession], int]:
        q = (
            db.query(models.FactFlightSession)
            .options(
                joinedload(models.FactFlightSession.aircraft),
                joinedload(models.FactFlightSession.operator),
                joinedload(models.FactFlightSession.dep_airport),
                joinedload(models.FactFlightSession.arr_airport),
            )
        )
        if callsign:
            q = q.filter(models.FactFlightSession.callsign.ilike(f"%{callsign.upper()}%"))
        if fr24_id:
            q = q.filter(models.FactFlightSession.fr24_id == fr24_id)
        if flight_number:
            q = q.filter(models.FactFlightSession.flight_number.ilike(f"%{flight_number.upper()}%"))
        if status:
            q = q.filter(models.FactFlightSession.flight_status == status)

        if icao24:
            sub = db.query(models.DimAircraft.id).filter(
                models.DimAircraft.icao24 == icao24.lower()
            ).subquery()
            q = q.filter(models.FactFlightSession.aircraft_id.in_(sub))

        if operator_icao:
            sub = db.query(models.DimOperator.id).filter(
                models.DimOperator.icao_code == operator_icao.upper()
            ).subquery()
            q = q.filter(models.FactFlightSession.operator_id.in_(sub))

        if dep_icao:
            sub = db.query(models.DimGeography.id).filter(
                models.DimGeography.icao_code == dep_icao.upper()
            ).subquery()
            q = q.filter(models.FactFlightSession.dep_airport_id.in_(sub))

        if arr_icao:
            sub = db.query(models.DimGeography.id).filter(
                models.DimGeography.icao_code == arr_icao.upper()
            ).subquery()
            q = q.filter(models.FactFlightSession.arr_airport_id.in_(sub))

        q = _apply_date_filter(q, date_from, date_to)
        total  = q.count()
        offset = (page - 1) * page_size
        return q.order_by(desc(models.FactFlightSession.first_seen_ts)).offset(offset).limit(page_size).all(), total

    @staticmethod
    def get_aircraft_history(
        db: Session,
        icao24:    str,
        date_from: Optional[str] = None,
        date_to:   Optional[str] = None,
        page:      int = 1,
        page_size: int = 50,
    ) -> Tuple[List[models.FactFlightSession], int]:
        aircraft = (
            db.query(models.DimAircraft)
            .filter(
                models.DimAircraft.icao24 == icao24.lower(),
                models.DimAircraft.valid_to.is_(None),
            )
            .first()
        )
        if not aircraft:
            return [], 0

        q = (
            db.query(models.FactFlightSession)
            .options(
                joinedload(models.FactFlightSession.dep_airport),
                joinedload(models.FactFlightSession.arr_airport),
                joinedload(models.FactFlightSession.operator),
            )
            .filter(models.FactFlightSession.aircraft_id == aircraft.id)
        )
        q = _apply_date_filter(q, date_from, date_to)
        total  = q.count()
        offset = (page - 1) * page_size
        return q.order_by(desc(models.FactFlightSession.first_seen_ts)).offset(offset).limit(page_size).all(), total

    @staticmethod
    def query_history(
        db: Session,
        request: schemas.HistoryQueryRequest,
    ) -> Tuple[List[models.FactFlightSession], int]:
        q = (
            db.query(models.FactFlightSession)
            .options(
                joinedload(models.FactFlightSession.aircraft),
                joinedload(models.FactFlightSession.operator),
                joinedload(models.FactFlightSession.dep_airport),
                joinedload(models.FactFlightSession.arr_airport),
            )
        )
        eid   = request.entity_id.strip()
        etype = request.entity_type

        if etype == "aircraft":
            ac = db.query(models.DimAircraft).filter(
                models.DimAircraft.icao24 == eid.lower()
            ).first()
            if not ac:
                return [], 0
            q = q.filter(models.FactFlightSession.aircraft_id == ac.id)

        elif etype == "airport":
            geo = db.query(models.DimGeography).filter(
                or_(
                    models.DimGeography.icao_code == eid.upper(),
                    models.DimGeography.iata_code == eid.upper(),
                )
            ).first()
            if not geo:
                return [], 0
            q = q.filter(or_(
                models.FactFlightSession.dep_airport_id == geo.id,
                models.FactFlightSession.arr_airport_id == geo.id,
            ))

        elif etype == "airline":
            op = db.query(models.DimOperator).filter(
                or_(
                    models.DimOperator.icao_code == eid.upper(),
                    models.DimOperator.iata_code == eid.upper(),
                )
            ).first()
            if not op:
                return [], 0
            q = q.filter(models.FactFlightSession.operator_id == op.id)

        elif etype == "country":
            sub = db.query(models.DimAircraft.id).filter(
                models.DimAircraft.country_code == eid.upper()
            ).subquery()
            q = q.filter(models.FactFlightSession.aircraft_id.in_(sub))

        elif etype == "region":
            sub = (
                db.query(models.CurrentAircraftState.session_id)
                .filter(
                    models.CurrentAircraftState.region_key == eid,
                    models.CurrentAircraftState.session_id.isnot(None),
                )
                .subquery()
            )
            q = q.filter(models.FactFlightSession.session_id.in_(sub))

        q = _apply_date_filter(q, request.date_from, request.date_to)
        total  = q.count()
        offset = (request.page - 1) * request.page_size
        return q.order_by(desc(models.FactFlightSession.first_seen_ts)).offset(offset).limit(request.page_size).all(), total


# ═════════════════════════════════════════════════════════════════════════════
# ANALYTICS CRUD
# ═════════════════════════════════════════════════════════════════════════════

class AnalyticsCRUD:

    @staticmethod
    def get_top_routes(
        db: Session,
        limit:     int = 10,
        date_from: Optional[str] = None,
        date_to:   Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        DepGeo = aliased(models.DimGeography, name="dep_geo")
        ArrGeo = aliased(models.DimGeography, name="arr_geo")

        q = (
            db.query(
                DepGeo.icao_code.label("departure"),
                ArrGeo.icao_code.label("arrival"),
                func.count(models.FactFlightSession.session_id).label("flight_count"),
            )
            .join(DepGeo, models.FactFlightSession.dep_airport_id == DepGeo.id)
            .join(ArrGeo, models.FactFlightSession.arr_airport_id == ArrGeo.id)
            .filter(
                models.FactFlightSession.dep_airport_id.isnot(None),
                models.FactFlightSession.arr_airport_id.isnot(None),
            )
        )
        q = _apply_date_filter_session(q, date_from, date_to)
        rows = (
            q.group_by(DepGeo.icao_code, ArrGeo.icao_code)
            .order_by(desc("flight_count"))
            .limit(limit)
            .all()
        )
        return [
            {"departure": r.departure, "arrival": r.arrival, "flight_count": r.flight_count}
            for r in rows
        ]

    @staticmethod
    def get_busiest_airports(
        db: Session,
        limit:     int = 10,
        date_from: Optional[str] = None,
        date_to:   Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        dep_q = (
            db.query(
                models.FactFlightSession.dep_airport_id.label("airport_id"),
                func.count(models.FactFlightSession.session_id).label("dep_count"),
            )
            .filter(models.FactFlightSession.dep_airport_id.isnot(None))
        )
        dep_q = _apply_date_filter_session(dep_q, date_from, date_to)
        dep_sq = dep_q.group_by(models.FactFlightSession.dep_airport_id).subquery()

        arr_q = (
            db.query(
                models.FactFlightSession.arr_airport_id.label("airport_id"),
                func.count(models.FactFlightSession.session_id).label("arr_count"),
            )
            .filter(models.FactFlightSession.arr_airport_id.isnot(None))
        )
        arr_q = _apply_date_filter_session(arr_q, date_from, date_to)
        arr_sq = arr_q.group_by(models.FactFlightSession.arr_airport_id).subquery()

        rows = (
            db.query(
                models.DimGeography.icao_code.label("airport_icao"),
                func.coalesce(dep_sq.c.dep_count, 0).label("as_departure"),
                func.coalesce(arr_sq.c.arr_count, 0).label("as_arrival"),
                (func.coalesce(dep_sq.c.dep_count, 0)
                 + func.coalesce(arr_sq.c.arr_count, 0)).label("flight_count"),
            )
            .join(dep_sq, models.DimGeography.id == dep_sq.c.airport_id, isouter=True)
            .join(arr_sq, models.DimGeography.id == arr_sq.c.airport_id, isouter=True)
            .filter(models.DimGeography.icao_code.isnot(None))
            .order_by(desc("flight_count"))
            .limit(limit)
            .all()
        )
        return [
            {"airport_icao": r.airport_icao, "flight_count": r.flight_count,
             "as_departure": r.as_departure, "as_arrival": r.as_arrival}
            for r in rows
        ]

    @staticmethod
    def get_daily_summary(db: Session, date_str: str) -> Dict[str, Any]:
        try:
            day_start = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            day_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)

        agg = (
            db.query(
                func.count(models.FactFlightSession.session_id).label("total_flights"),
                func.sum(case(
                    (models.FactFlightSession.flight_status == "active", 1), else_=0
                )).label("active_flights"),
                func.sum(case(
                    (models.FactFlightSession.flight_status == "landed", 1), else_=0
                )).label("landed_flights"),
                func.count(
                    func.distinct(models.FactFlightSession.aircraft_id)
                ).label("unique_aircraft"),
                func.count(
                    func.distinct(models.FactFlightSession.operator_id)
                ).label("unique_operators"),
            )
            .filter(
                models.FactFlightSession.first_seen_ts >= day_start,
                models.FactFlightSession.first_seen_ts <  day_end,
            )
            .one()
        )

        emergency_events = (
            db.query(func.count(models.FactAviationEvent.id))
            .filter(
                models.FactAviationEvent.event_category == "EMERGENCY",
                models.FactAviationEvent.timestamp >= day_start,
                models.FactAviationEvent.timestamp <  day_end,
            )
            .scalar() or 0
        )

        top_routes = AnalyticsCRUD.get_top_routes(db, limit=5, date_from=date_str, date_to=date_str)

        return {
            "date":             date_str,
            "total_flights":    agg.total_flights    or 0,
            "active_flights":   int(agg.active_flights  or 0),
            "landed_flights":   int(agg.landed_flights  or 0),
            "emergency_events": emergency_events,
            "unique_aircraft":  agg.unique_aircraft  or 0,
            "unique_operators": agg.unique_operators or 0,
            "top_routes":       top_routes,
        }

    @staticmethod
    def get_airline_performance(
        db: Session,
        limit:     int = 20,
        date_from: Optional[str] = None,
        date_to:   Optional[str] = None,
        page:      int = 1,
        page_size: int = 20,
    ) -> Tuple[int, List[Dict[str, Any]]]:
        q = (
            db.query(
                models.DimOperator.icao_code.label("operator_icao"),
                models.DimOperator.name.label("operator_name"),
                func.count(models.FactFlightSession.session_id).label("total_flights"),
                func.sum(case(
                    (models.FactFlightSession.flight_status == "active", 1), else_=0
                )).label("active_flights"),
                func.avg(
                    func.extract(
                        "epoch",
                        models.FactFlightSession.last_seen_ts
                        - models.FactFlightSession.first_seen_ts,
                    )
                ).label("avg_duration_s"),
                func.sum(models.FactFlightSession.total_distance_km).label("total_distance_km"),
            )
            .join(models.DimOperator,
                  models.FactFlightSession.operator_id == models.DimOperator.id)
            .filter(models.FactFlightSession.operator_id.isnot(None))
        )
        q = _apply_date_filter_session(q, date_from, date_to)
        q = q.group_by(models.DimOperator.icao_code, models.DimOperator.name)

        total  = q.count()
        offset = (page - 1) * page_size
        rows   = q.order_by(desc("total_flights")).offset(offset).limit(page_size).all()

        results = [
            {
                "operator_icao":           r.operator_icao,
                "operator_name":           r.operator_name,
                "total_flights":           r.total_flights,
                "active_flights":          int(r.active_flights or 0),
                "avg_flight_duration_min": (
                    round(float(r.avg_duration_s) / 60, 1) if r.avg_duration_s else None
                ),
                "total_distance_km": (
                    round(float(r.total_distance_km), 1) if r.total_distance_km else None
                ),
            }
            for r in rows
        ]
        return total, results

    @staticmethod
    def get_credits_summary(db: Session) -> List[Dict[str, Any]]:
        rows = (
            db.query(
                models.IngestionJob.job_type.label("endpoint"),
                func.count(models.IngestionJob.id).label("request_count"),
                func.coalesce(func.sum(models.IngestionJob.credits_used), 0).label("credits"),
            )
            .group_by(models.IngestionJob.job_type)
            .order_by(desc("credits"))
            .all()
        )
        return [
            {"endpoint": r.endpoint or "unknown",
             "request_count": r.request_count,
             "credits": int(r.credits)}
            for r in rows
        ]


# ═════════════════════════════════════════════════════════════════════════════
# INGESTION JOB CRUD
# ═════════════════════════════════════════════════════════════════════════════

class IngestionJobCRUD:

    @staticmethod
    def create_job(
        db: Session,
        job_type: str, region_key: str,
        date_str: Optional[str] = None,
        lamin: Optional[float] = None, lomin: Optional[float] = None,
        lamax: Optional[float] = None, lomax: Optional[float] = None,
        begin_ts: Optional[int] = None, end_ts: Optional[int] = None,
    ) -> models.IngestionJob:
        job = models.IngestionJob(
            job_type=job_type, region_key=region_key, status="pending",
            date_str=date_str, lamin=lamin, lomin=lomin, lamax=lamax, lomax=lomax,
            begin_ts=begin_ts, end_ts=end_ts,
            flights_ingested=0, chunks_total=0, chunks_done=0,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        return job

    @staticmethod
    def update_job(db: Session, job_id: int, **kwargs) -> Optional[models.IngestionJob]:
        job = db.query(models.IngestionJob).filter(models.IngestionJob.id == job_id).first()
        if not job:
            return None
        for key, value in kwargs.items():
            if hasattr(job, key):
                setattr(job, key, value)
        if kwargs.get("status") == "completed" and not job.completed_at:
            job.completed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(job)
        return job

    @staticmethod
    def list_jobs(
        db: Session,
        status:     Optional[str] = None,
        region_key: Optional[str] = None,
        page:       int = 1,
        page_size:  int = 20,
    ) -> Tuple[int, List[models.IngestionJob]]:
        q = db.query(models.IngestionJob)
        if status:
            q = q.filter(models.IngestionJob.status == status)
        if region_key:
            q = q.filter(models.IngestionJob.region_key == region_key)
        total  = q.count()
        offset = (page - 1) * page_size
        return total, q.order_by(desc(models.IngestionJob.created_at)).offset(offset).limit(page_size).all()

    @staticmethod
    def get_job(db: Session, job_id: int) -> Optional[models.IngestionJob]:
        return db.query(models.IngestionJob).filter(models.IngestionJob.id == job_id).first()


# ═════════════════════════════════════════════════════════════════════════════
# MODULE-LEVEL HELPERS (shared across classes)
# ═════════════════════════════════════════════════════════════════════════════

def _apply_date_filter(q, date_from: Optional[str], date_to: Optional[str]):
    return _apply_date_filter_session(q, date_from, date_to)


def _apply_date_filter_session(q, date_from: Optional[str], date_to: Optional[str]):
    if date_from:
        try:
            dt = datetime.strptime(date_from, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            q  = q.filter(models.FactFlightSession.first_seen_ts >= dt)
        except ValueError:
            pass
    if date_to:
        try:
            dt = datetime.strptime(date_to, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            dt = dt + timedelta(days=1)
            q  = q.filter(models.FactFlightSession.first_seen_ts < dt)
        except ValueError:
            pass
    return q