"""
Operational commands.

    python -m app.cli create-admin
    python -m app.cli reset-password
    python -m app.cli list-admins
    python -m app.cli enable-2fa
    python -m app.cli disable-2fa

Run with the venv's Python from `backend`.
"""

from __future__ import annotations

import getpass
import sys

from sqlalchemy import func, select

from app.core import security
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models.admin import AdminRole, AdminUser
from app.services import auth_service


def _read_stdin_secret() -> str:
    """
    Read a secret from stdin, defensively.

    PowerShell prepends a UTF-8 BOM when it pipes a string to a native process.
    `str.strip()` does NOT remove U+FEFF, so the BOM silently becomes part of
    the password — the account is created, the hash is for a value the operator
    never typed, and every subsequent login fails with "incorrect password".
    That is a miserable thing to debug, so it is handled here once.
    """
    raw = sys.stdin.read()
    return raw.lstrip("﻿").strip()


def _prompt_password(label: str = "Password") -> str:
    """
    Read a password without echoing it, and require it twice.

    Minimum 12 characters and nothing else: length is what actually resists
    guessing, whereas composition rules mostly produce `Password1!` and a
    written-down note.
    """
    while True:
        first = getpass.getpass(f"{label}: ")
        if len(first) < 12:
            print("  Too short — use at least 12 characters.")
            continue
        second = getpass.getpass(f"{label} (again): ")
        if first != second:
            print("  They did not match.")
            continue
        return first


def create_admin() -> int:
    """
    Create an admin account.

    Interactive by default. With `--stdin` the password is read from standard
    input instead, for setup scripts — deliberately stdin rather than an
    argument, because anything in argv is visible to every other process on the
    machine via the process list.
    """
    non_interactive = "--stdin" in sys.argv

    if non_interactive:
        email_arg = next(
            (a.split("=", 1)[1] for a in sys.argv if a.startswith("--email=")), None
        )
        if not email_arg:
            print("Usage: create-admin --stdin --email=you@example.com")
            return 2
        email = email_arg.strip().lower()
        password = _read_stdin_secret()
        if len(password) < 8:
            print("Password must be at least 8 characters.")
            return 1
        if len(password) < 12:
            # Not blocked — it is the operator's account and their call. But
            # said plainly, because the interactive path would have refused it.
            print(
                "WARNING: under 12 characters. Argon2 hashing, account lockout "
                "and rate limiting all still apply, but enable 2FA."
            )
        return _persist_admin(email, password)

    email = input("Email: ").strip().lower()
    if not email or "@" not in email:
        print("That does not look like an email address.")
        return 1

    full_name = input("Full name: ").strip() or "Administrator"
    return _persist_admin(email, _prompt_password(), full_name)


def _persist_admin(
    email: str, password: str, full_name: str = "Mohammed Majeed J"
) -> int:
    with SessionLocal() as db:
        existing = db.scalar(
            select(AdminUser).where(func.lower(AdminUser.email) == email)
        )
        if existing:
            print(f"An admin with {email} already exists.")
            return 1

        db.add(
            AdminUser(
                email=email,
                # Only ever stored as an Argon2id hash. The plaintext is not
                # written anywhere, logged, or echoed back.
                password_hash=security.hash_password(password),
                full_name=full_name,
                role=AdminRole.OWNER,
                is_active=True,
            )
        )
        db.commit()

    print(f"Created {email}.")
    print("2FA is NOT enabled. Turn it on with: python -m app.cli enable-2fa")
    return 0


def reset_password() -> int:
    non_interactive = "--stdin" in sys.argv
    if non_interactive:
        email_arg = next(
            (a.split("=", 1)[1] for a in sys.argv if a.startswith("--email=")), None
        )
        if not email_arg:
            print("Usage: reset-password --stdin --email=you@example.com")
            return 2
        email = email_arg.strip().lower()
        new_password = _read_stdin_secret()
        if len(new_password) < 8:
            print("Password must be at least 8 characters.")
            return 1
    else:
        email = input("Email: ").strip().lower()
        new_password = None

    with SessionLocal() as db:
        admin = db.scalar(
            select(AdminUser).where(func.lower(AdminUser.email) == email)
        )
        if not admin:
            print("No such admin.")
            return 1

        admin.password_hash = security.hash_password(
            new_password or _prompt_password("New password")
        )
        # Clear any lockout at the same time — the usual reason for resetting.
        admin.failed_login_count = 0
        admin.locked_until = None
        # Every existing session is invalidated: a password reset that leaves
        # old sessions alive does not actually lock anyone out.
        for session in admin.sessions:
            if session.revoked_at is None:
                from app.models.base import utcnow

                session.revoked_at = utcnow()
        db.commit()

    print("Password reset. All existing sessions were signed out.")
    return 0


