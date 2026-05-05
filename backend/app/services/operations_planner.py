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
   
UPGRADES (v8.0 — ADVANCED REGION-TO-AIRPORT RESOLUTION):
  - Solves the Region to Airport lookup for flight_summaries.
  - Slices large airport lists into compliant chunks of max 15 airports (FR24 limits).
  - Routes filter explicitly supported.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone, timedelta
from typing import List

from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.models import Operation, OperationChunk, DimGeography
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
        Returns the created chunks (already flushed, not yet committed).
        """
        engine     = PreflightEngine(db)
        # Using base plan to determine timelines
        base_chunk_plan = engine._build_chunk_plan(operation)

        chunks: List[OperationChunk] =[]
        final_chunk_index = 0

        for plan in base_chunk_plan:
            # 🚨 ADVANCED FIX (Region to Airport Resolution)
            # For flight_summaries, if no specific entity/filter is provided but a region is,
            # we MUST convert the region's bounding box into actual ICAO airport codes.
            # FR24 API limit: max 15 airports per request.
            
            airport_batches =[None] # Default to 1 batch with no airport override
            
            if operation.capability_type == "flight_summaries":
                filters = operation.scope_filters or {}
                has_entity_filter = operation.scope_entity_id or any(
                    k in filters and filters[k] for k in["operating_as", "painted_as", "flights", "registrations", "callsigns", "airports", "routes", "aircraft"]
                )
                
                # If no explicit filters, we must derive airports from the region bounds
                if not has_entity_filter and plan.region_key:
                    bounds = _build_bounds(operation, plan.region_key)
                    if bounds:
                        # Find all airports inside this bounding box
                        airports_in_region = db.query(DimGeography.icao_code).filter(
                            and_(
                                DimGeography.latitude <= bounds['lamax'],
                                DimGeography.latitude >= bounds['lamin'],
                                DimGeography.longitude >= bounds['lomin'],
                                DimGeography.longitude <= bounds['lomax'],
                                DimGeography.icao_code.isnot(None)
                            )
                        ).all()
                        
                        icao_list =[a[0] for a in airports_in_region if len(a[0]) == 4]
                        
                        if icao_list:
                            # Slice into batches of 15
                            airport_batches = [icao_list[i:i + 15] for i in range(0, len(icao_list), 15)]

            # Generate chunks (multiplying temporal chunks by airport batches if needed)
            for batch in airport_batches:
                fr24_params = OperationsPlanner._build_fr24_params(operation, plan, batch)

                chunk = OperationChunk(
                    operation_id=operation.id,
                    chunk_index=final_chunk_index,
                    chunk_type=operation.capability_type,

                    date_from=(date.fromisoformat(plan.date_from) if plan.date_from else None),
                    date_to=(date.fromisoformat(plan.date_to) if plan.date_to else None),
                    timestamp_from=(
                        int(datetime(*[int(x) for x in plan.date_from.split("-")], 0, 0, 0, tzinfo=timezone.utc).timestamp())
                        if plan.date_from else None
                    ),
                    timestamp_to=(
                        int(datetime(*[int(x) for x in plan.date_to.split("-")], 23, 59, 59, tzinfo=timezone.utc).timestamp())
                        if plan.date_to else None
                    ),

                    region_key=plan.region_key,
                    bounds=_build_bounds(operation, plan.region_key),
                    entity_id=plan.entity_id,

                    fr24_endpoint=plan.fr24_endpoint,
                    fr24_params=fr24_params,

                    status="pending",
                    attempt_count=0,
                    max_attempts=3,
                    partial_result_key=f"op:{operation.id}:chunk:{final_chunk_index}",
                )
                db.add(chunk)
                chunks.append(chunk)
                final_chunk_index += 1

        db.flush()

        operation.chunks_total = len(chunks)
        operation.planned_at   = datetime.now(timezone.utc)

        return chunks

    @staticmethod
    def _build_fr24_params(operation: Operation, plan, airport_batch_override: List[str] = None) -> dict:
        """
        Builds the exact parameters dict to pass to FR24 API.
        """
        cap = operation.capability_type
        params: dict = {}
        filters = operation.scope_filters or {}

        if cap == "live_positions":
            bounds = _build_bounds(operation, plan.region_key)
            if bounds:
                params["bounds"] = f"{bounds['lamax']},{bounds['lamin']},{bounds['lomin']},{bounds['lomax']}"
            params["limit"] = min(int(filters.get("limit", 1500)), 20000)

            for k in["airports", "aircraft", "categories", "data_sources", "squawks"]:
                if k in filters: params[k] = filters[k]
            if "gspeed" in filters: params["gspeed"] = filters["gspeed"]
            if "altitude_ranges" in filters: params["altitude_ranges"] = filters["altitude_ranges"]

        elif cap == "historic_positions":
            bounds = _build_bounds(operation, plan.region_key)
            if bounds:
                params["bounds"] = f"{bounds['lamax']},{bounds['lamin']},{bounds['lomin']},{bounds['lomax']}"
            if plan.date_from:
                d = date.fromisoformat(plan.date_from)
                params["timestamp"] = int(datetime(d.year, d.month, d.day, 12, 0, 0, tzinfo=timezone.utc).timestamp())
                
            params["limit"] = min(int(filters.get("limit", 1500)), 20000)
            
            for k in["airports", "aircraft", "categories", "data_sources", "squawks", "gspeed", "altitude_ranges"]:
                if k in filters: params[k] = filters[k]

        elif cap == "flight_summaries":
            if plan.date_from:
                params["flight_datetime_from"] = f"{plan.date_from}T00:00:00Z"
            if plan.date_to:
                params["flight_datetime_to"]   = f"{plan.date_to}T23:59:59Z"
                
            params["limit"] = min(int(filters.get("limit", 1500)), 20000)
            
            # Map explicit universal filters
            if operation.scope_entity_id:
                params["operating_as"] = operation.scope_entity_id
                
            valid_filters =["operating_as", "painted_as", "flights", "registrations", "callsigns", "airports", "routes", "aircraft", "sort"]
                             
            for k in valid_filters:
                if k in filters and filters[k]:
                    params[k] = filters[k]

            # Override with region-based airports if provided by the planner
            if airport_batch_override:
                params["airports"] = ",".join(airport_batch_override)

        elif cap == "flight_tracks":
            if plan.entity_id:
                params["flight_id"] = plan.entity_id

        elif cap in ("static_airport", "static_airline"):
            pass

        return params


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _build_bounds(operation: Operation, region_key=None) -> dict:
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