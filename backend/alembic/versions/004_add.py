"""Add source and eta fields — Truth compliance fix

Revision ID: 004
Revises: 003

WHY:
  FR24 OpenAPI FlightPositionsFull schema defines:
    source: string — data source (ADSB, MLAT, ESTIMATED, FLARM, ADSB_ICAO)
    eta:    string — estimated time of arrival (ISO 8601)

  DEVIATION FOUND: Both fields were parsed from FR24 response but never
  stored in the database. RawIngestionPayload, ingestion_service._parse_fr24_position,
  and CurrentAircraftState all missing these fields.

  FIX: Add source + eta columns to current_aircraft_state.
  Nullable on existing rows — backward safe.
"""
from alembic import op
import sqlalchemy as sa

revision     = "004"
down_revision = "003"
branch_labels = None
depends_on    = None


def upgrade() -> None:
    # current_aircraft_state — add source + eta
    op.add_column(
        "current_aircraft_state",
        sa.Column(
            "source", sa.String(length=20), nullable=True,
            comment="FR24 FlightPositionsFull.source: ADSB|MLAT|ESTIMATED|FLARM",
        ),
    )
    op.add_column(
        "current_aircraft_state",
        sa.Column(
            "eta", sa.String(length=30), nullable=True,
            comment="FR24 FlightPositionsFull.eta: ISO 8601 estimated arrival",
        ),
    )


def downgrade() -> None:
    op.drop_column("current_aircraft_state", "eta")
    op.drop_column("current_aircraft_state", "source")
