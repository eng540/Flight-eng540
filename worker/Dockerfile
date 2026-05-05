FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install backend deps (worker imports app.* modules)
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy both backend and worker code
# Worker imports app.config, app.models, app.crud, app.database
COPY backend/ ./backend/
COPY worker/  ./worker/

# PYTHONPATH so `from app.xxx import` resolves correctly
ENV PYTHONPATH=/app/backend

RUN useradd -m -u 1001 celeryuser && chown -R celeryuser:celeryuser /app
USER celeryuser

# Default: run worker on ingestion + maintenance queues
# Override CMD in docker-compose for beat scheduler
CMD ["celery", "-A", "worker.celery_app:celery_app", "worker", \
     "--queues=ingestion,maintenance", \
     "--loglevel=info", "--concurrency=2"]
