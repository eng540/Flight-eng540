"""Database configuration and session management – lazy engine creation."""
import os
import logging
from sqlalchemy import create_engine, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator

logger = logging.getLogger(__name__)

Base = declarative_base()


def _get_database_url() -> str:
    """Get and normalise DATABASE_URL. Converts postgres:// → postgresql://."""
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        try:
            from app.config import settings
            url = settings.DATABASE_URL
        except Exception:
            pass
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. "
            "In Railway: add DATABASE_URL = ${{Postgres.DATABASE_URL}} in Variables."
        )
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


# ── Lazy singletons ───────────────────────────────────────────────────────────

_engine = None
_session_factory = None


def _get_engine():
    global _engine
    if _engine is None:
        url = _get_database_url()
        _engine = create_engine(
            url,
            pool_pre_ping=True,
            pool_recycle=300,
            pool_size=5,
            max_overflow=10,
        )
        logger.info("Database engine created")
    return _engine


def _get_session_factory():
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            autocommit=False, autoflush=False, bind=_get_engine()
        )
    return _session_factory


# ── Public API ────────────────────────────────────────────────────────────────

def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency – yields a database session."""
    factory = _get_session_factory()
    db = factory()
    try:
        yield db
    finally:
        db.close()


def SessionLocal() -> Session:
    """
    Return a new database session.
    Compatible with code that calls SessionLocal() directly
    (e.g. ingestion_service.py, tasks.py).
    Caller is responsible for closing the session.
    """
    return _get_session_factory()()


def init_db():
    """Create all tables (development / testing)."""
    Base.metadata.create_all(bind=_get_engine())
    logger.info("Database tables initialised")


# Backwards-compatible proxy for code that does `engine.xxx`
class _LazyEngine:
    def __getattr__(self, name):
        return getattr(_get_engine(), name)

engine = _LazyEngine()
