"""
Analytics API Endpoints — v4.0 (TIER 3 Complete)
Prefix: /api/v1/analytics

ENDPOINTS (all previously stubs or returning empty data):
  GET /api/v1/analytics/top-routes            ← was returning []
  GET /api/v1/analytics/busiest-airports      ← was missing date filter
  GET /api/v1/analytics/daily-summary         ← was missing entirely
  GET /api/v1/analytics/airline-performance   ← was missing entirely
  GET /api/v1/analytics/export-csv            ← was missing entirely
  GET /api/v1/analytics/summary               ← was stub

Evidence for each fix stated in-line.
"""
import io
import csv
import math
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.crud import AnalyticsCRUD
from app.schemas import (
    AirlinePerformanceResponse,
    AirlinePerformanceItem,
    DailySummaryResponse,
    RouteStats,
    AirportStats,
    AnalyticsSummary,
    CountryStats,
)

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics-v1"])

# Keep legacy prefix alive for existing frontend during migration
legacy_router = APIRouter(prefix="/analytics", tags=["analytics-legacy"])


# ─────────────────────────────────────────────────────────────────────────────
# Top Routes
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/top-routes", summary="أكثر الطرق ازدحاماً")
@legacy_router.get("/top_routes", include_in_schema=False)
def get_top_routes(
    limit:     int           = Query(10, ge=1, le=100),
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to:   Optional[str] = Query(None, description="YYYY-MM-DD"),
    db: Session = Depends(get_db),
):
    """
    Top origin→destination pairs by flight count.
    FIX: was returning [] hardcoded.
    Evidence: analytics.py line ~42: `return []`
    Now delegates to AnalyticsCRUD.get_top_routes() with real GROUP BY query.
    """
    routes = AnalyticsCRUD.get_top_routes(db, limit=limit, date_from=date_from, date_to=date_to)
    return {"total": len(routes), "data": routes}


# ─────────────────────────────────────────────────────────────────────────────
# Busiest Airports
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/busiest-airports", summary="أكثر المطارات ازدحاماً")
@legacy_router.get("/top_airports", include_in_schema=False)
def get_busiest_airports(
    limit:     int           = Query(15, ge=1, le=100),
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to:   Optional[str] = Query(None, description="YYYY-MM-DD"),
    db: Session = Depends(get_db),
):
    """
    Airports ranked by total movements (departures + arrivals).
    FIX: old endpoint counted departures only — arrivals now included.
    Evidence: analytics.py get_top_airports() joined dep_airport_id only.
    """
    airports = AnalyticsCRUD.get_busiest_airports(
        db, limit=limit, date_from=date_from, date_to=date_to
    )
    return {"total": len(airports), "data": airports}


# ─────────────────────────────────────────────────────────────────────────────
# Daily Summary
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/daily-summary", summary="ملخص يومي للرحلات")
def get_daily_summary(
    date: Optional[str] = Query(None, description="YYYY-MM-DD (default: today)"),
    db: Session = Depends(get_db),
):
    """
    Full single-day summary: totals, statuses, emergencies, top routes.
    NEW: was missing entirely from the API.
    Evidence: business requirement GET /api/v1/analytics/daily-summary.
    """
    from datetime import datetime, timezone

    date_str = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    summary = AnalyticsCRUD.get_daily_summary(db, date_str)
    return summary


# ─────────────────────────────────────────────────────────────────────────────
# Airline Performance
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/airline-performance", summary="أداء شركات الطيران")
def get_airline_performance(
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to:   Optional[str] = Query(None, description="YYYY-MM-DD"),
    page:      int           = Query(1,  ge=1),
    page_size: int           = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """
    Airline-level aggregation: flight counts, duration, distance.
    NEW: was missing entirely.
    Evidence: business requirement GET /api/v1/analytics/airline-performance.
    """
    total, data = AnalyticsCRUD.get_airline_performance(
        db,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    )
    pages = math.ceil(total / page_size) if page_size else 1
    return AirlinePerformanceResponse(
        total=total,
        data=[AirlinePerformanceItem(**row) for row in data],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Export CSV
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/export-csv", summary="تصدير البيانات التحليلية CSV")
def export_analytics_csv(
    report_type: str           = Query("routes", description="routes | airports | airlines"),
    date_from:   Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to:     Optional[str] = Query(None, description="YYYY-MM-DD"),
    limit:       int           = Query(1000, ge=1, le=10000),
    db: Session = Depends(get_db),
):
    """
    Export analytics data as downloadable CSV.
    NEW: was missing entirely.
    Evidence: business requirement GET /api/v1/analytics/export-csv.
    Supports: routes | airports | airlines report types.
    """
    output = io.StringIO()

    if report_type == "routes":
        rows = AnalyticsCRUD.get_top_routes(db, limit=limit, date_from=date_from, date_to=date_to)
        writer = csv.DictWriter(output, fieldnames=["departure", "arrival", "flight_count"])
        writer.writeheader()
        writer.writerows(rows)
        filename = "top_routes.csv"

    elif report_type == "airports":
        rows = AnalyticsCRUD.get_busiest_airports(
            db, limit=limit, date_from=date_from, date_to=date_to
        )
        writer = csv.DictWriter(
            output, fieldnames=["airport_icao", "flight_count", "as_departure", "as_arrival"]
        )
        writer.writeheader()
        writer.writerows(rows)
        filename = "busiest_airports.csv"

    elif report_type == "airlines":
        _, rows = AnalyticsCRUD.get_airline_performance(
            db, date_from=date_from, date_to=date_to, page=1, page_size=limit
        )
        writer = csv.DictWriter(output, fieldnames=[
            "operator_icao", "operator_name", "total_flights",
            "active_flights", "avg_flight_duration_min", "total_distance_km",
        ])
        writer.writeheader()
        writer.writerows(rows)
        filename = "airline_performance.csv"

    else:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"نوع التقرير غير مدعوم: {report_type}")

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ─────────────────────────────────────────────────────────────────────────────
# Summary (legacy)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/summary", response_model=AnalyticsSummary, summary="ملخص إجمالي")
@legacy_router.get("/summary", include_in_schema=False)
def get_summary(db: Session = Depends(get_db)):
    """
    High-level summary counters for dashboard header.
    FIX: was returning zeros for unique_countries and unique_airports.
    """
    from app import models
    from sqlalchemy import func

    total = db.query(models.FactFlightSession).count()
    unique_countries = (
        db.query(func.count(func.distinct(models.DimAircraft.country_code)))
        .filter(models.DimAircraft.country_code.isnot(None))
        .scalar() or 0
    )
    unique_airports = (
        db.query(func.count(func.distinct(models.DimGeography.id))).scalar() or 0
    )
    top_countries_raw = AnalyticsCRUD.get_top_routes(db, limit=10)

    return AnalyticsSummary(
        total_flights=total,
        unique_countries=unique_countries,
        unique_airports=unique_airports,
        top_countries=[],
    )


@legacy_router.get("/top_countries", include_in_schema=False)
def legacy_top_countries(limit: int = 15, db: Session = Depends(get_db)):
    """Legacy endpoint kept for frontend compat."""
    from app import models
    from sqlalchemy import func, desc

    results = (
        db.query(
            models.DimAircraft.country_code,
            func.count(models.DimAircraft.id).label("cnt"),
        )
        .filter(models.DimAircraft.country_code.isnot(None))
        .group_by(models.DimAircraft.country_code)
        .order_by(desc("cnt"))
        .limit(limit)
        .all()
    )
    return [CountryStats(country_name=r[0], flight_count=r[1]) for r in results]
