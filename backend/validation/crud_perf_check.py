"""
TIER 2 — Runtime Validation Plan
تُشغَّل هذه الاختبارات بعد تشغيل الـ migrations لتأكيد غياب N+1 في production.

يوفر هذا الملف:
1. SQLAlchemy query counter لقياس عدد الـ queries الفعلي
2. تأكيد أن كل دالة لا تتجاوز الحد الأقصى المتوقع

الاستخدام:
  cd backend
  python validation/crud_perf_check.py
"""
import logging
import sys
import os
from contextlib import contextmanager
from typing import List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from app.config import settings


# ─────────────────────────────────────────────────────────────────────────────
# 1. SQLAlchemy Query Counter — captures every emitted SQL statement
# ─────────────────────────────────────────────────────────────────────────────

class QueryCounter:
    """
    Attaches to a SQLAlchemy engine via event listener.
    Counts every SQL statement actually sent to the DB.
    Usage:
        with QueryCounter(engine) as counter:
            result = my_crud_function(db)
        print(f"Queries executed: {counter.count}")
    """
    def __init__(self, engine):
        self.engine  = engine
        self.count   = 0
        self.queries: List[str] = []

    def _before_cursor_execute(self, conn, cursor, statement, params,
                               context, executemany):
        self.count += 1
        # Store first 120 chars for inspection
        self.queries.append(statement[:120].replace("\n", " ").strip())

    def __enter__(self):
        event.listen(self.engine, "before_cursor_execute",
                     self._before_cursor_execute)
        return self

    def __exit__(self, *args):
        event.remove(self.engine, "before_cursor_execute",
                     self._before_cursor_execute)

    def report(self, label: str, max_allowed: int):
        status = "✅ PASS" if self.count <= max_allowed else "❌ FAIL"
        print(f"{status}  {label}: {self.count} queries (max allowed: {max_allowed})")
        if self.count > max_allowed:
            print("   Queries emitted:")
            for i, q in enumerate(self.queries, 1):
                print(f"   [{i}] {q}")
        self.count   = 0
        self.queries = []


# ─────────────────────────────────────────────────────────────────────────────
# 2. Engine with echo=True for full SQL visibility
# ─────────────────────────────────────────────────────────────────────────────

def make_engine(echo: bool = False):
    """
    echo=True: logs every SQL to stdout — use for debugging.
    echo=False: silent — use for counter-only validation.

    Per STAGE 2 requirement:
        engine = create_engine(DB_URL, echo=True)
    """
    return create_engine(settings.DATABASE_URL, echo=echo)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Validation Scenarios
# ─────────────────────────────────────────────────────────────────────────────

def run_validation():
    engine     = make_engine(echo=False)   # set True for full SQL log
    SessionLocal = sessionmaker(bind=engine)
    db         = SessionLocal()
    counter    = QueryCounter(engine)

    from app.crud import AnalyticsCRUD, FlightQueryCRUD
    from app.schemas import HistoryQueryRequest

    print("\n" + "═" * 60)
    print("TIER 2 — CRUD N+1 Runtime Validation")
    print("═" * 60)

    # ── Test 1: get_top_routes ──────────────────────────────────────────────
    # Expected: exactly 1 query (dual-aliased JOIN + GROUP BY)
    with counter:
        _ = AnalyticsCRUD.get_top_routes(db, limit=10)
    counter.report("get_top_routes(limit=10)", max_allowed=1)

    # ── Test 2: get_busiest_airports ────────────────────────────────────────
    # Expected: exactly 1 query (two subqueries + outer join)
    with counter:
        _ = AnalyticsCRUD.get_busiest_airports(db, limit=10)
    counter.report("get_busiest_airports(limit=10)", max_allowed=1)

    # ── Test 3: get_daily_summary ───────────────────────────────────────────
    # Expected: 3 queries (aggregated + events + top_routes)
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with counter:
        _ = AnalyticsCRUD.get_daily_summary(db, today)
    counter.report("get_daily_summary(today)", max_allowed=3)

    # ── Test 4: get_airline_performance ────────────────────────────────────
    # Expected: 2 queries (count() subquery + GROUP BY result)
    # Regardless of page_size — no per-airline loop
    with counter:
        _ = AnalyticsCRUD.get_airline_performance(db, page=1, page_size=50)
    counter.report("get_airline_performance(page_size=50)", max_allowed=2)

    # ── Test 5: get_live_positions ──────────────────────────────────────────
    # Expected: 2 queries (count + .all())
    with counter:
        _ = FlightQueryCRUD.get_live_positions(db, limit=1000)
    counter.report("get_live_positions(limit=1000)", max_allowed=2)

    # ── Test 6: search_flights (no filters) ────────────────────────────────
    # Expected: 2 queries (count + .all() with joinedload)
    # Note: joinedload may produce 1 additional JOIN per relationship
    # in some SQLAlchemy versions → max_allowed=6 (2 base + 4 relationships)
    with counter:
        _ = FlightQueryCRUD.search_flights(db, page=1, page_size=50)
    counter.report("search_flights(no filters)", max_allowed=6)

    # ── Test 7: query_history (entity_type=airline) ─────────────────────────
    # Expected: 3 queries (operator lookup + count + .all() with joinedload)
    with counter:
        req = HistoryQueryRequest(
            entity_type="airline", entity_id="SVA", page=1, page_size=20
        )
        _ = FlightQueryCRUD.query_history(db, req)
    counter.report("query_history(airline=SVA)", max_allowed=7)

    # ── Test 8: get_credits_summary ─────────────────────────────────────────
    # Expected: 1 query
    with counter:
        _ = AnalyticsCRUD.get_credits_summary(db)
    counter.report("get_credits_summary()", max_allowed=1)

    print("═" * 60)
    print("Validation complete.")
    db.close()


# ─────────────────────────────────────────────────────────────────────────────
# 4. How to enable full SQL logging per STAGE 2 requirement
# ─────────────────────────────────────────────────────────────────────────────

LOGGING_SETUP = """
# Add to app/main.py or before first DB call:

import logging
logging.basicConfig()
logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO)
# Level INFO = logs SQL statements
# Level DEBUG = logs SQL + bind parameters
"""

if __name__ == "__main__":
    print(LOGGING_SETUP)
    run_validation()
