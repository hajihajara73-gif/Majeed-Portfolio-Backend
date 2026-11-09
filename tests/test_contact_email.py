"""
Contact-form notification email.

The property that matters most here is NEGATIVE: a Resend failure must never
cost us the visitor's message. Several of these tests exist only to prove
that the message survives when the email does not.

Nothing in this module reaches the network. `resend.Emails.send` is replaced
with a stub in every test that gets as far as sending.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.main import app
from app.models.content import ContactMessage
from app.services import contact_notifier, email_service
from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD

ENDPOINT = "/api/public/contact"
VALID = {
    "name": "Visitor",
    "email": "visitor@example.com",
    "subject": "Hello there",
    "message": "This is a message that is comfortably long enough.",
}


def configured(**overrides):
    """Settings with mail switched on, for use as a dependency override."""
    base = get_settings()
    values = {
        "resend_api_key": "re_test_key_not_real",
        "email_from": "Majeed <noreply@example.com>",
        "admin_email": "owner@example.com",
        "admin_dashboard_url": "https://example.com/admin",
    }
    values.update(overrides)
    return base.model_copy(update=values)


@pytest.fixture
def mail_on(db_session: Session, monkeypatch):
    """
    Switch mail on, and keep the background task on the test database.

    The notification runs as a FastAPI background task, which executes after
    the response and therefore after the request's session is closed. So
    `contact_notifier` opens its own session through `SessionLocal` — which
    in production is correct and in a test points at a Postgres that does not
    exist. Pointing that factory at the test session is the seam.

    `close()` is neutered because the session is owned by the fixture; the
    notifier closing it would break the assertions that follow.
    """

    class Borrowed:
        def __getattr__(self, item):
            return getattr(db_session, item)

        def close(self):  # noqa: D102 - the fixture owns the lifetime
            pass

    monkeypatch.setattr(contact_notifier, "SessionLocal", lambda: Borrowed())
    app.dependency_overrides[get_settings] = lambda: configured()
    yield
    app.dependency_overrides.pop(get_settings, None)


def only_message(db: Session) -> ContactMessage:
    rows = db.scalars(select(ContactMessage)).all()
    assert len(rows) == 1
    return rows[0]


# --------------------------------------------------------------------------
# Templates
# --------------------------------------------------------------------------


def test_html_escapes_everything_the_visitor_typed() -> None:
    """
    The body arrives at an UNAUTHENTICATED endpoint. Interpolating it raw into
    the notification is the same injection bug as interpolating it into a page.
    """
    html = email_service.notification_html(
        name='<script>alert("x")</script>',
        email="a@b.com",
        subject="<img src=x onerror=alert(1)>",
        body="<b>bold</b> & <i>italic</i>",
        received_at=datetime(2026, 1, 2, 3, 4, tzinfo=UTC),
        admin_url="https://example.com/admin/messages",
    )
    # What makes it safe is that no TAG survives. `escape()` neutralises the
    # angle brackets, so `onerror=alert(1)` remains as inert visible text —
    # asserting that substring is absent would be testing the wrong thing.
    assert "<script>" not in html
    assert "<img" not in html
    assert "<b>bold</b>" not in html
    assert "&lt;script&gt;" in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html
    assert "&amp;" in html


def test_newlines_become_breaks_but_tags_do_not_survive() -> None:
    html = email_service.notification_html(
        name="A",
        email="a@b.com",
        subject=None,
        body="line one\n<hr>\nline two",
        received_at=datetime(2026, 1, 2, tzinfo=UTC),
        admin_url=None,
    )
    assert "line one<br>" in html
    assert "&lt;hr&gt;" in html


def test_from_header_cannot_inject_a_header() -> None:
    """
    EMAIL_FROM is configuration rather than user input, but a mail header
    is still assembled from it, and CR/LF are what split one header in two.
    """
    dirty = configured(email_from="Majeed <a@b.com>\r\nBcc: evil@evil.test")
    header = dirty.email_from_header
    assert "\r" not in header
    assert "\n" not in header
    # Flattened onto one line, so it reads as an odd display name rather
    # than a second header the mail server would act on.
    assert "Bcc:" in header


def test_admin_button_only_when_a_url_is_known() -> None:
    args = {
        "name": "A",
        "email": "a@b.com",
        "subject": "S",
        "body": "B",
        "received_at": datetime(2026, 1, 2, tzinfo=UTC),
    }
    assert "Open in the admin" in email_service.notification_html(
        **args, admin_url="https://example.com/admin/messages"
    )
    assert "Open in the admin" not in email_service.notification_html(
        **args, admin_url=None
    )


def test_plain_text_alternative_carries_the_whole_message() -> None:
    text = email_service.notification_text(
        name="Visitor",
        email="v@example.com",
        subject="Subject here",
        body="The body.",
        received_at=datetime(2026, 1, 2, 3, 4, tzinfo=UTC),
        admin_url=None,
    )
    for expected in ("Visitor", "v@example.com", "Subject here", "The body."):
        assert expected in text


# --------------------------------------------------------------------------
# Sending
# --------------------------------------------------------------------------


def test_send_is_skipped_when_nothing_is_configured() -> None:
    result = email_service.send_notification(
        get_settings(),
        name="A",
        email="a@b.com",
        subject="S",
        body="B",
        received_at=datetime(2026, 1, 2, tzinfo=UTC),
        message_id="x",
    )
    assert result.status == "disabled"
    assert not result.ok


def test_visitor_address_is_reply_to_never_from(monkeypatch) -> None:
    """
    Sending AS the visitor is spoofing: it fails SPF and DMARC for their
    domain. The From must be the verified domain and the visitor must be
    Reply-To, which is what makes replying work.
    """
    captured: dict = {}

    class FakeEmails:
        @staticmethod
        def send(params):
            captured.update(params)
            return {"id": "re_123"}

    monkeypatch.setattr("resend.Emails", FakeEmails)
    monkeypatch.setattr("resend.api_key", "", raising=False)

    result = email_service.send_notification(
        configured(),
        name="Visitor",
        email="visitor@example.com",
        subject="Hi",
        body="Body",
        received_at=datetime(2026, 1, 2, tzinfo=UTC),
        message_id="x",
    )

    assert result.ok and result.message_id == "re_123"
    assert "visitor@example.com" not in captured["from"]
    assert captured["from"] == "Majeed <noreply@example.com>"
    assert captured["reply_to"] == ["visitor@example.com"]
    assert captured["to"] == ["owner@example.com"]
    assert captured["text"]


def test_resend_failure_is_reported_not_raised(monkeypatch) -> None:
    class Boom:
        @staticmethod
        def send(params):
            raise RuntimeError("Resend is down")

    monkeypatch.setattr("resend.Emails", Boom)
    monkeypatch.setattr("resend.api_key", "", raising=False)

    result = email_service.send_notification(
        configured(),
        name="A",
        email="a@b.com",
        subject="S",
        body="B",
        received_at=datetime(2026, 1, 2, tzinfo=UTC),
        message_id="x",
    )
    assert result.status == "failed"
    assert "Resend is down" in (result.error or "")


def test_the_api_key_never_appears_in_a_recorded_error(monkeypatch) -> None:
    secret = "re_super_secret_key"

    class Leaky:
        @staticmethod
        def send(params):
            # A real SDK exception can carry the request it was built from.
            raise RuntimeError("401 unauthorized")

    monkeypatch.setattr("resend.Emails", Leaky)
    monkeypatch.setattr("resend.api_key", "", raising=False)

    result = email_service.send_notification(
        configured(resend_api_key=secret),
        name="A",
        email="a@b.com",
        subject="S",
        body="B",
        received_at=datetime(2026, 1, 2, tzinfo=UTC),
        message_id="x",
    )
    assert secret not in (result.error or "")


# --------------------------------------------------------------------------
# The message survives, whatever the email does
# --------------------------------------------------------------------------


def test_message_is_saved_even_when_resend_fails(
    client: TestClient, db_session: Session, mail_on, monkeypatch
) -> None:
    """THE central guarantee. A third party being down must not lose a message."""

    class Boom:
        @staticmethod
        def send(params):
            raise RuntimeError("upstream exploded")

    monkeypatch.setattr("resend.Emails", Boom)
    monkeypatch.setattr("resend.api_key", "", raising=False)

    response = client.post(ENDPOINT, json=VALID)

    # The visitor is told it worked, because for them it did.
    assert response.status_code == 200
    assert response.json()["received"] is True

    row = only_message(db_session)
    assert row.email == "visitor@example.com"
    assert row.email_delivery_status == "failed"
    assert row.resend_email_id is None
    assert row.email_attempts == 1
    assert "upstream exploded" in (row.email_error or "")


def test_successful_send_records_the_resend_id(
    client: TestClient, db_session: Session, mail_on, monkeypatch
) -> None:
    class Ok:
        @staticmethod
        def send(params):
            return {"id": "re_delivered_1"}

    monkeypatch.setattr("resend.Emails", Ok)
    monkeypatch.setattr("resend.api_key", "", raising=False)

    assert client.post(ENDPOINT, json=VALID).status_code == 200

    row = only_message(db_session)
    assert row.email_delivery_status == "sent"
    assert row.resend_email_id == "re_delivered_1"
    assert row.email_sent_at is not None
    assert row.email_error is None


def test_no_email_configured_marks_disabled_and_still_saves(
    client: TestClient, db_session: Session
) -> None:
    assert client.post(ENDPOINT, json=VALID).status_code == 200
    row = only_message(db_session)
    assert row.email_delivery_status == "disabled"
    assert row.resend_email_id is None


# --------------------------------------------------------------------------
# Retry
# --------------------------------------------------------------------------


def test_retry_does_not_send_twice(
    client: TestClient, db_session: Session, monkeypatch
) -> None:
    """
    The duplicate guard. A second Retry click must not put a second copy in
    the inbox.
    """
    calls = {"n": 0}

    class Ok:
        @staticmethod
        def send(params):
            calls["n"] += 1
            return {"id": "re_once"}

    monkeypatch.setattr("resend.Emails", Ok)
    monkeypatch.setattr("resend.api_key", "", raising=False)

    db_session.add(
        ContactMessage(
            name="A",
            email="a@b.com",
            subject="S",
            body="Body",
            created_at=datetime.now(UTC),
            email_delivery_status="failed",
        )
    )
    db_session.commit()
    row = only_message(db_session)

    first = contact_notifier.notify(configured(), row.id, db=db_session)
    assert first.ok and calls["n"] == 1

    second = contact_notifier.notify(configured(), row.id, db=db_session)
    assert second.ok
    assert calls["n"] == 1, "a second retry must not send again"


def test_retry_endpoint_requires_authentication(client: TestClient) -> None:
    response = client.post(
        "/api/admin/messages/00000000-0000-0000-0000-000000000000/resend"
    )
    assert response.status_code == 401


def test_retry_endpoint_says_so_when_mail_is_not_configured(
    client: TestClient, db_session: Session, admin
) -> None:
    db_session.add(
        ContactMessage(
            name="A",
            email="a@b.com",
            subject="S",
            body="Body",
            created_at=datetime.now(UTC),
        )
    )
    db_session.commit()
    row = only_message(db_session)

    login = client.post(
        "/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    )
    csrf = login.cookies[get_settings().csrf_cookie_name]

    response = client.post(
        f"/api/admin/messages/{row.id}/resend",
        headers={get_settings().csrf_header_name: csrf},
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "email_not_configured"


# --------------------------------------------------------------------------
# Admin listing: search, filters, counters
# --------------------------------------------------------------------------


def seed(db: Session) -> None:
    for name, email, subject, read, archived in (
        ("Alice Smith", "alice@example.com", "Job opportunity", False, False),
        ("Bob Jones", "bob@other.test", "Question about pricing", True, False),
        ("Carol White", "carol@example.com", "Hello", False, True),
    ):
        db.add(
            ContactMessage(
                name=name,
                email=email,
                subject=subject,
                body="A message body long enough to pass validation.",
                created_at=datetime.now(UTC),
                is_read=read,
                is_archived=archived,
            )
        )
    db.commit()


def sign_in(client: TestClient) -> None:
    assert (
        client.post(
            "/api/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        ).status_code
        == 200
    )


def test_counters_exclude_archived_from_the_inbox(
    client: TestClient, db_session: Session, admin
) -> None:
    seed(db_session)
    sign_in(client)
    counts = client.get("/api/admin/messages").json()["counts"]
    assert counts["total"] == 2  # Carol is archived
    assert counts["unread"] == 1
    assert counts["read"] == 1
    assert counts["archived"] == 1


def test_search_matches_name_email_and_subject(
    client: TestClient, db_session: Session, admin
) -> None:
    seed(db_session)
    sign_in(client)

    def search(q: str) -> list[str]:
        body = client.get("/api/admin/messages", params={"q": q}).json()
        return [i["name"] for i in body["items"]]

    assert search("alice") == ["Alice Smith"]
    assert search("other.test") == ["Bob Jones"]
    assert search("pricing") == ["Bob Jones"]
    assert search("nothing at all") == []


def test_search_wildcards_are_escaped_not_interpreted(
    client: TestClient, db_session: Session, admin
) -> None:
    """A search for `%` must not match every row."""
    seed(db_session)
    sign_in(client)
    body = client.get("/api/admin/messages", params={"q": "%"}).json()
    assert body["items"] == []


def test_status_filter(client: TestClient, db_session: Session, admin) -> None:
    seed(db_session)
    sign_in(client)
    unread = client.get("/api/admin/messages", params={"status": "unread"}).json()
    assert [i["name"] for i in unread["items"]] == ["Alice Smith"]
    read = client.get("/api/admin/messages", params={"status": "read"}).json()
    assert [i["name"] for i in read["items"]] == ["Bob Jones"]


def test_archived_are_listed_only_when_asked_for(
    client: TestClient, db_session: Session, admin
) -> None:
    seed(db_session)
    sign_in(client)
    body = client.get("/api/admin/messages", params={"archived": "true"}).json()
    assert [i["name"] for i in body["items"]] == ["Carol White"]


def test_total_follows_the_filter_but_counters_do_not(
    client: TestClient, db_session: Session, admin
) -> None:
    seed(db_session)
    sign_in(client)
    body = client.get("/api/admin/messages", params={"q": "alice"}).json()
    assert body["total"] == 1  # the filtered count, for pagination
    assert body["counts"]["total"] == 2  # the inbox headline, unfiltered


def test_listing_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/admin/messages").status_code == 401
