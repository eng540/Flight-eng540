"""
Enterprise Aviation Intelligence Models (v3.2 — TIER 0 Fixed)
SQLAlchemy ORM representation of the Snowflake Schema.

CHANGES FROM v3.1:
  TrackTelemetry      → +operation_id, +chunk_id
                        Evidence: Added in DB migration 003 but missing in ORM,
                        causing 500 Internal Server Error during CSV export.
"""
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, ForeignKey,
    Boolean, Index, BigInteger, Text, Date, UniqueConstraint
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import JSONB
from app.database import Base


# ═════════════════════════════════════════════════════════════════════════════
# 1. DIMENSION TABLES (Master Data / Reference Entities)
# ═════════════════════════════════════════════════════════════════════════════

class DimGeography(Base):
    """Airports, Regions, and Boundaries."""
    __tablename__ = "dim_geography"

    id           = Column(Integer, primary_key=True, index=True)
    icao_code    = Column(String(4),   unique=True, nullable=True,  index=True)
    iata_code    = Column(String(3),   nullable=True,  index=True)
    name         = Column(String(255), nullable=False)
    city         = Column(String(100), nullable=True)
    country_code = Column(String(2),   nullable=True,  index=True)
    latitude     = Column(Float,       nullable=True)
    longitude    = Column(Float,       nullable=True)
    elevation_m  = Column(Float,       nullable=True)
    meta_data    = Column(JSONB,       nullable=True)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    updated_at   = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self):
        return f"<DimGeography(icao='{self.icao_code}', name='{self.name}')>"


class DimOperator(Base):
    """Airlines and Operators."""
    __tablename__ = "dim_operator"

    id            = Column(Integer,    primary_key=True, index=True)
    icao_code     = Column(String(3),  unique=True, nullable=True, index=True)
    iata_code     = Column(String(2),  nullable=True, index=True)
    name          = Column(String(255), nullable=False)
    country_code  = Column(String(2),  nullable=True)
    operator_type = Column(String(50), nullable=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    updated_at    = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self):
        return f"<DimOperator(icao='{self.icao_code}', name='{self.name}')>"


class DimAircraft(Base):
    """The Physical Airplane Asset (SCD Type 2 Ready)."""
    __tablename__ = "dim_aircraft"

    id            = Column(Integer,    primary_key=True, index=True)
    icao24        = Column(String(6),  nullable=False, index=True)
    registration  = Column(String(20), nullable=True,  index=True)
    manufacturer  = Column(String(100), nullable=True)
    model         = Column(String(100), nullable=True)
    type_code     = Column(String(10), nullable=True,  index=True)
    serial_number = Column(String(100), nullable=True)
    year_built    = Column(Integer,    nullable=True)
    operator_id   = Column(Integer,    ForeignKey("dim_operator.id"), nullable=True)
    country_code  = Column(String(2),  nullable=True)

    # SCD Type 2 boundaries
    valid_from    = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    valid_to      = Column(DateTime(timezone=True), nullable=True)

    operator      = relationship("DimOperator")

    __table_args__ = (
        Index("idx_aircraft_hex_active", "icao24", "valid_to"),
    )

    def __repr__(self):
        return f"<DimAircraft(icao24='{self.icao24}', reg='{self.registration}')>"


# ═════════════════════════════════════════════════════════════════════════════
# 2. OPERATIONAL FACT TABLES
# ═════════════════════════════════════════════════════════════════════════════

