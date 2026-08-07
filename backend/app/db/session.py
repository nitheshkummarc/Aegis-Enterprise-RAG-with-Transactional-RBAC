"""SQLAlchemy engine and session factory.

The engine and session factory are created ONCE at module level and reused
across all requests. Creating a new engine per request would leak connection
pools and exhaust Postgres connections under load.
"""

from sqlalchemy import create_engine, Engine
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator

from app.config import get_settings


# Module-level engine and session factory — created once, reused everywhere.
_settings = get_settings()
_engine: Engine = create_engine(
    _settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)
_SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


def get_engine() -> Engine:
    """Return the shared SQLAlchemy engine."""
    return _engine


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that provides a database session per request.

    Uses the shared engine/session factory — does NOT create a new engine
    per call.
    """
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()
