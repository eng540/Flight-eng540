# ✈️ منصة استخبارات الطيران | Flight Intelligence Platform

<div dir="rtl">

## 🌟 نظرة عامة (Overview)
منصة إنتاجية متقدمة (Production-Grade) لتتبع وتحليل بيانات الطيران الجوي في الوقت الفعلي والتاريخي. 
تعتمد المنصة على **محرك استيعاب هجين (Hybrid Ingestion Engine)** يسحب البيانات من مصادر متعددة (FlightRadar24, AirLabs, OpenSky) مع آليات حماية ذاتية (Self-Healing) وقواطع دوائر (Circuit Breakers) للتعامل مع حظر الشبكات. الواجهة الأمامية معربة بالكامل (RTL) وتقدم لوحات تحليلية، ومحرك بحث تاريخي، ولوحة تحكم بالعمليات.

---

## 🏗️ البنية المعمارية (Architecture)

```text
[External APIs] (FR24, AirLabs, OpenSky)
       │
       ▼
[Celery Workers] ──(Circuit Breakers & Fast-Fail)──> [Redis] (Message Broker)
       │
       ▼
[Data Router] ──(Physics Validation & Deduplication)
       │
       ▼
[PostgreSQL] (Snowflake Schema: Facts, Dimensions, Time-Series, Fast-Cache)
       │
       ▼
[FastAPI Backend] ──(Pydantic Validation & REST Endpoints)
       │
       ▼
[React/Vite Frontend] (Tailwind, Shadcn/UI, Leaflet Maps, Recharts)| N+1 in get_top_routes | aliased dual-join — 1 query |
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