class FactFlightSession(Base):
    """The specific journey of an aircraft."""
    __tablename__ = "fact_flight_session"

    session_id   = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    aircraft_id  = Column(Integer,   ForeignKey("dim_aircraft.id"),  nullable=False, index=True)
    operator_id  = Column(Integer,   ForeignKey("dim_operator.id"),  nullable=True,  index=True)

    # ── FR24 Primary Keys ─────────────────────────────────────────────────
    fr24_id      = Column(String(20), nullable=True, index=True)
    flight_number = Column(String(20), nullable=True, index=True)
    callsign     = Column(String(20), nullable=True, index=True)

    dep_airport_id = Column(Integer, ForeignKey("dim_geography.id"), nullable=True, index=True)
    arr_airport_id = Column(Integer, ForeignKey("dim_geography.id"), nullable=True, index=True)

    first_seen_ts      = Column(DateTime(timezone=True), nullable=False, index=True)
    last_seen_ts       = Column(DateTime(timezone=True), nullable=False, index=True)
    actual_takeoff_ts  = Column(DateTime(timezone=True), nullable=True)
    actual_landing_ts  = Column(DateTime(timezone=True), nullable=True)

    flight_status      = Column(String(20), default="active", index=True)
    total_distance_km  = Column(Float, nullable=True)
    max_altitude_m     = Column(Float, nullable=True)

    # Relationships
    aircraft    = relationship("DimAircraft")
    operator    = relationship("DimOperator")
    dep_airport = relationship("DimGeography", foreign_keys=[dep_airport_id])
    arr_airport = relationship("DimGeography", foreign_keys=[arr_airport_id])
    tracks      = relationship("TrackTelemetry", back_populates="session",
                               cascade="all, delete-orphan")

    # Operations Board: links this session to the Operation that ingested it.
    operation_id = Column(
        BigInteger,
        ForeignKey("operations.id"),
        nullable=True,
        index=True,
    )
    chunk_id = Column(
        BigInteger,
        ForeignKey("operation_chunks.id"),
        nullable=True,
    )

    __table_args__ = (
        Index("idx_flight_search",    "callsign",       "first_seen_ts"),
        Index("idx_flight_fr24",      "fr24_id"),
        Index("idx_flight_route",     "dep_airport_id", "arr_airport_id"),
        Index("idx_flight_number",    "flight_number",  "first_seen_ts"),
        Index("idx_session_operation","operation_id",   "chunk_id"),
    )

    def __repr__(self):
        return f"<FlightSession(id={self.session_id}, callsign='{self.callsign}')>"


