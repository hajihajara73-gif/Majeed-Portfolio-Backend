"""
The conversation thread hanging off a contact message.

Sending a reply is two things that must not be confused: an email leaving
the building, and a row recording that it did. This module owns the join, so
`email_service` stays free of persistence and the route stays free of both.

It follows the same contract as `contact_notifier`: never raises, records the
outcome, and refuses to send twice.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.base import utcnow
from app.models.content import ContactMessage, EmailMessage
from app.services import email_service
from app.services.email_service import EmailResult

logger = logging.getLogger(__name__)

# Resend caps a subject; a long one is truncated by every client anyway.
SUBJECT_MAX = 200


def reply_subject(original: str | None) -> str:
    """
    `Re: ` the original, without stacking prefixes.

    A thread that has been round a few times should read "Re: Question",
    not "Re: Re: Re: Question". Matching case-insensitively because clients
    differ on "Re:", "RE:" and "re:".
    """
    base = (original or "").strip()
    if not base:
        return "Re: your message"
    if base[:3].lower() == "re:":
        return base[:SUBJECT_MAX]
    return f"Re: {base}"[:SUBJECT_MAX]


def thread_for(db: Session, contact_message_id: uuid.UUID) -> list[EmailMessage]:
    """Every message in one conversation, oldest first."""
    return list(
        db.scalars(
            select(EmailMessage)
            .where(EmailMessage.contact_message_id == contact_message_id)
            .order_by(EmailMessage.created_at)
        ).all()
    )


def _threading_headers(
    thread: list[EmailMessage], parent: ContactMessage
) -> tuple[str | None, str | None]:
    """
    The `In-Reply-To` and `References` for the next outbound message.

    In-Reply-To points at the most recent message that has an id. References
    accumulates the whole chain — that is what clients actually walk to group
    a thread, and dropping it is why replies sometimes appear detached.
    """
    with_ids = [m for m in thread if m.message_id]
    if not with_ids:
        return None, None

    last = with_ids[-1]
    chain: list[str] = []
    for message in with_ids:
        if message.references:
            for ref in message.references.split():
                if ref not in chain:
                    chain.append(ref)
        if message.message_id and message.message_id not in chain:
            chain.append(message.message_id)

    # Keep it bounded. Clients trim long References anyway, and the first and
    # last entries are the ones that matter for grouping.
    if len(chain) > 20:
        chain = chain[:1] + chain[-19:]
    return last.message_id, " ".join(chain)


def send_reply(
    settings: Settings,
    db: Session,
    *,
    contact_message_id: uuid.UUID | str,
    body: str,
    admin_id: uuid.UUID | None,
) -> tuple[EmailMessage | None, EmailResult]:
    """
    Send a reply to the visitor and record it on the thread.

    THE ROW IS WRITTEN FIRST, for the same reason the contact form commits
    before notifying: if Resend fails, the admin must still be able to see
    that a reply was attempted and what went wrong, rather than losing the
    text they just typed.

    Never raises. Returns the stored row and the send result; the caller
    reads `result.status` to decide what to tell the operator.
    """
    parent = db.get(ContactMessage, contact_message_id)
    if parent is None:
        return None, EmailResult(status="failed", error="message not found")

    if not settings.email_configured:
        return None, EmailResult(
            status="disabled", error="email is not configured"
        )

    thread = thread_for(db, parent.id)
    in_reply_to, references = _threading_headers(thread, parent)

    # The domain of the sending address, so the Message-ID we mint is on a
    # domain we actually control.
    sender = (settings.email_from_header or "").rsplit("@", 1)
    domain = sender[-1].rstrip(">").strip() if len(sender) == 2 else "localhost"
    message_id = email_service.new_message_id(domain)

    subject = reply_subject(parent.subject)

    row = EmailMessage(
        contact_message_id=parent.id,
        direction="outbound",
        from_email=settings.email_from_header or "",
        to_email=parent.email,
        subject=subject,
        text_body=body,
        html_body=None,
        message_id=message_id,
        in_reply_to=in_reply_to,
        references=references,
        delivery_status="pending",
        attempts=0,
        sent_by_id=admin_id,
        created_at=utcnow(),
    )
    db.add(row)
    db.flush()

    try:
        result = email_service.send_reply(
            settings,
            to_email=parent.email,
            subject=subject,
            body=body,
            original_subject=parent.subject,
            original_body=parent.body,
            visitor_name=parent.name,
            message_id=message_id,
            in_reply_to=in_reply_to,
            references=references,
        )
    except Exception as error:  # noqa: BLE001 — a send must never raise out
        logger.warning("reply send errored: %s", error)
        result = EmailResult(status="failed", error=str(error)[:400])

    row.delivery_status = result.status
    row.delivery_error = result.error
    row.attempts = 1
    if result.ok:
        row.resend_email_id = result.message_id
        row.sent_at = utcnow()
        # The parent's `replied_at` has existed unused since the table was
        # created. This is what it was for. Only the FIRST reply sets it —
        # it means "has been answered", not "answered most recently".
        if parent.replied_at is None:
            parent.replied_at = utcnow()
        parent.updated_at = utcnow()

    db.commit()
    db.refresh(row)
    return row, result


# ---------------------------------------------------------------------------
# Inbound
# ---------------------------------------------------------------------------


def _candidate_ids(in_reply_to: str | None, references: str | None) -> list[str]:
    """
    Every Message-ID an inbound email claims to be answering.

    In-Reply-To first — it names the direct parent — then the References
    chain in reverse, because the most recent ancestor is the best match.
    """
    ids: list[str] = []
    if in_reply_to:
        ids.append(in_reply_to.strip())
    if references:
        ids.extend(reversed(references.split()))
    seen: set[str] = set()
    return [i for i in ids if i and not (i in seen or seen.add(i))]


def match_conversation(
    db: Session, *, in_reply_to: str | None, references: str | None
) -> ContactMessage | None:
    """
    Find the conversation an inbound reply belongs to.

    MATCHED ON THREADING HEADERS ONLY — never on `From`, `Reply-To` or the
    subject line. Those are supplied by the sender and trivially forged; if
    a match were made on them, anyone could inject a message into any
    conversation by guessing a subject. In-Reply-To and References name
    Message-IDs that THIS system minted and stored, so a match proves the
    sender is replying to something it actually sent.

    Returns None when nothing matches. An unmatched email is not attached to
    a conversation on a guess — that is how a stranger's mail ends up in
    somebody's thread.
    """
    for candidate in _candidate_ids(in_reply_to, references):
        prior = db.scalar(
            select(EmailMessage).where(EmailMessage.message_id == candidate)
        )
        if prior is not None:
            return db.get(ContactMessage, prior.contact_message_id)
    return None


def inbound_already_stored(
    db: Session, *, resend_email_id: str, message_id: str | None
) -> bool:
    """
    Has this email already been recorded?

    Resend retries a webhook until it gets a 2xx, so the same email WILL
    arrive more than once in normal operation. Checked on two keys because
    either alone can be absent: Resend's own id, and the RFC Message-ID.

    This is a check, not a guarantee — between it and the insert, a
    concurrent delivery can slip through. The partial unique index added in
    0007 is the authority; this is the cheap path that avoids a pointless
    network fetch for the overwhelmingly common sequential retry.
    """
    if resend_email_id:
        if db.scalar(
            select(EmailMessage).where(
                EmailMessage.resend_email_id == resend_email_id,
                EmailMessage.direction == "inbound",
            )
        ):
            return True
    if message_id:
        if db.scalar(
            select(EmailMessage).where(
                EmailMessage.message_id == message_id,
                EmailMessage.direction == "inbound",
            )
        ):
            return True
    return False


def record_inbound(
    db: Session, inbound, parent: ContactMessage
) -> EmailMessage | None:
    """
    Store a received reply against its conversation.

    The parent enquiry is NOT modified beyond being marked unread again —
    a new reply should resurface the thread — and its original text is
    never touched.

    Returns None when the row already existed. Two concurrent deliveries of
    the same email both pass `inbound_already_stored` and both reach here;
    the partial unique index from 0007 lets exactly one win, and the loser
    gets None rather than an exception. A duplicate is a success — the
    message IS stored — so the caller reports it as one.
    """
    row = EmailMessage(
        contact_message_id=parent.id,
        direction="inbound",
        from_email=inbound.from_email,
        to_email=inbound.to_email,
        subject=inbound.subject,
        text_body=inbound.text_body or "(no text content)",
        html_body=inbound.html_body,
        resend_email_id=inbound.email_id,
        message_id=inbound.message_id,
        in_reply_to=inbound.in_reply_to,
        references=inbound.references,
        # Inbound mail is not "delivered by us" — it arrived. A distinct
        # word keeps the outbound vocabulary meaningful.
        delivery_status="received",
        attempts=0,
        sent_at=None,
        sent_by_id=None,
        attachments=inbound.attachments or None,
        auth_results=inbound.auth_results,
        created_at=utcnow(),
    )
    db.add(row)

    # A reply makes the conversation live again.
    parent.is_read = False
    parent.updated_at = utcnow()

    try:
        db.commit()
    except IntegrityError:
        # The other delivery got there first. Rolled back so the session is
        # usable again, and reported as the duplicate it is.
        db.rollback()
        logger.info(
            "inbound email %s was already stored by a concurrent delivery",
            inbound.email_id,
        )
        return None

    db.refresh(row)
    return row
