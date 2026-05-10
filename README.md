
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
[React/Vite Frontend] (Tailwind, Shadcn/UI, Leaflet Maps, Recharts)
```

---

## ✨ أحدث الميزات الهندسية (Recent Engineering Upgrades)
- **محرك متعدد المصادر (Multi-Source Engine):** دمج بيانات FR24 (أساسي)، AirLabs (للمسارات)، و OpenSky (مجاني/عالي التردد).
- **قاطع الدائرة الذكي (Smart Circuit Breaker):** حماية الـ Workers من الاستنزاف عند حظر الـ IP باستخدام آلة حالة (CLOSED, OPEN, HALF_OPEN) وتراجع أسي (Exponential Backoff).
- **لوحة العمليات (Operations Board):** محرك "ما قبل التنفيذ" (Preflight Engine) لحساب تكلفة الـ API (Credits) وتقسيم المهام التاريخية الكبيرة تلقائياً (Auto-chunking).
- **واجهة مستخدم عربية (Full RTL):** دعم كامل للغة العربية مع خط `Tajawal` لجميع المكونات والرسوم البيانية.

---

## 🚀 التشغيل المحلي للتطوير (Local Development - VS Code)

لتشغيل النظام محلياً بدون Docker (مفيد جداً لتصحيح الأخطاء Debugging):

### 1. المتطلبات الأساسية (Prerequisites)
- Python 3.11+
- Node.js 20+
- PostgreSQL (يعمل على البورت 5432، مع قاعدة بيانات فارغة باسم `flight_intelligence`)
- Redis (يعمل على البورت 6379)

### 2. إعداد الباك إند (Backend)
افتح نافذة Terminal (Terminal 1):
```bash
cd backend
python -m venv venv
source venv/bin/activate  # في الويندوز: venv\Scripts\activate
pip install -r requirements.txt

# إنشاء ملف .env
echo "DATABASE_URL=postgresql://postgres:postgres@localhost:5432/flight_intelligence" > .env
echo "REDIS_URL=redis://localhost:6379/0" >> .env
echo "FR24_API_KEY=your_fr24_key_here" >> .env
echo "AIRLABS_API_KEY=your_airlabs_key_here" >> .env

# بناء قاعدة البيانات
alembic upgrade head

# تغذية البيانات الثابتة (المطارات والشركات)
python ../seed_static_data.py

# تشغيل الخادم
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### 3. إعداد عمال الخلفية (Celery Workers)
افتح نافذة Terminal جديدة (Terminal 2) وقم بتفعيل الـ `venv`:
```bash
cd worker
# لمستخدمي Mac/Linux:
celery -A worker.celery_app:celery_app worker --queues=ingestion,maintenance --loglevel=info --concurrency=2
# لمستخدمي Windows (إلزامي):
celery -A worker.celery_app:celery_app worker --queues=ingestion,maintenance --loglevel=info --pool=solo
```

افتح نافذة Terminal جديدة (Terminal 3) وقم بتفعيل الـ `venv`:
```bash
cd worker
celery -A worker.celery_app:celery_app beat --loglevel=info
```

### 4. إعداد الواجهة الأمامية (Frontend)
افتح نافذة Terminal جديدة (Terminal 4):
```bash
cd frontend
npm install
echo "VITE_API_URL=http://127.0.0.1:8000" > .env
npm run dev
```
✅ **الواجهة تعمل الآن على:** `http://localhost:5173`
✅ **توثيق الـ API يعمل على:** `http://127.0.0.1:8000/docs`

---

## 🐳 التشغيل عبر دوكر (Production / Docker Compose)

للتشغيل السريع على الخوادم باستخدام حاويات دوكر:

```bash
# 1. انسخ ملف البيئة وضع مفاتيح الـ API الخاصة بك
cp .env.example .env

# 2. شغل النظام بالكامل في الخلفية
docker compose up -d

# 3. راقب سجلات الباك إند أو الـ Worker
docker compose logs -f backend
docker compose logs -f worker
```
الواجهة: `http://localhost` | الـ API: `http://localhost:8000`

---

## ⚙️ المتغيرات البيئية (Environment Variables)

| المتغير | إلزامي؟ | الوصف |
|---|---|---|
| `DATABASE_URL` | نعم | رابط الاتصال بـ PostgreSQL |
| `REDIS_URL` | نعم | رابط الاتصال بـ Redis |
| `FR24_API_KEY` | نعم | مفتاح FlightRadar24 (المصدر الأساسي) |
| `AIRLABS_API_KEY` | لا | مفتاح AirLabs (لجلب مسارات الرحلات الدقيقة) |
| `OPENSKY_USERNAME` | لا | حساب OpenSky (لزيادة حد الطلبات المجانية) |
| `DATA_RETENTION_DAYS` | لا | عدد أيام الاحتفاظ بالبيانات (الافتراضي: 30) |
| `ACTIVE_REGIONS` | لا | المناطق المفعلة (مثال: `middle_east,north_africa`) |

---

## 🛡️ إدارة النظام (System Management)

**تصدير البيانات (Exporting Data):**
يدعم النظام تصدير البيانات بصيغة CSV من جميع الواجهات (البحث، التاريخية، التحليلات، والعمليات). يتم حل مشكلة (N+1 Queries) برمجياً لضمان تصدير ملايين السجلات دون انهيار الذاكرة.

**تنظيف البيانات (Data Pruning):**
تعمل مهمة `cleanup_old_data_task` يومياً لحذف السجلات الأقدم من `DATA_RETENTION_DAYS` للحفاظ على أداء قاعدة البيانات.

</div>
```

---

