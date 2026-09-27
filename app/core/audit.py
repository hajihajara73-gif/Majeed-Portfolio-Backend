from __future__ import annotations

import uuid
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.admin import AuditLog
from app.models.base import utcnow


class AuditAction:
    """Known audit actions, as constants rather than loose strings."""

    LOGIN_SUCCESS = "auth.login.success"
    LOGIN_FAILED = "auth.login.failed"
    LOGIN_LOCKED = "auth.login.locked"
    TWO_FACTOR_SUCCESS = "auth.2fa.success"
    TWO_FACTOR_FAILED = "auth.2fa.failed"
    RECOVERY_CODE_USED = "auth.2fa.recovery_used"
    LOGOUT = "auth.logout"
    LOGOUT_ALL = "auth.logout_all"
    SESSION_REVOKED = "auth.session.revoked"
    PASSWORD_CHANGED = "admin.password.changed"  # noqa: S105  (an action name, not a secret)
    TWO_FACTOR_ENABLED = "admin.2fa.enabled"
    TWO_FACTOR_DISABLED = "admin.2fa.disabled"


def client_ip(request: Request) -> str | None:
    """
    The client's IP, as far as it can be trusted.

    Every per-IP limit in the system rests on this, so the rule is explicit:
    `X-Forwarded-For` is believed only as far as `TRUSTED_PROXY_COUNT` says
    there are proxies in front of the app.

    The direction matters. A proxy *appends* the peer it saw, so the entries it
    added are on the RIGHT. Anything further left was supplied by the client and
    is not evidence of anything — reading the leftmost entry, as this once did,
    means a request carrying its own `X-Forwarded-For: 1.2.3.4` header gets a
    fresh rate-limit bucket on demand.

    With `TRUSTED_PROXY_COUNT=0` (the default, and correct for direct exposure)
    the header is ignored entirely and the socket peer is used.
    """
    settings = get_settings()
    hops = settings.trusted_proxy_count

    if hops > 0:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            parts = [part.strip() for part in forwarded.split(",") if part.strip()]
            # The n-th entry from the right, where n is the number of proxies we
            # trust. Clamped, so a header shorter than expected falls back to the
            # leftmost entry present rather than raising.
            if parts:
                return parts[max(0, len(parts) - hops)][:45]

    return request.client.host[:45] if request.client else None


def user_agent(request: Request) -> str | None:
    ua = request.headers.get("user-agent")
    return ua[:512] if ua else None


def record(
    db: Session,
    request: Request,
    *,
    action: str,
    actor_id: uuid.UUID | None = None,
    actor_email: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """
    Append an audit entry.

    Adds to the session but does not commit — the caller commits, so the audit
    row lands in the same transaction as the thing it describes. An audit entry
    for a change that was rolled back would be a lie.
    """
    db.add(
        AuditLog(
            actor_id=actor_id,
            actor_email=actor_email,
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=details,
            ip_address=client_ip(request),
            user_agent=user_agent(request),
            created_at=utcnow(),
        )
    )
