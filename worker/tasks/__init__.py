"""
Celery Tasks — Flight Intelligence Worker (v4.0 — Distributed Locking)
All task definitions match beat_schedule entries exactly.

UPGRADES FROM v3.1:
  [FIX] Introduced Redis Distributed Locks (`acquire_lock`) to prevent Task Pile-up.
        If a task (e.g., OpenSky) is already running and takes longer than its schedule,
        the next triggered instance will instantly skip execution, preventing DB Deadlocks.
"""
from . import operations_task
from celery import shared_task
from celery.exceptions import MaxRetriesExceededError, SoftTimeLimitExceeded
import logging
import sys
import os
import time
from typing import List, Optional
from contextlib import contextmanager

import redis
from sqlalchemy import create_engine, inspect

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from worker.ingestion_service import FlightIngestionService
from app.config import settings

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# INTERNAL: Redis Distributed Lock Manager
# ─────────────────────────────────────────────────────────────────────────────

# Initialize a single Redis client for the worker process
redis_client = redis.from_url(settings.REDIS_URL)

@contextmanager
def acquire_lock(lock_name: str, timeout: int = 600):
    """
    Context manager for acquiring a non-blocking Redis lock.
    Timeout ensures the lock is released eventually if the worker crashes.
    """
    lock = redis_client.lock(lock_name, timeout=timeout)
    acquired = lock.acquire(blocking=False)
    try:
        yield acquired
    finally:
        if acquired:
            try:
                lock.release()
            except redis.exceptions.LockError:
                # Lock might have expired naturally due to timeout, safe to ignore
                pass

# ─────────────────────────────────────────────────────────────────────────────
# INTERNAL: DB readiness guard
# ─────────────────────────────────────────────────────────────────────────────

def _wait_for_db(max_attempts: int = 30, sleep_s: float = 2.0) -> bool:
    """Returns True when 'dim_geography' table is present, False on timeout."""
    engine = create_engine(settings.DATABASE_URL)
    inspector = inspect(engine)
    for attempt in range(max_attempts):
        try:
            if "dim_geography" in inspector.get_table_names():
                return True
        except Exception:
            pass
        logger.warning(f"[DB Guard] Waiting for tables... {attempt+1}/{max_attempts}")
        time.sleep(sleep_s)
    logger.error("[DB Guard] Tables not ready after timeout. Aborting.")
    return False


# ─────────────────────────────────────────────────────────────────────────────
# TASK 1: OPENSKY LIVE INGESTION
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(
    bind=True, max_retries=1, default_retry_delay=30,
    soft_time_limit=600, time_limit=700,
    name="worker.tasks.ingest_live_opensky_task",
    queue="ingestion",
)
def ingest_live_opensky_task(self, region_keys: Optional[List[str]] = None):
    # 🚨 DISTRIBUTED LOCK: Prevent overlapping executions
    with acquire_lock("lock:ingestion:opensky", timeout=600) as acquired:
        if not acquired:
            logger.info("[OpenSky Task] Already running. Skipping to prevent overlap.")
            return {"status": "skipped", "reason": "already_running"}

        if not _wait_for_db():
            return {"status": "error", "message": "DB tables not ready"}

        try:
            active_keys = region_keys or settings.get_active_region_keys()
            regions = [r for r in (settings.get_region(k) for k in active_keys) if r]

            if not regions:
                return {"status": "skipped", "reason": "no regions"}

            svc = FlightIngestionService()
            logger.info(f"[OpenSky Task] Starting live sweep: {[r.key for r in regions]}")
            result = svc.ingest_live_radar_from_opensky(regions)
            return {"status": "success", "result": result}

        except SoftTimeLimitExceeded:
            logger.warning("[OpenSky Task] Soft time limit exceeded.")
            return {"status": "timeout"}
        except Exception as exc:
            logger.error(f"[OpenSky Task] Failed: {exc}", exc_info=True)
            try:
                self.retry(exc=exc)
            except MaxRetriesExceededError:
                return {"status": "failed", "error": str(exc)}


