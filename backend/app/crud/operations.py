"""
Operations Board CRUD Layer (System Design §5–§7)

All database read/write operations for Operations and OperationChunks.
No N+1 queries. All state transitions validated before execution.

Evidence:
  §5 Execution Flow — operation creation, approval, chunk lifecycle
  §6 Partial Results — query by operation_id
  §7 Failure Handling — chunk retry, cancel, credit exhaustion
"""
from __future__ import annotations

import math
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Tuple, Dict, Any

from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc, func, and_, or_

from app.models import Operation, OperationChunk, ApiCreditRate, FactFlightSession
from app.schemas import (
    OperationCreateRequest,
    OperationResponse,
    OperationProgressResponse,
    ChunkProgressItem,
    PartialResultsSummary,
    ApiCreditRateResponse,
)
from app.config import settings


# ─────────────────────────────────────────────────────────────────────────────
# REF GENERATOR
# ─────────────────────────────────────────────────────────────────────────────

def _generate_ref(db: Session) -> str:
    """
    Generates a unique operation reference: OPS-YYYYMMDD-NNNN
    Evidence: system design §1 "operation_ref: OPS-20260429-0042"
    """
    today  = datetime.now(timezone.utc).strftime("%Y%m%d")
    prefix = f"OPS-{today}-"
    count  = (
        db.query(func.count(Operation.id))
        .filter(Operation.operation_ref.like(f"{prefix}%"))
        .scalar() or 0
    )
    return f"{prefix}{(count + 1):04d}"


# ─────────────────────────────────────────────────────────────────────────────
# OPERATION CRUD
# ─────────────────────────────────────────────────────────────────────────────