class TrackTelemetry(Base):
    """Time-series radar breadcrumbs."""
    __tablename__ = "track_telemetry"

    id        = Column(BigInteger, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime(timezone=True), primary_key=True, nullable=False)

    session_id = Column(
        BigInteger,
        ForeignKey("fact_flight_session.session_id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    latitude   = Column(Float,   nullable=False)
    longitude  = Column(Float,   nullable=False)
    altitude_m = Column(Float,   nullable=True)
    velocity_kmh = Column(Float, nullable=True)
    heading_deg  = Column(Float, nullable=True)

    vertical_rate_ms = Column(Float, nullable=True)
    vspeed_fpm = Column(Float, nullable=True)

    is_on_ground = Column(Boolean, default=False)
    squawk       = Column(String(4), nullable=True)

    # ── FIX ADDED HERE: Operations Board Tagging ──────────────────────────
    operation_id = Column(BigInteger, nullable=True)
    chunk_id     = Column(BigInteger, nullable=True)

    session = relationship("FactFlightSession", back_populates="tracks")

    __table_args__ = (
        Index("idx_tracks_session_time", "session_id", "timestamp",
              postgresql_using="btree"),
        Index("idx_tracks_geo", "latitude", "longitude"),
    )


class FactAviationEvent(Base):
    """The Intelligence Layer — tracks anomalies, emergencies, and state changes."""
    __tablename__ = "fact_aviation_events"

    id        = Column(BigInteger, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)

    aircraft_id = Column(Integer,    ForeignKey("dim_aircraft.id"),          nullable=False)
    session_id  = Column(BigInteger, ForeignKey("fact_flight_session.session_id"), nullable=True)

    event_category = Column(String(50), nullable=False)  # EMERGENCY, SYSTEM, FLIGHT
    event_type     = Column(String(50), nullable=False)  # SQUAWK_7700, TAKEOFF, etc.
    event_details  = Column(JSONB, nullable=True)

    __table_args__ = (
        Index("idx_events_lookup", "aircraft_id", "event_category", "timestamp"),
    )


# ═════════════════════════════════════════════════════════════════════════════
# 3. UI ACCELERATION (Denormalized Fast-Read)
# ═════════════════════════════════════════════════════════════════════════════

class CurrentAircraftState(Base):
    """Lightning-fast flat table for the Live Map UI."""
    __tablename__ = "current_aircraft_state"

    icao24       = Column(String(6),   primary_key=True, nullable=False)
    aircraft_id  = Column(Integer,     nullable=True)
    session_id   = Column(BigInteger,  nullable=True)
    fr24_id      = Column(String(20),  nullable=True)
    callsign     = Column(String(20),  nullable=True)
    flight_number = Column(String(20), nullable=True)
    operator_name  = Column(String(255), nullable=True)
    aircraft_type  = Column(String(10),  nullable=True)
    aircraft_model = Column(String(100), nullable=True)
    dep_airport_iata = Column(String(4), nullable=True)
    arr_airport_iata = Column(String(4), nullable=True)
    latitude    = Column(Float,   nullable=True)
    longitude   = Column(Float,   nullable=True)
    altitude_m  = Column(Float,   nullable=True)
    velocity_kmh = Column(Float,  nullable=True)
    heading_deg  = Column(Float,  nullable=True)
    vspeed_fpm   = Column(Float,  nullable=True)
    on_ground    = Column(Boolean, nullable=True)
    squawk       = Column(String(4), nullable=True)
    region_key   = Column(String(50), nullable=True)
    last_updated = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_current_state_updated", "last_updated"),
        Index("idx_current_state_region",  "region_key"),
        Index("idx_current_state_ground",  "on_ground"),
    )


# ═════════════════════════════════════════════════════════════════════════════
# 4. MAINTENANCE
# ═════════════════════════════════════════════════════════════════════════════

class IngestionJob(Base):
    """Tracks worker jobs and API budget usage."""
    __tablename__ = "ingestion_jobs"

    id         = Column(Integer, primary_key=True, index=True)
    job_type   = Column(String(50), nullable=False)
    region_key = Column(String(50), nullable=False)
    status     = Column(String(20), default="pending", nullable=False)

    date_str   = Column(String(10), nullable=True)
    lamin = Column(Float, nullable=True)
    lomin = Column(Float, nullable=True)
    lamax = Column(Float, nullable=True)
    lomax = Column(Float, nullable=True)
    begin_ts = Column(BigInteger, nullable=True)
    end_ts   = Column(BigInteger, nullable=True)

    flights_ingested = Column(Integer, default=0)
    chunks_total     = Column(Integer, default=0)
    chunks_done      = Column(Integer, default=0)

    target_date       = Column(Date,    nullable=True)
    records_processed = Column(Integer, default=0)
    api_calls         = Column(Integer, default=0)
    credits_used      = Column(Integer, default=0)

    error_message = Column(Text,     nullable=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    started_at    = Column(DateTime(timezone=True), nullable=True)
    completed_at  = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_ingestion_lookup", "job_type", "target_date", "region_key"),
        Index("idx_ingestion_status", "status"),
        Index("idx_ingestion_date",   "date_str",  "region_key"),
    )


# ═════════════════════════════════════════════════════════════════════════════
# 5. OPERATIONS BOARD (System Design §1–§4)
# ═════════════════════════════════════════════════════════════════════════════

class ApiCreditRate(Base):
    __tablename__ = "api_credit_rates"

    id               = Column(Integer, primary_key=True)
    capability_type  = Column(String(50), nullable=False, unique=True)
    credits_per_call = Column(Integer,    nullable=False, server_default="0")
    credits_per_record = Column(Float,    nullable=False, server_default="0")
    avg_call_duration_seconds = Column(Float,   nullable=False, server_default="2.0")
    avg_results_per_call      = Column(Integer, nullable=False, server_default="500")
    updated_at = Column(DateTime(timezone=True),
                        server_default=func.now(), onupdate=func.now())
    notes = Column(Text, nullable=True)


class Operation(Base):
    __tablename__ = "operations"

    id            = Column(BigInteger, primary_key=True, autoincrement=True)
    operation_ref = Column(String(20), nullable=False, unique=True)
    capability_type = Column(String(50), nullable=False)

    scope_region_key    = Column(String(50), nullable=True)
    scope_date_from     = Column(Date(),     nullable=True)
    scope_date_to       = Column(Date(),     nullable=True)
    scope_entity_id     = Column(String(50), nullable=True)
    scope_entity_type   = Column(String(30), nullable=True)
    scope_filters       = Column(JSONB,      nullable=True)
    scope_bounds        = Column(JSONB,      nullable=True)

    estimated_chunks           = Column(Integer, nullable=False, server_default="0")
    estimated_api_calls        = Column(Integer, nullable=False, server_default="0")
    estimated_credits          = Column(Integer, nullable=False, server_default="0")
    estimated_duration_seconds = Column(Integer, nullable=False, server_default="0")
    estimated_results          = Column(Integer, nullable=False, server_default="0")

    actual_api_calls        = Column(Integer,    nullable=False, server_default="0")
    actual_credits_used     = Column(Integer,    nullable=False, server_default="0")
    actual_duration_seconds = Column(Integer,    nullable=True)
    total_results_count     = Column(BigInteger, nullable=False, server_default="0")

    status = Column(String(20), nullable=False, server_default="pending")

    chunks_total     = Column(Integer, nullable=False, server_default="0")
    chunks_completed = Column(Integer, nullable=False, server_default="0")
    chunks_failed    = Column(Integer, nullable=False, server_default="0")
    chunks_cancelled = Column(Integer, nullable=False, server_default="0")

    preflight_shown_at = Column(DateTime(timezone=True), nullable=True)
    approved_at        = Column(DateTime(timezone=True), nullable=True)
    approved_by        = Column(String(100), nullable=True, server_default="user")

    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    planned_at   = Column(DateTime(timezone=True), nullable=True)
    started_at   = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    cancelled_at = Column(DateTime(timezone=True), nullable=True)

    cancel_requested = Column(Boolean,     nullable=False, server_default="false")
    cancel_reason    = Column(String(255), nullable=True)
    failure_reason   = Column(Text,        nullable=True)

    result_table        = Column(String(100), nullable=True)
    result_query_filter = Column(JSONB,       nullable=True)

    chunks = relationship(
        "OperationChunk",
        back_populates="operation",
        cascade="all, delete-orphan",
        order_by="OperationChunk.chunk_index",
    )

    __table_args__ = (
        Index("idx_operations_status",   "status"),
        Index("idx_operations_created",  "created_at"),
        Index("idx_operations_ref",      "operation_ref", unique=True),
        Index("idx_operations_cap_date", "capability_type", "scope_date_from"),
    )

    @property
    def progress_pct(self) -> float:
        if not self.chunks_total:
            return 0.0
        return round(self.chunks_completed / self.chunks_total * 100, 1)

    @property
    def is_terminal(self) -> bool:
        return self.status in ("completed", "failed", "cancelled")

    @property
    def can_be_cancelled(self) -> bool:
        return self.status in ("planned", "running", "partial")


class OperationChunk(Base):
    __tablename__ = "operation_chunks"

    id           = Column(BigInteger, primary_key=True, autoincrement=True)
    operation_id = Column(
        BigInteger,
        ForeignKey("operations.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_index = Column(Integer,    nullable=False)
    chunk_type  = Column(String(50), nullable=False)

    date_from      = Column(Date(),     nullable=True)
    date_to        = Column(Date(),     nullable=True)
    timestamp_from = Column(BigInteger, nullable=True)
    timestamp_to   = Column(BigInteger, nullable=True)

    region_key = Column(String(50), nullable=True)
    bounds     = Column(JSONB,      nullable=True)
    entity_id = Column(String(100), nullable=True)

    fr24_endpoint = Column(String(200), nullable=True)
    fr24_params   = Column(JSONB,       nullable=True)

    status = Column(String(20), nullable=False, server_default="pending")

    attempt_count   = Column(Integer, nullable=False, server_default="0")
    max_attempts    = Column(Integer, nullable=False, server_default="3")
    last_attempt_at = Column(DateTime(timezone=True), nullable=True)
    next_retry_at   = Column(DateTime(timezone=True), nullable=True)

    results_count           = Column(Integer, nullable=False, server_default="0")
    api_response_size_bytes = Column(Integer, nullable=True)
    credits_used            = Column(Integer, nullable=False, server_default="0")

    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    started_at   = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    last_error  = Column(Text,    nullable=True)
    http_status = Column(Integer, nullable=True)

    partial_result_key = Column(String(200), nullable=True)

    operation = relationship("Operation", back_populates="chunks")

    __table_args__ = (
        Index("idx_chunks_operation", "operation_id", "chunk_index"),
        Index("idx_chunks_status",    "status"),
        UniqueConstraint("operation_id", "chunk_index", name="uq_chunk_index"),
    )

    @property
    def is_terminal(self) -> bool:
        return self.status in ("completed", "failed", "cancelled", "skipped")

    @property
    def can_retry(self) -> bool:
        return self.status == "failed" and self.attempt_count < self.max_attempts