"""
Celery Tasks — Flight Intelligence Worker (v4.3 — Telegram Restore Engine Added)
All task definitions match beat_schedule entries exactly.

UPGRADES FROM v4.2:
  [NEW] Added `restore_database_task` to download a backup file from Telegram,
        terminate active DB connections, and restore the database using psql.
"""
from . import operations_task
from celery import shared_task
from celery.exceptions import MaxRetriesExceededError, SoftTimeLimitExceeded
import logging
import sys
import os
import time
import subprocess
import tempfile
import requests
from datetime import datetime, timezone
from typing import List, Optional
from contextlib import contextmanager

import redis
from sqlalchemy import create_engine, inspect, text

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from worker.ingestion_service import FlightIngestionService
from app.config import settings
from app.database import SessionLocal
from app.crud import EnterpriseDataRouter

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# INTERNAL: Redis Distributed Lock Manager
# ─────────────────────────────────────────────────────────────────────────────

redis_client = redis.from_url(settings.REDIS_URL)

@contextmanager
def acquire_lock(lock_name: str, timeout: int = 600):
    lock = redis_client.lock(lock_name, timeout=timeout)
    acquired = lock.acquire(blocking=False)
    try:
        yield acquired
    finally:
        if acquired:
            try:
                lock.release()
            except redis.exceptions.LockError:
                pass

# ─────────────────────────────────────────────────────────────────────────────
# INTERNAL: DB readiness guard
# ─────────────────────────────────────────────────────────────────────────────

def _wait_for_db(max_attempts: int = 30, sleep_s: float = 2.0) -> bool:
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
# INTERNAL: Telegram Helper
# ─────────────────────────────────────────────────────────────────────────────

