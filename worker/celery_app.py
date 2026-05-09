"""
Celery application – supports redis:// and rediss:// (Upstash/TLS).
v3.2 — Multi-Source Hybrid Engine Configuration (with Startup Jitter)
"""
import os
import ssl
import logging
import random

from celery import Celery
from celery.signals import task_failure, task_success, worker_ready

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


def _ssl_options() -> dict:
    return {"ssl_cert_reqs": ssl.CERT_NONE,
            "ssl_ca_certs": None, "ssl_certfile": None, "ssl_keyfile": None}


celery_app = Celery(
    "flight_intelligence",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["worker.tasks"],
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
        # ── 1. OpenSky: Primary Free Source (Every 1 Minute) ──
        "ingest-live-opensky": {
            "task": "worker.tasks.ingest_live_opensky_task",
            "schedule": 60.0,
        },
        # ── 2. AirLabs: Secondary Free Source (Every 1 Hour) ──
        "ingest-live-airlabs": {
            "task": "worker.tasks.ingest_live_airlabs_task",
            "schedule": 3600.0,
        },
        # ── 3. FR24: Fallback/Premium Source (Every 1 Hour) ──
        "ingest-live-fr24": {
            "task": "worker.tasks.ingest_live_fr24_task",
            "schedule": 3600.0,
        },
        
        # ── System Maintenance ──
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
    },

    task_routes={
        "worker.tasks.ingest_live_opensky_task":  {"queue": "ingestion"},
        "worker.tasks.ingest_live_airlabs_task":  {"queue": "ingestion"},
        "worker.tasks.ingest_live_fr24_task":     {"queue": "ingestion"},
        "worker.tasks.ingest_historical_flights": {"queue": "ingestion"},
        "worker.tasks.cleanup_old_data_task":     {"queue": "maintenance"},
        "worker.tasks.operations_task.execute_operation_task": {"queue": "ingestion"},
        "worker.tasks.operations_task.retry_chunks_task":      {"queue": "maintenance"},
        
        # Legacy routes (kept to prevent unregistered task warnings)
        "worker.tasks.ingest_recent_geo_task":    {"queue": "ingestion"},
        "worker.tasks.ingest_flights_task":       {"queue": "ingestion"},
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
    SRE Fix: Trigger all live ingestion tasks on startup with Jitter.
    This prevents the 'Silent Empty UI' issue while avoiding a 'Trigger Storm'
    that causes DB Deadlocks and Connection Pool Exhaustion.
    """
    logger.info("[SRE] Worker ready! Triggering initial multi-source ingestion with Jitter...")
    
    # 1. OpenSky starts immediately (Fastest, most likely to be blocked)
    sender.app.send_task(
        "worker.tasks.ingest_live_opensky_task",
        queue="ingestion"
    )
    
    # 2. AirLabs starts after a random delay of 5 to 15 seconds
    airlabs_delay = random.uniform(5.0, 15.0)
    sender.app.send_task(
        "worker.tasks.ingest_live_airlabs_task",
        queue="ingestion",
        countdown=airlabs_delay
    )
    logger.info(f"[SRE] Scheduled AirLabs initial ingestion in {airlabs_delay:.1f}s")
    
    # 3. FR24 starts after a random delay of 15 to 30 seconds
    fr24_delay = random.uniform(15.0, 30.0)
    sender.app.send_task(
        "worker.tasks.ingest_live_fr24_task",
        queue="ingestion",
        countdown=fr24_delay
    )
    logger.info(f"[SRE] Scheduled FR24 initial ingestion in {fr24_delay:.1f}s")


if __name__ == "__main__":
    celery_app.start()