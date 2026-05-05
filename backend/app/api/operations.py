"""
Operations Board API (System Design §5–§7)
Prefix: /api/v1/operations

ENDPOINTS:
  POST   /api/v1/operations                        ← create + preflight
  GET    /api/v1/operations                        ← list all operations
  GET    /api/v1/operations/credit-rates           ← FR24 rate reference
  GET    /api/v1/operations/{id}                   ← full detail + chunks
  GET    /api/v1/operations/{id}/preflight         ← pre-flight summary
  POST   /api/v1/operations/{id}/approve           ← user confirms → launch
  POST   /api/v1/operations/{id}/cancel            ← request cancellation
  GET    /api/v1/operations/{id}/progress          ← polling (3s interval)
  GET    /api/v1/operations/{id}/chunks            ← chunk list with status
  GET    /api/v1/operations/{id}/results/summary   ← partial results count
  GET    /api/v1/operations/{id}/results/export    ← CSV of ready results

NOTE: /credit-rates MUST appear before /{id} to avoid path collision.
"""
import io
import csv
import math
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.crud.operations import (
    OperationsCRUD, ChunksCRUD, CreditRatesCRUD,
)
from app.services.preflight_engine import PreflightEngine
from app.services.operations_planner import OperationsPlanner
from app.schemas import (
    OperationCreateRequest,
    OperationApproveRequest,
    OperationCancelRequest,
    OperationResponse,
    OperationListResponse,
    OperationProgressResponse,
    PreflightSummary,
    ChunkProgressItem,
    ApiCreditRateResponse,
    PartialResultsSummary,
)
from app.models import Operation, OperationChunk, FactFlightSession
from app.config import settings

router = APIRouter(prefix="/api/v1/operations", tags=["operations-v1"])

# ─────────────────────────────────────────────────────────────────────────────
# STATIC: must appear before /{id} routes
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/credit-rates",
    response_model=list[ApiCreditRateResponse],
    summary="أسعار اعتمادات FR24 API لكل قدرة",
)
def get_credit_rates(db: Session = Depends(get_db)):
    """
    Returns current credit costs per capability type.
    Displayed in the Pre-flight Summary UI.
    Evidence: §4 Pre-flight Engine — "api_credit_rates (DB table — updatable)"
    """
    rates = CreditRatesCRUD.get_all(db)
    return [ApiCreditRateResponse.model_validate(r) for r in rates]


# ─────────────────────────────────────────────────────────────────────────────
# CREATE
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "",
    response_model=PreflightSummary,
    status_code=201,
    summary="إنشاء عملية جديدة + عرض ملخص ما قبل التنفيذ",
)
def create_operation(
    request: OperationCreateRequest,
    db: Session = Depends(get_db),
):
    """
    Step 1+2 of the Operations Wizard:
      1. Creates Operation in 'pending' state.
      2. Computes pre-flight estimates.
      3. Transitions to 'planned'.
      4. Returns PreflightSummary for user review.

    User must then call POST /{id}/approve to launch.
    Evidence: §5 Execution Flow — steps 1–3.
    """
    if not settings.is_fr24_configured():
        raise HTTPException(
            status_code=503,
            detail="FR24_API_KEY غير مُهيّأ — يرجى إضافته في ملف .env",
        )

    # Create in pending state
    op = OperationsCRUD.create(db, request)

    # Compute pre-flight
    engine = PreflightEngine(db)
    summary = engine.compute(op, current_balance=None)

    # Persist estimates + transition pending → planned
    estimates = engine.estimates_dict(op)
    OperationsCRUD.update_estimates(db, op.id, estimates)

    # Refresh the summary with the now-assigned operation_id
    return summary


