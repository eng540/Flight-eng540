"""
System API Endpoints — v1.1 (Telegram Webhook Added)
Prefix: /api/v1/system

ENDPOINTS:
  GET  /api/v1/system/credits-usage   ← FR24 API budget tracker
  GET  /api/v1/system/status          ← System health status
  GET  /api/v1/system/seed-static-data← Seed airports/airlines
  POST /api/v1/system/webhook/telegram/{token} ← Receive DB backups
"""
import os
import requests
from fastapi import APIRouter, Depends, Request, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.crud import AnalyticsCRUD
from app.schemas import CreditsUsageResponse, CreditsUsageItem
from app.config import settings

router = APIRouter(prefix="/api/v1/system", tags=["system-v1"])


@router.get("/credits-usage", response_model=CreditsUsageResponse,
            summary="استهلاك نقاط FR24 API")
def get_credits_usage(db: Session = Depends(get_db)):
    """
    Aggregate FR24 API credit consumption per endpoint type.
    Data sourced from IngestionJob.credits_used column.
    """
    rows = AnalyticsCRUD.get_credits_summary(db)
    total_credits = sum(r["credits"] for r in rows)

    return CreditsUsageResponse(
        data=[CreditsUsageItem(**r) for r in rows],
        total_credits=total_credits,
    )


@router.get("/status", summary="حالة النظام")
def get_system_status(db: Session = Depends(get_db)):
    """System health + FR24 configuration status."""
    from sqlalchemy import text
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    return {
        "database":        "connected"    if db_ok else "disconnected",
        "fr24_configured": settings.is_fr24_configured(),
        "fr24_base_url":   settings.FR24_BASE_URL,
        "active_regions":  settings.get_active_region_keys(),
        "retention_days":  settings.DATA_RETENTION_DAYS,
    }


@router.get("/seed-static-data", summary="تغذية قاعدة البيانات بالمطارات والشركات")
def seed_data_endpoint(db: Session = Depends(get_db)):
    """
    رابط خفي لتشغيل سكربت التغذية. يفتح من المتصفح مباشرة.
    """
    from app.services.static_seeder import seed_all_static_data
    return seed_all_static_data(db)


# ── Telegram Webhook Helper ──────────────────────────────────────────────────

def _send_telegram_message(token: str, chat_id: str, text: str):
    """Helper to send a quick reply back to Telegram."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=5)
    except Exception:
        pass


@router.post("/webhook/telegram/{token}", summary="استقبال نسخة احتياطية من تليجرام")
async def telegram_webhook(token: str, request: Request):
    """
    Webhook لاستقبال ملفات النسخ الاحتياطي من تليجرام.
    يجب إعداد الـ Webhook في تليجرام ليوجه إلى هذا المسار.
    """
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    allowed_chat_id = os.getenv("TELEGRAM_CHAT_ID")

    # 1. Security: Verify the token in the URL matches our Bot Token
    if not bot_token or token != bot_token:
        raise HTTPException(status_code=403, detail="Unauthorized")

    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    message = data.get("message", {})
    chat_id = str(message.get("chat", {}).get("id", ""))

    # 2. Security: Only accept messages from the authorized admin chat
    if chat_id != allowed_chat_id:
        return {"status": "ignored", "reason": "unauthorized_chat"}

    document = message.get("document")
    if not document:
        return {"status": "ignored", "reason": "no_document"}

    file_name = document.get("file_name", "")
    
    # 3. Validation: Ensure it's a database backup file
    if not file_name.endswith(".sql.gz"):
        _send_telegram_message(bot_token, chat_id, "❌ <b>خطأ:</b> صيغة الملف غير مدعومة. يجب إرسال ملف <code>.sql.gz</code>")
        return {"status": "ignored", "reason": "invalid_format"}

    file_id = document.get("file_id")
    
    # 4. Handoff: Dispatch to Celery worker to handle download and restore
    try:
        from worker.celery_app import celery_app
        celery_app.send_task(
            "worker.tasks.restore_database_task",
            args=[file_id, file_name],
            queue="maintenance"
        )
        _send_telegram_message(
            bot_token, 
            chat_id, 
            f"📥 <b>تم استلام الملف:</b> <code>{file_name}</code>\n"
            f"⏳ جاري التحميل والاستعادة في الخلفية. سيتم إشعارك عند الانتهاء."
        )
    except Exception as e:
        _send_telegram_message(bot_token, chat_id, f"❌ <b>خطأ في النظام:</b> فشل إرسال المهمة لمعالج البيانات.\n<code>{str(e)}</code>")
        return {"status": "error", "reason": "celery_dispatch_failed"}

    return {"status": "success", "message": "restore_queued"}