def list_admins() -> int:
    with SessionLocal() as db:
        admins = db.scalars(select(AdminUser).order_by(AdminUser.created_at)).all()
    if not admins:
        print("No admin accounts yet. Run: python -m app.cli create-admin")
        return 0
    for admin in admins:
        state = "active" if admin.is_active else "disabled"
        twofa = "2FA on" if admin.totp_enabled else "2FA OFF"
        print(f"{admin.email:<40} {admin.role:<8} {state:<9} {twofa}")
    return 0


def enable_2fa() -> int:
    """
    Enrol an authenticator app, from the terminal.

    This exists because 2FA has no enrolment screen in the admin UI, and telling
    an operator to "enable it in Settings" when no such setting exists is how a
    security control ends up permanently off. The flow mirrors the API exactly:
    stage a secret, prove a code against it, then promote it and mint recovery
    codes.

    The secret is printed once, to the operator's own terminal, because there is
    no other way to get it into an authenticator app. It is never logged.
    """
    settings = get_settings()
    email = input("Email: ").strip().lower()

    with SessionLocal() as db:
        admin = db.scalar(
            select(AdminUser).where(func.lower(AdminUser.email) == email)
        )
        if not admin:
            print("No such admin.")
            return 1
        if admin.totp_enabled:
            print(
                "2FA is already enabled for this account.\n"
                "To move it to a new device, run disable-2fa first — that way "
                "the working authenticator is never replaced silently."
            )
            return 1

        secret = security.generate_totp_secret()
        uri = security.totp_provisioning_uri(secret, admin.email, settings.project_name)

        print("\nAdd this to your authenticator app, then enter a code from it.")
        print("Scan the URI as a QR code, or type the secret in manually.\n")
        print(f"  secret: {secret}")
        print(f"  uri:    {uri}\n")

        for attempt in range(3):
            code = input("Code from the app: ").strip()
            if security.verify_totp(secret, code):
                break
            remaining = 2 - attempt
            print(
                f"  That code is not valid. {remaining} attempt(s) left."
                if remaining
                else "  That code is not valid."
            )
        else:
            print("\nNot enabled — nothing was changed.")
            return 1

        # Only now does it become live, exactly as the API route does it.
        admin.totp_secret = secret
        admin.totp_pending_secret = None
        admin.totp_last_counter = None
        admin.totp_enabled = True
        codes = auth_service.issue_recovery_codes(db, admin)
        db.commit()

    print("\n2FA enabled.\n")
    print("RECOVERY CODES — each works once, and this is the only time they are")
    print("shown. Store them somewhere you can reach without your phone.\n")
    for code in codes:
        print(f"  {code}")
    print()
    return 0


def disable_2fa() -> int:
    """
    Turn 2FA off, with the account password as the gate.

    Deliberately not an API route: an endpoint that removes the second factor is
    a tempting target, and this is a single-operator system with shell access to
    the machine that holds the database credential anyway.
    """
    email = input("Email: ").strip().lower()
    password = getpass.getpass("Account password: ")

    with SessionLocal() as db:
        admin = db.scalar(
            select(AdminUser).where(func.lower(AdminUser.email) == email)
        )
        if not admin or not security.verify_password(password, admin.password_hash):
            # One message for both cases, as the login endpoint does.
            print("Email or password is incorrect.")
            return 1

        admin.totp_enabled = False
        admin.totp_secret = None
        admin.totp_pending_secret = None
        admin.totp_last_counter = None
        for existing in list(admin.recovery_codes):
            db.delete(existing)
        # Sessions stay valid: this is a deliberate change by the account owner,
        # not a compromise response. Use reset-password for that.
        db.commit()

    print("2FA disabled and recovery codes destroyed.")
    print("Re-enrol with: python -m app.cli enable-2fa")
    return 0


COMMANDS = {
    "create-admin": create_admin,
    "reset-password": reset_password,
    "list-admins": list_admins,
    "enable-2fa": enable_2fa,
    "disable-2fa": disable_2fa,
}


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(f"Usage: python -m app.cli [{' | '.join(COMMANDS)}]")
        return 2
    return COMMANDS[sys.argv[1]]()


if __name__ == "__main__":
    raise SystemExit(main())
