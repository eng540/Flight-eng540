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
   
UPGRADES (v8.2 — FINAL OPENAPI COMPLIANCE):
  - Advanced Region-to-Airport resolution for flight_summaries.
  - Slices large airport lists into compliant chunks of max 15 airports.
  - Corrected filter mapping: airline_icao for airline, painted_as for livery.
  - Full support for all valid FR24 flight summary filters.
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
        engine     = PreflightEngine(db)
        base_chunk_plan = engine._build_chunk_plan(operation)

        chunks: List[OperationChunk] =[]
        final_chunk_index = 0

        for plan in base_chunk_plan:
            airport_batches = [None]
            
            if operation.capability_type == "flight_summaries":
                filters = operation.scope_filters or {}
                has_entity_filter = operation.scope_entity_id or any(
                    k in filters and filters[k] for k in["airline_icao", "painted_as", "flights", "registrations", "callsigns", "airports", "routes", "aircraft"]
                )
                
                if not has_entity_filter and plan.region_key:
                    bounds = _build_bounds(operation, plan.region_key)
                    if bounds:
                        airports_in_region = db.query(DimGeography.icao_code).filter(
                            and_(
                                DimGeography.latitude <= bounds['lamax'],
                                DimGeography.latitude >= bounds['lamin'],
                                DimGeography.longitude >= bounds['lomin'],
                                DimGeography.longitude <= bounds['lomax'],
                                DimGeography.icao_code.isnot(None)
                            )
                        ).all()
                        
                        icao_list = [a[0] for a in airports_in_region if len(a[0]) == 4]
                        
                        if icao_list:
                            airport_batches = [icao_list[i:i + 15] for i in range(0, len(icao_list), 15)]

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
        cap = operation.capability_type
        params: dict = {}
        filters = operation.scope_filters or {}

        if cap == "live_positions":
            bounds = _build_bounds(operation, plan.region_key)
            if bounds:
                params["bounds"] = f"{bounds['lamax']},{bounds['lamin']},{bounds['lomin']},{bounds['lomax']}"
            params["limit"] = min(int(filters.get("limit", 1500)), 20000)

            for k in ["airports", "aircraft", "categories", "data_sources", "squawks"]:
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
            
            # Map the airline filter correctly. The UI sends 'operating_as' as a convenience key.
            # We translate it to the API-compliant 'airline_icao' parameter.
            if operation.scope_entity_id:
                params["airline_icao"] = operation.scope_entity_id
                
            # All valid FR24 filter parameters for flight summaries
            valid_filters =["airline_icao", "painted_as", "flights", "registrations", "callsigns", "airports", "routes", "aircraft", "sort"]
                             
            for k in valid_filters:
                # Handle the translation from frontend key 'operating_as' to API key 'airline_icao'
                if k == "airline_icao" and "operating_as" in filters and filters["operating_as"]:
                    params[k] = filters["operating_as"]
                elif k in filters and filters[k]:
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


# ── HELPERS ─────────────────────────────────────────────────────────────────
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