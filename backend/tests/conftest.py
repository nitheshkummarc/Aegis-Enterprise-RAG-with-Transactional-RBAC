"""Shared test fixtures for ClearanceRAG backend tests."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db.session import get_db
from app.db.models import Base, User, UserRole
from app.core.security import hash_password
from app.config import get_settings, Settings


# ---------------------------------------------------------------------------
# Override settings for testing
# ---------------------------------------------------------------------------

def get_test_settings() -> Settings:
    """Return settings overridden for testing."""
    return Settings(
        DATABASE_URL="sqlite://",
        JWT_SECRET_KEY="test-secret-key-for-testing-only",
        JWT_ALGORITHM="HS256",
        JWT_EXPIRE_MINUTES=60,
    )


@pytest.fixture(autouse=True)
def override_settings(monkeypatch):
    """Override get_settings globally for all tests."""
    # Clear the lru_cache
    get_settings.cache_clear()
    monkeypatch.setattr("app.config.get_settings", get_test_settings)
    monkeypatch.setattr("app.auth.jwt.get_settings", get_test_settings)
    yield
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Database fixtures (SQLite in-memory for speed)
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_engine():
    """Create an in-memory SQLite engine for testing."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # Enable foreign key enforcement in SQLite
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
    
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(db_engine) -> Session:
    """Provide a transactional database session for testing."""
    TestingSessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=db_engine
    )
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db_session) -> TestClient:
    """FastAPI test client with database dependency overridden."""
    def override_get_db():
        yield db_session
    
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# User fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def admin_user(db_session) -> User:
    """Create and return an admin test user."""
    user = User(
        email="admin@test.com",
        password_hash=hash_password("adminpass"),
        role=UserRole.admin,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture()
def manager_user(db_session) -> User:
    """Create and return a manager test user."""
    user = User(
        email="manager@test.com",
        password_hash=hash_password("managerpass"),
        role=UserRole.manager,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture()
def viewer_user(db_session) -> User:
    """Create and return a viewer test user."""
    user = User(
        email="viewer@test.com",
        password_hash=hash_password("viewerpass"),
        role=UserRole.viewer,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user
