"""
Pre-flight Engine (v7.0 — FULL API CAPABILITY EXPOSURE)

Computes BEFORE user approval:
  - number of chunks (= FR24 API calls)
  - credit cost estimate (with 15% safety margin)
  - duration estimate (with 20% overhead buffer)
  - full chunk plan (list of ChunkPlan for UI display)
  - warnings (large range, low balance, etc.)

UPGRADES:
  - Auto-chunking: Splits date ranges > 14 days automatically for flight_summaries.
  - Schema Toggling: Supports switching between /light and /full endpoints.
  - Universal Filters: Accepts any valid FR24 filter (airports, flights, routes, etc.).
"""
from __future__ import annotations

import math
from datetime import date, datetime, timezone, timedelta
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models import ApiCreditRate, Operation
from app.schemas import (
    ChunkPlan,
    PreflightSummary,
    PreflightWarning,
    OperationCreateRequest,
)
from app.config import settings

# ── Constants ─────────────────────────────────────────────────────────────

# Safety margins (§4 formulas)
CREDIT_SAFETY_MARGIN   = 1.15   # +15% over base estimate
DURATION_OVERHEAD      = 1.20   # +20% for queue/overhead
WORKER_CONCURRENCY     = 2      # matches docker-compose celery concurrency

# Warning thresholds
LARGE_DATE_RANGE_DAYS  = 30
LOW_BALANCE_THRESHOLD  = 500   # نقاط — تحذير إذا أقل

# FR24 endpoint map per capability
CAPABILITY_ENDPOINT_MAP = {
    "live_positions":    "/api/live/flight-positions/full",
    "flight_summaries":  "/api/flight-summary/full",  # Defaults to full, dynamically changed to light if requested
    "flight_tracks":     "/api/flight-tracks",
    "historic_positions":"/api/historic/flight-positions/full",
    "static_airport":    "/api/static/airports/{code}/full",
    "static_airline":    "/api/static/airlines/{icao}/light",
}

# Human-readable Arabic labels per capability
CAPABILITY_LABELS_AR = {
    "live_positions":    "رصد حي — مواقع الطائرات الآن",
    "flight_summaries":  "ملخصات الرحلات",
    "flight_tracks":     "مسار رحلة بعينها",
    "historic_positions":"مواقع تاريخية",
    "static_airport":    "بيانات المطار",
    "static_airline":    "بيانات الناقل",
}

# Default fallback rates (used only if DB table is empty)
_FALLBACK_RATES = {
    "live_positions":    {"per_call": 10,  "per_record": 0,   "duration": 2.0, "results": 450},
    "flight_summaries":  {"per_call": 5,   "per_record": 0.1, "duration": 2.5, "results": 1200},
    "flight_tracks":     {"per_call": 5,   "per_record": 0,   "duration": 1.5, "results": 120},
    "historic_positions":{"per_call": 20,  "per_record": 0,   "duration": 3.0, "results": 800},
    "static_airport":    {"per_call": 0,   "per_record": 0,   "duration": 1.0, "results": 1},
    "static_airline":    {"per_call": 0,   "per_record": 0,   "duration": 1.0, "results": 1},
}


# ═════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═════════════════════════════════════════════════════════════════════════════

