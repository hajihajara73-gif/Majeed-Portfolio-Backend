"""
The only endpoint the public internet may call.

Everything else in this API is behind an admin session. This one is
deliberately unauthenticated, which means it is also the one endpoint that has
to survive being found by a bot, so the abuse controls are the point of the
module rather than an afterthought.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import func, select

from app.api.deps import DbDep, SettingsDep
from app.core import audit
from app.models.base import utcnow
from app.models.content import ContactMessage

router = APIRouter(prefix="/public", tags=["public"])

# Per-IP ceiling. Generous for a person, useless for a bot.
MAX_PER_HOUR = 5
MAX_PER_DAY = 20


class ContactRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    subject: str | None = Field(default=None, max_length=255)
    message: str = Field(min_length=10, max_length=5000)

    # Honeypot. A real form keeps this hidden and empty; most naive bots fill
    # every field they find. Named plausibly so it is not obviously a trap.
    website: str | None = Field(default=None, max_length=255)

    @field_validator("name", "subject", "message")
    @classmethod
    def _no_control_chars(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.replace("\r\n", "\n")
        # Strip control characters other than newline and tab — they have no
        # place in a message and are a classic header-injection vector.
        return "".join(
            ch for ch in cleaned if ch in "\n\t" or ord(ch) >= 32
        ).strip()


class ContactResponse(BaseModel):
    received: bool
    message: str


def _count_since(db, ip: str | None, since) -> int:
    if not ip:
        return 0
    return (
        db.scalar(
            select(func.count())
            .select_from(ContactMessage)
            .where(
                ContactMessage.ip_address == ip,
                ContactMessage.created_at >= since,
            )
        )
        or 0
    )


@router.post("/contact", response_model=ContactResponse)
def submit_contact(
    payload: ContactRequest,
    request: Request,
    db: DbDep,
    settings: SettingsDep,
) -> ContactResponse:
    ip = audit.client_ip(request)
    now = utcnow()

    # Honeypot tripped. Return the same success the sender would see, so a bot
    # learns nothing and does not retry with the field removed. Nothing is
    # stored.
    if payload.website:
        return ContactResponse(
            received=True, message="Thanks — your message has been sent."
        )

    if _count_since(db, ip, now - timedelta(hours=1)) >= MAX_PER_HOUR or _count_since(
        db, ip, now - timedelta(days=1)
    ) >= MAX_PER_DAY:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "rate_limited",
                "message": "Too many messages from this address. Try again later.",
            },
            headers={"Retry-After": "3600"},
        )

    db.add(
        ContactMessage(
            name=payload.name,
            email=str(payload.email),
            subject=payload.subject,
            body=payload.message,
            ip_address=ip,
            user_agent=audit.user_agent(request),
            created_at=now,
        )
    )
    # Not written to the audit log: that log is for admin actions, and filling
    # it from an unauthenticated endpoint would let anyone flood it.
    db.commit()

    return ContactResponse(
        received=True, message="Thanks — your message has been sent."
    )