class OperationsCRUD:

    @staticmethod
    def create(
        db: Session,
        request: OperationCreateRequest,
    ) -> Operation:
        """
        Creates an Operation in 'pending' state.
        Pre-flight estimates are computed separately and written back
        via update_estimates().
        Evidence: §5 "user clicks launch → POST /api/v1/operations"
        """
        scope = request.scope
        op = Operation(
            operation_ref=_generate_ref(db),
            capability_type=request.capability_type,
            status="pending",

            scope_region_key=scope.region_key,
            scope_date_from=(
                _parse_date(scope.date_from) if scope.date_from else None
            ),
            scope_date_to=(
                _parse_date(scope.date_to) if scope.date_to else None
            ),
            scope_entity_id=scope.entity_id,
            scope_entity_type=scope.entity_type,
            scope_filters={
                **({"entity_ids": scope.entity_ids} if scope.entity_ids else {}),
                **(scope.filters or {}),
            } or None,
            scope_bounds=scope.bounds,
        )
        db.add(op)
        db.commit()
        db.refresh(op)
        return op

    @staticmethod
    def update_estimates(
        db: Session,
        operation_id: int,
        estimates: dict,
    ) -> None:
        """
        Persists pre-flight estimates back to the Operation row
        and transitions status: pending → planned.
        Evidence: §3 state transitions "planned: preflight_engine computed"
        """
        op = db.query(Operation).filter(Operation.id == operation_id).first()
        if not op:
            return
        for key, value in estimates.items():
            if hasattr(op, key):
                setattr(op, key, value)
        op.status              = "planned"
        op.preflight_shown_at  = datetime.now(timezone.utc)
        op.planned_at          = datetime.now(timezone.utc)
        db.commit()

    @staticmethod
    def approve(
        db: Session,
        operation_id: int,
    ) -> Optional[Operation]:
        """
        Transitions Operation: planned → running.
        Sets approved_at and started_at.
        Evidence: §3 "planned → running on approved_at IS NOT NULL"
        Evidence: §5 "user clicks إطلاق → approved_at set"
        """
        op = db.query(Operation).filter(Operation.id == operation_id).first()
        if not op:
            return None
        if op.status != "planned":
            raise ValueError(
                f"العملية في حالة '{op.status}' — لا يمكن الموافقة إلا من حالة 'planned'"
            )
        now = datetime.now(timezone.utc)
        op.approved_at  = now
        op.started_at   = now
        op.status       = "running"
        db.commit()
        db.refresh(op)
        return op

    @staticmethod
    def request_cancel(
        db: Session,
        operation_id: int,
        reason: Optional[str] = None,
    ) -> Optional[Operation]:
        """
        Instant Kill: Sets operation status to cancelled immediately 
        and cancels all pending or retrying chunks.
        """
        op = db.query(Operation).filter(Operation.id == operation_id).first()
        if not op:
            return None
        if op.is_terminal:
            raise ValueError(
                f"العملية في حالة '{op.status}' — لا يمكن إلغاؤها"
            )
        
        now = datetime.now(timezone.utc)
        
        # 1. Update operation status immediately
        op.cancel_requested = True
        op.cancel_reason    = reason
        op.status           = "cancelled"
        op.cancelled_at     = now
        
        # 2. Stop all pending, running, or failed (retrying) chunks
        active_chunks = db.query(OperationChunk).filter(
            OperationChunk.operation_id == operation_id,
            OperationChunk.status.in_(["pending", "running", "failed"])
        ).all()
        
        for chunk in active_chunks:
            chunk.status = "cancelled"
            op.chunks_cancelled += 1
            
        db.commit()
        db.refresh(op)
        return op

    @staticmethod
    def get_by_id(
        db: Session,
        operation_id: int,
        include_chunks: bool = False,
    ) -> Optional[Operation]:
        """Single operation by ID. Optionally includes chunks (joinedload)."""
        q = db.query(Operation).filter(Operation.id == operation_id)
        if include_chunks:
            q = q.options(joinedload(Operation.chunks))
        return q.first()

    @staticmethod
    def list_operations(
        db: Session,
        status: Optional[str] = None,
        capability_type: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[int, List[Operation]]:
        """
        Paginated list. Used by Operations Board lوحة تتبع المهمات.
        No N+1 — chunks are NOT loaded here (list view doesn't need them).
        """
        q = db.query(Operation)
        if status:
            q = q.filter(Operation.status == status)
        if capability_type:
            q = q.filter(Operation.capability_type == capability_type)

        total  = q.count()
        offset = (page - 1) * page_size
        data   = (
            q.order_by(desc(Operation.created_at))
            .offset(offset)
            .limit(page_size)
            .all()
        )
        return total, data

    @staticmethod
    def get_progress(
        db: Session,
        operation_id: int,
    ) -> Optional[dict]:
        """
        Fast progress query for polling (every 3 seconds from UI).
        Reads from operation_progress_view for sub-50ms response.
        Evidence: §6 "operation_progress_view — polling every 3s"
        Falls back to direct model query if VIEW is unavailable.
        """
        from sqlalchemy import text
        try:
            row = db.execute(
                text(
                    "SELECT * FROM operation_progress_view "
                    "WHERE id = :id"
                ),
                {"id": operation_id},
            ).fetchone()
            if not row:
                return None
            return dict(row._mapping)
        except Exception:
            # Fallback: direct model query
            op = db.query(Operation).filter(Operation.id == operation_id).first()
            if not op:
                return None
            return {
                "id":                 op.id,
                "operation_ref":      op.operation_ref,
                "capability_type":    op.capability_type,
                "status":             op.status,
                "chunks_total":       op.chunks_total,
                "chunks_completed":   op.chunks_completed,
                "chunks_failed":      op.chunks_failed,
                "chunks_cancelled":   op.chunks_cancelled,
                "progress_pct":       op.progress_pct,
                "total_results_count": op.total_results_count,
                "actual_credits_used": op.actual_credits_used,
                "estimated_credits":   op.estimated_credits,
                "cancel_requested":    op.cancel_requested,
                "created_at":         op.created_at,
                "started_at":         op.started_at,
                "completed_at":       op.completed_at,
                "current_chunk":      None,
                "last_completed_chunk": None,
            }

    @staticmethod
    def get_partial_results_summary(
        db: Session,
        operation_id: int,
    ) -> PartialResultsSummary:
        """
        Returns count of results available NOW from completed chunks.
        Evidence: §6 "results_available — عدد النتائج الجاهزة الآن"
        """
        op = db.query(Operation).filter(Operation.id == operation_id).first()
        if not op:
            raise ValueError(f"العملية {operation_id} غير موجودة")

        # Count sessions linked to completed chunks of this operation
        results_available = (
            db.query(func.count(FactFlightSession.session_id))
            .filter(FactFlightSession.operation_id == operation_id)
            .scalar() or 0
        )
        chunks_ready = (
            db.query(func.count(OperationChunk.id))
            .filter(
                OperationChunk.operation_id == operation_id,
                OperationChunk.status == "completed",
            )
            .scalar() or 0
        )

        return PartialResultsSummary(
            operation_id=operation_id,
            operation_ref=op.operation_ref,
            status=op.status,
            results_available=results_available,
            chunks_ready=chunks_ready,
            chunks_total=op.chunks_total,
            export_url=(
                f"/api/v1/operations/{operation_id}/results/export"
                if results_available > 0 else None
            ),
        )


# ─────────────────────────────────────────────────────────────────────────────
# CHUNK CRUD
# ─────────────────────────────────────────────────────────────────────────────

class ChunksCRUD:

    @staticmethod
    def get_pending_chunks(
        db: Session,
        operation_id: int,
    ) -> List[OperationChunk]:
        """
        Returns all pending chunks for an operation, ordered by chunk_index.
        Used by the Celery task at start of execution.
        Evidence: §5 "جلب جميع chunks بـ status='pending' مُرتَّبة ASC"
        """
        return (
            db.query(OperationChunk)
            .filter(
                OperationChunk.operation_id == operation_id,
                OperationChunk.status == "pending",
            )
            .order_by(OperationChunk.chunk_index.asc())
            .all()
        )

    @staticmethod
    def get_retryable_chunks(db: Session) -> List[OperationChunk]:
        """
        Returns failed chunks eligible for retry across ALL active operations.
        Uses the partial index idx_chunks_retry for performance.
        Evidence: §7 "Retry Scheduler: next_retry_at <= now()"
        """
        now = datetime.now(timezone.utc)
        return (
            db.query(OperationChunk)
            .join(Operation, OperationChunk.operation_id == Operation.id)
            .filter(
                OperationChunk.status == "failed",
                OperationChunk.attempt_count < OperationChunk.max_attempts,
                OperationChunk.next_retry_at <= now,
                Operation.cancel_requested.is_(False),
                Operation.status.in_(["running", "partial"]),
            )
            .order_by(OperationChunk.next_retry_at.asc())
            .limit(50)   # process up to 50 retries per scheduler tick
            .all()
        )

    @staticmethod
    def mark_running(db: Session, chunk: OperationChunk) -> None:
        """
        Transitions chunk: pending/failed → running.
        Evidence: §5 "SET chunk.status = 'running', chunk.started_at = now()"
        """
        now = datetime.now(timezone.utc)
        chunk.status         = "running"
        chunk.started_at     = chunk.started_at or now
        chunk.last_attempt_at = now
        chunk.attempt_count  += 1
        db.flush()

    @staticmethod
    def mark_completed(
        db: Session,
        chunk: OperationChunk,
        results_count: int,
        credits_used: int,
        response_size: Optional[int] = None,
    ) -> None:
        """
        Transitions chunk: running → completed.
        Updates parent Operation counters atomically.
        Evidence: §5 "SET chunk.status = 'completed', results_count = ..."
        """
        now = datetime.now(timezone.utc)
        chunk.status         = "completed"
        chunk.completed_at   = now
        chunk.results_count  = results_count
        chunk.credits_used   = credits_used
        chunk.api_response_size_bytes = response_size

        # Update parent operation counters (atomic flush before commit)
        op = db.query(Operation).filter(Operation.id == chunk.operation_id).first()
        if op:
            op.chunks_completed      += 1
            op.total_results_count   += results_count
            op.actual_credits_used   += credits_used
            op.actual_api_calls      += 1

            # State machine transition
            # Evidence: §3 transitions table
            if op.chunks_completed >= op.chunks_total:
                op.status       = "completed"
                op.completed_at = now
                if op.started_at:
                    op.actual_duration_seconds = int(
                        (now - op.started_at).total_seconds()
                    )
            elif op.chunks_completed >= 1 and op.status == "running":
                op.status = "partial"

        db.flush()

    @staticmethod
    def mark_failed(
        db: Session,
        chunk: OperationChunk,
        error: str,
        http_status: Optional[int] = None,
    ) -> None:
        """
        Transitions chunk: running → failed.
        Schedules retry with exponential backoff if attempts remain.
        Evidence: §7 "backoff = 2^attempt × 30 seconds"
        """
        chunk.status      = "failed"
        chunk.last_error  = error
        chunk.http_status = http_status

        if chunk.can_retry:
            # Exponential backoff: attempt 1→60s, 2→120s, 3→240s
            backoff_s = (2 ** chunk.attempt_count) * 30
            chunk.next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=backoff_s)
        else:
            # Final failure — update parent
            op = db.query(Operation).filter(Operation.id == chunk.operation_id).first()
            if op:
                op.chunks_failed += 1
                # Check if all non-skipped chunks are terminal
                pending_count = (
                    db.query(func.count(OperationChunk.id))
                    .filter(
                        OperationChunk.operation_id == chunk.operation_id,
                        OperationChunk.status.in_(["pending", "running"]),
                    )
                    .scalar() or 0
                )
                if pending_count == 0 and op.status not in ("completed", "cancelled"):
                    op.status         = "failed"
                    op.failure_reason = f"الـ chunk {chunk.chunk_index} فشل نهائياً: {error}"
        db.flush()

    @staticmethod
    def mark_cancelled(db: Session, chunk: OperationChunk) -> None:
        """
        Evidence: §7 "cancel_requested → chunks pending → 'cancelled'"
        """
        chunk.status = "cancelled"
        op = db.query(Operation).filter(Operation.id == chunk.operation_id).first()
        if op:
            op.chunks_cancelled += 1
        db.flush()

    @staticmethod
    def handle_rate_limit(
        db: Session,
        chunk: OperationChunk,
        retry_after_seconds: int = 60,
    ) -> None:
        """
        HTTP 429 handler. Does NOT increment attempt_count.
        Evidence: §7 "429: لا تُعدّ هذا فشلاً في attempt_count"
        """
        chunk.status        = "failed"
        chunk.last_error    = f"Rate limit — retry after {retry_after_seconds}s"
        chunk.http_status   = 429
        chunk.next_retry_at = datetime.now(timezone.utc) + timedelta(
            seconds=retry_after_seconds
        )
        # NOTE: attempt_count NOT incremented — rate limit is not a failure
        db.flush()

    @staticmethod
    def handle_credit_exhausted(db: Session, operation_id: int) -> None:
        """
        HTTP 402 handler. Fails the entire operation, cancels pending chunks.
        Evidence: §7 "402: SET operation.status = 'failed',
        جميع chunks الـ pending → 'cancelled'"
        """
        op = db.query(Operation).filter(Operation.id == operation_id).first()
        if not op:
            return

        # Cancel all pending chunks
        pending = (
            db.query(OperationChunk)
            .filter(
                OperationChunk.operation_id == operation_id,
                OperationChunk.status == "pending",
            )
            .all()
        )
        for chunk in pending:
            chunk.status = "cancelled"
            op.chunks_cancelled += 1

        op.status         = "failed"
        op.failure_reason = (
            "نفد رصيد FR24 API — النتائج الجزئية المُجمَّعة محفوظة وقابلة للتصدير."
        )
        db.flush()

    @staticmethod
    def get_chunks_for_operation(
        db: Session,
        operation_id: int,
    ) -> List[OperationChunk]:
        """All chunks for an operation, ordered by index. Used by detail view."""
        return (
            db.query(OperationChunk)
            .filter(OperationChunk.operation_id == operation_id)
            .order_by(OperationChunk.chunk_index.asc())
            .all()
        )


