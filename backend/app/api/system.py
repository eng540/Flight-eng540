"""
System API Endpoints — v2.0 (Truth-Compliant)
Prefix: /api/v1/system

TRUTH COMPLIANCE FIX:
  GET /api/v1/system/credits-usage

  DEVIATION FOUND: Previous version read from IngestionJob.credits_used (DB).
  TRUTH (FR24 OpenAPI): /api/usage returns UsageLogSummary[] directly from FR24.
    Fields: endpoint, request_count, credits
    curl example: {"data":[{"endpoint":"airports/{code}","request_count":5,"credits":5}]}

  FIX: Now calls FR24 GET /api/usage FIRST.
       Falls back to DB aggregation ONLY if FR24 call fails (e.g. no network).
       This matches the Single Source of Truth specification exactly.

  Truth: UsageLogSummary schema:
    endpoint:      string  — Endpoint of the API call
    request_count: integer — Number of requests
    credits:       integer — Number of credits used
"""
import logging
import requests
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.database import get_db
from app.config import settings
from app.schemas import CreditsUsageResponse, CreditsUsageItem

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/system", tags=["system-v1"])


@router.get(
    "/credits-usage",
    response_model=CreditsUsageResponse,
    summary="استهلاك نقاط FR24 API — مباشر من FR24",
)
def get_credits_usage(
    period: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    Returns API credit usage from FR24 /api/usage endpoint.

    TRUTH: FR24 OpenAPI GET /api/usage → UsageLogSummary[]
      Parameters:
        period (optional): string — query param per FR24 spec
      Response:
        data: [{endpoint, request_count, credits}]

    Flow:
      1. Call FR24 GET /api/usage directly (primary source of truth)
      2. If FR24 unavailable → fallback to DB aggregation from IngestionJob
    """
    if settings.is_fr24_configured():
        fr24_result = _call_fr24_usage(period)
        if fr24_result is not None:
            return fr24_result

    # Fallback: DB aggregation (when FR24 unreachable or key not set)
    logger.warning(
        "[system] FR24 /api/usage unavailable — falling back to DB aggregation"
    )
    return _db_fallback_usage(db)


def _call_fr24_usage(period: Optional[str]) -> Optional[CreditsUsageResponse]:
    """
    Calls FR24 GET /api/usage directly.
    Truth: UsageLogSummary[] — {endpoint, request_count, credits}
    """
    headers = {
        "Accept": "application/json",
        "Accept-Version": "v1",
        "Authorization": f"Bearer {settings.FR24_API_KEY}",
    }
    params = {}
    if period:
        params["period"] = period  # Truth: period query param per /api/usage spec

    try:
        response = requests.get(
            f"{settings.FR24_BASE_URL}/api/usage",
            headers=headers,
            params=params,
            timeout=10,
        )
        if response.status_code != 200:
            logger.warning(
                f"[system] FR24 /api/usage returned HTTP {response.status_code}"
            )
            return None

        data = response.json()
        items_raw = data.get("data", [])

        items = []
        total_credits = 0
        for row in items_raw:
            # Truth: UsageLogSummary fields — endpoint, request_count, credits
            credits = int(row.get("credits", 0))
            items.append(CreditsUsageItem(
                endpoint=row.get("endpoint", "unknown"),
                request_count=int(row.get("request_count", 0)),
                credits=credits,
            ))
            total_credits += credits

        logger.info(
            f"[system] FR24 /api/usage: {len(items)} endpoints, "
            f"{total_credits} total credits"
        )
        return CreditsUsageResponse(data=items, total_credits=total_credits)

    except requests.exceptions.Timeout:
        logger.error("[system] FR24 /api/usage timed out")
        return None
    except requests.exceptions.RequestException as exc:
        logger.error(f"[system] FR24 /api/usage network error: {exc}")
        return None
    except (KeyError, ValueError, TypeError) as exc:
        logger.error(f"[system] FR24 /api/usage parse error: {exc}")
        return None


def _db_fallback_usage(db: Session) -> CreditsUsageResponse:
    """
    Fallback: aggregate credits from IngestionJob table when FR24 is unavailable.
    Schema maps job_type → endpoint, count → request_count, sum(credits) → credits.
    """
    from app.models import IngestionJob
    from sqlalchemy import func, desc

    rows = (
        db.query(
            IngestionJob.job_type.label("endpoint"),
            func.count(IngestionJob.id).label("request_count"),
            func.coalesce(func.sum(IngestionJob.credits_used), 0).label("credits"),
        )
        .group_by(IngestionJob.job_type)
        .order_by(desc("credits"))
        .all()
    )

    items = [
        CreditsUsageItem(
            endpoint=r.endpoint or "unknown",
            request_count=r.request_count,
            credits=int(r.credits),
        )
        for r in rows
    ]
    total_credits = sum(i.credits for i in items)
    return CreditsUsageResponse(data=items, total_credits=total_credits)


@router.get("/status", summary="حالة النظام")
def get_system_status(db: Session = Depends(get_db)):
    """System health + FR24 configuration status."""
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    return {
        "database":        "connected" if db_ok else "disconnected",
        "fr24_configured": settings.is_fr24_configured(),
        "fr24_base_url":   settings.FR24_BASE_URL,
        "active_regions":  settings.get_active_region_keys(),
        "retention_days":  settings.DATA_RETENTION_DAYS,
    }
