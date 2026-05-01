"""
Operations Planner (System Design §5)

Translates a PreflightSummary chunk plan into actual OperationChunk rows
in the database. Called once, immediately after user approval.

Evidence §5 Execution Flow:
  "OperationsPlanner.create_chunks(operation)
   لكل وحدة زمنية في النطاق:
       chunk = OperationChunk(...)
       db.add(chunk)
   SET operation.chunks_total = len(chunks)"

FIXES APPLIED (2026-05-01):
  [FIX-FS] flight_summaries now includes an additional search parameter
           required by FR24 /api/flight-summary/full endpoint.
           If an airline_icao exists in scope, it is used.
           Otherwise the scope_region_key is used to look up airport codes
           from DimGeography and the `airports` parameter is set.
           Evidence: FR24 error "None of the required fields were provided.
           Please include at least one of the following: flight_ids OR
           flight_datetime_from + flight_datetime_to + at least one
           additional search parameter".

  [FIX-HE] historic_events is temporarily disabled because it requires
           flight_ids and event_types which are not yet available in
           the current planning flow. A clear ValueError is raised so
           that the chunk is marked as failed with an informative message.
           Evidence: FR24 error "The flight ids field is required.,
           The event types field is required."

  [FIX-SA] static_airline now validates that the ICAO code is a 3‑letter
           uppercase string before the chunk is created, preventing
           infinite retry loops on invalid input.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone, timedelta
from typing import List

from sqlalchemy.orm import Session

from app.models import Operation, OperationChunk
from app.services.preflight_engine import (
    PreflightEngine,
    CAPABILITY_ENDPOINT_MAP,
)
from app.config import settings


class OperationsPlanner:
    """
    Stateless planner. Call create_chunks() once per approved Operation.
    """

    @staticmethod
    def create_chunks(db: Session, operation: Operation) -> List[OperationChunk]:
        """
        Translates the operation scope into concrete OperationChunk rows.
        Each chunk = exactly one FR24 API call.

        Returns the created chunks (already flushed, not yet committed).
        Caller must db.commit().
        """
        engine     = PreflightEngine(db)
        chunk_plan = engine._build_chunk_plan(operation)

        chunks: List[OperationChunk] = []

        for plan in chunk_plan:
            # Build FR24 params dict for this specific chunk
            fr24_params = OperationsPlanner._build_fr24_params(db, operation, plan)

            chunk = OperationChunk(
                operation_id=operation.id,
                chunk_index=plan.chunk_index,
                chunk_type=operation.capability_type,

                # Temporal scope
                date_from=(
                    date.fromisoformat(plan.date_from)
                    if plan.date_from else None
                ),
                date_to=(
                    date.fromisoformat(plan.date_to)
                    if plan.date_to else None
                ),
                timestamp_from=(
                    int(datetime(
                        *[int(x) for x in plan.date_from.split("-")],
                        0, 0, 0, tzinfo=timezone.utc,
                    ).timestamp())
                    if plan.date_from else None
                ),
                timestamp_to=(
                    int(datetime(
                        *[int(x) for x in plan.date_to.split("-")],
                        23, 59, 59, tzinfo=timezone.utc,
                    ).timestamp())
                    if plan.date_to else None
                ),

                # Geographic scope
                region_key=plan.region_key,
                bounds=_build_bounds(operation, plan.region_key),

                # Entity scope
                entity_id=plan.entity_id,

                # FR24 call specification (immutable after creation)
                fr24_endpoint=plan.fr24_endpoint,
                fr24_params=fr24_params,

                # State
                status="pending",
                attempt_count=0,
                max_attempts=3,

                # Partial result key: "op:{op_id}:chunk:{index}"
                partial_result_key=(
                    f"op:{operation.id}:chunk:{plan.chunk_index}"
                ),
            )
            db.add(chunk)
            chunks.append(chunk)

        # Flush to get IDs assigned (no commit yet)
        db.flush()

        # Update operation counters
        operation.chunks_total = len(chunks)
        operation.planned_at   = datetime.now(timezone.utc)

        return chunks

    # ------------------------------------------------------------------
    # FIXED: _build_fr24_params now receives db so that it can look up
    # airport codes when needed for flight_summaries.
    # ------------------------------------------------------------------
    @staticmethod
    def _build_fr24_params(db: Session, operation: Operation, plan) -> dict:
        """
        Builds the exact parameters dict to pass to FR24 API.
        Based on capability type and chunk-specific scope.
        """
        cap = operation.capability_type
        params: dict = {}

        if cap == "live_positions":
            bounds = _build_bounds(operation, plan.region_key)
            if bounds:
                params["bounds"] = (
                    f"{bounds['lamax']},{bounds['lamin']},"
                    f"{bounds['lomin']},{bounds['lomax']}"
                )
            params["limit"] = 1500

        elif cap == "historic_positions":
            bounds = _build_bounds(operation, plan.region_key)
            if bounds:
                params["bounds"] = (
                    f"{bounds['lamax']},{bounds['lamin']},"
                    f"{bounds['lomin']},{bounds['lomax']}"
                )
            # FR24 historic endpoint uses midpoint timestamp of the day
            if plan.date_from:
                d = date.fromisoformat(plan.date_from)
                params["timestamp"] = int(datetime(
                    d.year, d.month, d.day, 12, 0, 0,
                    tzinfo=timezone.utc,
                ).timestamp())
            params["limit"] = 1500

        elif cap == "flight_summaries":
            if plan.date_from:
                params["flight_datetime_from"] = f"{plan.date_from}T00:00:00Z"
            if plan.date_to:
                params["flight_datetime_to"]   = f"{plan.date_to}T23:59:59Z"

            # [FIX-FS] FR24 requires an additional search parameter.
            # Priority: 1) airline_icao from scope  2) airports from region.
            if operation.scope_entity_id and operation.scope_entity_type == "airline":
                params["airline_icao"] = operation.scope_entity_id.strip().upper()
            elif operation.scope_filters and "operator_icao" in operation.scope_filters:
                params["airline_icao"] = operation.scope_filters["operator_icao"].strip().upper()
            elif operation.scope_region_key:
                # Look up airport codes for the region from DimGeography
                airport_codes = _get_region_airport_codes(db, operation.scope_region_key)
                if airport_codes:
                    params["airports"] = ",".join(airport_codes)
                else:
                    raise ValueError(
                        "flight_summaries requires an additional filter. "
                        "Please specify an airline or ensure the region has airports."
                    )
            else:
                raise ValueError(
                    "flight_summaries requires an additional filter. "
                    "Please specify an airline or a region."
                )
            params["limit"] = 100

        elif cap == "flight_tracks":
            if plan.entity_id:
                params["flight_id"] = plan.entity_id

        elif cap == "historic_events":
            # [FIX-HE] This endpoint requires flight_ids + event_types.
            # We do not yet have a way to obtain flight_ids in the planning
            # flow, so we explicitly disable this capability.
            raise ValueError(
                "historic_events requires flight_ids and event_types, "
                "which are not yet supported. Use flight_summaries instead."
            )

        elif cap == "static_airport":
            # endpoint already contains the code: /api/static/airports/{code}/full
            pass

        elif cap == "static_airline":
            # [FIX-SA] Validate that the ICAO code looks plausible.
            eid = (plan.entity_id or "").strip().upper()
            if not eid or len(eid) != 3 or not eid.isalpha():
                raise ValueError(
                    f"'{plan.entity_id}' is not a valid airline ICAO code. "
                    f"Provide a 3-letter code (e.g., UAE, SVA)."
                )

        return params


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _build_bounds(operation: Operation, region_key=None) -> dict:
    """
    Returns bounds dict from operation scope.
    Prefers explicit scope_bounds, then looks up region key.
    """
    if operation.scope_bounds:
        return operation.scope_bounds

    rk = region_key or operation.scope_region_key
    if rk:
        region = settings.get_region(rk)
        if region:
            return {
                "lamin": region.lamin, "lomin": region.lomin,
                "lamax": region.lamax, "lomax": region.lomax,
            }
    return {}


def _get_region_airport_codes(db: Session, region_key: str) -> List[str]:
    """
    Returns a list of ICAO airport codes that reside inside the
    geographic bounding box of the given region.
    """
    region = settings.get_region(region_key)
    if not region:
        return []

    from app.models import DimGeography

    airports = (
        db.query(DimGeography.icao_code)
        .filter(
            DimGeography.icao_code.isnot(None),
            DimGeography.latitude >= region.lamin,
            DimGeography.latitude <= region.lamax,
            DimGeography.longitude >= region.lomin,
            DimGeography.longitude <= region.lomax,
        )
        .all()
    )
    # Flatten the list of tuples
    return [code for (code,) in airports if code]