"""
Authentication logic.

Kept out of the route handlers so the rules can be read — and tested — in one
place, without HTTP plumbing in the way.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import security
from app.core.config import Settings
from app.models.admin import (
    AdminRecoveryCode,
    AdminSession,
    AdminUser,
    LoginAttempt,
)
from app.models.base import utcnow


class AuthError(Exception):
    """Authentication failed. `code` is safe to return to the client."""

    def __init__(self, code: str, message: str, *, retry_after: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retry_after = retry_after


@dataclass(frozen=True)
class IssuedSession:
    session: AdminSession
    token: str
    csrf_token: str


# --------------------------------------------------------------------------
# Rate limiting and lockout
# --------------------------------------------------------------------------


def _lockout_duration(settings: Settings, failed_count: int) -> int:
    """
    Exponential backoff, capped.

    Doubling per failure past the threshold makes sustained guessing
    impractical, while the cap stops a determined attacker from locking a real
    account out permanently just by hammering it.
    """
    over = max(0, failed_count - settings.max_failed_logins + 1)
    return min(
        settings.lockout_base_seconds * (2 ** (over - 1)),
        settings.lockout_max_seconds,
    )


def check_ip_rate_limit(db: Session, settings: Settings, ip: str | None) -> None:
    if not ip:
        return
    window_start = utcnow() - timedelta(seconds=settings.ip_rate_limit_window_seconds)
    failed = db.scalar(
        select(func.count())
        .select_from(LoginAttempt)
        .where(
            LoginAttempt.ip_address == ip,
            LoginAttempt.successful.is_(False),
            LoginAttempt.created_at >= window_start,
        )
    )
    if (failed or 0) >= settings.ip_rate_limit_max_attempts:
        raise AuthError(
            "rate_limited",
            "Too many attempts from this address. Try again later.",
            retry_after=settings.ip_rate_limit_window_seconds,
        )


def record_attempt(
    db: Session,
    *,
    email: str,
    ip: str | None,
    ua: str | None,
    successful: bool,
    reason: str | None = None,
) -> None:
    db.add(
        LoginAttempt(
            email=email[:254],
            ip_address=ip,
            user_agent=ua,
            successful=successful,
            reason=reason,
            created_at=utcnow(),
        )
    )


# --------------------------------------------------------------------------
# Password stage
# --------------------------------------------------------------------------


def authenticate_password(
    db: Session, settings: Settings, *, email: str, password: str
) -> AdminUser:
    """
    Stage one: verify the password.

    Every failure path raises the same `invalid_credentials` error, and the
    password is verified even when no account exists (against a dummy hash), so
    neither the response nor its timing reveals whether an email is registered.
    """
    admin = db.scalar(
        select(AdminUser).where(func.lower(AdminUser.email) == email.strip().lower())
    )

    now = utcnow()
    if admin and admin.locked_until and admin.locked_until > now:
        raise AuthError(
            "account_locked",
            "This account is temporarily locked.",
            retry_after=int((admin.locked_until - now).total_seconds()),
        )

    password_ok = security.verify_password(
        password, admin.password_hash if admin else None
    )

    if not admin or not password_ok:
        if admin:
            admin.failed_login_count += 1
            if admin.failed_login_count >= settings.max_failed_logins:
                admin.locked_until = now + timedelta(
                    seconds=_lockout_duration(settings, admin.failed_login_count)
                )
        raise AuthError("invalid_credentials", "Email or password is incorrect.")

    if not admin.is_active:
        # Deliberately the same error as a bad password: a disabled account
        # should not be distinguishable from a non-existent one.
        raise AuthError("invalid_credentials", "Email or password is incorrect.")

    # Transparently upgrade the hash if policy has since been strengthened.
    if security.needs_rehash(admin.password_hash):
        admin.password_hash = security.hash_password(password)

    admin.failed_login_count = 0
    admin.locked_until = None
    return admin


# --------------------------------------------------------------------------
# Second factor
# --------------------------------------------------------------------------


def check_second_factor_lockout(admin: AdminUser) -> None:
    """
    The second factor needs its own lockout.

    A correct password buys a pending token that is valid for minutes. Without
    this, that token permits unlimited guesses at a six-digit code — the
    password stage's lockout does not apply, because the password already
    succeeded.
    """
    now = utcnow()
    if admin.locked_until and admin.locked_until > now:
        raise AuthError(
            "account_locked",
            "This account is temporarily locked.",
            retry_after=int((admin.locked_until - now).total_seconds()),
        )


def register_failed_second_factor(settings: Settings, admin: AdminUser) -> None:
    """Count the failure and lock the account once the threshold is crossed."""
    admin.failed_login_count += 1
    if admin.failed_login_count >= settings.max_failed_logins:
        admin.locked_until = utcnow() + timedelta(
            seconds=_lockout_duration(settings, admin.failed_login_count)
        )


def verify_second_factor(
    db: Session, admin: AdminUser, code: str
) -> tuple[bool, bool]:
    """
    Verify a TOTP code or a recovery code.

    Returns (ok, used_recovery_code).
    """
    if not admin.totp_secret:
        return False, False

    counter = security.totp_counter(admin.totp_secret, code)
    if counter is not None:
        # Replay defence: a step that has already been used is spent, even
        # though the code itself is still inside its validity window.
        if admin.totp_last_counter is not None and counter <= admin.totp_last_counter:
            return False, False
        admin.totp_last_counter = counter
        return True, False

    # Fall back to recovery codes. Each is single-use and burned on success.
    normalised = code.strip().lower()
    code_hash = security.hash_token(normalised)
    recovery = db.scalar(
        select(AdminRecoveryCode).where(
            AdminRecoveryCode.admin_id == admin.id,
            AdminRecoveryCode.code_hash == code_hash,
            AdminRecoveryCode.used_at.is_(None),
        )
    )
    if recovery:
        recovery.used_at = utcnow()
        return True, True

    return False, False


def issue_recovery_codes(db: Session, admin: AdminUser) -> list[str]:
    """Replace any existing codes and return the new plaintext set — the only
    time these values exist outside the user's hands."""
    for existing in list(admin.recovery_codes):
        db.delete(existing)
    codes = security.generate_recovery_codes()
    for code in codes:
        db.add(
            AdminRecoveryCode(
                admin_id=admin.id, code_hash=security.hash_token(code.lower())
            )
        )
    return codes


