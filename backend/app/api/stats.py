"""
Enterprise Stats API Endpoints (MVP Delivery)
Reads fast aggregations from the Snowflake Schema.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text, func
from datetime import datetime, timedelta, timezone
import logging

from app.database import get_db
from app import models
from app.schemas import FlightStatistics, HealthCheck, DailyFlightStats

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/stats", tags=["statistics"])

@router.get("", response_model=FlightStatistics)
async def get_statistics(db: Session = Depends(get_db)):
    """MVP: Deliver actual stats from the new Enterprise tables."""
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=7)
    month_start = today_start - timedelta(days=30)

    # 1. Fast Total counts
    total_flights = db.query(models.FactFlightSession).count()
    flights_today = db.query(models.FactFlightSession).filter(models.FactFlightSession.first_seen_ts >= today_start).count()
    flights_this_week = db.query(models.FactFlightSession).filter(models.FactFlightSession.first_seen_ts >= week_start).count()
    flights_this_month = db.query(models.FactFlightSession).filter(models.FactFlightSession.first_seen_ts >= month_start).count()

    # 2. Daily Stats (Simple Rollup)
    daily_stats = []
    for i in range(7):
        day = today_start - timedelta(days=i)
        next_day = day + timedelta(days=1)
        cnt = db.query(models.FactFlightSession).filter(
            models.FactFlightSession.first_seen_ts >= day,
            models.FactFlightSession.first_seen_ts < next_day
        ).count()
        daily_stats.append(DailyFlightStats(date=day.strftime("%Y-%m-%d"), flight_count=cnt))
    daily_stats.reverse()

    return FlightStatistics(
        total_flights=total_flights,
        daily_stats=daily_stats,
        top_airlines=[], # Temporarily empty for UI safety
        top_countries=[], # Temporarily empty for UI safety
        flights_today=flights_today,
        flights_this_week=flights_this_week,
        flights_this_month=flights_this_month
    )

@router.get("/airlines")
async def get_airline_statistics(limit: int = 10, db: Session = Depends(get_db)):
    return {"data": []}

@router.get("/health")
async def health_check(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        logger.error(f"DB health check failed: {e}")
        db_status = "disconnected"
    # FIX: datetime.utcnow() → datetime.now(timezone.utc) — naive datetime
    # causes type mismatch with PostgreSQL TIMESTAMPTZ columns.
    return HealthCheck(status="healthy" if db_status=="connected" else "unhealthy", timestamp=datetime.now(timezone.utc), database=db_status)