# ─────────────────────────────────────────────────────────────────────────────
# TASK 2: AIRLABS LIVE INGESTION
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(
    bind=True, max_retries=1, default_retry_delay=60,
    soft_time_limit=600, time_limit=700,
    name="worker.tasks.ingest_live_airlabs_task",
    queue="ingestion",
)
def ingest_live_airlabs_task(self, region_keys: Optional[List[str]] = None):
    # 🚨 DISTRIBUTED LOCK: Prevent overlapping executions
    with acquire_lock("lock:ingestion:airlabs", timeout=600) as acquired:
        if not acquired:
            logger.info("[AirLabs Task] Already running. Skipping to prevent overlap.")
            return {"status": "skipped", "reason": "already_running"}

        if not _wait_for_db():
            return {"status": "error", "message": "DB tables not ready"}

        try:
            active_keys = region_keys or settings.get_active_region_keys()
            regions = [r for r in (settings.get_region(k) for k in active_keys) if r]

            if not regions:
                return {"status": "skipped", "reason": "no regions"}

            svc = FlightIngestionService()
            logger.info(f"[AirLabs Task] Starting live sweep: {[r.key for r in regions]}")
            result = svc.ingest_live_radar_from_airlabs(regions)
            return {"status": "success", "result": result}

        except SoftTimeLimitExceeded:
            logger.warning("[AirLabs Task] Soft time limit exceeded.")
            return {"status": "timeout"}
        except Exception as exc:
            logger.error(f"[AirLabs Task] Failed: {exc}", exc_info=True)
            try:
                self.retry(exc=exc)
            except MaxRetriesExceededError:
                return {"status": "failed", "error": str(exc)}


# ─────────────────────────────────────────────────────────────────────────────
# TASK 3: FR24 LIVE INGESTION
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(
    bind=True, max_retries=1, default_retry_delay=60,
    soft_time_limit=600, time_limit=700,
    name="worker.tasks.ingest_live_fr24_task",
    queue="ingestion",
)
def ingest_live_fr24_task(self, region_keys: Optional[List[str]] = None):
    # 🚨 DISTRIBUTED LOCK: Prevent overlapping executions
    with acquire_lock("lock:ingestion:fr24", timeout=600) as acquired:
        if not acquired:
            logger.info("[FR24 Task] Already running. Skipping to prevent overlap.")
            return {"status": "skipped", "reason": "already_running"}

        if not _wait_for_db():
            return {"status": "error", "message": "DB tables not ready"}

        try:
            active_keys = region_keys or settings.get_active_region_keys()
            regions = [r for r in (settings.get_region(k) for k in active_keys) if r]

            if not regions:
                return {"status": "skipped", "reason": "no regions"}

            svc = FlightIngestionService()
            logger.info(f"[FR24 Task] Starting live sweep: {[r.key for r in regions]}")
            result = svc.ingest_live_radar_from_fr24(regions)
            return {"status": "success", "result": result}

        except SoftTimeLimitExceeded:
            logger.warning("[FR24 Task] Soft time limit exceeded.")
            return {"status": "timeout"}
        except Exception as exc:
            logger.error(f"[FR24 Task] Failed: {exc}", exc_info=True)
            try:
                self.retry(exc=exc)
            except MaxRetriesExceededError:
                return {"status": "failed", "error": str(exc)}


