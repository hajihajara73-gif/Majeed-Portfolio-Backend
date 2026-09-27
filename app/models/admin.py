from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamps, UUIDPrimaryKey
from app.models.types import UtcDateTime

# JSONB in PostgreSQL (indexable, binary), plain JSON elsewhere. The variant
# exists so the test suite can run against in-memory SQLite without a database
# server — tests that need a server tend to stop being run.
JSONType = JSONB().with_variant(JSON(), "sqlite")


class AdminRole(StrEnum):
    OWNER = "owner"
    EDITOR = "editor"


class AdminUser(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "admin_users"

    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(
        String(32), default=AdminRole.OWNER, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # 2FA. `totp_secret` is set during enrolment; `totp_enabled` only flips once
    # the user has proved they can generate a valid code, so a half-finished
    # enrolment can never lock them out.
    totp_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    # A secret being enrolled, kept apart from the live one.
    #
    # Re-enrolment used to overwrite `totp_secret` directly while
    # `totp_enabled` stayed true, which silently broke the authenticator that
    # was working a moment earlier. Staging it here means an abandoned
    # enrolment changes nothing at all.
    totp_pending_secret: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    # The last TOTP time-step this account successfully used.
    #
    # RFC 6238 §5.2: a verifier must not accept the same one-time password
    # twice. Without this the code is good for its whole validity window, so
    # anyone who reads it over a shoulder or off a screen share can reuse it.
    # Storing the counter — not the code — means nothing sensitive is kept.
    totp_last_counter: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Lockout state, kept on the account so it survives an IP change.
    failed_login_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    locked_until: Mapped[datetime | None] = mapped_column(
        UtcDateTime, nullable=True
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        UtcDateTime, nullable=True
    )

    sessions: Mapped[list[AdminSession]] = relationship(
        back_populates="admin", cascade="all, delete-orphan"
    )
    recovery_codes: Mapped[list[AdminRecoveryCode]] = relationship(
        back_populates="admin", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # Declared here as well as in migration 0001 so autogenerate does not
        # see it as drift and propose dropping it. Login looks the address up
        # case-insensitively, so the index must match that expression.
        Index(
            "ix_admin_users_email_lower",
            text("lower(email)"),
            unique=True,
        ),
    )


class AdminRecoveryCode(UUIDPrimaryKey, Base):
    """Single-use 2FA fallback. Stored hashed; shown to the user only once."""

    __tablename__ = "admin_recovery_codes"

    admin_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=False
    )
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(
        UtcDateTime, nullable=True
    )

    admin: Mapped[AdminUser] = relationship(back_populates="recovery_codes")

    __table_args__ = (
        Index("ix_admin_recovery_codes_admin_id", "admin_id"),
    )


class AdminSession(UUIDPrimaryKey, Base):
    """
    A live login.

    The session token and the CSRF token are both stored hashed — a database
    leak must not yield usable credentials. Expiry is absolute rather than
    sliding, so a stolen cookie has a bounded lifetime however actively it is
    used.
    """

    __tablename__ = "admin_sessions"

    admin_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False
    )
    csrf_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        UtcDateTime, nullable=True
    )

    admin: Mapped[AdminUser] = relationship(back_populates="sessions")

    __table_args__ = (Index("ix_admin_sessions_admin_id", "admin_id"),)


class LoginAttempt(UUIDPrimaryKey, Base):
    """
    Every authentication attempt, successful or not.

    Drives per-IP rate limiting and gives a record of who tried to get in.
    """

    __tablename__ = "login_attempts"

    email: Mapped[str] = mapped_column(String(254), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    successful: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False
    )

    __table_args__ = (
        Index("ix_login_attempts_ip_created", "ip_address", "created_at"),
        Index("ix_login_attempts_email_created", "email", "created_at"),
    )


class AuditLog(UUIDPrimaryKey, Base):
    """
    Append-only record of authentication events and content mutations.

    There is deliberately no update or delete path for this table anywhere in
    the application — an audit log that the application can rewrite is not one.
    """

    __tablename__ = "audit_logs"

    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True
    )
    # Denormalised so the record survives the account being deleted.
    actor_email: Mapped[str | None] = mapped_column(String(254), nullable=True)

    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)

    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False
    )

    __table_args__ = (
        Index("ix_audit_logs_created_at", "created_at"),
        Index("ix_audit_logs_action", "action"),
    )
