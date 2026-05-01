"""
Live Positions API — v1.0 (TIER 3 New)
Prefix: /api/v1/live

ENDPOINTS:
  GET /api/v1/live/positions   ← real-time aircraft on map

Evidence: business requirement GET /api/v1/live/positions
Source: CurrentAircraftState denormalized table — single query, no joins.
Designed for sub-100ms response even at 1000+ concurrent aircraft.
"""
import math
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.crud import FlightQueryCRUD
from app.schemas import LivePositionsResponse, LivePositionResponse

router = APIRouter(prefix="/api/v1/live", tags=["live-v1"])


@router.get("/positions", response_model=LivePositionsResponse, summary="مواقع الطائرات اللحظية")
def get_live_positions(
    region_key: Optional[str] = Query(None, description="فلترة حسب المنطقة الجغرافية"),
    on_ground:  Optional[bool] = Query(None, description="true=على الأرض | false=في الجو"),
    limit:      int = Query(1000, ge=1, le=5000, description="الحد الأقصى للنتائج"),
    page:       int = Query(1, ge=1),
    db: Session = Depends(get_db),
):
    """
    Real-time positions for the live map.

    Reads from CurrentAircraftState (denormalized cache table):
    - Updated every ingestion cycle (~60s)
    - Excludes aircraft not seen in last 15 minutes
    - Single query, no JOINs, no N+1
    - Supports region and on_ground filtering via indexed columns

    Returns total count + active (airborne) count for dashboard counters.
    """
    positions, total = FlightQueryCRUD.get_live_positions(
        db,
        region_key=region_key,
        on_ground=on_ground,
        limit=limit,
        page=page,
    )

    active_count = sum(1 for p in positions if p.on_ground is False)

    return LivePositionsResponse(
        total=total,
        active=active_count,
        data=[LivePositionResponse.model_validate(p) for p in positions],
    )
