"""
Enterprise CRUD Operations (v7.0 — Deep Analytics Filtering & Pagination)
Compliant with Aviation Physics, State Machines, and FR24 OpenAPI spec.

CHANGES FROM v6.4:
  [ENHANCEMENT] AnalyticsCRUD:
        - All methods now accept deep filters (operator_icao, dep_icao, arr_icao, region_key).
        - get_top_routes & get_busiest_airports now return (total, data) to support Pagination.
  [FIX] FlightQueryCRUD & AnalyticsCRUD:
        - Replaced `.subquery()` with `select()` in `in_()` clauses to fix SQLAlchemy 2.0 
          "Coercing Subquery object into a select()" warnings (ITEM-7.5).
"""
from sqlalchemy.orm import Session, joinedload, aliased
from sqlalchemy import func, and_, or_, desc, case, extract, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError, OperationalError
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

            if (abs(time_diff) < 1
                    and abs(payload.latitude  - current_state.latitude)  < 0.0001
                    and abs(payload.longitude - current_state.longitude) < 0.0001):
                return False

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

        icao24s = list({p.icao24 for p in payloads})
        
        current_states = {
            s.icao24: s for s in db.query(models.CurrentAircraftState)
            .filter(models.CurrentAircraftState.icao24.in_(icao24s)).all()
        }

        aircraft_cache = {
            a.icao24: a for a in db.query(models.DimAircraft)
            .filter(models.DimAircraft.icao24.in_(icao24s), models.DimAircraft.valid_to.is_(None)).all()
        }

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

        state_upsert_dicts = []

        for payload in payloads:
            try:
                with db.begin_nested():
                    current_state = current_states.get(payload.icao24)

                    if not DataQualityValidator.validate_physics(payload, current_state):
                        stats["rejected"] += 1
                        continue

                    dep_id = EnterpriseDataRouter._ensure_geo_safe(db, geo_cache, payload.est_departure_airport)
                    arr_id = EnterpriseDataRouter._ensure_geo_safe(db, geo_cache, payload.est_arrival_airport)
                    op_entry = EnterpriseDataRouter._ensure_operator_safe(db, operator_cache, payload.operator_icao)
                    
                    op_id    = op_entry["id"]   if op_entry else None
                    op_name  = op_entry["name"] if op_entry else None

                    aircraft = aircraft_cache.get(payload.icao24)
                    if not aircraft:
                        try:
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
                            db.rollback() 
                            aircraft = db.query(models.DimAircraft).filter_by(icao24=payload.icao24, valid_to=None).first()
                            aircraft_cache[payload.icao24] = aircraft

                    if not aircraft:
                        continue 

                    dt_timestamp = datetime.fromtimestamp(payload.timestamp, tz=timezone.utc)

                    session = active_sessions.get(payload.icao24)
                    is_moving = payload.velocity and payload.velocity > 50
                    should_open = False

                    if not session:
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

                    if payload.squawk in ("7500", "7600", "7700"):
                        last_sq = current_state.squawk if current_state else None
                        if payload.squawk != last_sq and session:
                            db.add(models.FactAviationEvent(
                                timestamp=dt_timestamp, aircraft_id=aircraft.id,
                                session_id=session.session_id,
                                event_category="EMERGENCY", event_type=f"SQUAWK_{payload.squawk}",
                            ))
                            stats["events"] += 1

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

            except OperationalError as exc:
                logger.warning(f"[Router] OperationalError (Deadlock?) on {payload.icao24}. Skipping. Details: {exc}")
                stats["errors"] += 1
            except Exception as exc:
                logger.error(f"[Router] Error processing {payload.icao24}: {exc}", exc_info=True)
                stats["errors"] += 1

        try:
            db.flush()
        except Exception as exc:
            logger.error(f"[Router] Pre-upsert flush failed: {exc}")
            db.rollback()
            return stats

        if state_upsert_dicts:
            state_upsert_dicts.sort(key=lambda x: x["icao24"])

            batch_size = 50
            for i in range(0, len(state_upsert_dicts), batch_size):
                batch = state_upsert_dicts[i:i+batch_size]
                
                stmt = pg_insert(models.CurrentAircraftState).values(batch)
                
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

                try:
                    with db.begin_nested():
                        db.execute(update_stmt)
                except OperationalError as exc:
                    logger.warning(f"[Router] Upsert Deadlock on batch. Recovering... Details: {exc}")
                    stats["errors"] += len(batch)
                except Exception as exc:
                    logger.error(f"[Router] Atomic Upsert batch failed: {exc}")
                    stats["errors"] += len(batch)

        try:
            db.commit()
        except OperationalError as exc:
            logger.error(f"[Router] Final commit failed due to OperationalError (Deadlock?): {exc}")
            db.rollback()
            stats["errors"] += 1
        except Exception as exc:
            logger.error(f"[Router] Final commit failed: {exc}", exc_info=True)
            db.rollback()
            stats["errors"] += 1

        return stats

    @staticmethod
    def close_orphaned_sessions(db: Session, timeout_minutes: int = 45) -> int:
        cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)
        closed_count = 0

        try:
            orphans = db.query(models.FactFlightSession).filter(
                models.FactFlightSession.flight_status == "active",
                models.FactFlightSession.last_seen_ts < cutoff_time
            ).all()

            if not orphans:
                return 0

            orphans.sort(key=lambda s: s.session_id)

            batch_size = 50
            for i in range(0, len(orphans), batch_size):
                batch = orphans[i:i+batch_size]
                
                try:
                    for session in batch:
                        current_state = db.query(models.CurrentAircraftState).filter(
                            models.CurrentAircraftState.session_id == session.session_id
                        ).first()

                        is_on_ground = current_state.on_ground if current_state else False
                        close_reason = "landed" if is_on_ground else "completed"
                        
                        session.flight_status = close_reason
                        if close_reason == "landed":
                            session.actual_landing_ts = session.last_seen_ts

                        db.add(models.FactAviationEvent(
                            timestamp=datetime.now(timezone.utc),
                            aircraft_id=session.aircraft_id,
                            session_id=session.session_id,
                            event_category="SYSTEM", 
                            event_type="AUTO_CLOSED"
                        ))
                    
                    db.commit()
                    closed_count += len(batch)
                    
                except OperationalError as exc:
                    logger.warning(f"[Sweeper] Deadlock detected in batch. Skipping this batch. Details: {exc}")
                    db.rollback()
                except Exception as exc:
                    logger.error(f"[Sweeper] Unexpected error in batch: {exc}", exc_info=True)
                    db.rollback()

            if closed_count > 0:
                logger.info(f"[Sweeper] Successfully closed {closed_count} orphaned sessions.")

        except Exception as exc:
            logger.error(f"[Sweeper] Failed to fetch orphaned sessions: {exc}", exc_info=True)
            db.rollback()

        return closed_count

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
            except OperationalError:
                return None 
        
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
            except OperationalError:
                return None 
                
        if op:
            cache[key] = {"id": op.id, "name": op.name}
            return cache[key]
        return None


