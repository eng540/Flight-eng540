"""Operations Board — full schema

Revision ID: 003
Revises: 002
Create Date: 2026-04-30

WHAT THIS MIGRATION DOES:
  CREATE TABLE  operations              ← user-intent entity
  CREATE TABLE  operation_chunks        ← execution units (one FR24 call each)
  CREATE TABLE  api_credit_rates        ← updatable credit cost table
  ALTER TABLE   fact_flight_session     ← add operation_id + chunk_id
  ALTER TABLE   track_telemetry         ← add operation_id + chunk_id
  CREATE VIEW   operation_progress_view ← live progress polling

WHY (evidence — system design document):
  §1  Operation model: "نموذج جديد منفصل تماماً"
  §2  Chunk model: one chunk = one FR24 API call
  §4  Pre-flight: "api_credit_rates (DB table — updatable)"
  §6  Partial results: "operation_id + chunk_id لكل صف"
  §6  Monitoring: "operation_progress_view (PostgreSQL VIEW)"

SAFETY:
  All new columns on existing tables are nullable — safe on live data.
  No existing columns are dropped or modified.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision     = "003"
down_revision = "002"
branch_labels = None
depends_on    = None


def upgrade() -> None:

    # ── 1. operations ──────────────────────────────────────────────────────
    op.create_table(
        "operations",
        sa.Column("id",            sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("operation_ref", sa.String(20),   nullable=False, unique=True),

        # Classification
        sa.Column("capability_type", sa.String(50), nullable=False),

        # Scope
        sa.Column("scope_region_key",  sa.String(50),  nullable=True),
        sa.Column("scope_date_from",   sa.Date(),       nullable=True),
        sa.Column("scope_date_to",     sa.Date(),       nullable=True),
        sa.Column("scope_entity_id",   sa.String(50),   nullable=True),
        sa.Column("scope_entity_type", sa.String(30),   nullable=True),
        sa.Column("scope_filters",     JSONB,           nullable=True),
        sa.Column("scope_bounds",      JSONB,           nullable=True),

        # Pre-flight estimates
        sa.Column("estimated_chunks",           sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_api_calls",        sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_credits",          sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_duration_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_results",          sa.Integer(), nullable=False, server_default="0"),

        # Actuals
        sa.Column("actual_api_calls",        sa.Integer(),    nullable=False, server_default="0"),
        sa.Column("actual_credits_used",     sa.Integer(),    nullable=False, server_default="0"),
        sa.Column("actual_duration_seconds", sa.Integer(),    nullable=True),
        sa.Column("total_results_count",     sa.BigInteger(), nullable=False, server_default="0"),

        # State machine
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),

        # Progress counters
        sa.Column("chunks_total",     sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chunks_completed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chunks_failed",    sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chunks_cancelled", sa.Integer(), nullable=False, server_default="0"),

        # Approval gate
        sa.Column("preflight_shown_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at",        sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by",        sa.String(100), nullable=True, server_default="'user'"),

        # Lifecycle
        sa.Column("created_at",   sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("planned_at",   sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at",   sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),

        # Cancellation / failure
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("cancel_reason",    sa.String(255), nullable=True),
        sa.Column("failure_reason",   sa.Text(),      nullable=True),

        # Result location
        sa.Column("result_table",        sa.String(100), nullable=True),
        sa.Column("result_query_filter", JSONB,          nullable=True),

        # Constraints
        sa.CheckConstraint(
            "status IN ('pending','planned','running','partial',"
            "'completed','failed','cancelled')",
            name="chk_operation_status",
        ),
        sa.CheckConstraint(
            "capability_type IN ('live_positions','flight_summaries',"
            "'flight_tracks','historic_positions','historic_events',"
            "'static_airport','static_airline')",
            name="chk_operation_capability",
        ),
    )
    op.create_index("idx_operations_status",   "operations", ["status"])
    op.create_index("idx_operations_created",  "operations", ["created_at"])
    op.create_index("idx_operations_ref",      "operations", ["operation_ref"], unique=True)
    op.create_index("idx_operations_cap_date", "operations",
                    ["capability_type", "scope_date_from"])

    # ── 2. operation_chunks ────────────────────────────────────────────────
    op.create_table(
        "operation_chunks",
        sa.Column("id",           sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("operation_id", sa.BigInteger(),
                  sa.ForeignKey("operations.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("chunk_index",  sa.Integer(), nullable=False),
        sa.Column("chunk_type",   sa.String(50), nullable=False),

        # Temporal scope
        sa.Column("date_from",       sa.Date(),      nullable=True),
        sa.Column("date_to",         sa.Date(),      nullable=True),
        sa.Column("timestamp_from",  sa.BigInteger(), nullable=True),
        sa.Column("timestamp_to",    sa.BigInteger(), nullable=True),

        # Geographic scope
        sa.Column("region_key", sa.String(50), nullable=True),
        sa.Column("bounds",     JSONB,          nullable=True),

        # Entity scope
        sa.Column("entity_id", sa.String(100), nullable=True),

        # FR24 API call spec
        sa.Column("fr24_endpoint", sa.String(200), nullable=True),
        sa.Column("fr24_params",   JSONB,          nullable=True),

        # State machine
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),

        # Execution tracking
        sa.Column("attempt_count",   sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts",    sa.Integer(), nullable=False, server_default="3"),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_retry_at",   sa.DateTime(timezone=True), nullable=True),

        # Results
        sa.Column("results_count",          sa.Integer(), nullable=False, server_default="0"),
        sa.Column("api_response_size_bytes", sa.Integer(), nullable=True),
        sa.Column("credits_used",           sa.Integer(), nullable=False, server_default="0"),

        # Lifecycle
        sa.Column("created_at",   sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("started_at",   sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),

        # Error
        sa.Column("last_error",  sa.Text(),    nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),

        # Partial result pointer
        sa.Column("partial_result_key", sa.String(200), nullable=True),

        # Constraints
        sa.CheckConstraint(
            "status IN ('pending','running','completed','failed','cancelled','skipped')",
            name="chk_chunk_status",
        ),
        sa.UniqueConstraint("operation_id", "chunk_index", name="uq_chunk_index"),
    )
    op.create_index("idx_chunks_operation", "operation_chunks",
                    ["operation_id", "chunk_index"])
    op.create_index("idx_chunks_status", "operation_chunks", ["status"])
    # Partial index for retry scheduler — only failed chunks that can be retried
    op.execute(
        """
        CREATE INDEX idx_chunks_retry
        ON operation_chunks (next_retry_at)
        WHERE status = 'failed' AND attempt_count < max_attempts
        """
    )

    # ── 3. api_credit_rates ────────────────────────────────────────────────
    # Evidence: §4 Pre-flight: "قابلة للتحديث في جدول منفصل"
    op.create_table(
        "api_credit_rates",
        sa.Column("id",               sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("capability_type",  sa.String(50), nullable=False, unique=True),
        sa.Column("credits_per_call", sa.Integer(),  nullable=False, server_default="0"),
        sa.Column("credits_per_record", sa.Float(), nullable=False, server_default="0"),
        sa.Column("avg_call_duration_seconds", sa.Float(), nullable=False, server_default="2.0"),
        sa.Column("avg_results_per_call",      sa.Integer(), nullable=False, server_default="500"),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("notes", sa.Text(), nullable=True),
    )

    # Seed initial rates from system design §4
    op.execute(
        """
        INSERT INTO api_credit_rates
            (capability_type, credits_per_call, credits_per_record,
             avg_call_duration_seconds, avg_results_per_call, notes)
        VALUES
            ('live_positions',    10,  0,    2.0, 450,  'FR24 live positions endpoint'),
            ('historic_positions',20,  0,    3.0, 800,  'FR24 historic positions endpoint'),
            ('flight_summaries',  5,   0.1,  2.5, 1200, 'FR24 flight summary endpoint'),
            ('flight_tracks',     5,   0,    1.5, 120,  'FR24 flight tracks per flight_id'),
            ('historic_events',   15,  0,    2.5, 300,  'FR24 historic events endpoint'),
            ('static_airport',    0,   0,    1.0, 1,    'Static data - free'),
            ('static_airline',    0,   0,    1.0, 1,    'Static data - free')
        """
    )

    # ── 4. ALTER fact_flight_session ───────────────────────────────────────
    # Evidence: §6 "إضافة operation_id + chunk_id لكل صف في fact_flight_session"
    op.add_column(
        "fact_flight_session",
        sa.Column("operation_id", sa.BigInteger(),
                  sa.ForeignKey("operations.id"), nullable=True),
    )
    op.add_column(
        "fact_flight_session",
        sa.Column("chunk_id", sa.BigInteger(),
                  sa.ForeignKey("operation_chunks.id"), nullable=True),
    )
    op.create_index("idx_session_operation", "fact_flight_session",
                    ["operation_id", "chunk_id"])

    # ── 5. ALTER track_telemetry ───────────────────────────────────────────
    op.add_column(
        "track_telemetry",
        sa.Column("operation_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "track_telemetry",
        sa.Column("chunk_id", sa.BigInteger(), nullable=True),
    )

    # ── 6. operation_progress_view ─────────────────────────────────────────
    # Evidence: §6 "VIEW لا جدول فعلي — polling every 3s"
    op.execute(
        """
        CREATE VIEW operation_progress_view AS
        SELECT
            o.id,
            o.operation_ref,
            o.capability_type,
            o.status,
            o.chunks_total,
            o.chunks_completed,
            o.chunks_failed,
            o.chunks_cancelled,
            o.total_results_count,
            o.actual_credits_used,
            o.estimated_credits,
            o.cancel_requested,
            CASE
                WHEN o.chunks_total = 0 THEN 0.0
                ELSE ROUND(
                    o.chunks_completed::NUMERIC / o.chunks_total * 100, 1
                )
            END AS progress_pct,
            o.created_at,
            o.started_at,
            o.completed_at,
            (
                SELECT json_build_object(
                    'index',      oc.chunk_index,
                    'date_from',  oc.date_from,
                    'date_to',    oc.date_to,
                    'entity_id',  oc.entity_id,
                    'status',     oc.status,
                    'started_at', oc.started_at
                )
                FROM operation_chunks oc
                WHERE oc.operation_id = o.id
                  AND oc.status = 'running'
                ORDER BY oc.chunk_index
                LIMIT 1
            ) AS current_chunk,
            (
                SELECT json_build_object(
                    'index',         oc.chunk_index,
                    'date_from',     oc.date_from,
                    'results_count', oc.results_count,
                    'credits_used',  oc.credits_used,
                    'completed_at',  oc.completed_at
                )
                FROM operation_chunks oc
                WHERE oc.operation_id = o.id
                  AND oc.status = 'completed'
                ORDER BY oc.chunk_index DESC
                LIMIT 1
            ) AS last_completed_chunk
        FROM operations o
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS operation_progress_view")

    # Remove FK columns from existing tables
    op.drop_index("idx_session_operation", table_name="fact_flight_session")
    op.drop_column("fact_flight_session", "chunk_id")
    op.drop_column("fact_flight_session", "operation_id")
    op.drop_column("track_telemetry", "chunk_id")
    op.drop_column("track_telemetry", "operation_id")

    # Drop new tables (reverse creation order)
    op.execute("DROP INDEX IF EXISTS idx_chunks_retry")
    op.drop_index("idx_chunks_status",    table_name="operation_chunks")
    op.drop_index("idx_chunks_operation", table_name="operation_chunks")
    op.drop_table("operation_chunks")

    op.drop_index("idx_operations_cap_date", table_name="operations")
    op.drop_index("idx_operations_ref",      table_name="operations")
    op.drop_index("idx_operations_created",  table_name="operations")
    op.drop_index("idx_operations_status",   table_name="operations")
    op.drop_table("operations")

    op.drop_table("api_credit_rates")
