"""
Two-way conversation: the admin replying to a contact message.

Nothing here reaches the network; `resend.Emails.send` is stubbed in every
test that gets as far as sending.

The properties that matter:
  * the reply is RECORDED even when Resend refuses, so the operator never
    loses what they typed;
  * threading headers are set, and do not stack "Re: Re: Re:";
  * the endpoint is behind the admin session.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.main import app
from app.models.content import ContactMessage, EmailMessage
from app.services import conversation
from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD


def configured(**overrides):
    base = get_settings()
    values = {
        "resend_api_key": "re_test_key_not_real",
        "email_from": "Majeed <contact@mail.example.com>",
        "admin_email": "owner@example.com",
    }
    values.update(overrides)
    return base.model_copy(update=values)


@pytest.fixture
def mail_on():
    app.dependency_overrides[get_settings] = lambda: configured()
    yield
    app.dependency_overrides.pop(get_settings, None)


@pytest.fixture
def enquiry(db_session: Session) -> ContactMessage:
    row = ContactMessage(
        name="Priya Raman",
        email="priya@example.com",
        subject="Freelance enquiry",
        body="Hello, are you available for a React project?",
        created_at=datetime.now(UTC),
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def sign_in(client: TestClient) -> str:
    login = client.post(
        "/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    )
    assert login.status_code == 200
    return login.cookies[get_settings().csrf_cookie_name]


def stub_send(monkeypatch, captured: dict, *, fail: bool = False, eid="re_reply_1"):
    class Fake:
        @staticmethod
        def send(params):
            captured.update(params)
            if fail:
                raise RuntimeError("Resend refused")
            return {"id": eid}

    monkeypatch.setattr("resend.Emails", Fake)
    monkeypatch.setattr("resend.api_key", "", raising=False)


# --------------------------------------------------------------------------
# Subject handling
# --------------------------------------------------------------------------


def test_subject_gets_one_re_prefix() -> None:
    assert conversation.reply_subject("Freelance enquiry") == "Re: Freelance enquiry"


@pytest.mark.parametrize("existing", ["Re: Hello", "RE: Hello", "re: Hello"])
def test_re_prefix_does_not_stack(existing: str) -> None:
    """A thread that has been round a few times must not read Re: Re: Re:."""
    assert conversation.reply_subject(existing) == existing


def test_missing_subject_gets_a_sensible_one() -> None:
    assert conversation.reply_subject(None) == "Re: your message"
    assert conversation.reply_subject("   ") == "Re: your message"


# --------------------------------------------------------------------------
# Sending
# --------------------------------------------------------------------------


def test_reply_is_sent_and_recorded(
    db_session: Session, enquiry: ContactMessage, monkeypatch
) -> None:
    captured: dict = {}
    stub_send(monkeypatch, captured)

    row, result = conversation.send_reply(
        configured(),
        db_session,
        contact_message_id=enquiry.id,
        body="Hello Priya, yes — happy to discuss.",
        admin_id=None,
    )

    assert result.ok
    assert row is not None
    assert row.direction == "outbound"
    assert row.delivery_status == "sent"
    assert row.resend_email_id == "re_reply_1"
    assert row.to_email == "priya@example.com"
    assert row.subject == "Re: Freelance enquiry"
    assert row.sent_at is not None

    # The visitor is the recipient; the verified domain is the sender.
    assert captured["to"] == ["priya@example.com"]
    assert "priya@example.com" not in captured["from"]
    assert captured["headers"]["Message-ID"].startswith("<")


def test_first_reply_stamps_replied_at(
    db_session: Session, enquiry: ContactMessage, monkeypatch
) -> None:
    """`replied_at` has existed unused since the table was made. This is it."""
    assert enquiry.replied_at is None
    stub_send(monkeypatch, {})

    conversation.send_reply(
        configured(), db_session, contact_message_id=enquiry.id,
        body="First reply.", admin_id=None,
    )
    db_session.refresh(enquiry)
    first = enquiry.replied_at
    assert first is not None

    # A second reply must not move it: it means "has been answered".
    stub_send(monkeypatch, {}, eid="re_reply_2")
    conversation.send_reply(
        configured(), db_session, contact_message_id=enquiry.id,
        body="Second reply.", admin_id=None,
    )
    db_session.refresh(enquiry)
    assert enquiry.replied_at == first


def test_reply_is_recorded_even_when_resend_fails(
    db_session: Session, enquiry: ContactMessage, monkeypatch
) -> None:
    """THE central guarantee: the operator never loses what they typed."""
    stub_send(monkeypatch, {}, fail=True)

    row, result = conversation.send_reply(
        configured(), db_session, contact_message_id=enquiry.id,
        body="This should survive the failure.", admin_id=None,
    )

    assert not result.ok
    assert row is not None
    assert row.delivery_status == "failed"
    assert row.resend_email_id is None
    assert row.text_body == "This should survive the failure."
    assert "Resend refused" in (row.delivery_error or "")

    stored = db_session.scalars(select(EmailMessage)).all()
    assert len(stored) == 1


def test_unconfigured_email_sends_nothing(
    db_session: Session, enquiry: ContactMessage
) -> None:
    row, result = conversation.send_reply(
        get_settings(), db_session, contact_message_id=enquiry.id,
        body="Nope.", admin_id=None,
    )
    assert result.status == "disabled"
    assert row is None
    assert db_session.scalars(select(EmailMessage)).all() == []


# --------------------------------------------------------------------------
# Threading
# --------------------------------------------------------------------------


def test_second_reply_references_the_first(
    db_session: Session, enquiry: ContactMessage, monkeypatch
) -> None:
    """
    In-Reply-To points at the previous message and References accumulates the
    chain — that is what a client walks to group a thread.
    """
    first_params: dict = {}
    stub_send(monkeypatch, first_params, eid="re_1")
    first_row, _ = conversation.send_reply(
        configured(), db_session, contact_message_id=enquiry.id,
        body="One.", admin_id=None,
    )

    second_params: dict = {}
    stub_send(monkeypatch, second_params, eid="re_2")
    second_row, _ = conversation.send_reply(
        configured(), db_session, contact_message_id=enquiry.id,
        body="Two.", admin_id=None,
    )

    assert first_params["headers"].get("In-Reply-To") is None
    assert second_params["headers"]["In-Reply-To"] == first_row.message_id
    assert first_row.message_id in second_params["headers"]["References"]
    assert second_row.message_id != first_row.message_id


def test_reply_to_is_the_owner_until_inbound_is_configured(
    db_session: Session, enquiry: ContactMessage, monkeypatch
) -> None:
    captured: dict = {}
    stub_send(monkeypatch, captured)
    conversation.send_reply(
        configured(), db_session, contact_message_id=enquiry.id,
        body="Hi.", admin_id=None,
    )
    assert captured["reply_to"] == ["owner@example.com"]


def test_reply_to_switches_to_the_inbox_address_when_set(
    db_session: Session, enquiry: ContactMessage, monkeypatch
) -> None:
    captured: dict = {}
    stub_send(monkeypatch, captured)
    conversation.send_reply(
        configured(contact_inbound_address="reply@inbox.example.com"),
        db_session, contact_message_id=enquiry.id, body="Hi.", admin_id=None,
    )
    assert captured["reply_to"] == ["reply@inbox.example.com"]


def test_reply_body_is_escaped_in_the_html(
    db_session: Session, enquiry: ContactMessage, monkeypatch
) -> None:
    """An admin pasting a snippet should not produce a broken email."""
    captured: dict = {}
    stub_send(monkeypatch, captured)
    conversation.send_reply(
        configured(), db_session, contact_message_id=enquiry.id,
        body="Use <script>alert(1)</script> carefully", admin_id=None,
    )
    assert "<script>" not in captured["html"]
    assert "&lt;script&gt;" in captured["html"]


def test_the_quoted_original_is_escaped_too(
    db_session: Session, db_session_unused=None, monkeypatch=None
) -> None:
    """The quoted text is visitor input, so it is the dangerous half."""
    from app.services import email_service

    html = email_service.reply_html(
        body="Thanks",
        original_subject="<b>subject</b>",
        original_body="<img src=x onerror=alert(1)>",
        visitor_name="<script>x</script>",
    )
    assert "<img" not in html
    assert "<script>" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html


# --------------------------------------------------------------------------
# The endpoint
# --------------------------------------------------------------------------


def test_reply_endpoint_requires_authentication(client: TestClient) -> None:
    r = client.post(
        "/api/admin/messages/00000000-0000-0000-0000-000000000000/reply",
        json={"body": "hello"},
    )
    assert r.status_code == 401


def test_thread_endpoint_requires_authentication(client: TestClient) -> None:
    r = client.get(
        "/api/admin/messages/00000000-0000-0000-0000-000000000000/thread"
    )
    assert r.status_code == 401


def test_reply_endpoint_rejects_an_empty_body(
    client: TestClient, enquiry: ContactMessage, admin, mail_on
) -> None:
    csrf = sign_in(client)
    r = client.post(
        f"/api/admin/messages/{enquiry.id}/reply",
        json={"body": "   "},
        headers={get_settings().csrf_header_name: csrf},
    )
    assert r.status_code == 422


def test_reply_endpoint_says_so_when_mail_is_unconfigured(
    client: TestClient, enquiry: ContactMessage, admin
) -> None:
    csrf = sign_in(client)
    r = client.post(
        f"/api/admin/messages/{enquiry.id}/reply",
        json={"body": "Hello there."},
        headers={get_settings().csrf_header_name: csrf},
    )
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "email_not_configured"


def test_thread_endpoint_returns_the_conversation(
    client: TestClient, db_session: Session, enquiry: ContactMessage,
    admin, mail_on, monkeypatch,
) -> None:
    stub_send(monkeypatch, {})
    csrf = sign_in(client)

    sent = client.post(
        f"/api/admin/messages/{enquiry.id}/reply",
        json={"body": "Happy to help."},
        headers={get_settings().csrf_header_name: csrf},
    )
    assert sent.status_code == 200
    assert sent.json()["status"] == "sent"

    thread = client.get(f"/api/admin/messages/{enquiry.id}/thread")
    assert thread.status_code == 200
    items = thread.json()
    assert len(items) == 1
    assert items[0]["direction"] == "outbound"
    assert items[0]["text_body"] == "Happy to help."
    # Plumbing stays out of the API surface.
    assert "html_body" not in items[0]
    assert "references" not in items[0]


def test_a_failed_reply_is_not_an_error_response(
    client: TestClient, enquiry: ContactMessage, admin, mail_on, monkeypatch
) -> None:
    """
    Returning 500 would lose the operator's typed text and tell them nothing.
    The reply is stored; the status says what happened.
    """
    stub_send(monkeypatch, {}, fail=True)
    csrf = sign_in(client)

    r = client.post(
        f"/api/admin/messages/{enquiry.id}/reply",
        json={"body": "Will not be delivered."},
        headers={get_settings().csrf_header_name: csrf},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "failed"
    assert "not delivered" in body["message"]
    assert body["email"]["delivery_status"] == "failed"
