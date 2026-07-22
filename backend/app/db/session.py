"""SQLAlchemy engine and session factory."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator

from app.config import get_settings


def get_engine():
    """Create SQLAlchemy engine from settings."""
    settings = get_settings()
    return create_engine(settings.DATABASE_URL, pool_pre_ping=True)


def get_session_factory():
    """Create a sessionmaker bound to the engine."""
    engine = get_engine()
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that provides a database session per request."""
    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
