"""add data_source columns for multi-source tracking

Revision ID: 005
Revises: 004
Create Date: 2026-05-06
"""
from alembic import op
import sqlalchemy as sa

revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None

def upgrade():
    # Add data_source to current_aircraft_state
    op.add_column('current_aircraft_state', 
                  sa.Column('data_source', sa.String(20), nullable=True))
    # Add data_source to track_telemetry
    op.add_column('track_telemetry', 
                  sa.Column('data_source', sa.String(20), nullable=True))
    
    # Optional: create indexes for performance
    op.create_index('idx_current_state_data_source', 'current_aircraft_state', ['data_source'])
    op.create_index('idx_tracks_data_source', 'track_telemetry', ['data_source'])

def downgrade():
    op.drop_index('idx_tracks_data_source', table_name='track_telemetry')
    op.drop_index('idx_current_state_data_source', table_name='current_aircraft_state')
    op.drop_column('track_telemetry', 'data_source')
    op.drop_column('current_aircraft_state', 'data_source')