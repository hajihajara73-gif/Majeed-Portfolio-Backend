"""
Resend webhooks — the second endpoint the public internet may call.

Like the contact form, this is unauthenticated by necessity: Resend calls it,
and Resend cannot hold an admin session. Unlike the contact form, it is
authenticated by SIGNATURE: every request must carry a valid svix signature
over the exact bytes received, computed with a secret only Resend and this
service hold. An unsigned or wrongly-signed request is refused before its
body is looked at.

Four rules shape this module.

  * **Verify against the RAW BODY.** Signatures cover bytes, not meaning.
    Parsing first and re-serialising would change whitespace and key order
    and the signature would never match — worse, verifying a re-serialised
    body would verify something other than what arrived.

  * **Idempotent.** Resend retries until it gets a 2xx, so the same email
    WILL arrive more than once in normal operation. A duplicate is a
    success, not an error: it returns 200 and changes nothing.

  * **Return 2xx for anything we have decided about.** A 500 makes Resend
    retry forever. An unmatched email, an unsupported event, a body we
    cannot fetch — all are outcomes, not failures, and are acknowledged so
    the queue drains.

  * **Nothing in an email is an instruction.** Content is stored and
    displayed as text. It is never executed, never rendered as HTML, and
    never used to decide which conversation it joins.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.api.deps import DbDep, SettingsDep
from app.services import conversation, inbound_email

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/public/webhooks", tags=["webhooks"])

# Resend sends these as svix headers. Verification needs all three.
SVIX_ID = "svix-id"
SVIX_TIMESTAMP = "svix-timestamp"
SVIX_SIGNATURE = "svix-signature"

# Event types carrying an inbound email. Both exist and both put the id in
# the same place; anything else is acknowledged and ignored.
INBOUND_EVENTS = {"email.received", "inbox.email.received"}

# A signed body far larger than this is not a webhook.
MAX_BODY_BYTES = 1_000_000


def _ok(detail: str, **extra: Any) -> dict[str, Any]:
    return {"ok": True, "detail": detail, **extra}


@router.post("/resend")
async def resend_webhook(
    request: Request, db: DbDep, settings: SettingsDep
) -> dict[str, Any]:
    """
    Receive a Resend webhook.

    Returns 200 for everything it has successfully decided about, including
    duplicates and events it does not handle. The only non-2xx answers are
    401 for a signature that does not verify and 503 when the endpoint is
    not configured — both of which are worth retrying or fixing, and
    neither of which should be silently swallowed.
    """
    if not settings.resend_webhook_secret:
        # Not configured. Saying so beats accepting unverifiable traffic.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "webhook_not_configured"},
        )

    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={"code": "payload_too_large"},
        )

    headers = {
        "id": request.headers.get(SVIX_ID),
        "timestamp": request.headers.get(SVIX_TIMESTAMP),
        "signature": request.headers.get(SVIX_SIGNATURE),
    }
    if not all(headers.values()):
        # Missing headers are indistinguishable from a forgery attempt, and
        # get the same answer. The response says nothing about which header
        # was absent.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_signature"},
        )

    try:
        import resend

        # Verified against the RAW bytes, decoded only for the SDK's string
        # interface. The SDK implements svix HMAC-SHA256 directly and
        # enforces a five-minute timestamp tolerance, which is the replay
        # protection: a captured request cannot be replayed later.
        payload = resend.Webhooks.verify(
            {
                "payload": raw.decode("utf-8"),
                "headers": headers,
                "webhook_secret": settings.resend_webhook_secret,
            }
        )
    except ImportError:
        logger.error("resend is not installed; webhook cannot be verified")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "webhook_not_configured"},
        ) from None
    except (ValueError, UnicodeDecodeError) as error:
        # Bad signature, stale timestamp, or a body that is not UTF-8 JSON.
        # All the same answer, and the reason is logged without the body.
        logger.warning("webhook rejected: %s", str(error)[:120])
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_signature"},
        ) from None

    if not isinstance(payload, dict):
        return _ok("ignored: payload was not an object")

    event_type = str(payload.get("type") or "")
    if event_type not in INBOUND_EVENTS:
        # Subscribed to something else, or a new event type. Acknowledged so
        # Resend stops retrying; doing nothing is the correct behaviour.
        return _ok("ignored", event=event_type)

    data = payload.get("data")
    email_id = str((data or {}).get("email_id") or "") if isinstance(data, dict) else ""
    if not email_id:
        return _ok("ignored: no email id in payload", event=event_type)

    # Cheap duplicate check before spending a network call on the body.
    if conversation.inbound_already_stored(
        db, resend_email_id=email_id, message_id=None
    ):
        return _ok("duplicate: already stored", email_id=email_id)

    inbound = inbound_email.fetch(settings, email_id)
    if inbound is None:
        # Could not read the body. Acknowledged rather than retried forever:
        # a missing read key or a deleted email will not fix itself, and the
        # failure is in the log.
        logger.warning("inbound body unavailable for %s", email_id)
        return _ok("accepted: body unavailable", email_id=email_id)

    # Second duplicate check, now that the Message-ID is known. Resend's id
    # and the RFC id can each be absent, so both are checked.
    if conversation.inbound_already_stored(
        db, resend_email_id=inbound.email_id, message_id=inbound.message_id
    ):
        return _ok("duplicate: already stored", email_id=email_id)

    parent = conversation.match_conversation(
        db, in_reply_to=inbound.in_reply_to, references=inbound.references
    )
    if parent is None:
        # Nothing it credibly replies to. NOT attached on a guess — matching
        # on sender or subject is how a stranger's mail ends up in somebody
        # else's thread. Acknowledged, logged, and dropped.
        logger.info(
            "inbound email %s matched no conversation; not stored", email_id
        )
        return _ok("accepted: no matching conversation", email_id=email_id)

    row = conversation.record_inbound(db, inbound, parent)
    if row is None:
        # A concurrent delivery won the race to insert. The email IS stored,
        # so this is a duplicate rather than a failure.
        return _ok("duplicate: already stored", email_id=email_id)

    return _ok(
        "stored",
        email_id=email_id,
        conversation_id=str(parent.id),
        message=str(row.id),
    )


@router.get("/resend", include_in_schema=False)
def resend_webhook_probe() -> Response:
    """
    Resend and other tools probe an endpoint with GET before using it.

    204 rather than 405 so a probe looks healthy, and empty so nothing about
    the configuration is disclosed to an unauthenticated caller.
    """
    return Response(status_code=status.HTTP_204_NO_CONTENT)