# ─────────────────────────────────────────────────────────────────────────────
# TASK 4: Historical ingestion
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(
    bind=True, max_retries=2, default_retry_delay=120,
    soft_time_limit=3600, time_limit=7200,
    name="worker.tasks.ingest_historical_flights",
    queue="ingestion",
)
def ingest_historical_flights(
    self,
    begin_date: str,
    end_date: str,
    region_keys: List[str],
    force_reingest: bool = False,
):
    from datetime import datetime, timedelta

    logger.info(
        f"[Historical] {begin_date}→{end_date} regions={region_keys} force={force_reingest}"
    )

    try:
        begin_ts = int(datetime.strptime(begin_date, "%Y-%m-%d").timestamp())
        end_ts   = int(
            (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)).timestamp()
        ) - 1
    except ValueError as exc:
        return {"status": "failed", "error": f"Invalid date format: {exc}"}

    regions = [r for r in (settings.get_region(k) for k in region_keys) if r]
    if not regions:
        return {"status": "failed", "error": "No valid regions found for given keys"}

    totals = {
        "jobs_processed": 0,
        "jobs_skipped": 0,
        "flights_created": 0,
        "flights_updated": 0,
    }
    svc = FlightIngestionService()

    try:
        for region in regions:
            result = svc.ingest_date_range_for_region(
                begin_ts=begin_ts,
                end_ts=end_ts,
                region=region,
                force_reingest=force_reingest,
            )
            for k in totals:
                totals[k] += result.get(k, 0)

    except SoftTimeLimitExceeded:
        logger.warning("[Historical] Soft time limit exceeded mid-run.")
        return {"status": "partial", **totals}
    except Exception as exc:
        logger.error(f"[Historical] Failed: {exc}", exc_info=True)
        try:
            self.retry(exc=exc)
        except MaxRetriesExceededError:
            return {"status": "failed", "error": str(exc)}

    logger.info(f"[Historical] Completed: {totals}")
    return {"status": "success", **totals}


# ─────────────────────────────────────────────────────────────────────────────
# TASK 5: Cleanup (runs daily)
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(
    bind=True, max_retries=3, default_retry_delay=60,
    name="worker.tasks.cleanup_old_data_task",
    queue="maintenance",
)
def cleanup_old_data_task(self, days: int = 0):
    retention = settings.DATA_RETENTION_DAYS if days == 0 else days
    if not retention or retention <= 0:
        logger.info("[Cleanup] DATA_RETENTION_DAYS=0 — keeping all data.")
        return {"status": "skipped", "deleted": 0}

    try:
        with FlightIngestionService() as svc:
            deleted = svc.cleanup_old_data(retention)
        logger.info(f"[Cleanup] Deleted {deleted} records older than {retention} days.")
        return {"status": "success", "deleted": deleted}
    except Exception as exc:
        logger.error(f"[Cleanup] Failed: {exc}", exc_info=True)
        try:
            self.retry(exc=exc)
        except MaxRetriesExceededError:
            return {"status": "failed", "error": str(exc)}


# ─────────────────────────────────────────────────────────────────────────────
# TASK 6: Enrichment
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(
    bind=True, max_retries=2, default_retry_delay=30,
    soft_time_limit=1800, time_limit=3600,
    name="worker.tasks.enrich_flight_details_task",
    queue="ingestion",
)
def enrich_flight_details_task(self, fr24_ids: List[str]):
    if not fr24_ids:
        return {"status": "skipped", "reason": "no fr24_ids provided"}

    try:
        svc = FlightIngestionService()
        result = svc.enrich_flight_details(fr24_ids)
        return {"status": "success", **result}
    except Exception as exc:
        logger.error(f"[Enrich Task] Failed: {exc}", exc_info=True)
        try:
            self.retry(exc=exc)
        except MaxRetriesExceededError:
            return {"status": "failed", "error": str(exc)}


# ─────────────────────────────────────────────────────────────────────────────
# LEGACY STUBS
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(bind=True, name="worker.tasks.run_realtime_radar_task", queue="ingestion")
def run_realtime_radar_task(self):
    return {"status": "skipped", "reason": "legacy task"}

@shared_task(bind=True, name="worker.tasks.ingest_aviationstack_task", queue="ingestion")
def ingest_aviationstack_task(self):
    return {"status": "skipped", "reason": "deprecated — use FR24"}

@shared_task(bind=True, name="worker.tasks.ingest_recent_geo_task", queue="ingestion")
def ingest_recent_geo_task(self, *args, **kwargs):
    return {"status": "skipped", "reason": "deprecated"}

@shared_task(bind=True, name="worker.tasks.ingest_flights_task", queue="ingestion")
def ingest_flights_task(self, *args, **kwargs):
    return {"status": "skipped", "reason": "deprecated"}