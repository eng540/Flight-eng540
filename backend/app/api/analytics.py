"""
Analytics API Endpoints — v4.2 (Deep Filtering & Pagination Enabled)
Prefix: /api/v1/analytics

ENDPOINTS:
  GET /api/v1/analytics/top-routes
  GET /api/v1/analytics/busiest-airports
  GET /api/v1/analytics/daily-summary
  GET /api/v1/analytics/time-distribution
  GET /api/v1/analytics/airline-performance
  GET /api/v1/analytics/export-csv

CHANGES FROM v4.1:
  [ENHANCEMENT] All endpoints now accept deep filters: operator_icao, dep_icao, arr_icao, region_key.
  [ENHANCEMENT] top-routes and busiest-airports now support `page` parameter for full pagination.
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
    page:          int           = Query(1, ge=1),
    limit:         int           = Query(10, ge=1, le=100),
    date_from:     Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to:       Optional[str] = Query(None, description="YYYY-MM-DD"),
    operator_icao: Optional[str] = Query(None, description="كود الناقل ICAO"),
    dep_icao:      Optional[str] = Query(None, description="مطار المغادرة ICAO"),
    arr_icao:      Optional[str] = Query(None, description="مطار الوصول ICAO"),
    region_key:    Optional[str] = Query(None, description="مفتاح المنطقة"),
    db: Session = Depends(get_db),
):
    total, routes = AnalyticsCRUD.get_top_routes(
        db, limit=limit, page=page, date_from=date_from, date_to=date_to,
        operator_icao=operator_icao, dep_icao=dep_icao, arr_icao=arr_icao, region_key=region_key
    )
    pages = math.ceil(total / limit) if limit else 1
    return {"total": total, "page": page, "pages": pages, "data": routes}


# ─────────────────────────────────────────────────────────────────────────────
# Busiest Airports
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/busiest-airports", summary="أكثر المطارات ازدحاماً")
@legacy_router.get("/top_airports", include_in_schema=False)
def get_busiest_airports(
    page:          int           = Query(1, ge=1),
    limit:         int           = Query(15, ge=1, le=100),
    date_from:     Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to:       Optional[str] = Query(None, description="YYYY-MM-DD"),
    operator_icao: Optional[str] = Query(None, description="كود الناقل ICAO"),
    dep_icao:      Optional[str] = Query(None, description="مطار المغادرة ICAO"),
    arr_icao:      Optional[str] = Query(None, description="مطار الوصول ICAO"),
    region_key:    Optional[str] = Query(None, description="مفتاح المنطقة"),
    db: Session = Depends(get_db),
):
    total, airports = AnalyticsCRUD.get_busiest_airports(
        db, limit=limit, page=page, date_from=date_from, date_to=date_to,
        operator_icao=operator_icao, dep_icao=dep_icao, arr_icao=arr_icao, region_key=region_key
    )
    pages = math.ceil(total / limit) if limit else 1
    return {"total": total, "page": page, "pages": pages, "data": airports}


# ─────────────────────────────────────────────────────────────────────────────
# Period Summary
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/daily-summary", summary="ملخص الرحلات للفترة المحددة")
def get_daily_summary(
    date_from:     Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to:       Optional[str] = Query(None, description="YYYY-MM-DD"),
    operator_icao: Optional[str] = Query(None, description="كود الناقل ICAO"),
    dep_icao:      Optional[str] = Query(None, description="مطار المغادرة ICAO"),
    arr_icao:      Optional[str] = Query(None, description="مطار الوصول ICAO"),
    region_key:    Optional[str] = Query(None, description="مفتاح المنطقة"),
    db: Session = Depends(get_db),
):
    summary = AnalyticsCRUD.get_period_summary(
        db, date_from=date_from, date_to=date_to,
        operator_icao=operator_icao, dep_icao=dep_icao, arr_icao=arr_icao, region_key=region_key
    )
    return summary


# ─────────────────────────────────────────────────────────────────────────────
# Time Distribution
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/time-distribution", summary="التوزيع الزمني للرحلات (حسب ساعات اليوم)")
def get_time_distribution(
    date_from:     Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to:       Optional[str] = Query(None, description="YYYY-MM-DD"),
    operator_icao: Optional[str] = Query(None, description="كود الناقل ICAO"),
    dep_icao:      Optional[str] = Query(None, description="مطار المغادرة ICAO"),
    arr_icao:      Optional[str] = Query(None, description="مطار الوصول ICAO"),
    region_key:    Optional[str] = Query(None, description="مفتاح المنطقة"),
    db: Session = Depends(get_db),
):
    distribution = AnalyticsCRUD.get_time_distribution(
        db, date_from=date_from, date_to=date_to,
        operator_icao=operator_icao, dep_icao=dep_icao, arr_icao=arr_icao, region_key=region_key
    )
    return {"data": distribution}


# ─────────────────────────────────────────────────────────────────────────────
# Airline Performance
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/airline-performance", summary="أداء شركات الطيران")
def get_airline_performance(
    page:          int           = Query(1,  ge=1),
    page_size:     int           = Query(20, ge=1, le=200),
    date_from:     Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to:       Optional[str] = Query(None, description="YYYY-MM-DD"),
    operator_icao: Optional[str] = Query(None, description="كود الناقل ICAO"),
    dep_icao:      Optional[str] = Query(None, description="مطار المغادرة ICAO"),
    arr_icao:      Optional[str] = Query(None, description="مطار الوصول ICAO"),
    region_key:    Optional[str] = Query(None, description="مفتاح المنطقة"),
    db: Session = Depends(get_db),
):
    total, data = AnalyticsCRUD.get_airline_performance(
        db, limit=page_size, page=page, date_from=date_from, date_to=date_to,
        operator_icao=operator_icao, dep_icao=dep_icao, arr_icao=arr_icao, region_key=region_key
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
    report_type:   str           = Query("routes", description="routes | airports | airlines"),
    limit:         int           = Query(1000, ge=1, le=10000),
    date_from:     Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to:       Optional[str] = Query(None, description="YYYY-MM-DD"),
    operator_icao: Optional[str] = Query(None, description="كود الناقل ICAO"),
    dep_icao:      Optional[str] = Query(None, description="مطار المغادرة ICAO"),
    arr_icao:      Optional[str] = Query(None, description="مطار الوصول ICAO"),
    region_key:    Optional[str] = Query(None, description="مفتاح المنطقة"),
    db: Session = Depends(get_db),
):
    output = io.StringIO()

    if report_type == "routes":
        _, rows = AnalyticsCRUD.get_top_routes(
            db, limit=limit, page=1, date_from=date_from, date_to=date_to,
            operator_icao=operator_icao, dep_icao=dep_icao, arr_icao=arr_icao, region_key=region_key
        )
        writer = csv.DictWriter(output, fieldnames=["departure", "arrival", "flight_count"])
        writer.writeheader()
        writer.writerows(rows)
        filename = "top_routes.csv"

    elif report_type == "airports":
        _, rows = AnalyticsCRUD.get_busiest_airports(
            db, limit=limit, page=1, date_from=date_from, date_to=date_to,
            operator_icao=operator_icao, dep_icao=dep_icao, arr_icao=arr_icao, region_key=region_key
        )
        writer = csv.DictWriter(
            output, fieldnames=["airport_icao", "flight_count", "as_departure", "as_arrival"]
        )
        writer.writeheader()
        writer.writerows(rows)
        filename = "busiest_airports.csv"

    elif report_type == "airlines":
        _, rows = AnalyticsCRUD.get_airline_performance(
            db, limit=limit, page=1, date_from=date_from, date_to=date_to,
            operator_icao=operator_icao, dep_icao=dep_icao, arr_icao=arr_icao, region_key=region_key
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

    return AnalyticsSummary(
        total_flights=total,
        unique_countries=unique_countries,
        unique_airports=unique_airports,
        top_countries=[],
    )


@legacy_router.get("/top_countries", include_in_schema=False)
def legacy_top_countries(limit: int = 15, db: Session = Depends(get_db)):
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