class PreflightEngine:
    """
    Stateless engine — instantiate per request.
    All methods are deterministic given the same inputs.
    """

    def __init__(self, db: Session):
        self._db    = db
        self._rates: dict = {}   # loaded lazily from DB

    def compute(
        self,
        operation: Operation,
        current_balance: Optional[int] = None,
    ) -> PreflightSummary:
        """
        Main entry point.
        Computes full PreflightSummary for an Operation in 'pending' state.
        Returns the summary; caller is responsible for persisting estimates
        back to the Operation record.
        """
        self._load_rates()
        cap = operation.capability_type

        # 1. Build chunk plan
        chunk_plan = self._build_chunk_plan(operation)

        # 2. Derived counts
        n_chunks    = len(chunk_plan)
        n_api_calls = sum(1 for _ in chunk_plan)   # 1 FR24 call per chunk

        # 3. Credits
        estimated_credits = self._estimate_credits(cap, n_api_calls, operation)

        # 4. Duration
        estimated_duration_s = self._estimate_duration(cap, n_api_calls)

        # 5. Results
        estimated_results = self._estimate_results(cap, n_api_calls)

        # 6. Warnings
        warnings = self._build_warnings(
            operation, n_api_calls, estimated_credits,
            current_balance, chunk_plan,
        )

        return PreflightSummary(
            operation_id=operation.id,
            operation_ref=operation.operation_ref,
            capability_type=cap,
            capability_label=CAPABILITY_LABELS_AR.get(cap, cap),
            estimated_chunks=n_chunks,
            estimated_api_calls=n_api_calls,
            estimated_credits=estimated_credits,
            estimated_duration_seconds=estimated_duration_s,
            estimated_duration_label=_format_duration(estimated_duration_s),
            estimated_results=estimated_results,
            current_credits_balance=current_balance,
            credits_sufficient=(
                current_balance >= estimated_credits
                if current_balance is not None else None
            ),
            chunk_plan=chunk_plan,
            warnings=warnings,
        )

    def estimates_dict(self, operation: Operation) -> dict:
        """
        Returns only the numeric estimates (for persisting to Operation row).
        Avoids re-computing chunk_plan twice.
        """
        self._load_rates()
        cap = operation.capability_type
        chunk_plan = self._build_chunk_plan(operation)
        n = len(chunk_plan)
        return {
            "estimated_chunks":           n,
            "estimated_api_calls":        n,
            "estimated_credits":          self._estimate_credits(cap, n, operation),
            "estimated_duration_seconds": self._estimate_duration(cap, n),
            "estimated_results":          self._estimate_results(cap, n),
        }

    # ─────────────────────────────────────────────────────────────────────────
    # CHUNK PLAN BUILDER
    # ─────────────────────────────────────────────────────────────────────────

    def _build_chunk_plan(self, op: Operation) -> List[ChunkPlan]:
        cap = op.capability_type
        
        if cap not in CAPABILITY_ENDPOINT_MAP:
            return[]
            
        ep = CAPABILITY_ENDPOINT_MAP[cap]

        # Dynamic Schema Toggling (Light vs Full)
        if cap == "flight_summaries" and op.scope_filters and op.scope_filters.get("schema_mode") == "light":
            ep = "/api/flight-summary/light"

        if cap == "live_positions":
            return self._plan_live_positions(op, ep)

        if cap in ("historic_positions", "flight_summaries"):
            return self._plan_temporal(op, ep)

        if cap == "flight_tracks":
            return self._plan_entity_list(op, ep)

        if cap in ("static_airport", "static_airline"):
            return self._plan_static(op, ep)

        return[]

    def _plan_live_positions(self, op: Operation, ep: str) -> List[ChunkPlan]:
        """
        One call per geographic region.
        """
        region_keys = (
            [op.scope_region_key]
            if op.scope_region_key
            else settings.get_active_region_keys()
        )
        plans =[]
        for i, rk in enumerate(region_keys):
            region = settings.get_region(rk)
            plans.append(ChunkPlan(
                chunk_index=i,
                label=f"منطقة: {region.name_ar if region else rk}",
                region_key=rk,
                fr24_endpoint=ep,
                estimated_credits=self._per_call_credits(op.capability_type),
            ))
        return plans

    def _plan_temporal(self, op: Operation, ep: str) -> List[ChunkPlan]:
        """
        Auto-chunking strategy:
        - historic_positions: 1 day per chunk (API design).
        - flight_summaries: up to 14 days per chunk (FR24 limit).
        """
        if not op.scope_date_from or not op.scope_date_to:
            today = datetime.now(timezone.utc).date()
            d_from, d_to = today, today
        else:
            d_from = op.scope_date_from
            d_to   = op.scope_date_to

        plans =[]
        current = d_from
        idx = 0
        
        step_days = 14 if op.capability_type == "flight_summaries" else 1

        while current <= d_to:
            chunk_end = current + timedelta(days=step_days - 1)
            if chunk_end > d_to:
                chunk_end = d_to
                
            label = _date_label(current) if current == chunk_end else f"من {_date_label(current)} إلى {_date_label(chunk_end)}"
            
            plans.append(ChunkPlan(
                chunk_index=idx,
                label=label,
                date_from=current.isoformat(),
                date_to=chunk_end.isoformat(),
                region_key=op.scope_region_key,
                fr24_endpoint=ep,
                estimated_credits=self._per_call_credits(op.capability_type),
            ))
            current = chunk_end + timedelta(days=1)
            idx += 1
            
        return plans

    def _plan_entity_list(self, op: Operation, ep: str) -> List[ChunkPlan]:
        """
        One call per entity ID (flight_id).
        """
        entity_ids: List[str] =[]

        if op.scope_filters and "entity_ids" in op.scope_filters:
            entity_ids = op.scope_filters["entity_ids"]
        elif op.scope_entity_id:
            entity_ids = [op.scope_entity_id]

        return[
            ChunkPlan(
                chunk_index=i,
                label=f"رحلة: {eid}",
                entity_id=eid,
                fr24_endpoint=ep,
                estimated_credits=self._per_call_credits(op.capability_type),
            )
            for i, eid in enumerate(entity_ids)
        ]

    def _plan_static(self, op: Operation, ep: str) -> List[ChunkPlan]:
        """
        One call per entity (airport/airline code). Free cost.
        """
        entity_ids: List[str] =[]
        if op.scope_filters and "entity_ids" in op.scope_filters:
            entity_ids = op.scope_filters["entity_ids"]
        elif op.scope_entity_id:
            entity_ids = [op.scope_entity_id]

        code_placeholder = "{code}" if op.capability_type == "static_airport" else "{icao}"
        
        return[
            ChunkPlan(
                chunk_index=i,
                label=f"{'مطار' if 'airport' in op.capability_type else 'ناقل'}: {eid}",
                entity_id=eid,
                fr24_endpoint=ep.replace(code_placeholder, eid),
                estimated_credits=0,
            )
            for i, eid in enumerate(entity_ids)
        ]

    # ─────────────────────────────────────────────────────────────────────────
    # FORMULAS 
    # ─────────────────────────────────────────────────────────────────────────

    def _estimate_credits(self, cap: str, n_api_calls: int, op: Operation) -> int:
        r = self._rates.get(cap, _FALLBACK_RATES.get(cap, {}))
        base  = n_api_calls * r.get("per_call", 0)
        extra = n_api_calls * r.get("results", 0) * r.get("per_record", 0)
        
        total = (base + extra)
        
        # Discount for 'light' schema
        if cap == "flight_summaries" and op.scope_filters and op.scope_filters.get("schema_mode") == "light":
            total = total * 0.5  # Light is roughly 50% cheaper based on FR24 pricing
            
        return math.ceil(total * CREDIT_SAFETY_MARGIN)

    def _estimate_duration(self, cap: str, n_api_calls: int) -> int:
        r         = self._rates.get(cap, _FALLBACK_RATES.get(cap, {}))
        call_time = r.get("duration", 2.0)
        delay     = settings.INGESTION_DELAY_SECONDS
        total     = n_api_calls * (call_time + delay)
        effective = total / WORKER_CONCURRENCY
        return math.ceil(effective * DURATION_OVERHEAD)

    def _estimate_results(self, cap: str, n_api_calls: int) -> int:
        r = self._rates.get(cap, _FALLBACK_RATES.get(cap, {}))
        return n_api_calls * r.get("results", 500)

    def _per_call_credits(self, cap: str) -> int:
        r = self._rates.get(cap, _FALLBACK_RATES.get(cap, {}))
        return r.get("per_call", 0)

    # ─────────────────────────────────────────────────────────────────────────
    # WARNINGS & VALIDATIONS
    # ─────────────────────────────────────────────────────────────────────────

    def _build_warnings(
        self,
        op: Operation,
        n_api_calls: int,
        estimated_credits: int,
        current_balance: Optional[int],
        chunk_plan: List[ChunkPlan],
    ) -> List[PreflightWarning]:
        warnings: List[PreflightWarning] =[]

        if op.scope_date_from and op.scope_date_to:
            days = (op.scope_date_to - op.scope_date_from).days + 1
            if days > LARGE_DATE_RANGE_DAYS:
                warnings.append(PreflightWarning(
                    level="warning",
                    code="LARGE_DATE_RANGE",
                    message=(
                        f"النطاق الزمني واسع جداً ({days} يومًا). "
                        f"النظام سيقوم بتقطيع الطلب تلقائياً إلى {n_api_calls} دفعات لتوافق قيود FR24."
                    ),
                ))

        # Check for mandatory filters in flight_summaries
        if op.capability_type == "flight_summaries":
            filters = op.scope_filters or {}
            valid_filters =["operating_as", "painted_as", "flights", "registrations", "callsigns", "airports", "routes", "aircraft"]
            
            has_filter = op.scope_entity_id or any(k in filters for k in valid_filters)
            
            if not has_filter:
                warnings.append(PreflightWarning(
                    level="critical",
                    code="MISSING_ENTITY",
                    message="ملخصات الرحلات تتطلب إدخال فلتر واحد على الأقل (مثل كود المطار، الشركة، أو نوع الطائرة) لتجنب رفض الطلب."
                ))

        if current_balance is not None and current_balance < estimated_credits:
            shortfall = estimated_credits - current_balance
            warnings.append(PreflightWarning(
                level="critical",
                code="INSUFFICIENT_CREDITS",
                message=(
                    f"رصيدك الحالي ({current_balance:,} نقطة) "
                    f"أقل من التكلفة التقديرية ({estimated_credits:,} نقطة). "
                    f"العجز: {shortfall:,} نقطة."
                ),
            ))
        elif current_balance is not None and current_balance < LOW_BALANCE_THRESHOLD:
            warnings.append(PreflightWarning(
                level="warning",
                code="LOW_BALANCE",
                message="رصيدك المتبقي منخفض. قد لا يكفي لعمليات ضخمة."
            ))

        if op.capability_type in ("flight_tracks", "static_airport", "static_airline") and not chunk_plan:
            warnings.append(PreflightWarning(
                level="critical",
                code="NO_ENTITIES",
                message="لم يتم تحديد أي معرّفات (رحلات/مطارات/ناقلين) لهذه العملية.",
            ))

        if op.capability_type in ("historic_positions", "flight_summaries"):
            if not op.scope_date_from or not op.scope_date_to:
                warnings.append(PreflightWarning(
                    level="info",
                    code="DEFAULT_DATES",
                    message="لم يتم تحديد نطاق زمني — سيتم جلب بيانات اليوم الحالي كإجراء افتراضي."
                ))

        return warnings

    def _load_rates(self) -> None:
        if self._rates:
            return
        rows = self._db.query(ApiCreditRate).all()
        if rows:
            self._rates = {
                r.capability_type: {
                    "per_call": r.credits_per_call,
                    "per_record": r.credits_per_record,
                    "duration": r.avg_call_duration_seconds,
                    "results": r.avg_results_per_call,
                }
                for r in rows
            }
        else:
            self._rates = {k: v for k, v in _FALLBACK_RATES.items()}


def _format_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} ثانية"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} {'دقيقة' if minutes == 1 else 'دقائق'}"
    hours   = minutes // 60
    rem_min = minutes % 60
    label   = f"{hours} {'ساعة' if hours == 1 else 'ساعات'}"
    if rem_min:
        label += f" و {rem_min} دقيقة"
    return label


def _date_label(d: date) -> str:
    MONTHS_AR =[
        "", "يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
        "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر",
    ]
    return f"{d.day} {MONTHS_AR[d.month]} {d.year}"