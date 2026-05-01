"""
Historical Engine API — v1.0 (TIER 3 New)
Prefix: /api/v1/history

ENDPOINTS:
  POST /api/v1/history/query   ← multi-dimensional history query
  GET  /api/v1/history/export  ← CSV export of history results

Evidence: business requirement
  GET /api/v1/history/query
  POST /api/v1/history/export
  "Must support querying by: Aircraft | Airport | Country | Airline | Region"
  "With date range filtering + aggregated insights"
"""
import io
import csv
import math
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.crud import FlightQueryCRUD, AnalyticsCRUD
from app.schemas import HistoryQueryRequest, HistoryQueryResponse, HistoryAggregations

router = APIRouter(prefix="/api/v1/history", tags=["history-v1"])


@router.post("/query", summary="استعلام البيانات التاريخية")
def query_history(
    request: HistoryQueryRequest,
    db: Session = Depends(get_db),
):
    """
    Multi-dimensional historical flight query engine.

    entity_type options:
      aircraft  → entity_id = ICAO24 hex (e.g. "a12345")
      airport   → entity_id = ICAO or IATA code (e.g. "OERK" or "RUH")
      airline   → entity_id = operator ICAO (e.g. "SVA")
      country   → entity_id = 2-letter country code (e.g. "SA")
      region    → entity_id = region key (e.g. "middle_east")

    Returns paginated sessions + aggregated insights (totals, distances, top routes).
    """
    sessions, total = FlightQueryCRUD.query_history(db, request)
    pages = math.ceil(total / request.page_size) if request.page_size else 1

    # Compute lightweight aggregations on the returned page
    unique_aircraft  = len({s.aircraft_id for s in sessions if s.aircraft_id})
    unique_operators = len({s.operator_id  for s in sessions if s.operator_id})
    total_distance   = sum(
        s.total_distance_km for s in sessions if s.total_distance_km
    )

    # Duration average (seconds → minutes)
    durations = [
        (s.last_seen_ts - s.first_seen_ts).total_seconds() / 60
        for s in sessions
        if s.first_seen_ts and s.last_seen_ts
    ]
    avg_duration = round(sum(durations) / len(durations), 1) if durations else None

    # Top routes from current page
    route_counter: dict = {}
    for s in sessions:
        dep = s.dep_airport.icao_code if s.dep_airport else None
        arr = s.arr_airport.icao_code if s.arr_airport else None
        if dep and arr:
            key = (dep, arr)
            route_counter[key] = route_counter.get(key, 0) + 1
    top_routes = [
        {"departure": k[0], "arrival": k[1], "flight_count": v}
        for k, v in sorted(route_counter.items(), key=lambda x: -x[1])[:5]
    ]

    from app.api.flights import _session_to_dict
    return HistoryQueryResponse(
        entity_type=request.entity_type,
        entity_id=request.entity_id,
        total=total,
        page=request.page,
        page_size=request.page_size,
        pages=pages,
        data=[_session_to_dict(s) for s in sessions],
        aggregations=HistoryAggregations(
            total_flights=total,
            unique_aircraft=unique_aircraft,
            unique_operators=unique_operators,
            total_distance_km=round(total_distance, 1) if total_distance else None,
            avg_duration_min=avg_duration,
            top_routes=top_routes,
        ),
    )


@router.get("/export", summary="تصدير البيانات التاريخية CSV")
def export_history(
    entity_type: str           = Query(..., description="aircraft|airport|airline|country|region"),
    entity_id:   str           = Query(..., description="معرف الكيان"),
    date_from:   Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to:     Optional[str] = Query(None, description="YYYY-MM-DD"),
    max_rows:    int           = Query(5000, ge=1, le=50000),
    db: Session = Depends(get_db),
):
    """
    Export historical query results as downloadable CSV.
    Evidence: business requirement POST /api/v1/history/export
    """
    from app.schemas import HistoryQueryRequest

    request = HistoryQueryRequest(
        entity_type=entity_type,
        entity_id=entity_id,
        date_from=date_from,
        date_to=date_to,
        page=1,
        page_size=max_rows,
    )
    sessions, total = FlightQueryCRUD.query_history(db, request)

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
            duration = round(
                (s.last_seen_ts - s.first_seen_ts).total_seconds() / 60, 1
            )
        writer.writerow({
            "session_id":      s.session_id,
            "fr24_id":         s.fr24_id or "",
            "flight_number":   s.flight_number or "",
            "callsign":        s.callsign or "",
            "status":          s.flight_status or "",
            "aircraft_icao24": s.aircraft.icao24    if s.aircraft    else "",
            "aircraft_type":   s.aircraft.type_code if s.aircraft    else "",
            "operator":        s.operator.icao_code if s.operator    else "",
            "dep_airport":     s.dep_airport.icao_code if s.dep_airport else "",
            "arr_airport":     s.arr_airport.icao_code if s.arr_airport else "",
            "first_seen":      s.first_seen_ts.isoformat() if s.first_seen_ts else "",
            "last_seen":       s.last_seen_ts.isoformat()  if s.last_seen_ts  else "",
            "duration_min":    duration or "",
            "max_altitude_m":  s.max_altitude_m    or "",
            "total_distance_km": s.total_distance_km or "",
        })

    output.seek(0)
    filename = f"history_{entity_type}_{entity_id}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