# ─────────────────────────────────────────────────────────────────────────────
# LIST
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "",
    response_model=OperationListResponse,
    summary="قائمة العمليات",
)
def list_operations(
    status: Optional[str] = Query(
        None,
        description="pending|planned|running|partial|completed|failed|cancelled",
    ),
    capability_type: Optional[str] = Query(None),
    page:      int = Query(1,  ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """
    Paginated list of all operations.
    Used by the Operations Board لوحة تتبع المهمات.
    """
    total, ops = OperationsCRUD.list_operations(
        db,
        status=status,
        capability_type=capability_type,
        page=page,
        page_size=page_size,
    )
    pages = math.ceil(total / page_size) if page_size else 1
    return OperationListResponse(
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
        data=[_op_to_response(op) for op in ops],
    )


# ─────────────────────────────────────────────────────────────────────────────
# DETAIL
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/{operation_id}",
    response_model=OperationResponse,
    summary="تفاصيل عملية مع قائمة الـ chunks",
)
def get_operation(
    operation_id: int,
    include_chunks: bool = Query(True),
    db: Session = Depends(get_db),
):
    op = OperationsCRUD.get_by_id(db, operation_id, include_chunks=include_chunks)
    if not op:
        raise HTTPException(status_code=404, detail=f"العملية {operation_id} غير موجودة")

    response = _op_to_response(op)
    if include_chunks:
        chunks = ChunksCRUD.get_chunks_for_operation(db, operation_id)
        response.chunks = [_chunk_to_item(c) for c in chunks]
    return response


# ─────────────────────────────────────────────────────────────────────────────
# PRE-FLIGHT (re-compute on demand)
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/{operation_id}/preflight",
    response_model=PreflightSummary,
    summary="ملخص ما قبل التنفيذ",
)
def get_preflight(
    operation_id: int,
    db: Session = Depends(get_db),
):
    """
    Returns PreflightSummary for the operation.
    Can be called before approval to re-display the summary.
    Evidence: §4 Pre-flight Engine.
    """
    op = OperationsCRUD.get_by_id(db, operation_id)
    if not op:
        raise HTTPException(status_code=404, detail=f"العملية {operation_id} غير موجودة")
    if op.status not in ("pending", "planned"):
        raise HTTPException(
            status_code=409,
            detail=f"العملية في حالة '{op.status}' — ملخص ما قبل التنفيذ متاح فقط قبل الإطلاق",
        )
    engine = PreflightEngine(db)
    return engine.compute(op, current_balance=None)


