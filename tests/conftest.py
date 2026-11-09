from __future__ import annotations

import os
from collections.abc import Generator

import pytest

# Settings are read at import time, so the environment must be primed before
# anything from `app` is imported.
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@localhost/test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-at-least-32-characters-long")

# THE SUITE MUST NEVER BE ABLE TO SEND REAL EMAIL.
#
# `.env` holds a working Resend key on any machine where mail is set up, and
# pydantic-settings reads that file. Without this the suite picks the key up
# and starts making real API calls — which it did, and which showed up as
# tests expecting "disabled" getting "failed" instead. One of them had
# genuinely tried to send.
#
# Assigned, not `setdefault`: an environment variable overrides the `.env`
# file, and forcing them empty is the whole point. Tests that need mail
# switched on build their own Settings and override the dependency, so they
# exercise the code without ever reaching the network.
os.environ["RESEND_API_KEY"] = ""
os.environ["EMAIL_FROM"] = ""
os.environ["ADMIN_EMAIL"] = ""
os.environ["SEND_VISITOR_CONFIRMATION"] = "false"

# The same applies to the INBOUND credentials, for the same reason and with
# the same failure mode. Once `.env` gained CONTACT_INBOUND_ADDRESS, the test
# pinning "Reply-To falls back to the owner until inbound is configured"
# started seeing the real inbound address and failing — the suite was reading
# the machine's configuration instead of its own.
#
# Forced empty so every test starts from "inbound is off". The inbound tests
# build their own Settings and override the dependency, so they exercise the
# webhook and the fetch without a real key, a real secret or a real mailbox
# anywhere near them.
os.environ["CONTACT_INBOUND_ADDRESS"] = ""
os.environ["RESEND_READ_API_KEY"] = ""
os.environ["RESEND_WEBHOOK_SECRET"] = ""

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
