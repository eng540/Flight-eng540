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
   
UPGRADES (v7.0 — FULL API CAPABILITY EXPOSURE):
  - Dynamic Endpoint routing: Switch between /light and /full automatically.
  - Universal Filter mapping: Injects airports, flights, callsigns, categories, etc.
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

        chunks: List[OperationChunk] =[]

        for plan in chunk_plan:
            # Build FR24 params dict for this specific chunk
            fr24_params = OperationsPlanner._build_fr24_params(operation, plan)

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
                # Set here so DB queries can reference it immediately
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

    @staticmethod
    def _build_fr24_params(operation: Operation, plan) -> dict:
        """
        Builds the exact parameters dict to pass to FR24 API.
        Based on capability type and chunk-specific scope.
        """
        cap = operation.capability_type
        params: dict = {}
        filters = operation.scope_filters or {}

        if cap == "live_positions":
            bounds = _build_bounds(operation, plan.region_key)
            if bounds:
                params["bounds"] = (
                    f"{bounds['lamax']},{bounds['lamin']},"
                    f"{bounds['lomin']},{bounds['lomax']}"
                )
            # Universal limit to prevent runaway queries
            params["limit"] = min(int(filters.get("limit", 1500)), 20000)

            # Extra valid FR24 live filters
            for k in ["airports", "aircraft", "categories", "data_sources", "squawks"]:
                if k in filters: params[k] = filters[k]
            if "gspeed" in filters: params["gspeed"] = filters["gspeed"]
            if "altitude_ranges" in filters: params["altitude_ranges"] = filters["altitude_ranges"]


        elif cap == "historic_positions":
            bounds = _build_bounds(operation, plan.region_key)
            if bounds:
                params["bounds"] = (
                    f"{bounds['lamax']},{bounds['lamin']},"
                    f"{bounds['lomin']},{bounds['lomax']}"
                )
            if plan.date_from:
                d = date.fromisoformat(plan.date_from)
                params["timestamp"] = int(datetime(
                    d.year, d.month, d.day, 12, 0, 0,
                    tzinfo=timezone.utc,
                ).timestamp())
                
            params["limit"] = min(int(filters.get("limit", 1500)), 20000)
            
            # Historic positions supports same filters as live
            for k in["airports", "aircraft", "categories", "data_sources", "squawks", "gspeed", "altitude_ranges"]:
                if k in filters: params[k] = filters[k]


        elif cap == "flight_summaries":
            if plan.date_from:
                params["flight_datetime_from"] = f"{plan.date_from}T00:00:00Z"
            if plan.date_to:
                params["flight_datetime_to"]   = f"{plan.date_to}T23:59:59Z"
                
            # Limit is mandatory in flight_summaries to prevent massive bills
            params["limit"] = min(int(filters.get("limit", 1500)), 20000)
            
            # Map universal filters supported by flight-summaries
            if operation.scope_entity_id:
                params["operating_as"] = operation.scope_entity_id
                
            valid_filters =["operating_as", "painted_as", "flights", "registrations", 
                             "callsigns", "airports", "routes", "aircraft", "sort"]
                             
            for k in valid_filters:
                if k in filters and filters[k]:
                    params[k] = filters[k]


        elif cap == "flight_tracks":
            if plan.entity_id:
                params["flight_id"] = plan.entity_id


        elif cap in ("static_airport", "static_airline"):
            # Static data doesn't require extra params; the ID is embedded in the URL path.
            pass

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