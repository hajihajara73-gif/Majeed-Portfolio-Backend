"""
Notification email for the public contact form, via Resend.

Three rules shape this module, and they are the whole design:

  * **A failed send must never lose a message.** The message is committed to
    the database before anything here is called. Everything in this file
    returns a result rather than raising, exactly like `deploy_service`: a
    Resend outage means the owner was not emailed, not that the visitor's
    message was rejected. The delivery status is recorded so the failure is
    visible and retryable rather than silent.

  * **The visitor is never the From address.** Sending as someone else's
    domain is precisely what SPF and DMARC exist to stop, and it gets mail
    classified as spoofing. The From is the verified domain; the visitor's
    address goes in Reply-To, which is what makes "reply" work in the inbox.

  * **Everything the visitor typed is escaped before it reaches HTML.** The
    message body is attacker-controlled text arriving at an unauthenticated
    endpoint. Interpolating it raw into an email template is the same
    injection bug as interpolating it into a web page.

The API key lives in the environment, is never returned by the API, and is
never written to a log.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from html import escape

from app.core.config import Settings

logger = logging.getLogger(__name__)

# Resend's own cap is 100, and a long subject line is truncated by every mail
# client anyway.
SUBJECT_MAX = 120


@dataclass
class EmailResult:
    """
    The outcome of one send attempt.

    `status` is written straight to `ContactMessage.email_delivery_status`,
    so the vocabulary is shared with the database and the admin UI.
    """

    status: str  # "sent" | "failed" | "disabled"
    message_id: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "sent"


def _clip(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _display_name(name: str) -> str:
    """
    A From display name that cannot inject a header.

    Quotes, newlines and commas are the characters that break out of a
    `Name <addr>` header, so they are removed rather than escaped — a
    display name has no legitimate need for any of them.
    """
    cleaned = "".join(ch for ch in name if ch not in '"\\\r\n,<>')
    return _clip(cleaned.strip(), 78)


def _row(label: str, value: str) -> str:
    return (
        '<tr>'
        '<td style="padding:8px 16px 8px 0;color:#6b6558;font-size:13px;'
        'white-space:nowrap;vertical-align:top">' + escape(label) + "</td>"
        '<td style="padding:8px 0;color:#1c1a16;font-size:15px">'
        + escape(value)
        + "</td></tr>"
    )


def notification_html(
    *,
    name: str,
    email: str,
    subject: str | None,
    body: str,
    received_at: datetime,
    admin_url: str | None,
) -> str:
    """
    The owner's notification.

    Table-based and inline-styled on purpose: that is what survives Gmail,
    Outlook and Apple Mail, none of which support a stylesheet reliably. The
    width caps at 600px, which is the one width every client renders without
    horizontal scrolling on a phone.

    EVERY interpolated value goes through `escape()`. `body` especially — it
    is free text from an unauthenticated form.
    """
    safe_body = escape(body).replace("\n", "<br>")
    when = received_at.strftime("%d %B %Y at %H:%M UTC")

    button = ""
    if admin_url:
        button = (
            '<tr><td style="padding:24px 0 0">'
            f'<a href="{escape(admin_url)}" '
            'style="display:inline-block;background:#8a6d1f;color:#ffffff;'
            'text-decoration:none;padding:11px 22px;border-radius:6px;'
            'font-size:14px;font-weight:600">Open in the admin</a>'
            "</td></tr>"
        )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:24px 12px;background:#f4f1ea;
 font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,
 Helvetica,Arial,sans-serif">
<table role="presentation" cellpadding="0" cellspacing="0" border="0"
 style="max-width:600px;margin:0 auto;background:#ffffff;border-radius:10px;
 border:1px solid #e3ddd1">
  <tr><td style="padding:24px 28px 8px">
    <p style="margin:0;font-size:12px;letter-spacing:.08em;text-transform:uppercase;
     color:#8a6d1f;font-weight:600">New contact message</p>
    <h1 style="margin:6px 0 0;font-size:20px;color:#1c1a16;font-weight:600">
      {escape(subject or "(no subject)")}</h1>
  </td></tr>
  <tr><td style="padding:8px 28px 0">
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">
      {_row("From", name)}
      {_row("Email", email)}
      {_row("Received", when)}
    </table>
  </td></tr>
  <tr><td style="padding:18px 28px 0">
    <div style="background:#faf8f3;border:1px solid #ece5d8;border-radius:8px;
     padding:16px;color:#1c1a16;font-size:15px;line-height:1.6">{safe_body}</div>
  </td></tr>
  <tr><td style="padding:0 28px">
    <table role="presentation" cellpadding="0" cellspacing="0"
     border="0">{button}</table>
  </td></tr>
  <tr><td style="padding:22px 28px 26px">
    <p style="margin:0;font-size:12px;color:#6b6558;line-height:1.5">
      Reply to this email to answer {escape(name)} directly — the
      Reply-To is set to their address.</p>
  </td></tr>
</table></body></html>"""