# ═════════════════════════════════════════════════════════════════════════════
# MODULE-LEVEL HELPERS (Advanced Filtering)
# ═════════════════════════════════════════════════════════════════════════════

def _apply_advanced_filters_session(
    q, db: Session, 
    date_from: Optional[str] = None, date_to: Optional[str] = None,
    operator_icao: Optional[str] = None, dep_icao: Optional[str] = None,
    arr_icao: Optional[str] = None, region_key: Optional[str] = None
):
    """Applies deep cross-filtering to any FactFlightSession query."""
    if date_from:
        try:
            dt = datetime.strptime(date_from, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            q  = q.filter(models.FactFlightSession.first_seen_ts >= dt)
        except ValueError: pass
    if date_to:
        try:
            dt = datetime.strptime(date_to, "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1)
            q  = q.filter(models.FactFlightSession.first_seen_ts < dt)
        except ValueError: pass
        
    if operator_icao:
        stmt = select(models.DimOperator.id).where(models.DimOperator.icao_code == operator_icao.upper())
        q = q.filter(models.FactFlightSession.operator_id.in_(stmt))
        
    if dep_icao:
        stmt = select(models.DimGeography.id).where(models.DimGeography.icao_code == dep_icao.upper())
        q = q.filter(models.FactFlightSession.dep_airport_id.in_(stmt))
        
    if arr_icao:
        stmt = select(models.DimGeography.id).where(models.DimGeography.icao_code == arr_icao.upper())
        q = q.filter(models.FactFlightSession.arr_airport_id.in_(stmt))
        
    if region_key:
        stmt = select(models.CurrentAircraftState.session_id).where(
            models.CurrentAircraftState.region_key == region_key,
            models.CurrentAircraftState.session_id.isnot(None)
        )
        q = q.filter(models.FactFlightSession.session_id.in_(stmt))
        
    return q


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
            stmt = select(models.DimAircraft.id).where(models.DimAircraft.icao24 == icao24.lower())
            q = q.filter(models.FactFlightSession.aircraft_id.in_(stmt))

        q = _apply_advanced_filters_session(q, db, date_from, date_to, operator_icao, dep_icao, arr_icao, None)
        
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
        q = _apply_advanced_filters_session(q, db, date_from, date_to)
        total  = q.count()
        offset = (page - 1) * page_size
        return q.order_by(desc(models.FactFlightSession.first_seen_ts)).offset(offset).limit(page_size).all(), total

    @staticmethod
    def _build_history_base_query(db: Session, request: schemas.HistoryQueryRequest):
        q = db.query(models.FactFlightSession)
        eid   = request.entity_id.strip()
        etype = request.entity_type

        if etype == "aircraft":
            ac = db.query(models.DimAircraft).filter(models.DimAircraft.icao24 == eid.lower()).first()
            if not ac: return None
            q = q.filter(models.FactFlightSession.aircraft_id == ac.id)
            return _apply_advanced_filters_session(q, db, request.date_from, request.date_to)

        elif etype == "airport":
            geo = db.query(models.DimGeography).filter(
                or_(models.DimGeography.icao_code == eid.upper(), models.DimGeography.iata_code == eid.upper())
            ).first()
            if not geo: return None
            q = q.filter(or_(
                models.FactFlightSession.dep_airport_id == geo.id,
                models.FactFlightSession.arr_airport_id == geo.id,
            ))
            return _apply_advanced_filters_session(q, db, request.date_from, request.date_to)

        elif etype == "airline":
            return _apply_advanced_filters_session(q, db, request.date_from, request.date_to, operator_icao=eid)

        elif etype == "country":
            stmt = select(models.DimAircraft.id).where(models.DimAircraft.country_code == eid.upper())
            q = q.filter(models.FactFlightSession.aircraft_id.in_(stmt))
            return _apply_advanced_filters_session(q, db, request.date_from, request.date_to)

        elif etype == "region":
            return _apply_advanced_filters_session(q, db, request.date_from, request.date_to, region_key=eid)

        return _apply_advanced_filters_session(q, db, request.date_from, request.date_to)

    @staticmethod
    def query_history(
        db: Session,
        request: schemas.HistoryQueryRequest,
    ) -> Tuple[List[models.FactFlightSession], int]:
        
        q = FlightQueryCRUD._build_history_base_query(db, request)
        if q is None:
            return [], 0

        q = q.options(
            joinedload(models.FactFlightSession.aircraft),
            joinedload(models.FactFlightSession.operator),
            joinedload(models.FactFlightSession.dep_airport),
            joinedload(models.FactFlightSession.arr_airport),
        )

        total  = q.count()
        offset = (request.page - 1) * request.page_size
        return q.order_by(desc(models.FactFlightSession.first_seen_ts)).offset(offset).limit(request.page_size).all(), total

    @staticmethod
    def get_history_aggregations(
        db: Session,
        request: schemas.HistoryQueryRequest,
    ) -> Optional[Dict[str, Any]]:
        q = FlightQueryCRUD._build_history_base_query(db, request)
        if q is None:
            return None

        agg_result = db.query(
            func.count(models.FactFlightSession.session_id).label("total_flights"),
            func.count(func.distinct(models.FactFlightSession.aircraft_id)).label("unique_aircraft"),
            func.count(func.distinct(models.FactFlightSession.operator_id)).label("unique_operators"),
            func.sum(models.FactFlightSession.total_distance_km).label("total_distance_km"),
            func.avg(
                func.extract("epoch", models.FactFlightSession.last_seen_ts - models.FactFlightSession.first_seen_ts)
            ).label("avg_duration_s")
        ).select_from(q.subquery()).one()

        if agg_result.total_flights == 0:
            return None

        DepGeo = aliased(models.DimGeography, name="dep_geo")
        ArrGeo = aliased(models.DimGeography, name="arr_geo")
        
        routes_q = (
            db.query(
                DepGeo.icao_code.label("departure"),
                ArrGeo.icao_code.label("arrival"),
                func.count(models.FactFlightSession.session_id).label("flight_count")
            )
            .select_from(q.subquery())
            .join(DepGeo, models.FactFlightSession.dep_airport_id == DepGeo.id)
            .join(ArrGeo, models.FactFlightSession.arr_airport_id == ArrGeo.id)
            .group_by(DepGeo.icao_code, ArrGeo.icao_code)
            .order_by(desc("flight_count"))
            .limit(5)
        )
        
        top_routes = [
            {"departure": r.departure, "arrival": r.arrival, "flight_count": r.flight_count}
            for r in routes_q.all()
        ]

        return {
            "total_flights": agg_result.total_flights,
            "unique_aircraft": agg_result.unique_aircraft,
            "unique_operators": agg_result.unique_operators,
            "total_distance_km": float(agg_result.total_distance_km) if agg_result.total_distance_km else None,
            "avg_duration_min": round(float(agg_result.avg_duration_s) / 60, 1) if agg_result.avg_duration_s else None,
            "top_routes": top_routes
        }


# ═════════════════════════════════════════════════════════════════════════════
# ANALYTICS CRUD
# ═════════════════════════════════════════════════════════════════════════════

class AnalyticsCRUD:

    @staticmethod
    def get_top_routes(
        db: Session, limit: int = 10, page: int = 1,
        date_from: Optional[str] = None, date_to: Optional[str] = None,
        operator_icao: Optional[str] = None, dep_icao: Optional[str] = None,
        arr_icao: Optional[str] = None, region_key: Optional[str] = None
    ) -> Tuple[int, List[Dict[str, Any]]]:
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
        q = _apply_advanced_filters_session(q, db, date_from, date_to, operator_icao, dep_icao, arr_icao, region_key)
        q = q.group_by(DepGeo.icao_code, ArrGeo.icao_code)
        
        # Pagination logic
        total = q.count()
        offset = (page - 1) * limit
        rows = q.order_by(desc("flight_count")).offset(offset).limit(limit).all()
        
        results = [
            {"departure": r.departure, "arrival": r.arrival, "flight_count": r.flight_count}
            for r in rows
        ]
        return total, results

    @staticmethod
    def get_busiest_airports(
        db: Session, limit: int = 10, page: int = 1,
        date_from: Optional[str] = None, date_to: Optional[str] = None,
        operator_icao: Optional[str] = None, dep_icao: Optional[str] = None,
        arr_icao: Optional[str] = None, region_key: Optional[str] = None
    ) -> Tuple[int, List[Dict[str, Any]]]:
        
        dep_q = db.query(
            models.FactFlightSession.dep_airport_id.label("airport_id"),
            func.count(models.FactFlightSession.session_id).label("dep_count")
        ).filter(models.FactFlightSession.dep_airport_id.isnot(None))
        dep_q = _apply_advanced_filters_session(dep_q, db, date_from, date_to, operator_icao, dep_icao, arr_icao, region_key)
        dep_sq = dep_q.group_by(models.FactFlightSession.dep_airport_id).subquery()

        arr_q = db.query(
            models.FactFlightSession.arr_airport_id.label("airport_id"),
            func.count(models.FactFlightSession.session_id).label("arr_count")
        ).filter(models.FactFlightSession.arr_airport_id.isnot(None))
        arr_q = _apply_advanced_filters_session(arr_q, db, date_from, date_to, operator_icao, dep_icao, arr_icao, region_key)
        arr_sq = arr_q.group_by(models.FactFlightSession.arr_airport_id).subquery()

        main_q = (
            db.query(
                models.DimGeography.icao_code.label("airport_icao"),
                func.coalesce(dep_sq.c.dep_count, 0).label("as_departure"),
                func.coalesce(arr_sq.c.arr_count, 0).label("as_arrival"),
                (func.coalesce(dep_sq.c.dep_count, 0) + func.coalesce(arr_sq.c.arr_count, 0)).label("flight_count"),
            )
            .join(dep_sq, models.DimGeography.id == dep_sq.c.airport_id, isouter=True)
            .join(arr_sq, models.DimGeography.id == arr_sq.c.airport_id, isouter=True)
            .filter(models.DimGeography.icao_code.isnot(None))
            .filter(or_(dep_sq.c.dep_count > 0, arr_sq.c.arr_count > 0)) # Only airports with activity
        )
        
        total = main_q.count()
        offset = (page - 1) * limit
        rows = main_q.order_by(desc("flight_count")).offset(offset).limit(limit).all()
        
        results = [
            {"airport_icao": r.airport_icao, "flight_count": r.flight_count,
             "as_departure": r.as_departure, "as_arrival": r.as_arrival}
            for r in rows
        ]
        return total, results

    @staticmethod
    def get_period_summary(
        db: Session, 
        date_from: Optional[str] = None, date_to: Optional[str] = None,
        operator_icao: Optional[str] = None, dep_icao: Optional[str] = None,
        arr_icao: Optional[str] = None, region_key: Optional[str] = None
    ) -> Dict[str, Any]:
        
        q = db.query(
            func.count(models.FactFlightSession.session_id).label("total_flights"),
            func.sum(case((models.FactFlightSession.flight_status == "active", 1), else_=0)).label("active_flights"),
            func.sum(case((models.FactFlightSession.flight_status == "landed", 1), else_=0)).label("landed_flights"),
            func.count(func.distinct(models.FactFlightSession.aircraft_id)).label("unique_aircraft"),
            func.count(func.distinct(models.FactFlightSession.operator_id)).label("unique_operators"),
        )
        q = _apply_advanced_filters_session(q, db, date_from, date_to, operator_icao, dep_icao, arr_icao, region_key)
        agg = q.one()

        # Emergency events require joining FactFlightSession to apply the same filters
        events_q = db.query(func.count(models.FactAviationEvent.id)).join(
            models.FactFlightSession, models.FactAviationEvent.session_id == models.FactFlightSession.session_id
        ).filter(models.FactAviationEvent.event_category == "EMERGENCY")
        
        events_q = _apply_advanced_filters_session(events_q, db, date_from, date_to, operator_icao, dep_icao, arr_icao, region_key)
        emergency_events = events_q.scalar() or 0

        # Get top 5 routes for the summary
        _, top_routes = AnalyticsCRUD.get_top_routes(
            db, limit=5, date_from=date_from, date_to=date_to, 
            operator_icao=operator_icao, dep_icao=dep_icao, arr_icao=arr_icao, region_key=region_key
        )

        date_label = "كل الأوقات"
        if date_from and date_to: date_label = f"{date_from} إلى {date_to}"
        elif date_from: date_label = f"من {date_from}"
        elif date_to: date_label = f"حتى {date_to}"

        return {
            "date":             date_label,
            "total_flights":    agg.total_flights    or 0,
            "active_flights":   int(agg.active_flights  or 0),
            "landed_flights":   int(agg.landed_flights  or 0),
            "emergency_events": emergency_events,
            "unique_aircraft":  agg.unique_aircraft  or 0,
            "unique_operators": agg.unique_operators or 0,
            "top_routes":       top_routes,
        }

    @staticmethod
    def get_time_distribution(
        db: Session, 
        date_from: Optional[str] = None, date_to: Optional[str] = None,
        operator_icao: Optional[str] = None, dep_icao: Optional[str] = None,
        arr_icao: Optional[str] = None, region_key: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        
        q = db.query(
            extract('hour', models.FactFlightSession.first_seen_ts).label('hour'),
            func.count(models.FactFlightSession.session_id).label('flight_count')
        )
        q = _apply_advanced_filters_session(q, db, date_from, date_to, operator_icao, dep_icao, arr_icao, region_key)
        
        rows = q.group_by('hour').order_by('hour').all()
        
        distribution = {i: 0 for i in range(24)}
        for r in rows:
            if r.hour is not None:
                distribution[int(r.hour)] = r.flight_count
                
        return [{"hour": h, "flight_count": c} for h, c in distribution.items()]

    @staticmethod
    def get_airline_performance(
        db: Session, limit: int = 20, page: int = 1,
        date_from: Optional[str] = None, date_to: Optional[str] = None,
        operator_icao: Optional[str] = None, dep_icao: Optional[str] = None,
        arr_icao: Optional[str] = None, region_key: Optional[str] = None
    ) -> Tuple[int, List[Dict[str, Any]]]:
        
        q = (
            db.query(
                models.DimOperator.icao_code.label("operator_icao"),
                models.DimOperator.name.label("operator_name"),
                func.count(models.FactFlightSession.session_id).label("total_flights"),
                func.sum(case((models.FactFlightSession.flight_status == "active", 1), else_=0)).label("active_flights"),
                func.avg(func.extract("epoch", models.FactFlightSession.last_seen_ts - models.FactFlightSession.first_seen_ts)).label("avg_duration_s"),
                func.sum(models.FactFlightSession.total_distance_km).label("total_distance_km"),
            )
            .join(models.DimOperator, models.FactFlightSession.operator_id == models.DimOperator.id)
            .filter(models.FactFlightSession.operator_id.isnot(None))
        )
        q = _apply_advanced_filters_session(q, db, date_from, date_to, operator_icao, dep_icao, arr_icao, region_key)
        q = q.group_by(models.DimOperator.icao_code, models.DimOperator.name)

        total  = q.count()
        offset = (page - 1) * limit
        rows   = q.order_by(desc("total_flights")).offset(offset).limit(limit).all()

        results = [
            {
                "operator_icao":           r.operator_icao,
                "operator_name":           r.operator_name,
                "total_flights":           r.total_flights,
                "active_flights":          int(r.active_flights or 0),
                "avg_flight_duration_min": round(float(r.avg_duration_s) / 60, 1) if r.avg_duration_s else None,
                "total_distance_km":       round(float(r.total_distance_km), 1) if r.total_distance_km else None,
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