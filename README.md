# ✈️ منصة استخبارات الطيران | Flight Intelligence Platform

<div dir="rtl">

## نظرة عامة

منصة تحليل بيانات الطيران الجوي في الوقت الفعلي، مبنية على Flightradar24 API.
تدعم التتبع اللحظي للطائرات، والاستعلام التاريخي متعدد الأبعاد، ولوحات تحليلية كاملة باللغة العربية.

## المتطلبات

| المتطلب | الإصدار |
|---|---|
| Docker | 24+ |
| Docker Compose | 2.20+ |
| مفتاح FR24 API | احصل عليه من fr24api.flightradar24.com |

## التشغيل السريع

```bash
cp .env.example .env
# عدّل FR24_API_KEY في ملف .env
docker compose up -d
docker compose logs -f backend
```

الواجهة: http://localhost | API Docs: http://localhost:8000/docs

## API Endpoints

| Endpoint | الوصف |
|---|---|
| `GET /api/v1/live/positions` | مواقع الطائرات اللحظية |
| `GET /api/v1/flights/search` | بحث متعدد الحقول |
| `GET /api/v1/flights/{id}` | تفاصيل رحلة |
| `GET /api/v1/flights/{id}/trajectory` | مسار الرحلة |
| `GET /api/v1/aircraft/{icao24}/history` | سجل طائرة |
| `POST /api/v1/history/query` | محرك البيانات التاريخية |
| `GET /api/v1/analytics/top-routes` | أكثر الطرق ازدحاماً |
| `GET /api/v1/analytics/busiest-airports` | أكثر المطارات حركةً |
| `GET /api/v1/analytics/daily-summary` | ملخص يومي |
| `GET /api/v1/analytics/airline-performance` | أداء الناقلين |
| `GET /api/v1/analytics/export-csv` | تصدير CSV |
| `GET /api/v1/history/export` | تصدير سجل تاريخي |
| `GET /api/v1/system/credits-usage` | استهلاك اعتمادات FR24 |

## إدارة الخدمات

```bash
docker compose down                           # إيقاف
docker compose down -v                        # إيقاف + حذف البيانات
docker compose exec backend alembic upgrade head   # تشغيل migrations
docker compose logs -f worker beat            # مراقبة المهام
```

</div>

---

# ✈️ Flight Intelligence Platform

## Overview

Real-time aviation intelligence platform built on Flightradar24 API.
Features live tracking, multi-dimensional historical queries, and full Arabic dashboards.

## Quick Start

```bash
cp .env.example .env      # edit FR24_API_KEY
docker compose up -d
```

UI: http://localhost | API: http://localhost:8000/docs

## Architecture

```
FR24 API → Celery Worker → PostgreSQL (Snowflake Schema)
                                  ↕
                     FastAPI backend (/api/v1/*)
                                  ↕
                  React frontend (Arabic RTL, Leaflet, Recharts)
```

## Key Fixes Applied

| Issue | Fix |
|---|---|
| fr24_id never stored | Extracted from FR24 FlightPositionsFull.fr24_id |
| on_ground = (alt==0) | Fixed to: alt < 100 AND gspeed < 30 |
| hashlib.md5 as dedup key | Removed — fr24_id is the stable key |
| painted_as fallback | Removed — operating_as only |
| cleanup_old_data() was no-op | Real 30-day retention deletion |
| ingest_date_range_for_region() missing | Implemented |
| NameError in tasks.py | except scr → except exc |
| IngestionJobResponse schema mismatch | 9 columns added to model |
| N+1 in get_top_routes | aliased dual-join — 1 query |
| N+1 in get_airline_performance | CASE WHEN aggregate — 1 query |
| Arabic UI missing | Full RTL + Tajawal font |
| 11 endpoints missing | All implemented |

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| FR24_API_KEY | YES | Flightradar24 Bearer token |
| DATABASE_URL | YES | PostgreSQL connection |
| REDIS_URL | YES | Redis connection |
| ACTIVE_REGIONS | No | Comma-separated region keys |
| DATA_RETENTION_DAYS | No | Days to keep data (0=forever) |

## Service Management

```bash
# Manual migration
docker compose exec backend alembic upgrade head

# Trigger historical ingestion
docker compose exec worker celery -A worker.celery_app:celery_app call \
  worker.tasks.ingest_historical_flights \
  --args='["2026-04-01","2026-04-07",["middle_east"]]'

# DB shell
docker compose exec postgres psql -U flightuser -d flightdb
```