def _send_tg_msg(text: str):
    """Helper to send status updates to the admin chat."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=5)
    except Exception as e:
        logger.error(f"[Telegram] Failed to send message: {e}")


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
# TASK 7: Orphaned Session Sweeper
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(
    bind=True, max_retries=2, default_retry_delay=60,
    name="worker.tasks.close_orphaned_sessions_task",
    queue="maintenance",
)
def close_orphaned_sessions_task(self, timeout_minutes: int = 45):
    if not _wait_for_db():
        return {"status": "error", "message": "DB tables not ready"}

    db = SessionLocal()
    try:
        logger.info(f"[Sweeper Task] Sweeping for sessions inactive for >{timeout_minutes} mins...")
        closed_count = EnterpriseDataRouter.close_orphaned_sessions(db, timeout_minutes)
        return {"status": "success", "closed_sessions": closed_count}
    except Exception as exc:
        logger.error(f"[Sweeper Task] Failed: {exc}", exc_info=True)
        try:
            self.retry(exc=exc)
        except MaxRetriesExceededError:
            return {"status": "failed", "error": str(exc)}
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# TASK 8: Telegram Backup Engine (FIXED)
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(
    bind=True, max_retries=2, default_retry_delay=300,
    soft_time_limit=1200, time_limit=1800,
    name="worker.tasks.backup_database_task",
    queue="maintenance",
)
def backup_database_task(self):
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        return {"status": "skipped", "reason": "credentials_missing"}

    db_url = settings.DATABASE_URL
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"flight_db_backup_{timestamp}.sql.gz"
    filepath = os.path.join(tempfile.gettempdir(), filename)

    try:
        # Parse database URL securely (same approach as restore task)
        engine = create_engine(db_url)
        url_obj = engine.url
        host = url_obj.host
        port = str(url_obj.port) if url_obj.port else "5432"
        dbname = url_obj.database
        user = url_obj.username
        password = url_obj.password

        env = os.environ.copy()
        if password:
            env["PGPASSWORD"] = password

        # Build pg_dump command without password in URL to avoid special-char issues
        cmd_full = [
            "pg_dump",
            "-h", host,
            "-p", port,
            "-U", user,
            "-d", dbname,
            "-Z", "9",
            "-f", filepath
        ]

        logger.info(f"[Backup] Starting database dump to {filepath}...")
        result = subprocess.run(cmd_full, capture_output=True, text=True, env=env)

        if result.returncode != 0:
            logger.error(f"[Backup] pg_dump failed: {result.stderr}")
            return {"status": "failed", "error": "pg_dump execution failed"}

        file_size_mb = os.path.getsize(filepath) / (1024 * 1024)
        is_partial = False

        if file_size_mb > 49.0:
            os.remove(filepath)
            filename = f"flight_db_backup_partial_{timestamp}.sql.gz"
            filepath = os.path.join(tempfile.gettempdir(), filename)
            cmd_partial = [
                "pg_dump",
                "-h", host,
                "-p", port,
                "-U", user,
                "-d", dbname,
                "-Z", "9",
                "-T", "track_telemetry",
                "-f", filepath
            ]

            result_partial = subprocess.run(cmd_partial, capture_output=True, text=True, env=env)
            if result_partial.returncode != 0:
                logger.error(f"[Backup] Partial pg_dump failed: {result_partial.stderr}")
                return {"status": "failed", "error": "partial pg_dump failed"}

            file_size_mb = os.path.getsize(filepath) / (1024 * 1024)
            is_partial = True

            if file_size_mb > 49.0:
                return {"status": "failed", "error": "file_exceeds_telegram_limit"}

        url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
        caption = (
            f"📦 <b>Flight Intelligence Backup</b>\n"
            f"📅 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
            f"📊 Size: {file_size_mb:.2f} MB\n"
            f"⚠️ <i>Partial Backup (Telemetry excluded)</i>" if is_partial else "✅ <i>Full Backup</i>"
        )

        with open(filepath, "rb") as f:
            resp = requests.post(
                url,
                data={"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"},
                files={"document": f},
                timeout=300
            )

        if resp.status_code != 200:
            return {"status": "failed", "error": "Telegram upload failed"}

        return {"status": "success", "file": filename, "size_mb": round(file_size_mb, 2), "is_partial": is_partial}

    except Exception as exc:
        try:
            self.retry(exc=exc)
        except MaxRetriesExceededError:
            return {"status": "failed", "error": str(exc)}
    finally:
        if os.path.exists(filepath):
            os.remove(filepath)


# ─────────────────────────────────────────────────────────────────────────────
# TASK 9: Telegram Restore Engine (NEW)
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(
    bind=True, max_retries=0, 
    soft_time_limit=1800, time_limit=2000,
    name="worker.tasks.restore_database_task",
    queue="maintenance",
)
def restore_database_task(self, file_id: str, file_name: str):
    """
    Downloads a backup file from Telegram, drops all connections to the DB,
    and restores the database using psql.
    """
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        return {"status": "failed", "reason": "credentials_missing"}

    db_url = settings.DATABASE_URL
    filepath = os.path.join(tempfile.gettempdir(), file_name)

    try:
        # 1. Get file path from Telegram
        logger.info(f"[Restore] Fetching file path for {file_id}...")
        file_info_url = f"https://api.telegram.org/bot{bot_token}/getFile?file_id={file_id}"
        file_info_resp = requests.get(file_info_url, timeout=15).json()

        if not file_info_resp.get("ok"):
            _send_tg_msg("❌ <b>فشل الاستعادة:</b> لم أتمكن من العثور على الملف في خوادم تليجرام.")
            return {"status": "failed", "error": "file_not_found_on_telegram"}

        tg_file_path = file_info_resp["result"]["file_path"]
        download_url = f"https://api.telegram.org/file/bot{bot_token}/{tg_file_path}"

        # 2. Download the file
        logger.info(f"[Restore] Downloading {file_name}...")
        with requests.get(download_url, stream=True, timeout=300) as r:
            r.raise_for_status()
            with open(filepath, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192): 
                    f.write(chunk)

        file_size_mb = os.path.getsize(filepath) / (1024 * 1024)
        logger.info(f"[Restore] Download complete. Size: {file_size_mb:.2f} MB")
        _send_tg_msg(f"🔄 <b>جاري الاستعادة:</b> تم تحميل الملف ({file_size_mb:.1f} MB).\nجاري إيقاف الاتصالات بقاعدة البيانات...")

        # 3. Isolate the database (Terminate other connections)
        engine = create_engine(db_url)
        db_name = engine.url.database
        terminate_sql = text(f"""
            SELECT pg_terminate_backend(pg_stat_activity.pid)
            FROM pg_stat_activity
            WHERE pg_stat_activity.datname = '{db_name}'
              AND pid <> pg_backend_pid();
        """)
        with engine.connect() as conn:
            conn.execute(terminate_sql)
            conn.commit()
        engine.dispose()

        logger.info("[Restore] Terminated other DB connections.")

        # 4. Execute the restore (zcat | psql)
        # Using zcat to decompress on the fly and pipe directly to psql
        logger.info("[Restore] Executing psql restore...")

        # Note: psql requires PGPASSWORD environment variable if password is used
        env = os.environ.copy()
        if engine.url.password:
            env["PGPASSWORD"] = engine.url.password

        # Build psql command (without password in URL for security)
        psql_url = f"postgresql://{engine.url.username}@{engine.url.host}:{engine.url.port}/{db_name}"

        # The command: zcat file.sql.gz | psql -d url
        cmd = f"zcat {filepath} | psql -d {psql_url}"

        result = subprocess.run(cmd, shell=True, env=env, capture_output=True, text=True)

        if result.returncode != 0:
            logger.error(f"[Restore] psql failed: {result.stderr}")
            _send_tg_msg(f"❌ <b>فشل الاستعادة:</b> حدث خطأ أثناء تنفيذ السكربت.\n<pre>{result.stderr[:500]}</pre>")
            return {"status": "failed", "error": "psql_execution_failed"}

        # 5. Success!
        logger.info("[Restore] Database restored successfully.")
        _send_tg_msg(f"✅ <b>تمت الاستعادة بنجاح!</b>\nقاعدة البيانات الآن مطابقة لملف <code>{file_name}</code>.")
        return {"status": "success"}

    except Exception as exc:
        logger.error(f"[Restore] Exception during restore: {exc}", exc_info=True)
        _send_tg_msg(f"❌ <b>انهيار أثناء الاستعادة:</b>\n<pre>{str(exc)}</pre>")
        return {"status": "failed", "error": str(exc)}
    finally:
        # 6. Clean up
        if os.path.exists(filepath):
            os.remove(filepath)


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