from __future__ import annotations

import os
from collections.abc import Generator

import pytest

# Settings are read at import time, so the environment must be primed before
# anything from `app` is imported.
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@localhost/test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-at-least-32-characters-long")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core import security  # noqa: E402
from app.core.db import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.admin import AdminUser  # noqa: E402
from app.models.base import Base  # noqa: E402


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    """
    In-memory SQLite, one connection shared by the whole test.

    StaticPool keeps every session on the same connection, so the schema
    created here is visible to the request handlers — with the default pool
    each connection would get its own empty database.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def client(db_session: Session) -> Generator[TestClient, None, None]:
    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "correct-horse-battery-staple"


@pytest.fixture
def admin(db_session: Session) -> AdminUser:
    user = AdminUser(
        email=ADMIN_EMAIL,
        password_hash=security.hash_password(ADMIN_PASSWORD),
        full_name="Test Admin",
        role="owner",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return user
