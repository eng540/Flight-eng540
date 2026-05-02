"""
System API Endpoints — v1.0 (TIER 3 New)
Prefix: /api/v1/system

ENDPOINTS:
  GET /api/v1/system/credits-usage   ← FR24 API budget tracker

Evidence: business requirement GET /api/v1/system/credits-usage
FR24 OpenAPI UsageLogSummary schema: {endpoint, request_count, credits}
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.crud import AnalyticsCRUD
from app.schemas import CreditsUsageResponse, CreditsUsageItem
from app.config import settings

router = APIRouter(prefix="/api/v1/system", tags=["system-v1"])


@router.get("/credits-usage", response_model=CreditsUsageResponse,
            summary="استهلاك نقاط FR24 API")
def get_credits_usage(db: Session = Depends(get_db)):
    """
    Aggregate FR24 API credit consumption per endpoint type.
    Data sourced from IngestionJob.credits_used column.
    Maps to FR24 OpenAPI UsageLogSummary schema:
      endpoint: job_type (live | historic | enrich)
      request_count: number of jobs of this type
      credits: sum of credits_used

    Evidence: business requirement GET /api/v1/system/credits-usage
    FR24 OpenAPI: UsageLogSummary.{endpoint, request_count, credits}
    """
    rows = AnalyticsCRUD.get_credits_summary(db)
    total_credits = sum(r["credits"] for r in rows)

    return CreditsUsageResponse(
        data=[CreditsUsageItem(**r) for r in rows],
        total_credits=total_credits,
    )


@router.get("/status", summary="حالة النظام")
def get_system_status(db: Session = Depends(get_db)):
    """System health + FR24 configuration status."""
    from sqlalchemy import text
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    return {
        "database":        "connected"    if db_ok else "disconnected",
        "fr24_configured": settings.is_fr24_configured(),
        "fr24_base_url":   settings.FR24_BASE_URL,
        "active_regions":  settings.get_active_region_keys(),
        "retention_days":  settings.DATA_RETENTION_DAYS,
    }


@router.get("/seed-static-data", summary="تغذية قاعدة البيانات بالمطارات والشركات")
def seed_data_endpoint(db: Session = Depends(get_db)):
    """
    رابط خفي لتشغيل سكربت التغذية. يفتح من المتصفح مباشرة.
    """
    from app.services.static_seeder import seed_all_static_data
    return seed_all_static_data(db)