def notification_text(
    *,
    name: str,
    email: str,
    subject: str | None,
    body: str,
    received_at: datetime,
    admin_url: str | None,
) -> str:
    """
    Plain-text alternative.

    Not optional politeness: a message with no text part scores worse with
    spam filters, and this is exactly the mail that must not be filtered.
    """
    lines = [
        "New contact message",
        "",
        f"From:     {name}",
        f"Email:    {email}",
        f"Subject:  {subject or '(no subject)'}",
        f"Received: {received_at.strftime('%d %B %Y at %H:%M UTC')}",
        "",
        "-" * 48,
        body,
        "-" * 48,
        "",
        "Reply to this email to answer directly.",
    ]
    if admin_url:
        lines += ["", f"Open in the admin: {admin_url}"]
    return "\n".join(lines)


def confirmation_html(*, name: str, subject: str | None) -> str:
    """The visitor's acknowledgement. Deliberately short, and says nothing
    about when a reply will come, because that is a promise this cannot keep."""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:24px 12px;background:#f4f1ea;
 font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,
 Helvetica,Arial,sans-serif">
<table role="presentation" cellpadding="0" cellspacing="0" border="0"
 style="max-width:600px;margin:0 auto;background:#ffffff;border-radius:10px;
 border:1px solid #e3ddd1">
  <tr><td style="padding:28px">
    <h1 style="margin:0 0 12px;font-size:20px;color:#1c1a16;font-weight:600">
      Thank you for getting in touch</h1>
    <p style="margin:0 0 14px;color:#1c1a16;font-size:15px;line-height:1.6">
      Hello {escape(name)}, your message has been received successfully.
      I will get back to you soon.</p>
    <p style="margin:0;color:#6b6558;font-size:14px;line-height:1.6">
      For reference, your subject was:
      <strong style="color:#1c1a16">{escape(subject or "(no subject)")}</strong></p>
    <p style="margin:18px 0 0;color:#6b6558;font-size:12px">
      This is an automated acknowledgement — there is no need to reply to it.</p>
  </td></tr>
</table></body></html>"""


def _send(
    settings: Settings,
    *,
    to: str,
    subject: str,
    html: str,
    text: str | None = None,
    reply_to: str | None = None,
) -> EmailResult:
    """
    One Resend call. Never raises.

    The import is inside the function so the package is only needed when mail
    is actually configured — the API, its tests and a local install all run
    without it.
    """
    if not settings.email_configured:
        return EmailResult(status="disabled", error="email is not configured")

    try:
        import resend
    except ImportError:
        logger.warning("resend is not installed; contact notification skipped")
        return EmailResult(status="disabled", error="resend is not installed")

    resend.api_key = settings.resend_api_key

    params: dict[str, object] = {
        # Verbatim from configuration, with header-splitting characters
        # stripped. Resend accepts both "Name <addr>" and a bare address.
        "from": settings.email_from_header,
        "to": [to],
        "subject": _clip(subject, SUBJECT_MAX),
        "html": html,
    }
    if text:
        params["text"] = text
    if reply_to:
        params["reply_to"] = [reply_to]

    try:
        sent = resend.Emails.send(params)  # type: ignore[arg-type]
    except Exception as error:  # noqa: BLE001 — any failure is the same answer
        # str(error) only. A Resend exception can carry the request it was
        # built from, and that includes the Authorization header.
        detail = _clip(f"{type(error).__name__}: {error}", 400)
        logger.warning("contact notification failed: %s", detail)
        return EmailResult(status="failed", error=detail)

    message_id = (sent or {}).get("id") if isinstance(sent, dict) else None
    if not message_id:
        return EmailResult(
            status="failed", error="Resend returned no message id"
        )
    return EmailResult(status="sent", message_id=str(message_id))


def send_notification(
    settings: Settings,
    *,
    name: str,
    email: str,
    subject: str | None,
    body: str,
    received_at: datetime,
    message_id: str,
) -> EmailResult:
    """Tell the owner about a new message. Reply-To is the visitor."""
    admin_url = None
    if settings.admin_dashboard_url:
        admin_url = settings.admin_dashboard_url.rstrip("/") + "/messages"

    common = {
        "name": name,
        "email": email,
        "subject": subject,
        "body": body,
        "received_at": received_at,
        "admin_url": admin_url,
    }
    return _send(
        settings,
        to=settings.admin_email,  # type: ignore[arg-type]
        subject=f"New Portfolio Message - {subject or '(no subject)'}",
        html=notification_html(**common),  # type: ignore[arg-type]
        text=notification_text(**common),  # type: ignore[arg-type]
        reply_to=email,
    )


def send_confirmation(
    settings: Settings, *, name: str, email: str, subject: str | None
) -> EmailResult:
    """Acknowledge to the visitor. Off unless SEND_VISITOR_CONFIRMATION is on."""
    if not settings.send_visitor_confirmation:
        return EmailResult(status="disabled", error="confirmation is disabled")
    return _send(
        settings,
        to=email,
        subject="Thank you for contacting me",
        html=confirmation_html(name=name, subject=subject),
        text=(
            f"Hello {name},\n\n"
            "Your message has been received successfully. "
            "I will get back to you soon.\n\n"
            "This is an automated acknowledgement."
        ),
    )