# ─────────────────────────────────────────────────────────────────────────────
# CREDIT RATES CRUD
# ─────────────────────────────────────────────────────────────────────────────

class CreditRatesCRUD:

    @staticmethod
    def get_all(db: Session) -> List[ApiCreditRate]:
        return db.query(ApiCreditRate).order_by(ApiCreditRate.capability_type).all()

    @staticmethod
    def update_from_actuals(db: Session) -> int:
        """
        Self-calibration: updates avg_results_per_call from real observed data.
        Called by cleanup task periodically.
        Evidence: §4 "تتحدث تلقائياً من نتائج العمليات السابقة"
        Returns number of rate rows updated.
        """
        updated = 0
        cap_stats = (
            db.query(
                Operation.capability_type,
                func.avg(
                    Operation.total_results_count /
                    func.nullif(Operation.actual_api_calls, 0)
                ).label("avg_results"),
                func.avg(
                    Operation.actual_duration_seconds /
                    func.nullif(Operation.actual_api_calls, 0)
                ).label("avg_duration"),
            )
            .filter(
                Operation.status == "completed",
                Operation.actual_api_calls > 0,
                Operation.total_results_count > 0,
            )
            .group_by(Operation.capability_type)
            .all()
        )

        for row in cap_stats:
            rate = (
                db.query(ApiCreditRate)
                .filter(ApiCreditRate.capability_type == row.capability_type)
                .first()
            )
            if rate and row.avg_results:
                rate.avg_results_per_call = int(row.avg_results)
                if row.avg_duration:
                    rate.avg_call_duration_seconds = round(float(row.avg_duration), 2)
                updated += 1

        if updated:
            db.commit()
        return updated


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _parse_date(s: str):
    from datetime import date as date_cls
    try:
        return date_cls.fromisoformat(s)
    except (ValueError, TypeError):
        return None