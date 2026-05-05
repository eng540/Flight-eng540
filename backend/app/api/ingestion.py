"""
Ingestion API Endpoints — v4.0 (TIER 3 Fixed)
Prefix: /ingestion (legacy) + /api/v1/ingestion

FIX: All endpoints were stubs returning empty data.
Evidence: ingestion.py — list_jobs() returned {"total": 0, "data": []}
          get_job() returned None
Now delegates to IngestionJobCRUD which queries the DB.
"""
import math
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session

from app.database import get_db
from app.crud import IngestionJobCRUD
from app.schemas import (
    IngestionJobResponse,
    IngestionJobListResponse,
    IngestionStartRequest,
)
from app.config import settings

router     = APIRouter(prefix="/ingestion",     tags=["ingestion"])
router_v1  = APIRouter(prefix="/api/v1/ingestion", tags=["ingestion-v1"])


def _job_list_response(total, results, page, page_size):
    pages = math.ceil(total / page_size) if page_size else 1
    return {
        "total":     total,
        "page":      page,
        "page_size": page_size,
        "pages":     pages,
        "data":      [IngestionJobResponse.model_validate(j) for j in results],
    }


# ── List Jobs ──────────────────────────────────────────────────────────────

@router.get("/jobs")
@router_v1.get("/jobs", summary="قائمة مهام الاستيعاب")
def list_jobs(
    status:     Optional[str] = Query(None, description="pending|running|completed|failed"),
    region_key: Optional[str] = Query(None),
    page:       int           = Query(1,  ge=1),
    page_size:  int           = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """
    FIX: was returning {"total": 0, "data": []} — hardcoded stub.
    Now queries IngestionJob table via IngestionJobCRUD.list_jobs().
    """
    total, results = IngestionJobCRUD.list_jobs(
        db, status=status, region_key=region_key, page=page, page_size=page_size
    )
    return _job_list_response(total, results, page, page_size)


# ── Get Single Job ─────────────────────────────────────────────────────────

@router.get("/jobs/{job_id}")
@router_v1.get("/jobs/{job_id}", summary="تفاصيل مهمة واحدة")
def get_job(job_id: int, db: Session = Depends(get_db)):
    """
    FIX: was returning None — stub with no DB access.
    Now queries IngestionJob by ID.
    """
    job = IngestionJobCRUD.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"المهمة {job_id} غير موجودة")
    return IngestionJobResponse.model_validate(job)


# ── Start Historical Ingestion ─────────────────────────────────────────────

@router_v1.post("/start", summary="بدء استيعاب تاريخي")
def start_historical_ingestion(
    request: IngestionStartRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Trigger historical ingestion for a date range + region list.
    Creates IngestionJob records and dispatches Celery tasks.
    """
    if not settings.is_fr24_configured():
        raise HTTPException(
            status_code=503,
            detail="FR24_API_KEY غير مُهيّأ — يرجى إضافته في ملف .env",
        )

    created_jobs = []
    for region_key in request.region_keys:
        region = settings.get_region(region_key)
        if not region:
            continue

        job = IngestionJobCRUD.create_job(
            db,
            job_type="historic",
            region_key=region_key,
            date_str=request.begin_date,
            lamin=region.lamin,
            lomin=region.lomin,
            lamax=region.lamax,
            lomax=region.lomax,
        )
        created_jobs.append(job.id)

        # Dispatch Celery task
        try:
            from worker.tasks import ingest_historical_flights
            ingest_historical_flights.delay(
                begin_date=request.begin_date,
                end_date=request.end_date,
                region_keys=[region_key],
                force_reingest=request.force_reingest,
            )
        except Exception as exc:
            # Non-fatal: job created, worker dispatch failed
            IngestionJobCRUD.update_job(
                db, job.id,
                status="failed",
                error_message=f"Worker dispatch failed: {exc}",
            )

    return {
        "status":       "dispatched",
        "jobs_created": len(created_jobs),
        "job_ids":      created_jobs,
        "begin_date":   request.begin_date,
        "end_date":     request.end_date,
        "regions":      request.region_keys,
    }
