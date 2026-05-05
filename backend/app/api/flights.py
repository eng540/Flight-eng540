"""
Flight API Endpoints — v4.0 (TIER 3 Complete)
Prefix: /api/v1/flights

ENDPOINTS:
  GET  /api/v1/flights/search                  ← multi-field search
  GET  /api/v1/flights/{session_id}             ← single flight detail
  GET  /api/v1/flights/{session_id}/trajectory  ← trajectory points
  GET  /api/v1/aircraft/{icao24}/history        ← aircraft history

LIVE MAP:
  GET  /api/v1/live/positions   ← in live.py (separate router)

FIXES:
  [FIX-N+1] Removed TrackTelemetry-per-session loop.
             Old code in flights.py queried TrackTelemetry individually
             for every session in the result set → 501 queries for 500 aircraft.
             New code: /api/v1/live/positions reads CurrentAircraftState table
             (single query, denormalized, updated every ingestion cycle).
             Evidence: original flights.py lines 35-43 — db.query(TrackTelemetry)
             inside a for-loop over sessions.

  [FIX-AUTH] /search comes before /{session_id} in route order.
             FastAPI matches routes top-down; if /{session_id} is first,
             "search" would be interpreted as a session_id integer → 422 error.
"""
import io
import csv
import math
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.crud import FlightQueryCRUD
from app.schemas import (
    FlightDetailResponse,
    FlightListResponse,
    FlightSessionResponse,
    TrajectoryResponse,
    TrajectoryPoint,
    HistoryQueryResponse,
    HistoryAggregations,
)

router = APIRouter(prefix="/api/v1/flights", tags=["flights-v1"])
aircraft_router = APIRouter(prefix="/api/v1/aircraft", tags=["aircraft-v1"])


# ─────────────────────────────────────────────────────────────────────────────
# NOTE: /search MUST come before /{session_id} to avoid path collision
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/search", summary="بحث متعدد الحقول عن الرحلات")
def search_flights(
    callsign:       Optional[str] = Query(None, description="رمز الاستدعاء"),
    icao24:         Optional[str] = Query(None, description="كود ICAO24 للطائرة"),
    fr24_id:        Optional[str] = Query(None, description="معرف FR24 للرحلة"),
    flight_number:  Optional[str] = Query(None, description="رقم الرحلة التجارية"),
    operator_icao:  Optional[str] = Query(None, description="كود ICAO للناقل"),
    dep_icao:       Optional[str] = Query(None, description="مطار المغادرة ICAO"),
    arr_icao:       Optional[str] = Query(None, description="مطار الوصول ICAO"),
    status:         Optional[str] = Query(None, description="active | landed | lost_signal"),
    date_from:      Optional[str] = Query(None, description="من تاريخ YYYY-MM-DD"),
    date_to:        Optional[str] = Query(None, description="إلى تاريخ YYYY-MM-DD"),
    page:           int           = Query(1,  ge=1),
    page_size:      int           = Query(50, ge=1, le=500),
    export_csv:     bool          = Query(False, description="تصدير CSV"),
    db: Session = Depends(get_db),
):
    """
    Multi-field flight search with optional CSV export.
    All filters are optional and combinable.
    """
    sessions, total = FlightQueryCRUD.search_flights(
        db,
        callsign=callsign,
        icao24=icao24,
        fr24_id=fr24_id,
        flight_number=flight_number,
        operator_icao=operator_icao,
        dep_icao=dep_icao,
        arr_icao=arr_icao,
        status=status,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    )

    if export_csv:
        return _export_sessions_csv(sessions, filename="flight_search.csv")

    pages = math.ceil(total / page_size) if page_size else 1
    return {
        "total":     total,
        "page":      page,
        "page_size": page_size,
        "pages":     pages,
        "data":      [_session_to_dict(s) for s in sessions],
    }


