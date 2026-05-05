"""Celery application – supports redis:// and rediss:// (Upstash/TLS)."""
import os
import ssl
import logging

from celery import Celery
from celery.signals import task_failure, task_success, worker_ready

logger = logging.getLogger(__name__)

# FIX: kombu "No hostname" warning when REDIS_URL is empty.
# Use docker service name 'redis' not 'localhost' as default.
REDIS_URL = os.getenv("REDIS_URL", "").strip()
if not REDIS_URL or not REDIS_URL.startswith("redis"):
    import logging as _log
    _log.warning("[celery_app] REDIS_URL missing — defaulting to redis://redis:6379/0")
    REDIS_URL = "redis://redis:6379/0"


def _ssl_options() -> dict:
    return {"ssl_cert_reqs": ssl.CERT_NONE,
            "ssl_ca_certs": None, "ssl_certfile": None, "ssl_keyfile": None}


celery_app = Celery(
    "flight_intelligence",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=[
        "worker.tasks",                   # ingest_recent_geo_task, cleanup, etc.
        "worker.tasks.operations_task",   # execute_operation_task, retry_chunks_task
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_ignore_result=False,
    result_expires=3600,
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,
    broker_connection_retry_on_startup=True,
    beat_schedule_filename="/tmp/celerybeat-schedule",

    beat_schedule={
        # ── Geo-filtered ingestion every 60 min (was 30, reduced to ease load)
        "ingest-geo-every-60-minutes": {
            "task": "worker.tasks.ingest_recent_geo_task",
            "schedule": 3600.0,
        },
        # ── Cleanup daily (keeps all data by default; DATA_RETENTION_DAYS=0)
        "recover-stalled-ops": {
            "task": "worker.tasks.recover_stalled_operations",
            "schedule": 60.0,   # every 60 seconds
            "options": {"queue": "maintenance"},
        },
        "retry-ops-chunks": {
            "task": "worker.tasks.operations_task.retry_chunks_task",
            "schedule": 30.0,
            "options": {"queue": "maintenance"},
        },
        "cleanup-old-data-daily": {
            "task": "worker.tasks.cleanup_old_data_task",
            "schedule": 86400.0,
            "args": (0,),
        },
        # NOTE: ingest_flights_task (global, no geo) REMOVED.
        # It was calling /flights/all which times out from cloud IPs exactly
        # like /flights/area.  Removing it stops wasting one worker thread
        # on 4-minute timeout loops every 5 minutes.
    },

    task_routes={
        "worker.tasks.ingest_recent_geo_task":    {"queue": "ingestion"},
        "worker.tasks.ingest_historical_flights": {"queue": "ingestion"},
        "worker.tasks.ingest_flights_task":       {"queue": "ingestion"},
        "worker.tasks.cleanup_old_data_task":     {"queue": "maintenance"},
        "worker.tasks.operations_task.execute_operation_task": {"queue": "ingestion"},
        "worker.tasks.operations_task.retry_chunks_task":      {"queue": "maintenance"},
        "worker.tasks.recover_stalled_operations":             {"queue": "maintenance"},
        "worker.tasks.run_realtime_radar_task":   {"queue": "ingestion"},
    },
)

if REDIS_URL.startswith("rediss://"):
    logger.info("rediss:// detected – configuring SSL for broker/backend")
    ssl_opts = _ssl_options()
    celery_app.conf.broker_use_ssl        = ssl_opts
    celery_app.conf.redis_backend_use_ssl = ssl_opts
    celery_app.conf.broker_transport_options = {
        "visibility_timeout": 3600,
        "socket_timeout": 30,
        "socket_connect_timeout": 30,
    }


@task_success.connect
def on_success(sender=None, result=None, **kwargs):
    logger.info(f"Task {sender.name} OK: {result}")


@task_failure.connect
def on_failure(sender=None, exception=None, **kwargs):
    logger.error(f"Task {sender.name} FAILED: {exception}")


@celery_app.task(bind=True)
def health_check_task(self):
    return {"status": "healthy", "worker": self.request.hostname}


@worker_ready.connect
def trigger_initial_ingestion(sender, **kwargs):
    """
    SRE Fix: Trigger ingestion immediately on startup to prevent 
    the 'Silent Empty UI' issue while waiting for the 60-min schedule.
    """
    logger.info("[SRE] Worker ready! Triggering initial geo-ingestion...")
    # نرسل المهمة إلى الطابور فوراً
    sender.app.send_task(
        "worker.tasks.ingest_recent_geo_task",
        queue="ingestion",
        kwargs={"lookback_hours": 2}
    )


if __name__ == "__main__":
    celery_app.start()