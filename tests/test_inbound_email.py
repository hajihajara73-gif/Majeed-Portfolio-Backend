"""
Inbound email: the Resend webhook, conversation matching, and attachments.

NOTHING HERE TOUCHES THE NETWORK. `resend.Emails.Receiving.get`,
`resend.Emails.Receiving.Attachments.get` and `requests.get` are stubbed in
every test that reaches them, and the suite-wide guard in `conftest` empties
`RESEND_API_KEY` so an unstubbed call could not authenticate even if one
slipped through.

Webhook signatures are computed here rather than mocked away. Faking
`Webhooks.verify` would leave the one security property that matters —
that a forged request is refused — completely untested, so these tests
build real svix signatures with a test secret and let the SDK judge them.

The properties being pinned:

  * a forged, tampered, stale or unsigned request is refused;
  * a duplicate delivery stores one row, not two;
  * a reply joins a conversation ONLY via threading headers this system
    minted — never via `From`, `Reply-To` or the subject line;
  * an unmatched email is dropped rather than attached on a guess;
  * attachment metadata is sanitised, and the bytes are reachable only by an
    authenticated admin, only for their own thread, and only within the
    type and size rules;
  * a malformed payload is an answer, not a stack trace.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.main import app
from app.models.content import ContactMessage, EmailMessage
from app.services import conversation, inbound_email
from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD

WEBHOOK_URL = "/api/public/webhooks/resend"

# A real-shaped secret. The `whsec_` prefix is stripped before base64 decoding,
# exactly as Resend's own secrets are.
TEST_SECRET = "whsec_" + base64.b64encode(b"inbound-webhook-test-secret").decode()

READ_KEY = "re_test_read_key_not_real"

# Message-IDs. The outbound one is what this system would have minted; the
# inbound one is what the visitor's client generates when replying to it.
OUTBOUND_MID = "<reply-abc123@mail.example.com>"
INBOUND_MID = "<CAFrRn5e-visitor-reply@mail.gmail.com>"


# --------------------------------------------------------------- settings --


def configured(**overrides: Any):
    """Settings with inbound switched on, built per test rather than global."""
    values = {
        "resend_api_key": "re_test_send_key_not_real",
        "resend_read_api_key": READ_KEY,
        "resend_webhook_secret": TEST_SECRET,
        "contact_inbound_address": "inbound@test.resend.app",
        "email_from": "Majeed <contact@mail.example.com>",
        "admin_email": "owner@example.com",
    }
    values.update(overrides)
    return get_settings().model_copy(update=values)


@pytest.fixture
def inbound_on():
    app.dependency_overrides[get_settings] = lambda: configured()
    yield
    app.dependency_overrides.pop(get_settings, None)


# ---------------------------------------------------------------- signing --


def sign(payload: str, *, secret: str = TEST_SECRET, timestamp: int | None = None):
    """
    Build the svix headers for a payload, the way Resend does.

    This is the real algorithm — HMAC-SHA256 over `{id}.{timestamp}.{body}`
    with the base64-decoded secret — so a test that passes here would pass
    against a genuine Resend delivery.
    """
    ts = int(time.time()) if timestamp is None else timestamp
    msg_id = "msg_test_0001"
    raw_secret = base64.b64decode(secret.removeprefix("whsec_"))
    digest = hmac.new(
        raw_secret, f"{msg_id}.{ts}.{payload}".encode(), hashlib.sha256
    ).digest()
    return {
        "svix-id": msg_id,
        "svix-timestamp": str(ts),
        "svix-signature": "v1," + base64.b64encode(digest).decode(),
    }


def post_signed(client: TestClient, body: dict[str, Any], **kwargs: Any):
    """POST a correctly signed webhook. `content=` so the bytes signed are the
    bytes sent — re-serialising would change them and break the signature."""
    payload = json.dumps(body)
    return client.post(
        WEBHOOK_URL,
        content=payload,
        headers={
            "content-type": "application/json",
            **sign(payload, **kwargs),
        },
    )


def event(email_id: str = "em_inbound_1", kind: str = "email.received"):
    return {
        "type": kind,
        "created_at": "2026-11-09T10:00:00.000Z",
        "data": {"email_id": email_id},
    }


# --------------------------------------------------------------- fixtures --


@pytest.fixture
def enquiry(db_session: Session) -> ContactMessage:
    row = ContactMessage(
        name="Priya Raman",
        email="priya@example.com",
        subject="Freelance enquiry",
        body="Hello, are you available for a React project?",
        is_read=True,
        created_at=datetime.now(UTC),
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


@pytest.fixture
def replied(db_session: Session, enquiry: ContactMessage) -> ContactMessage:
    """An enquiry the admin has already answered, so a thread exists to join."""
    db_session.add(
        EmailMessage(
            contact_message_id=enquiry.id,
            direction="outbound",
            from_email="contact@mail.example.com",
            to_email=enquiry.email,
            subject="Re: Freelance enquiry",
            text_body="Yes — happy to talk. What is the timeline?",
            message_id=OUTBOUND_MID,
            delivery_status="sent",
            attempts=1,
            created_at=datetime.now(UTC),
        )
    )
    db_session.commit()
    return enquiry


def received_payload(**overrides: Any) -> dict[str, Any]:
    """A received email shaped like the live API's response."""
    payload: dict[str, Any] = {
        "object": "email",
        "id": "em_inbound_1",
        "from": "priya@example.com",
        "to": ["inbound@test.resend.app"],
        "received_for": ["inbound@test.resend.app"],
        "cc": [],
        "bcc": [],
        "reply_to": [],
        "subject": "Re: Freelance enquiry",
        "text": "Three weeks would work. Shall we talk Tuesday?",
        "html": "<p>Three weeks would work.</p>",
        "html_format": "data_uri",
        "message_id": INBOUND_MID,
        "created_at": "2026-11-09T10:00:00.000Z",
        "headers": {
            "message-id": INBOUND_MID,
            "in-reply-to": OUTBOUND_MID,
            "references": OUTBOUND_MID,
            "from": "Priya Raman <priya@example.com>",
            "subject": "Re: Freelance enquiry",
        },
        "attachments": [],
        "authentication": {"spf": "pass", "dkim": "pass", "dmarc": "pass"},
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def stub_fetch(monkeypatch):
    """
    Stub `Emails.Receiving.get` and record the api key in force when called.

    The recorded key is what proves the READ key is swapped in for the call
    and the send key restored afterwards.
    """
    calls: list[dict[str, Any]] = []

    def factory(payload: dict[str, Any] | None = None, error: Exception | None = None):
        import resend

        def fake_get(email_id: str, params: Any = None):
            calls.append(
                {
                    "email_id": email_id,
                    "params": params,
                    "api_key": resend.api_key,
                }
            )
            if error is not None:
                raise error
            return payload if payload is not None else received_payload()

        monkeypatch.setattr(resend.Emails.Receiving, "get", fake_get)
        return calls

    return factory


def sign_in(client: TestClient) -> str:
    login = client.post(
        "/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    )
    assert login.status_code == 200
    return login.cookies[get_settings().csrf_cookie_name]


def inbound_rows(db: Session) -> list[EmailMessage]:
    return list(
        db.scalars(
            select(EmailMessage).where(EmailMessage.direction == "inbound")
        ).all()
    )


# ========================================================================
# 1-6. Webhook signature verification
# ========================================================================


def test_valid_signature_is_accepted(client, inbound_on, replied, stub_fetch):
    """A correctly signed delivery is processed and the email is stored."""
    stub_fetch()
    response = post_signed(client, event())
    assert response.status_code == 200
    assert response.json()["detail"] == "stored"


def test_invalid_signature_is_rejected(client, inbound_on, replied, stub_fetch):
    """A signature computed with the wrong secret gets 401 and stores nothing."""
    calls = stub_fetch()
    other = "whsec_" + base64.b64encode(b"an-attackers-guess").decode()
    response = post_signed(client, event(), secret=other)
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "invalid_signature"
    # Refused BEFORE the body was looked at: no fetch was attempted.
    assert calls == []


def test_missing_signature_headers_are_rejected(client, inbound_on, replied):
    """An unsigned request is refused, with no hint about which header was
    absent."""
    response = client.post(
        WEBHOOK_URL,
        content=json.dumps(event()),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == {"code": "invalid_signature"}


def test_tampered_body_is_rejected(client, inbound_on, replied, stub_fetch):
    """
    A body altered after signing is refused.

    This is the test that would fail if verification ran against a re-parsed
    and re-serialised payload instead of the raw bytes.
    """
    calls = stub_fetch()
    original = json.dumps(event("em_original"))
    headers = sign(original)
    tampered = json.dumps(event("em_substituted"))
    response = client.post(
        WEBHOOK_URL,
        content=tampered,
        headers={"content-type": "application/json", **headers},
    )
    assert response.status_code == 401
    assert calls == []


def test_stale_timestamp_is_rejected(client, inbound_on, replied, stub_fetch):
    """
    A captured request replayed later is refused.

    The signature is perfectly valid; only the timestamp is old. That is the
    replay protection, and it is the SDK's five-minute tolerance doing the
    work.
    """
    stub_fetch()
    old = int(time.time()) - 3600
    response = post_signed(client, event(), timestamp=old)
    assert response.status_code == 401


def test_webhook_refuses_when_unconfigured(client, replied):
    """
    With no webhook secret, the endpoint reports 503 rather than accepting
    traffic it cannot verify.
    """
    app.dependency_overrides[get_settings] = lambda: configured(
        resend_webhook_secret=None
    )
    try:
        response = post_signed(client, event())
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "webhook_not_configured"
    finally:
        app.dependency_overrides.pop(get_settings, None)


# ========================================================================
# 7-9. Payload handling
# ========================================================================


def test_unsupported_event_is_acknowledged(client, inbound_on, replied, stub_fetch):
    """
    An event we do not handle returns 200 so Resend stops retrying.

    A 4xx or 5xx here would leave `email.sent` deliveries churning in
    Resend's retry queue forever.
    """
    calls = stub_fetch()
    response = post_signed(client, event(kind="email.delivered"))
    assert response.status_code == 200
    assert response.json()["detail"] == "ignored"
    assert calls == []


def test_malformed_payload_is_handled_safely(client, inbound_on, replied):
    """
    A signed body that is valid JSON but structurally wrong gets an answer,
    not a 500.
    """
    for body in (
        {"type": "email.received"},                       # no data
        {"type": "email.received", "data": {}},           # no email id
        {"type": "email.received", "data": "not-a-dict"},  # wrong type
        {"data": {"email_id": "x"}},                      # no event type
    ):
        response = post_signed(client, body)
        assert response.status_code == 200, body
        assert response.json()["ok"] is True


def test_signed_non_json_body_is_rejected(client, inbound_on, replied):
    """A correctly signed body that is not JSON fails verification, not the
    process."""
    payload = "this is not json"
    response = client.post(
        WEBHOOK_URL,
        content=payload,
        headers={"content-type": "application/json", **sign(payload)},
    )
    assert response.status_code == 401


def test_unfetchable_body_is_acknowledged(client, inbound_on, replied, stub_fetch):
    """
    When the body cannot be read, the delivery is acknowledged rather than
    retried forever — a missing read key will not fix itself.
    """
    stub_fetch(error=RuntimeError("read key rejected"))
    response = post_signed(client, event())
    assert response.status_code == 200
    assert response.json()["detail"] == "accepted: body unavailable"


# ========================================================================
# 10-11. Idempotency
# ========================================================================


def test_duplicate_delivery_stores_one_row(
    client, inbound_on, replied, stub_fetch, db_session
):
    """
    Resend retries until it gets a 2xx, so the same email arrives twice in
    normal operation. The second delivery must be a no-op.
    """
    stub_fetch()
    first = post_signed(client, event())
    second = post_signed(client, event())

    assert first.json()["detail"] == "stored"
    assert second.status_code == 200
    assert second.json()["detail"] == "duplicate: already stored"
    assert len(inbound_rows(db_session)) == 1


def test_duplicate_detected_by_message_id_alone(
    client, inbound_on, replied, stub_fetch, db_session
):
    """
    The same email redelivered under a different Resend id is still the same
    email. Caught on the RFC Message-ID, which is the dual key doing its job.
    """
    stub_fetch()
    assert post_signed(client, event("em_first")).json()["detail"] == "stored"

    # Same message, new Resend id — what a replayed or re-ingested delivery
    # looks like.
    stub_fetch(payload=received_payload(id="em_second"))
    second = post_signed(client, event("em_second"))
    assert second.json()["detail"] == "duplicate: already stored"
    assert len(inbound_rows(db_session)) == 1


# ========================================================================
# 12-14. Conversation matching — the security boundary
# ========================================================================


def test_matched_by_in_reply_to(client, inbound_on, replied, stub_fetch, db_session):
    """A reply naming our Message-ID in In-Reply-To joins that conversation."""
    stub_fetch()
    post_signed(client, event())

    rows = inbound_rows(db_session)
    assert len(rows) == 1
    assert rows[0].contact_message_id == replied.id
    assert rows[0].delivery_status == "received"
    assert rows[0].text_body.startswith("Three weeks")


def test_matched_by_references_chain(
    client, inbound_on, replied, stub_fetch, db_session
):
    """
    With no In-Reply-To, the References chain is walked.

    Some clients drop In-Reply-To but keep References, and a thread should
    not come apart because of it.
    """
    stub_fetch(
        payload=received_payload(
            headers={
                "message-id": INBOUND_MID,
                "references": f"<older@example.com> {OUTBOUND_MID}",
            }
        )
    )
    post_signed(client, event())
    rows = inbound_rows(db_session)
    assert len(rows) == 1
    assert rows[0].contact_message_id == replied.id


def test_unmatched_email_is_not_stored(
    client, inbound_on, replied, stub_fetch, db_session
):
    """
    Mail that replies to nothing we sent is dropped, not attached on a guess.

    Storing it against the nearest-looking conversation is how a stranger's
    mail ends up in somebody else's thread.
    """
    stub_fetch(
        payload=received_payload(
            headers={
                "message-id": "<unrelated@example.com>",
                "in-reply-to": "<never-sent-by-us@example.com>",
            }
        )
    )
    response = post_signed(client, event())
    assert response.status_code == 200
    assert response.json()["detail"] == "accepted: no matching conversation"
    assert inbound_rows(db_session) == []


def test_forged_sender_cannot_join_a_conversation(
    client, inbound_on, replied, stub_fetch, db_session
):
    """
    THE ONE THAT MATTERS. An attacker who knows the visitor's address and the
    subject line still cannot inject a message into the thread, because
    matching ignores both.

    `From`, `Reply-To` and `Subject` are all supplied by the sender. Only the
    threading headers name a Message-ID this system minted, and this payload
    has none.
    """
    stub_fetch(
        payload=received_payload(
            **{
                "from": "priya@example.com",
                "reply_to": ["priya@example.com"],
                "subject": "Re: Freelance enquiry",
                "message_id": "<forged@attacker.example>",
                "headers": {
                    "message-id": "<forged@attacker.example>",
                    "from": "Priya Raman <priya@example.com>",
                    "subject": "Re: Freelance enquiry",
                },
            }
        )
    )
    response = post_signed(client, event())
    assert response.json()["detail"] == "accepted: no matching conversation"
    assert inbound_rows(db_session) == []


def test_matching_helper_ignores_sender_and_subject(db_session, replied):
    """
    The matcher's signature cannot even see `From` or the subject.

    Pinned directly as well as through the endpoint, so a later refactor that
    "helpfully" adds a sender fallback has to delete a test to do it.
    """
    assert (
        conversation.match_conversation(
            db_session, in_reply_to=None, references=None
        )
        is None
    )
    assert (
        conversation.match_conversation(
            db_session, in_reply_to=OUTBOUND_MID, references=None
        ).id
        == replied.id
    )


def test_inbound_reply_marks_the_enquiry_unread(
    client, inbound_on, replied, stub_fetch, db_session
):
    """A new reply resurfaces the thread, and leaves the original text alone."""
    assert replied.is_read is True
    original_body = replied.body

    stub_fetch()
    post_signed(client, event())
    db_session.refresh(replied)

    assert replied.is_read is False
    assert replied.body == original_body


# ========================================================================
# 15-16. Fetch behaviour and key handling
# ========================================================================


def test_fetch_uses_the_read_key_and_restores_the_send_key(
    client, inbound_on, replied, stub_fetch, monkeypatch
):
    """
    The read key is in force for the fetch and the send key is back
    afterwards, so a read can never widen what sending is able to do.
    """
    import resend

    # monkeypatch, so the module-level key this test sets cannot leak into
    # another test in the same process.
    monkeypatch.setattr(resend, "api_key", "re_the_send_key")
    calls = stub_fetch()
    post_signed(client, event())

    assert len(calls) == 1
    assert calls[0]["api_key"] == READ_KEY
    assert calls[0]["params"] == {"html_format": "cid"}
    assert resend.api_key == "re_the_send_key"


def test_fetch_without_a_read_key_returns_none(monkeypatch):
    """No read key is a configuration failure, reported quietly and without
    a network call."""
    import resend

    def explode(*args: Any, **kwargs: Any):
        raise AssertionError("the network must not be reached")

    monkeypatch.setattr(resend.Emails.Receiving, "get", explode)
    settings = configured(resend_read_api_key=None, resend_api_key=None)
    assert inbound_email.fetch(settings, "em_x") is None


# ========================================================================
# 17-20. Parsing and sanitisation
# ========================================================================


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("../../etc/passwd", "passwd"),
        ("..\\..\\windows\\system32\\cmd.exe", "cmd.exe"),
        ("/absolute/path/report.pdf", "report.pdf"),
        ("..", "attachment"),
        ("...", "attachment"),
        (".hidden", "hidden"),
        ("", "attachment"),
        (None, "attachment"),
        ("in voice <2026>.pdf", "in_voice__2026_.pdf"),
    ],
)
def test_filename_sanitisation(given, expected):
    """
    A filename cannot escape a directory, hide itself, or carry markup.

    Both separators are handled: a Windows-style name arriving at a POSIX
    host keeps its backslashes and would otherwise survive intact.
    """
    assert inbound_email.safe_filename(given) == expected


def test_attachment_rules_are_recorded_not_guessed():
    """
    Each attachment carries a verdict and a reason, and nothing is downloaded
    to reach it.
    """
    settings = configured(inbound_attachment_max_bytes=1000)
    described = inbound_email.describe_attachments(
        [
            {
                "id": "a1",
                "filename": "brief.pdf",
                "content_type": "application/pdf",
                "size": 500,
            },
            {
                "id": "a2",
                "filename": "huge.pdf",
                "content_type": "application/pdf",
                "size": 5000,
            },
            {
                "id": "a3",
                "filename": "run.exe",
                "content_type": "application/x-msdownload",
                "size": 10,
            },
            {
                "id": "a4",
                "filename": "logo.png",
                "content_type": "image/png",
                "size": 10,
                "content_disposition": "inline",
                "content_id": "<logo>",
            },
        ],
        settings,
    )
    by_id = {a["id"]: a for a in described}

    assert by_id["a1"]["downloadable"] is True
    assert by_id["a1"]["blocked_reason"] is None
    assert by_id["a2"]["downloadable"] is False
    assert by_id["a2"]["blocked_reason"] == "too large"
    # An executable is refused by ABSENCE from the allowlist, not by a
    # blocklist that has to anticipate every dangerous type.
    assert by_id["a3"]["downloadable"] is False
    assert by_id["a3"]["blocked_reason"] == "type not allowed"
    assert by_id["a4"]["inline"] is True


def test_parsing_bounds_and_sanitises_a_hostile_payload():
    """
    Every field is bounded, and markup in the body is stored as text — it is
    never rendered, so the defence is the renderer, but an unbounded body is
    still a denial of service.
    """
    settings = configured()
    parsed = inbound_email.parse_received(
        received_payload(
            subject="S" * 900,
            text="T" * 500_000,
            attachments="not-a-list",
            authentication="not-a-dict",
            to=["inbound@test.resend.app", "someone@else.example"],
        ),
        settings,
    )
    assert len(parsed.subject) <= 255
    assert len(parsed.text_body) <= 200_000
    assert parsed.attachments == []
    assert parsed.auth_results is None
    # One recipient, the first — the envelope is not a list we iterate over.
    assert parsed.to_email == "inbound@test.resend.app"


def test_html_only_message_yields_readable_text():
    """
    A message with no plain part still shows something in the timeline, with
    the tags stripped rather than rendered.
    """
    parsed = inbound_email.parse_received(
        received_payload(
            text="",
            html="<p>Hello <b>there</b></p><script>alert(1)</script>",
        ),
        configured(),
    )
    assert "Hello there" in parsed.text_body
    # The tags are gone from the derived text; the HTML is kept on the row
    # for the record but is never served to the admin UI.
    assert "<script>" not in parsed.text_body
    assert "<p>" not in parsed.text_body


def test_html_body_is_kept_despite_the_data_uri_format_flag():
    """
    `html_format` describes how INLINE IMAGES are encoded inside the markup,
    not what the body is — and the API reports `data_uri` even for a message
    with no inline images at all. Treating it as "this is not markup" would
    silently discard every HTML body.
    """
    parsed = inbound_email.parse_received(
        received_payload(html_format="data_uri", html="<p>real markup</p>"),
        configured(),
    )
    assert parsed.html_body == "<p>real markup</p>"


# ========================================================================
# 21-24. Attachments: the authenticated download path
# ========================================================================


@pytest.fixture
def with_attachment(db_session: Session, replied: ContactMessage) -> EmailMessage:
    row = EmailMessage(
        contact_message_id=replied.id,
        direction="inbound",
        from_email="priya@example.com",
        to_email="inbound@test.resend.app",
        subject="Re: Freelance enquiry",
        text_body="Brief attached.",
        resend_email_id="em_with_attachment",
        message_id=INBOUND_MID,
        delivery_status="received",
        attachments=[
            {
                "id": "att_1",
                "filename": "brief.pdf",
                "content_type": "application/pdf",
                "size": 2048,
                "inline": False,
                "downloadable": True,
                "blocked_reason": None,
            }
        ],
        auth_results={"spf": "pass", "dkim": "pass", "dmarc": "pass"},
        created_at=datetime.now(UTC),
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def test_attachment_download_requires_a_session(client, inbound_on, with_attachment):
    """Unauthenticated, it is 401 — the bytes are private mail."""
    response = client.get(
        f"/api/admin/messages/{with_attachment.contact_message_id}"
        f"/attachments/att_1"
    )
    assert response.status_code == 401


def test_attachment_is_streamed_without_exposing_the_signed_url(
    client, inbound_on, admin, with_attachment, monkeypatch
):
    """
    The bytes come back through our own endpoint, and Resend's temporary
    download URL never appears in the response.
    """
    import requests
    import resend

    signed = "https://attachments.resend.test/signed/abc?token=secret-token"

    monkeypatch.setattr(
        resend.Emails.Receiving.Attachments,
        "get",
        lambda email_id, attachment_id: {
            "id": attachment_id,
            "filename": "brief.pdf",
            "content_type": "application/pdf",
            "size": 7,
            "download_url": signed,
            "expires_at": "2026-11-09T11:00:00.000Z",
        },
    )
    monkeypatch.setattr(requests, "get", lambda url, **kw: _FakeResponse(b"%PDF-1.7"))

    sign_in(client)
    response = client.get(
        f"/api/admin/messages/{with_attachment.contact_message_id}"
        f"/attachments/att_1"
    )

    assert response.status_code == 200
    assert response.content == b"%PDF-1.7"
    assert response.headers["content-type"] == "application/pdf"
    # Never inline: nothing from an inbound email is rendered in the admin's
    # own origin, whatever its declared type.
    assert "attachment" in response.headers["content-disposition"]
    assert "brief.pdf" in response.headers["content-disposition"]
    assert response.headers["x-content-type-options"] == "nosniff"
    # The signed URL and its token are nowhere in what the browser receives.
    assert signed.encode() not in response.content
    assert "secret-token" not in str(dict(response.headers))


def test_attachment_from_another_thread_is_not_reachable(
    client, inbound_on, admin, with_attachment, db_session
):
    """
    An authenticated admin cannot walk attachment ids across conversations.

    404, not 403: the difference would confirm the id exists somewhere else.
    """
    other = ContactMessage(
        name="Someone Else",
        email="other@example.com",
        subject="Different enquiry",
        body="Unrelated.",
        created_at=datetime.now(UTC),
    )
    db_session.add(other)
    db_session.commit()
    db_session.refresh(other)

    sign_in(client)
    response = client.get(f"/api/admin/messages/{other.id}/attachments/att_1")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "attachment_not_found"


def test_oversized_attachment_is_abandoned_mid_download(monkeypatch):
    """
    The cap is enforced on the bytes that actually arrive, not on the size
    the sender declared. A response that lies about its length is dropped on
    the chunk that crosses the line.
    """
    import requests
    import resend

    monkeypatch.setattr(
        resend.Emails.Receiving.Attachments,
        "get",
        lambda email_id, attachment_id: {
            "id": attachment_id,
            "filename": "small.pdf",
            "content_type": "application/pdf",
            "size": 10,  # the claim
            "download_url": "https://attachments.resend.test/signed/x",
        },
    )
    # The reality: far more than the cap allows, behind a Content-Length that
    # claims otherwise. Both the declared size and the header are the remote
    # end's word, so only counting the bytes catches this.
    monkeypatch.setattr(
        requests,
        "get",
        lambda url, **kw: _FakeResponse(b"A" * 200_000, declared=10),
    )

    settings = configured(inbound_attachment_max_bytes=1024)
    assert inbound_email.download_attachment(settings, "em_x", "att_1") is None


def test_disallowed_attachment_type_is_refused_at_download(monkeypatch):
    """
    The allowlist is re-checked against Resend's metadata at download time,
    not trusted from the stored row — the row records what the SENDER
    claimed, and that is not what should authorise a download.
    """
    import requests
    import resend

    monkeypatch.setattr(
        resend.Emails.Receiving.Attachments,
        "get",
        lambda email_id, attachment_id: {
            "id": attachment_id,
            "filename": "payload.exe",
            "content_type": "application/x-msdownload",
            "size": 10,
            "download_url": "https://attachments.resend.test/signed/x",
        },
    )

    def explode(*args: Any, **kwargs: Any):
        raise AssertionError("a refused type must not be downloaded")

    monkeypatch.setattr(requests, "get", explode)
    assert inbound_email.download_attachment(configured(), "em_x", "att_1") is None


def test_non_https_download_url_is_refused(monkeypatch):
    """A plain-HTTP URL would put private mail on the wire in clear text."""
    import requests
    import resend

    monkeypatch.setattr(
        resend.Emails.Receiving.Attachments,
        "get",
        lambda email_id, attachment_id: {
            "id": attachment_id,
            "filename": "brief.pdf",
            "content_type": "application/pdf",
            "size": 10,
            "download_url": "http://attachments.resend.test/signed/x",
        },
    )

    def explode(*args: Any, **kwargs: Any):
        raise AssertionError("a non-https url must not be fetched")

    monkeypatch.setattr(requests, "get", explode)
    assert inbound_email.download_attachment(configured(), "em_x", "att_1") is None


# ========================================================================
# 25. The thread endpoint exposes the metadata and withholds the rest
# ========================================================================


def test_thread_exposes_metadata_but_never_html_or_urls(
    client, inbound_on, admin, with_attachment
):
    """
    The timeline gets attachment metadata and the authentication verdict, and
    does NOT get the inbound HTML — which is the reason it is never rendered.
    """
    sign_in(client)
    response = client.get(
        f"/api/admin/messages/{with_attachment.contact_message_id}/thread"
    )
    assert response.status_code == 200

    received = [m for m in response.json() if m["direction"] == "inbound"]
    assert len(received) == 1
    entry = received[0]
    assert entry["attachments"][0]["filename"] == "brief.pdf"
    assert entry["auth_results"] == {"spf": "pass", "dkim": "pass", "dmarc": "pass"}
    assert "html_body" not in entry
    assert "download_url" not in json.dumps(entry)


# ----------------------------------------------------------------- helpers --


class _FakeResponse:
    """The slice of `requests.Response` that `download_attachment` touches."""

    def __init__(self, content: bytes, declared: int | None = None):
        self._content = content
        self.headers = {
            "content-length": str(declared if declared is not None else len(content))
        }

    def __enter__(self):
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, chunk_size: int = 65_536):
        for i in range(0, len(self._content), chunk_size):
            yield self._content[i : i + chunk_size]


def test_concurrent_delivery_loses_gracefully(
    client, inbound_on, replied, stub_fetch, db_session, monkeypatch
):
    """
    When the database refuses the insert, the delivery is reported as a
    duplicate rather than a 500.

    The pre-check cannot close this race on its own — between the check and
    the insert a concurrent delivery can commit — so the partial unique
    index from 0007 is the authority. This simulates losing that race by
    making the commit raise exactly what Postgres would raise.

    Not covered by the plain duplicate test: that one never reaches the
    insert at all.
    """
    from sqlalchemy.exc import IntegrityError

    stub_fetch()
    real_commit = db_session.commit
    state = {"raised": False}

    def commit_once_then_conflict():
        if not state["raised"]:
            state["raised"] = True
            raise IntegrityError("INSERT", {}, Exception("duplicate key"))
        return real_commit()

    monkeypatch.setattr(db_session, "commit", commit_once_then_conflict)
    monkeypatch.setattr(db_session, "rollback", lambda: None)

    response = post_signed(client, event())
    assert response.status_code == 200
    assert response.json()["detail"] == "duplicate: already stored"
    # The conflict really was hit — otherwise this test proves nothing.
    assert state["raised"] is True
    # And it was absorbed rather than propagated: no stack trace, no 500,
    # and no "internal_error" body for Resend to keep retrying against.
    assert "internal_error" not in response.text


def test_download_failure_does_not_log_the_signed_url(monkeypatch, caplog):
    """
    A failed download must not write the signed URL into the log.

    `requests` puts the URL it failed on into the exception message, and that
    URL carries an access token to private mail. Logging it verbatim would
    leave a working key in the log, outliving the short expiry that made it
    safe in the first place.
    """
    import logging

    import requests
    import resend

    token = "tok-must-not-be-logged"
    url = f"https://attachments.resend.test/signed/x?token={token}"

    monkeypatch.setattr(
        resend.Emails.Receiving.Attachments,
        "get",
        lambda email_id, attachment_id: {
            "id": attachment_id,
            "filename": "brief.pdf",
            "content_type": "application/pdf",
            "size": 10,
            "download_url": url,
        },
    )

    def fail(*args: Any, **kwargs: Any):
        # The shape of a real requests failure: the URL is in the message.
        raise requests.exceptions.ConnectionError(
            f"HTTPSConnectionPool: Max retries exceeded with url: {url}"
        )

    monkeypatch.setattr(requests, "get", fail)

    with caplog.at_level(logging.WARNING, logger="app.services.inbound_email"):
        assert inbound_email.download_attachment(configured(), "em_x", "a1") is None

    logged = " ".join(record.getMessage() for record in caplog.records)
    assert "attachment download failed" in logged
    assert token not in logged
    assert "<redacted download url>" in logged
