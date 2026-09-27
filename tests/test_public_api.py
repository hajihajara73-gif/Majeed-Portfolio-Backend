"""
Tests for the one endpoint the public internet may call.

Because it is unauthenticated, the interesting assertions are not "does it
store a message" but "what happens when it is abused" — the honeypot, the
per-IP ceiling, and the promise that a rejected submission stores nothing.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.routes.public import MAX_PER_HOUR
from app.core.config import get_settings
from app.models.content import ContactMessage
from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD

settings = get_settings()

ENDPOINT = "/api/public/contact"

VALID = {
    "name": "A Visitor",
    "email": "visitor@example.com",
    "subject": "About your PhD system",
    "message": "I read about the scholarly workflow project and had a question.",
}


def count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(ContactMessage)) or 0


def test_accepts_a_real_message(client: TestClient, db_session: Session) -> None:
    response = client.post(ENDPOINT, json=VALID)

    assert response.status_code == 200
    assert response.json()["received"] is True

    row = db_session.scalars(select(ContactMessage)).one()
    assert row.name == "A Visitor"
    assert row.email == "visitor@example.com"
    assert row.body.startswith("I read about")
    assert row.is_read is False
    # Recorded for the rate limiter; it is also what makes abuse traceable.
    assert row.ip_address


def test_requires_no_authentication(client: TestClient) -> None:
    """The whole point of this endpoint. Guard against a stray dependency."""
    assert client.post(ENDPOINT, json=VALID).status_code == 200


def test_honeypot_looks_like_success_but_stores_nothing(
    client: TestClient, db_session: Session
) -> None:
    response = client.post(ENDPOINT, json={**VALID, "website": "http://spam.example"})

    # Same shape and status a genuine sender gets: a bot must not be able to
    # tell the trap from a delivery, or it just retries without the field.
    assert response.status_code == 200
    assert response.json()["received"] is True
    assert count(db_session) == 0


@pytest.mark.parametrize(
    "payload",
    [
        {**VALID, "message": "too short"},
        {**VALID, "email": "not-an-email"},
        {**VALID, "name": ""},
        {**VALID, "message": ""},
    ],
)
def test_rejects_invalid_submissions(
    client: TestClient, db_session: Session, payload: dict
) -> None:
    assert client.post(ENDPOINT, json=payload).status_code == 422
    assert count(db_session) == 0


def test_strips_control_characters(client: TestClient, db_session: Session) -> None:
    """
    Header-injection shaped input. Newlines survive because a message may
    legitimately have paragraphs; bare control characters do not.
    """
    client.post(
        ENDPOINT,
        json={
            **VALID,
            "subject": "Hello\r\nBcc: victim@example.com",
            "message": "Line one\n\nLine two\x00\x07 with junk in it.",
        },
    )

    row = db_session.scalars(select(ContactMessage)).one()
    assert "\r" not in (row.subject or "")
    assert "\x00" not in row.body and "\x07" not in row.body
    assert "\n\nLine two" in row.body


def test_rate_limit_returns_429_with_retry_after(
    client: TestClient, db_session: Session
) -> None:
    for i in range(MAX_PER_HOUR):
        ok = client.post(ENDPOINT, json={**VALID, "message": f"Message number {i}."})
        assert ok.status_code == 200

    blocked = client.post(ENDPOINT, json=VALID)

    assert blocked.status_code == 429
    assert blocked.headers["Retry-After"] == "3600"
    assert blocked.json()["detail"]["code"] == "rate_limited"
    # The blocked one is not stored, so the limit cannot ratchet itself.
    assert count(db_session) == MAX_PER_HOUR


def test_message_reaches_the_admin_inbox(client: TestClient, admin) -> None:
    """End to end: the public form is the source of the admin Messages list."""
    assert client.post(ENDPOINT, json=VALID).status_code == 200

    login = client.post(
        "/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    )
    assert login.status_code == 200

    inbox = client.get("/api/admin/messages")
    assert inbox.status_code == 200

    body = inbox.json()
    assert len(body) == 1
    assert body[0]["email"] == "visitor@example.com"
    assert body[0]["is_read"] is False