@router.get("/{session_id}", summary="تفاصيل رحلة واحدة")
def get_flight_detail(
    session_id: int,
    include_trajectory: bool = Query(False, description="تضمين مسار الرحلة"),
    db: Session = Depends(get_db),
):
    """
    Full flight detail for a single session_id.
    Optionally includes trajectory points (expensive — only fetch when needed).
    """
    session = FlightQueryCRUD.get_flight_by_session_id(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"لم يتم العثور على الرحلة {session_id}")

    result = _session_to_dict(session, detail=True)

    if include_trajectory:
        tracks = FlightQueryCRUD.get_trajectory(db, session_id)
        result["trajectory"] = {
            "session_id": session_id,
            "fr24_id":    session.fr24_id,
            "callsign":   session.callsign,
            "points": [
                {
                    "ts":   int(t.timestamp.timestamp()),
                    "lat":  t.latitude,
                    "lon":  t.longitude,
                    "alt":  t.altitude_m,
                    "vel":  t.velocity_kmh,
                    "hdg":  t.heading_deg,
                    "vspd": t.vspeed_fpm,
                }
                for t in tracks
            ],
        }

    return result


@router.get("/{session_id}/trajectory", summary="مسار الرحلة (breadcrumbs)")
def get_flight_trajectory(
    session_id: int,
    db: Session = Depends(get_db),
):
    """
    Ordered list of telemetry points for map trajectory drawing.
    Returns lightweight TrajectoryPoint list — no relationship data.
    """
    session = FlightQueryCRUD.get_flight_by_session_id(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"الرحلة {session_id} غير موجودة")

    tracks = FlightQueryCRUD.get_trajectory(db, session_id)
    return TrajectoryResponse(
        session_id=session_id,
        fr24_id=session.fr24_id,
        callsign=session.callsign,
        points=[
            TrajectoryPoint(
                ts=int(t.timestamp.timestamp()),
                lat=t.latitude,
                lon=t.longitude,
                alt=t.altitude_m,
                vel=t.velocity_kmh,
                hdg=t.heading_deg,
                vspd=t.vspeed_fpm,
            )
            for t in tracks
        ],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Aircraft History (separate router prefix: /api/v1/aircraft)
# ─────────────────────────────────────────────────────────────────────────────

@aircraft_router.get("/{icao24}/history", summary="سجل رحلات طائرة بعينها")
def get_aircraft_history(
    icao24:     str,
    date_from:  Optional[str] = Query(None, description="من تاريخ YYYY-MM-DD"),
    date_to:    Optional[str] = Query(None, description="إلى تاريخ YYYY-MM-DD"),
    page:       int           = Query(1,  ge=1),
    page_size:  int           = Query(50, ge=1, le=500),
    export_csv: bool          = Query(False),
    db: Session = Depends(get_db),
):
    """
    All recorded sessions for a specific aircraft ICAO24.
    Supports date range filtering and CSV export.
    Evidence: business requirement GET /api/v1/aircraft/{icao24}/history
    """
    sessions, total = FlightQueryCRUD.get_aircraft_history(
        db,
        icao24=icao24,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    )

    if not sessions and total == 0:
        raise HTTPException(
            status_code=404,
            detail=f"لا توجد سجلات للطائرة {icao24.upper()} في الفترة المحددة",
        )

    if export_csv:
        return _export_sessions_csv(sessions, filename=f"aircraft_{icao24}_history.csv")

    pages = math.ceil(total / page_size) if page_size else 1
    return {
        "icao24":    icao24.upper(),
        "total":     total,
        "page":      page,
        "page_size": page_size,
        "pages":     pages,
        "data":      [_session_to_dict(s) for s in sessions],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Legacy compatibility — keeps old /flights endpoint alive for existing frontend
# ─────────────────────────────────────────────────────────────────────────────

legacy_router = APIRouter(prefix="/flights", tags=["flights-legacy"])


@legacy_router.get("", include_in_schema=False)
def legacy_get_flights(
    page:      int = Query(1,   ge=1),
    page_size: int = Query(500, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """
    Legacy endpoint — kept for frontend backward compat during TIER 4 migration.
    Reads from CurrentAircraftState (single query, no N+1).
    FIX-N+1: original code queried TrackTelemetry per session (501 queries → 1).
    """
    from app.crud import FlightQueryCRUD as FQ
    positions, total = FQ.get_live_positions(db, limit=page_size, page=page)
    pages = math.ceil(total / page_size) if page_size else 1
    return {
        "total":     total,
        "page":      page,
        "page_size": page_size,
        "pages":     pages,
        "data": [
            {
                "id":                    p.session_id,
                "icao24":               p.icao24,
                "callsign":             p.callsign,
                "fr24_id":              p.fr24_id,
                "flight_number":        p.flight_number,
                "operator_name":        p.operator_name,
                "aircraft_model":       p.aircraft_model,
                "aircraft_type":        p.aircraft_type,
                "est_departure_airport": p.dep_airport_iata,
                "est_arrival_airport":   p.arr_airport_iata,
                "latitude":             p.latitude,
                "longitude":            p.longitude,
                "altitude":             p.altitude_m,
                "velocity":             p.velocity_kmh,
                "heading":              p.heading_deg,
                "vspeed_fpm":           p.vspeed_fpm,
                "on_ground":            p.on_ground,
                "squawk":               p.squawk,
                "region_key":           p.region_key,
                "last_seen":            int(p.last_updated.timestamp()) if p.last_updated else None,
            }
            for p in positions
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _session_to_dict(s, detail: bool = False) -> dict:
    """Serialize a FactFlightSession ORM object to a dict safe for JSON."""
    base = {
        "session_id":    s.session_id,
        "fr24_id":       s.fr24_id,
        "flight_number": s.flight_number,
        "callsign":      s.callsign,
        "flight_status": s.flight_status,
        "first_seen_ts": s.first_seen_ts.isoformat() if s.first_seen_ts else None,
        "last_seen_ts":  s.last_seen_ts.isoformat()  if s.last_seen_ts  else None,
        "actual_takeoff_ts": s.actual_takeoff_ts.isoformat() if s.actual_takeoff_ts else None,
        "actual_landing_ts": s.actual_landing_ts.isoformat() if s.actual_landing_ts else None,
        "max_altitude_m":    s.max_altitude_m,
        "total_distance_km": s.total_distance_km,
        "aircraft": {
            "icao24":       s.aircraft.icao24       if s.aircraft else None,
            "registration": s.aircraft.registration if s.aircraft else None,
            "type_code":    s.aircraft.type_code    if s.aircraft else None,
            "model":        s.aircraft.model        if s.aircraft else None,
        } if s.aircraft else None,
        "operator": {
            "icao_code": s.operator.icao_code if s.operator else None,
            "name":      s.operator.name      if s.operator else None,
        } if s.operator else None,
        "dep_airport": {
            "icao_code": s.dep_airport.icao_code if s.dep_airport else None,
            "iata_code": s.dep_airport.iata_code if s.dep_airport else None,
            "name":      s.dep_airport.name      if s.dep_airport else None,
        } if s.dep_airport else None,
        "arr_airport": {
            "icao_code": s.arr_airport.icao_code if s.arr_airport else None,
            "iata_code": s.arr_airport.iata_code if s.arr_airport else None,
            "name":      s.arr_airport.name      if s.arr_airport else None,
        } if s.arr_airport else None,
    }

    if detail and s.first_seen_ts and s.last_seen_ts:
        base["duration_seconds"] = int(
            (s.last_seen_ts - s.first_seen_ts).total_seconds()
        )

    return base


def _export_sessions_csv(sessions, filename: str = "export.csv") -> StreamingResponse:
    """Convert session list to CSV and stream as download."""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        "session_id", "fr24_id", "flight_number", "callsign", "status",
        "aircraft_icao24", "aircraft_type", "operator",
        "dep_airport", "arr_airport",
        "first_seen", "last_seen", "duration_min",
        "max_altitude_m", "total_distance_km",
    ])
    writer.writeheader()
    for s in sessions:
        duration = None
        if s.first_seen_ts and s.last_seen_ts:
            duration = round((s.last_seen_ts - s.first_seen_ts).total_seconds() / 60, 1)
        writer.writerow({
            "session_id":     s.session_id,
            "fr24_id":        s.fr24_id or "",
            "flight_number":  s.flight_number or "",
            "callsign":       s.callsign or "",
            "status":         s.flight_status or "",
            "aircraft_icao24": s.aircraft.icao24 if s.aircraft else "",
            "aircraft_type":  s.aircraft.type_code if s.aircraft else "",
            "operator":       s.operator.icao_code if s.operator else "",
            "dep_airport":    s.dep_airport.icao_code if s.dep_airport else "",
            "arr_airport":    s.arr_airport.icao_code if s.arr_airport else "",
            "first_seen":     s.first_seen_ts.isoformat() if s.first_seen_ts else "",
            "last_seen":      s.last_seen_ts.isoformat()  if s.last_seen_ts  else "",
            "duration_min":   duration or "",
            "max_altitude_m": s.max_altitude_m or "",
            "total_distance_km": s.total_distance_km or "",
        })
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
