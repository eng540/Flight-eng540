"""Add FR24 fields and fix IngestionJob schema alignment

Revision ID: 002
Revises: 001
Create Date: 2026-04-27 00:00:00.000000

WHAT THIS MIGRATION DOES:
  - Adds fr24_id, flight_number to fact_flight_session
  - Adds vspeed_fpm to track_telemetry
  - Adds fr24_id, flight_number, aircraft_type, region_key, vspeed_fpm
    to current_aircraft_state
  - Adds date_str, lamin, lomin, lamax, lomax, begin_ts, end_ts,
    flights_ingested, chunks_total, chunks_done, created_at to ingestion_jobs

WHY (evidence-based):
  - fr24_id: FR24 OpenAPI FlightPositionsFull.fr24_id — required for
    /api/flight-tracks and /api/flight-summary calls.
  - flight_number: FR24 OpenAPI FlightPositionsFull.flight — commercial
    flight number, distinct from ATC callsign.
  - vspeed_fpm: FR24 OpenAPI FlightPositionsFull.vspeed (ft/min).
  - aircraft_type: FR24 OpenAPI FlightPositionsFull.type (ICAO type code).
  - IngestionJob additions: Fix ValidationError crash — IngestionJobResponse
    in schemas.py referenced 9 columns absent from the model.

SAFETY: No existing columns are modified or dropped. All new columns are
nullable or have sensible defaults — safe on live databases.
"""
from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── fact_flight_session ───────────────────────────────────────────────
    # fr24_id: FR24 primary identifier — needed for enrichment API calls
    op.add_column(
        "fact_flight_session",
        sa.Column("fr24_id", sa.String(length=20), nullable=True),
    )
    op.create_index(
        "idx_flight_fr24", "fact_flight_session", ["fr24_id"], unique=False
    )

    # flight_number: Commercial flight number e.g. "SV461" (FR24 field: flight)
    op.add_column(
        "fact_flight_session",
        sa.Column("flight_number", sa.String(length=20), nullable=True),
    )
    op.create_index(
        "idx_flight_number",
        "fact_flight_session",
        ["flight_number", "first_seen_ts"],
        unique=False,
    )

    # ── track_telemetry ───────────────────────────────────────────────────
    # vspeed_fpm: Vertical rate in feet per minute (FR24 native unit)
    op.add_column(
        "track_telemetry",
        sa.Column("vspeed_fpm", sa.Float(), nullable=True),
    )

    # ── current_aircraft_state ────────────────────────────────────────────
    op.add_column(
        "current_aircraft_state",
        sa.Column("fr24_id", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "current_aircraft_state",
        sa.Column("flight_number", sa.String(length=20), nullable=True),
    )
    # aircraft_type: ICAO type code e.g. "B77W" (FR24 field: type)
    op.add_column(
        "current_aircraft_state",
        sa.Column("aircraft_type", sa.String(length=10), nullable=True),
    )
    # region_key: stored for O(1) region filtering on live map
    op.add_column(
        "current_aircraft_state",
        sa.Column("region_key", sa.String(length=50), nullable=True),
    )
    # vspeed_fpm: for live map vertical rate display
    op.add_column(
        "current_aircraft_state",
        sa.Column("vspeed_fpm", sa.Float(), nullable=True),
    )
    op.create_index(
        "idx_current_state_region",
        "current_aircraft_state",
        ["region_key"],
        unique=False,
    )
    op.create_index(
        "idx_current_state_ground",
        "current_aircraft_state",
        ["on_ground"],
        unique=False,
    )

    # ── ingestion_jobs ────────────────────────────────────────────────────
    # All columns below fix the IngestionJobResponse ValidationError crash.
    op.add_column(
        "ingestion_jobs",
        sa.Column("date_str", sa.String(length=10), nullable=True),
    )
    op.add_column(
        "ingestion_jobs",
        sa.Column("lamin", sa.Float(), nullable=True),
    )
    op.add_column(
        "ingestion_jobs",
        sa.Column("lomin", sa.Float(), nullable=True),
    )
    op.add_column(
        "ingestion_jobs",
        sa.Column("lamax", sa.Float(), nullable=True),
    )
    op.add_column(
        "ingestion_jobs",
        sa.Column("lomax", sa.Float(), nullable=True),
    )
    op.add_column(
        "ingestion_jobs",
        sa.Column("begin_ts", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "ingestion_jobs",
        sa.Column("end_ts", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "ingestion_jobs",
        sa.Column("flights_ingested", sa.Integer(), nullable=True, server_default="0"),
    )
    op.add_column(
        "ingestion_jobs",
        sa.Column("chunks_total", sa.Integer(), nullable=True, server_default="0"),
    )
    op.add_column(
        "ingestion_jobs",
        sa.Column("chunks_done", sa.Integer(), nullable=True, server_default="0"),
    )
    op.add_column(
        "ingestion_jobs",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=True,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "idx_ingestion_status",
        "ingestion_jobs",
        ["status"],
        unique=False,
    )
    op.create_index(
        "idx_ingestion_date",
        "ingestion_jobs",
        ["date_str", "region_key"],
        unique=False,
    )


def downgrade() -> None:
    # Drop indexes first, then columns — reverse of upgrade order.

    # ingestion_jobs
    op.drop_index("idx_ingestion_date",   table_name="ingestion_jobs")
    op.drop_index("idx_ingestion_status", table_name="ingestion_jobs")
    for col in ["created_at", "chunks_done", "chunks_total", "flights_ingested",
                "end_ts", "begin_ts", "lomax", "lamax", "lomin", "lamin", "date_str"]:
        op.drop_column("ingestion_jobs", col)

    # current_aircraft_state
    op.drop_index("idx_current_state_ground",  table_name="current_aircraft_state")
    op.drop_index("idx_current_state_region",  table_name="current_aircraft_state")
    for col in ["vspeed_fpm", "region_key", "aircraft_type", "flight_number", "fr24_id"]:
        op.drop_column("current_aircraft_state", col)

    # track_telemetry
    op.drop_column("track_telemetry", "vspeed_fpm")

    # fact_flight_session
    op.drop_index("idx_flight_number", table_name="fact_flight_session")
    op.drop_column("fact_flight_session", "flight_number")
    op.drop_index("idx_flight_fr24",   table_name="fact_flight_session")
    op.drop_column("fact_flight_session", "fr24_id")
