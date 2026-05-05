#!/bin/bash
set -e

echo "🚀 Flight Intelligence – Starting up"

# ── Validate DATABASE_URL ─────────────────────────────────────────────────────
if [ -z "$DATABASE_URL" ]; then
    echo "❌ ERROR: DATABASE_URL is not set."
    echo "   In Railway: add DATABASE_URL = \${{Postgres.DATABASE_URL}}"
    exit 1
fi

# Convert postgres:// → postgresql:// (Railway / Heroku compatibility)
if [[ "$DATABASE_URL" == postgres://* ]]; then
    export DATABASE_URL="${DATABASE_URL/postgres:\/\//postgresql:\/\/}"
    echo "✅ Converted postgres:// → postgresql://"
fi
echo "✅ DATABASE_URL OK"

# ── REDIS_URL ─────────────────────────────────────────────────────────────────
if [ -z "$REDIS_URL" ]; then
    echo "⚠️  REDIS_URL not set – Celery will not run"
else
    echo "✅ REDIS_URL OK (${REDIS_URL:0:25}…)"
fi

# ── Run Alembic migrations ────────────────────────────────────────────────────
# ROOT CAUSE NOTE: PYTHONPATH must be EMPTY when running alembic.
# If /app/backend is in PYTHONPATH, Python resolves the local /app/backend/alembic/
# directory before the installed 'alembic' package → ModuleNotFoundError.
# alembic/env.py adds /app/backend to sys.path itself after alembic loads.
echo "🔄 Running database migrations..."
export PYTHONPATH=/app/backend:/app
PYTHONPATH="" alembic -c /app/backend/alembic.ini upgrade head
echo "✅ Migrations complete"

# ── Start Celery worker & beat ────────────────────────────────────────────────
if [ -n "$REDIS_URL" ]; then
    echo "🔄 Starting Celery worker..."
    celery -A worker.celery_app worker \
        -l info \
        -Q ingestion,maintenance,default \
        --concurrency=2 \
        --without-gossip \
        --without-mingle &

    echo "🔄 Starting Celery beat..."
    celery -A worker.celery_app beat -l info &
else
    echo "⚠️  Celery skipped (no REDIS_URL)"
fi

# ── Start FastAPI ─────────────────────────────────────────────────────────────
echo "🚀 Starting FastAPI on port ${PORT:-8000}..."
cd /app/backend
exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --workers 1