# --------------------------------------------------------------------------
# Sessions
# --------------------------------------------------------------------------


def create_session(
    db: Session,
    settings: Settings,
    admin: AdminUser,
    *,
    ip: str | None,
    ua: str | None,
) -> IssuedSession:
    token = security.generate_token()
    csrf_token = security.generate_token(24)
    now = utcnow()

    session = AdminSession(
        admin_id=admin.id,
        token_hash=security.hash_token(token),
        csrf_token_hash=security.hash_token(csrf_token),
        ip_address=ip,
        user_agent=ua,
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(hours=settings.session_lifetime_hours),
    )
    db.add(session)
    admin.last_login_at = now
    return IssuedSession(session=session, token=token, csrf_token=csrf_token)


def resolve_session(db: Session, token: str) -> AdminSession | None:
    """Return the live session for a raw token, or None."""
    session = db.scalar(
        select(AdminSession).where(
            AdminSession.token_hash == security.hash_token(token)
        )
    )
    if session is None or session.revoked_at is not None:
        return None
    if session.expires_at <= utcnow():
        return None
    return session


def revoke_session(session: AdminSession) -> None:
    if session.revoked_at is None:
        session.revoked_at = utcnow()


def revoke_all_sessions(
    db: Session, admin_id: uuid.UUID, *, except_session_id: uuid.UUID | None = None
) -> int:
    sessions = db.scalars(
        select(AdminSession).where(
            AdminSession.admin_id == admin_id,
            AdminSession.revoked_at.is_(None),
        )
    ).all()
    count = 0
    for session in sessions:
        if except_session_id and session.id == except_session_id:
            continue
        revoke_session(session)
        count += 1
    return count
