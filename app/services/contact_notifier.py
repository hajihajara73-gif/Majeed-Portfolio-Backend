"""
Deliver the notification for a saved contact message, and record what happened.

This is the only place that joins the database to the email service, which
keeps `email_service` free of persistence and this file free of HTML.

It is called in two situations and behaves identically in both:

  * from the public endpoint, as a background task, AFTER the message has
    been committed;
  * from the admin, to retry a notification that failed.

Both open their own session. A background task runs after the response has
been returned, so the request's session is already closed by then.

DUPLICATE PROTECTION. `notify` refuses to send when `resend_email_id` is
already set. Resend has accepted that message once; a second send would put
a second copy in the inbox, and the likeliest trigger is an impatient second
click on Retry.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.db import SessionLocal
from app.models.base import utcnow
from app.models.content import ContactMessage
from app.services import email_service
from app.services.email_service import EmailResult

logger = logging.getLogger(__name__)


def notify(
    settings: Settings, message_id: uuid.UUID | str, *, db: Session | None = None
) -> EmailResult:
    """
    Send the owner's notification for one message and record the outcome.

    Never raises. The message is already safely stored by the time this runs;
    nothing that happens here may undo that, so every failure path ends in a
    recorded status rather than an exception.
    """
    owned = db is None
    session = db or SessionLocal()
    try:
        row = session.get(ContactMessage, _as_uuid(message_id))
        if row is None:
            return EmailResult(status="failed", error="message not found")

        if row.resend_email_id:
            # Already delivered. Saying "sent" is accurate: the notification
            # for this message exists, which is what the caller asked for.
            return EmailResult(status="sent", message_id=row.resend_email_id)

        result = email_service.send_notification(
            settings,
            name=row.name,
            email=row.email,
            subject=row.subject,
            body=row.body,
            received_at=row.created_at,
            message_id=str(row.id),
        )

        row.email_delivery_status = result.status
        row.email_error = result.error
        row.email_attempts = (row.email_attempts or 0) + 1
        row.updated_at = utcnow()
        if result.ok:
            row.resend_email_id = result.message_id
            row.email_sent_at = utcnow()
        session.commit()

        # The visitor's acknowledgement is deliberately not recorded on the
        # message and never affects its status: it is a courtesy, and failing
        # to send it is not a failure to notify the owner.
        if result.ok and settings.send_visitor_confirmation:
            email_service.send_confirmation(
                settings, name=row.name, email=row.email, subject=row.subject
            )

        return result
    except Exception as error:  # noqa: BLE001
        # A background task has nobody to raise to, and an unhandled
        # exception here would be invisible. Record and move on.
        logger.warning("contact notification errored: %s", error)
        try:
            session.rollback()
        except Exception:  # noqa: BLE001
            # A rollback that itself fails means the connection is gone.
            # Nothing can be done about it here, but it must not be silent.
            logger.exception("rollback failed after a notification error")
        return EmailResult(status="failed", error=str(error)[:400])
    finally:
        if owned:
            session.close()


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID | str:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError):
        return value
