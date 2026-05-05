"""Enterprise Architecture - Snowflake Schema + Fast State Table + Events + Indexes

Revision ID: 001
Revises: 
Create Date: 2026-04-26 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None

def upgrade() -> None:
    # =========================================================================
    # 1. CREATE DIMENSION TABLES (Reference Data)
    # =========================================================================
    
    # DimGeography (Airports & Regions)
    op.create_table(
        'dim_geography',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('icao_code', sa.String(length=4), nullable=True),
        sa.Column('iata_code', sa.String(length=3), nullable=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('city', sa.String(length=100), nullable=True),
        sa.Column('country_code', sa.String(length=2), nullable=True),
        sa.Column('latitude', sa.Float(), nullable=True),
        sa.Column('longitude', sa.Float(), nullable=True),
        sa.Column('elevation_m', sa.Float(), nullable=True),
        sa.Column('meta_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('icao_code')
    )
    op.create_index(op.f('ix_dim_geography_country_code'), 'dim_geography', ['country_code'], unique=False)
    op.create_index(op.f('ix_dim_geography_iata_code'), 'dim_geography', ['iata_code'], unique=False)

    # DimOperator (Airlines)
    op.create_table(
        'dim_operator',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('icao_code', sa.String(length=3), nullable=True),
        sa.Column('iata_code', sa.String(length=2), nullable=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('country_code', sa.String(length=2), nullable=True),
        sa.Column('operator_type', sa.String(length=50), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('icao_code')
    )
    op.create_index(op.f('ix_dim_operator_iata_code'), 'dim_operator', ['iata_code'], unique=False)

    # DimAircraft (The Physical Asset)
    op.create_table(
        'dim_aircraft',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('icao24', sa.String(length=6), nullable=False),
        sa.Column('registration', sa.String(length=20), nullable=True),
        sa.Column('manufacturer', sa.String(length=100), nullable=True),
        sa.Column('model', sa.String(length=100), nullable=True),
        sa.Column('type_code', sa.String(length=10), nullable=True),
        sa.Column('serial_number', sa.String(length=100), nullable=True),
        sa.Column('year_built', sa.Integer(), nullable=True),
        sa.Column('operator_id', sa.Integer(), nullable=True),
        sa.Column('country_code', sa.String(length=2), nullable=True),
        sa.Column('valid_from', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('valid_to', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['operator_id'], ['dim_operator.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_aircraft_hex_active', 'dim_aircraft', ['icao24', 'valid_to'], unique=False)
    op.create_index(op.f('ix_dim_aircraft_icao24'), 'dim_aircraft', ['icao24'], unique=False)
    op.create_index(op.f('ix_dim_aircraft_registration'), 'dim_aircraft', ['registration'], unique=False)
    op.create_index(op.f('ix_dim_aircraft_type_code'), 'dim_aircraft', ['type_code'], unique=False)


    # =========================================================================
    # 2. CREATE FACT TABLES (Operational Data)
    # =========================================================================

    # FactFlightSession (The Journey)
    op.create_table(
        'fact_flight_session',
        sa.Column('session_id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('aircraft_id', sa.Integer(), nullable=False),
        sa.Column('operator_id', sa.Integer(), nullable=True),
        sa.Column('callsign', sa.String(length=20), nullable=True),
        sa.Column('dep_airport_id', sa.Integer(), nullable=True),
        sa.Column('arr_airport_id', sa.Integer(), nullable=True),
        sa.Column('first_seen_ts', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_seen_ts', sa.DateTime(timezone=True), nullable=False),
        sa.Column('actual_takeoff_ts', sa.DateTime(timezone=True), nullable=True),
        sa.Column('actual_landing_ts', sa.DateTime(timezone=True), nullable=True),
        sa.Column('flight_status', sa.String(length=20), nullable=True),
        sa.Column('total_distance_km', sa.Float(), nullable=True),
        sa.Column('max_altitude_m', sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(['aircraft_id'], ['dim_aircraft.id'], ),
        sa.ForeignKeyConstraint(['arr_airport_id'], ['dim_geography.id'], ),
        sa.ForeignKeyConstraint(['dep_airport_id'], ['dim_geography.id'], ),
        sa.ForeignKeyConstraint(['operator_id'], ['dim_operator.id'], ),
        sa.PrimaryKeyConstraint('session_id')
    )
    op.create_index('idx_flight_route', 'fact_flight_session', ['dep_airport_id', 'arr_airport_id'], unique=False)
    op.create_index('idx_flight_search', 'fact_flight_session', ['callsign', 'first_seen_ts'], unique=False)
    op.create_index(op.f('ix_fact_flight_session_aircraft_id'), 'fact_flight_session', ['aircraft_id'], unique=False)
    op.create_index(op.f('ix_fact_flight_session_flight_status'), 'fact_flight_session', ['flight_status'], unique=False)

    # TrackTelemetry (The Time-Series Radar Breadcrumbs)
    op.create_table(
        'track_telemetry',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('session_id', sa.BigInteger(), nullable=False),
        sa.Column('latitude', sa.Float(), nullable=False),
        sa.Column('longitude', sa.Float(), nullable=False),
        sa.Column('altitude_m', sa.Float(), nullable=True),
        sa.Column('velocity_kmh', sa.Float(), nullable=True),
        sa.Column('heading_deg', sa.Float(), nullable=True),
        sa.Column('vertical_rate_ms', sa.Float(), nullable=True),
        sa.Column('is_on_ground', sa.Boolean(), nullable=True),
        sa.Column('squawk', sa.String(length=4), nullable=True),
        sa.ForeignKeyConstraint(['session_id'], ['fact_flight_session.session_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', 'timestamp') # Composite PK required for Time-Series partitioning
    )
    op.create_index('idx_tracks_geo', 'track_telemetry', ['latitude', 'longitude'], unique=False)
    op.create_index('idx_tracks_session_time', 'track_telemetry', ['session_id', 'timestamp'], unique=False, postgresql_using='btree')

    # FactAviationEvents (The Intelligence Layer)
    op.create_table(
        'fact_aviation_events',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('aircraft_id', sa.Integer(), nullable=False),
        sa.Column('session_id', sa.BigInteger(), nullable=True),
        sa.Column('event_category', sa.String(length=50), nullable=False),
        sa.Column('event_type', sa.String(length=50), nullable=False),
        sa.Column('event_details', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(['aircraft_id'], ['dim_aircraft.id'], ),
        sa.ForeignKeyConstraint(['session_id'], ['fact_flight_session.session_id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_events_lookup', 'fact_aviation_events', ['aircraft_id', 'event_category', 'timestamp'], unique=False)

    # =========================================================================
    # 3. CREATE FAST-READ TABLES (UI Performance)
    # =========================================================================

    # Current Aircraft State (Denormalized table for lightning-fast Map UI)
    op.create_table(
        'current_aircraft_state',
        sa.Column('icao24', sa.String(length=6), nullable=False),
        sa.Column('aircraft_id', sa.Integer(), nullable=True),
        sa.Column('session_id', sa.BigInteger(), nullable=True),
        sa.Column('callsign', sa.String(length=20), nullable=True),
        sa.Column('operator_name', sa.String(length=255), nullable=True),
        sa.Column('aircraft_model', sa.String(length=100), nullable=True),
        sa.Column('dep_airport_iata', sa.String(length=4), nullable=True),
        sa.Column('arr_airport_iata', sa.String(length=4), nullable=True),
        sa.Column('latitude', sa.Float(), nullable=True),
        sa.Column('longitude', sa.Float(), nullable=True),
        sa.Column('altitude_m', sa.Float(), nullable=True),
        sa.Column('velocity_kmh', sa.Float(), nullable=True),
        sa.Column('heading_deg', sa.Float(), nullable=True),
        sa.Column('on_ground', sa.Boolean(), nullable=True),
        sa.Column('squawk', sa.String(length=4), nullable=True),
        sa.Column('last_updated', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('icao24')
    )
    op.create_index('idx_current_state_updated', 'current_aircraft_state', ['last_updated'], unique=False)

    # =========================================================================
    # 4. SYSTEM MAINTENANCE (Audit & Worker Jobs)
    # =========================================================================

    op.create_table(
        'ingestion_jobs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('job_type', sa.String(length=50), nullable=False),
        sa.Column('target_date', sa.Date(), nullable=True),
        sa.Column('region_key', sa.String(length=50), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('records_processed', sa.Integer(), nullable=True),
        sa.Column('api_calls', sa.Integer(), default=0, nullable=True),
        sa.Column('credits_used', sa.Integer(), default=0, nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_ingestion_lookup', 'ingestion_jobs', ['job_type', 'target_date', 'region_key'], unique=False)


def downgrade() -> None:
    # Reverse order drop
    op.drop_table('ingestion_jobs')
    op.drop_table('current_aircraft_state')
    op.drop_table('fact_aviation_events')
    op.drop_table('track_telemetry')
    op.drop_table('fact_flight_session')
    op.drop_table('dim_aircraft')
    op.drop_table('dim_operator')
    op.drop_table('dim_geography')