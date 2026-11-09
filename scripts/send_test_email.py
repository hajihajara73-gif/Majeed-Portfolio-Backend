"""
Send a real contact notification through Resend, to check the setup.

    python scripts/send_test_email.py            # dry run: builds, sends nothing
    python scripts/send_test_email.py --send     # actually sends

SAFE BY DEFAULT. Without `--send` it renders the templates, prints where the
mail would go and exits. Nothing leaves the machine, so running the script to
see what it does cannot surprise anybody.

It writes nothing to the database. It is a check of credentials, domain
verification and deliverability only.

The API key is never printed. The script reports whether one is loaded and
shows the first and last few characters so you can tell WHICH key is in use
without the value appearing in a terminal, a screenshot or a log.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import get_settings  # noqa: E402
from app.services import email_service  # noqa: E402


def masked(secret: str | None) -> str:
    if not secret:
        return "MISSING"
    return f"{secret[:6]}…{secret[-4:]}" if len(secret) > 12 else "set"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--send",
        action="store_true",
        help="actually send; without it the script is a dry run",
    )
    parser.add_argument(
        "--to",
        default=None,
        help="override the recipient (defaults to ADMIN_EMAIL)",
    )
    args = parser.parse_args()

    settings = get_settings()

    print("Configuration")
    print(f"  RESEND_API_KEY      {masked(settings.resend_api_key)}")
    print(f"  EMAIL_FROM          {settings.email_from_header or 'MISSING'}")
    print(f"  ADMIN_EMAIL         {settings.admin_email or 'MISSING'}")
    print(f"  ADMIN_DASHBOARD_URL {settings.admin_dashboard_url or '(none)'}")
    print(f"  configured          {settings.email_configured}")

    if not settings.email_configured:
        print(
            "\nNot configured. Set RESEND_API_KEY, EMAIL_FROM and ADMIN_EMAIL "
            "in backend/.env.",
            file=sys.stderr,
        )
        return 1

    now = datetime.now(UTC)
    sample = {
        "name": "Test Visitor",
        "email": "visitor@example.com",
        "subject": "Resend configuration test",
        "body": (
            "This is a test of the portfolio contact notification.\n\n"
            "If you can read this, Resend is configured and the domain is "
            "verified.\n\n"
            "Pressing Reply should address visitor@example.com, not the "
            "sending address — that is the Reply-To header doing its job."
        ),
        "received_at": now,
    }

    html = email_service.notification_html(
        **sample,
        admin_url=(settings.admin_dashboard_url or "").rstrip("/") + "/messages"
        if settings.admin_dashboard_url
        else None,
    )
    recipient = args.to or settings.admin_email

    print("\nMessage")
    print(f"  to        {recipient}")
    print(f"  subject   New Portfolio Message - {sample['subject']}")
    print(f"  reply-to  {sample['email']}")
    print(f"  html      {len(html)} bytes")

    if not args.send:
        print("\nDry run. Nothing was sent. Re-run with --send to deliver it.")
        return 0

    print("\nSending…")
    result = email_service.send_notification(
        settings, message_id="test", **sample
    )

    if result.ok:
        print(f"  SENT. Resend id {result.message_id}")
        print(f"  Check {recipient}. It can take a minute, and the first")
        print("  message from a new domain sometimes lands in spam.")
        return 0

    print(f"  FAILED ({result.status}): {result.error}", file=sys.stderr)
    print(
        "\n  Common causes:\n"
        "    - the EMAIL_FROM domain is not verified in Resend\n"
        "    - the API key is revoked, or is for a different account\n"
        "    - the key lacks send permission",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
