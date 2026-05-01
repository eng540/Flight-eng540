"""Alembic environment."""
import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# ── Path setup ────────────────────────────────────────────────────────────────
# Add backend and root directories to sys.path so app.models can be imported.
# We use absolute paths derived from this file's location to be location-agnostic.
_this_dir    = os.path.dirname(os.path.abspath(__file__))   # .../alembic/
_backend_dir = os.path.dirname(_this_dir)                   # .../backend/
_app_dir     = os.path.dirname(_backend_dir)                # .../  (project root)

for _p in (_backend_dir, _app_dir):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── DATABASE_URL ──────────────────────────────────────────────────────────────
def _get_db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        try:
            from app.config import settings
            url = settings.DATABASE_URL
        except Exception:
            pass
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. "
            "In Railway: add DATABASE_URL = ${{Postgres.DATABASE_URL}}"
        )
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url

# ── Import models (must come AFTER sys.path is set) ──────────────────────────
from app.models import Base  # noqa: E402

# ── Alembic config ────────────────────────────────────────────────────────────
config = context.config
config.set_main_option("sqlalchemy.url", _get_db_url())

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


# ── Migration runners ─────────────────────────────────────────────────────────

def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