# ─────────────────────────────────────────────────────────────────────────────
# APPROVE (launch)
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/{operation_id}/approve",
    response_model=OperationResponse,
    summary="موافقة المستخدم وإطلاق العملية",
)
def approve_operation(
    operation_id: int,
    request: OperationApproveRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    User clicks 'إطلاق' after reviewing PreflightSummary.
    1. Validates confirmed=True.
    2. Transitions: planned → running.
    3. Creates all OperationChunk rows.
    4. Dispatches Celery task (async).
    Evidence: §5 Execution Flow — approve → create_chunks → dispatch.
    """
    if not request.confirmed:
        raise HTTPException(
            status_code=400,
            detail="يجب تأكيد قراءة ملخص ما قبل التنفيذ (confirmed=true)",
        )

    op = OperationsCRUD.get_by_id(db, operation_id)
    if not op:
        raise HTTPException(status_code=404, detail=f"العملية {operation_id} غير موجودة")

    try:
        op = OperationsCRUD.approve(db, operation_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    # Create all chunks
    OperationsPlanner.create_chunks(db, op)
    db.commit()
    db.refresh(op)

    # Dispatch Celery task (non-blocking)
    background_tasks.add_task(_dispatch_operation_task, operation_id)

    return _op_to_response(op)


# ─────────────────────────────────────────────────────────────────────────────
# CANCEL
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/{operation_id}/cancel",
    response_model=OperationResponse,
    summary="طلب إلغاء العملية",
)
def cancel_operation(
    operation_id: int,
    request: OperationCancelRequest,
    db: Session = Depends(get_db),
):
    """
    Sets cancel_requested=True. Worker will stop after current chunk completes.
    Already-collected results are preserved and exportable.
    Evidence: §7 Failure Handling — user cancels.
    """
    try:
        op = OperationsCRUD.request_cancel(db, operation_id, request.reason)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    if not op:
        raise HTTPException(status_code=404, detail=f"العملية {operation_id} غير موجودة")

    return _op_to_response(op)


# ─────────────────────────────────────────────────────────────────────────────
# PROGRESS (polling endpoint — optimized for 3s interval)
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/{operation_id}/progress",
    response_model=OperationProgressResponse,
    summary="تقدم العملية — استطلاع كل 3 ثوانٍ",
)
def get_progress(
    operation_id: int,
    db: Session = Depends(get_db),
):
    """
    Lightweight progress endpoint.
    Reads from operation_progress_view for sub-50ms response.
    Evidence: §6 "polling every 3s — operation_progress_view"
    """
    progress = OperationsCRUD.get_progress(db, operation_id)
    if not progress:
        raise HTTPException(status_code=404, detail=f"العملية {operation_id} غير موجودة")

    op = OperationsCRUD.get_by_id(db, operation_id)
    return OperationProgressResponse(
        id=progress["id"],
        operation_ref=progress["operation_ref"],
        capability_type=progress["capability_type"],
        status=progress["status"],
        chunks_total=progress["chunks_total"],
        chunks_completed=progress["chunks_completed"],
        chunks_failed=progress["chunks_failed"],
        chunks_cancelled=progress["chunks_cancelled"],
        progress_pct=float(progress.get("progress_pct") or 0),
        total_results_count=progress.get("total_results_count") or 0,
        actual_credits_used=progress.get("actual_credits_used") or 0,
        estimated_credits=progress.get("estimated_credits") or 0,
        cancel_requested=bool(progress.get("cancel_requested")),
        created_at=progress.get("created_at"),
        started_at=progress.get("started_at"),
        completed_at=progress.get("completed_at"),
        current_chunk=progress.get("current_chunk"),
        last_completed_chunk=progress.get("last_completed_chunk"),
        is_terminal=op.is_terminal if op else True,
        can_be_cancelled=op.can_be_cancelled if op else False,
    )


# ─────────────────────────────────────────────────────────────────────────────
# CHUNKS LIST
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/{operation_id}/chunks",
    summary="قائمة الـ chunks مع حالة كل منها",
)
def get_chunks(
    operation_id: int,
    db: Session = Depends(get_db),
):
    """
    Returns all chunks for an operation with live status.
    Evidence: §2 "بطاقة لكل chunk توضح: ماذا تفعل، حالتها، نتائجها"
    """
    op = OperationsCRUD.get_by_id(db, operation_id)
    if not op:
        raise HTTPException(status_code=404, detail=f"العملية {operation_id} غير موجودة")

    chunks = ChunksCRUD.get_chunks_for_operation(db, operation_id)
    return {
        "operation_id":  operation_id,
        "operation_ref": op.operation_ref,
        "total":         len(chunks),
        "data":          [_chunk_to_item(c) for c in chunks],
    }


# ─────────────────────────────────────────────────────────────────────────────
# PARTIAL RESULTS
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/{operation_id}/results/summary",
    response_model=PartialResultsSummary,
    summary="ملخص النتائج الجاهزة الآن",
)
def get_results_summary(
    operation_id: int,
    db: Session = Depends(get_db),
):
    """
    Returns count of results available NOW from completed chunks.
    Available even while operation is still running (partial).
    Evidence: §6 "أريد أن أتمكن من رؤية نتائج الأسبوع الأول
              بمجرد أن يصبح جاهزًا"
    """
    try:
        return OperationsCRUD.get_partial_results_summary(db, operation_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get(
    "/{operation_id}/results/export",
    summary="تصدير CSV للنتائج الجاهزة الآن",
)
def export_results(
    operation_id: int,
    db: Session = Depends(get_db),
):
    """
    Exports all available results as CSV based on the capability type.
    Handles empty results gracefully with clear messages.
    """
    op = OperationsCRUD.get_by_id(db, operation_id)
    if not op:
        raise HTTPException(status_code=404, detail=f"العملية {operation_id} غير موجودة")

    output = io.StringIO()

    # ── Static Airport ────────────────────────────────────────────────────
    if op.capability_type == "static_airport":
        from app.models import DimGeography

        entity_id = op.scope_entity_id
        if not entity_id:
            raise HTTPException(
                status_code=404,
                detail="لم يتم تحديد رمز مطار عند إنشاء العملية. لا توجد بيانات للتصدير."
            )

        airport = db.query(DimGeography).filter(
            DimGeography.icao_code == entity_id
        ).first()

        if not airport:
            raise HTTPException(
                status_code=404,
                detail=f"المطار {entity_id} غير موجود في قاعدة البيانات."
            )

        writer = csv.DictWriter(output, fieldnames=[
            "icao_code", "iata_code", "name", "city", "country_code",
            "latitude", "longitude", "elevation_m"
        ])
        writer.writeheader()
        writer.writerow({
            "icao_code": airport.icao_code,
            "iata_code": airport.iata_code or "",
            "name": airport.name,
            "city": airport.city or "",
            "country_code": airport.country_code or "",
            "latitude": airport.latitude or "",
            "longitude": airport.longitude or "",
            "elevation_m": airport.elevation_m or "",
        })

    # ── Static Airline ────────────────────────────────────────────────────
    elif op.capability_type == "static_airline":
        from app.models import DimOperator

        entity_id = op.scope_entity_id
        if not entity_id:
            raise HTTPException(
                status_code=404,
                detail="لم يتم تحديد رمز شركة طيران عند إنشاء العملية. لا توجد بيانات للتصدير."
            )

        operator = db.query(DimOperator).filter(
            DimOperator.icao_code == entity_id
        ).first()

        if not operator:
            raise HTTPException(
                status_code=404,
                detail=f"شركة الطيران {entity_id} غير موجودة في قاعدة البيانات."
            )

        writer = csv.DictWriter(output, fieldnames=[
            "icao_code", "iata_code", "name", "country_code"
        ])
        writer.writeheader()
        writer.writerow({
            "icao_code": operator.icao_code,
            "iata_code": operator.iata_code or "",
            "name": operator.name,
            "country_code": operator.country_code or "",
        })

    # ── Flight Summaries / Live / Historic / Tracks ──────────────────────
    else:
        sessions = (
            db.query(FactFlightSession)
            .filter(FactFlightSession.operation_id == operation_id)
            .order_by(FactFlightSession.first_seen_ts.asc())
            .all()
        )

        if not sessions:
            raise HTTPException(
                status_code=404,
                detail="لا توجد نتائج جاهزة للتصدير. قد تكون العملية لم تكتمل بعد، أو فشلت القطع (chunks)."
            )

        writer = csv.DictWriter(output, fieldnames=[
            "session_id", "fr24_id", "flight_number", "callsign", "status",
            "aircraft_icao24", "operator", "dep_airport", "arr_airport",
            "first_seen", "last_seen", "max_altitude_m", "total_distance_km",
        ])
        writer.writeheader()
        for s in sessions:
            writer.writerow({
                "session_id":    s.session_id,
                "fr24_id":       s.fr24_id or "",
                "flight_number": s.flight_number or "",
                "callsign":      s.callsign or "",
                "status":        s.flight_status or "",
                "aircraft_icao24": s.aircraft.icao24 if s.aircraft else "",
                "operator":      s.operator.icao_code if s.operator else "",
                "dep_airport":   s.dep_airport.icao_code if s.dep_airport else "",
                "arr_airport":   s.arr_airport.icao_code if s.arr_airport else "",
                "first_seen":    s.first_seen_ts.isoformat() if s.first_seen_ts else "",
                "last_seen":     s.last_seen_ts.isoformat()  if s.last_seen_ts  else "",
                "max_altitude_m":    s.max_altitude_m    or "",
                "total_distance_km": s.total_distance_km or "",
            })

    output.seek(0)
    filename = f"operation_{op.operation_ref}_results.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ─────────────────────────────────────────────────────────────────────────────
# INTERNAL HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _op_to_response(op: Operation) -> OperationResponse:
    return OperationResponse(
        id=op.id,
        operation_ref=op.operation_ref,
        capability_type=op.capability_type,
        scope_region_key=op.scope_region_key,
        scope_date_from=op.scope_date_from,
        scope_date_to=op.scope_date_to,
        scope_entity_id=op.scope_entity_id,
        scope_entity_type=op.scope_entity_type,
        scope_filters=op.scope_filters,
        scope_bounds=op.scope_bounds,
        estimated_chunks=op.estimated_chunks,
        estimated_api_calls=op.estimated_api_calls,
        estimated_credits=op.estimated_credits,
        estimated_duration_seconds=op.estimated_duration_seconds,
        estimated_results=op.estimated_results,
        actual_api_calls=op.actual_api_calls,
        actual_credits_used=op.actual_credits_used,
        actual_duration_seconds=op.actual_duration_seconds,
        total_results_count=op.total_results_count,
        status=op.status,
        progress_pct=op.progress_pct,
        chunks_total=op.chunks_total,
        chunks_completed=op.chunks_completed,
        chunks_failed=op.chunks_failed,
        chunks_cancelled=op.chunks_cancelled,
        preflight_shown_at=op.preflight_shown_at,
        approved_at=op.approved_at,
        created_at=op.created_at,
        started_at=op.started_at,
        completed_at=op.completed_at,
        cancelled_at=op.cancelled_at,
        cancel_requested=op.cancel_requested,
        cancel_reason=op.cancel_reason,
        failure_reason=op.failure_reason,
    )


# Status icon + Arabic label per chunk status
_CHUNK_STATUS_MAP = {
    "pending":   ("⏸️", "في الانتظار"),
    "running":   ("⏳", "جاري التنفيذ"),
    "completed": ("✅", "مكتمل"),
    "failed":    ("❌", "فشل"),
    "cancelled": ("🚫", "ملغى"),
    "skipped":   ("⏭️", "تم التخطي"),
}


def _chunk_to_item(c: OperationChunk) -> ChunkProgressItem:
    icon, label = _CHUNK_STATUS_MAP.get(c.status, ("❓", c.status))

    # Build human-readable label
    if c.date_from:
        from app.services.preflight_engine import _date_label
        from datetime import date
        d = c.date_from if isinstance(c.date_from, date) else date.fromisoformat(str(c.date_from))
        display_label = _date_label(d)
    elif c.entity_id:
        display_label = f"كيان: {c.entity_id}"
    elif c.region_key:
        display_label = f"منطقة: {c.region_key}"
    else:
        display_label = f"chunk #{c.chunk_index}"

    return ChunkProgressItem(
        chunk_index=c.chunk_index,
        label=display_label,
        date_from=c.date_from.isoformat() if c.date_from else None,
        date_to=c.date_to.isoformat()     if c.date_to   else None,
        entity_id=c.entity_id,
        region_key=c.region_key,
        fr24_endpoint=c.fr24_endpoint,
        fr24_params=c.fr24_params,
        status=c.status,
        attempt_count=c.attempt_count,
        results_count=c.results_count,
        credits_used=c.credits_used,
        started_at=c.started_at,
        completed_at=c.completed_at,
        next_retry_at=c.next_retry_at,
        last_error=c.last_error,
        http_status=c.http_status,
        partial_result_key=c.partial_result_key,
        status_icon=icon,
        status_label=label,
    )


def _dispatch_operation_task(operation_id: int) -> None:
    """Dispatches the Celery execution task asynchronously."""
    try:
        from worker.celery_app import celery_app
        celery_app.send_task("worker.tasks.operations_task.execute_operation_task", args=[operation_id])
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error(
            f"[Operations] Failed to dispatch task for op {operation_id}: {exc}"
        )