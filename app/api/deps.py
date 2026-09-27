from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core import security
from app.core.config import Settings, get_settings
from app.core.db import get_db
from app.models.admin import AdminSession, AdminUser
from app.models.base import utcnow
from app.services import auth_service

SettingsDep = Annotated[Settings, Depends(get_settings)]
DbDep = Annotated[Session, Depends(get_db)]

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def get_current_session(
    request: Request, db: DbDep, settings: SettingsDep
) -> AdminSession:
    """
    Resolve and authorise the caller's session.

    This is the security boundary. Every protected route depends on it, and it
    runs server-side on every request — the admin UI hiding a control is a
    convenience, never a control.
    """
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
        )

    session = auth_service.resolve_session(db, token)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired"
        )

    # Double-submit CSRF. The cookie rides along automatically on a
    # cross-site request, but the header cannot be set by another origin
    # without CORS permission — so requiring both proves same-origin intent.
    if request.method in UNSAFE_METHODS:
        header_token = request.headers.get(settings.csrf_header_name)
        if not header_token or not security.constant_time_equals(
            security.hash_token(header_token), session.csrf_token_hash
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="CSRF check failed"
            )

    session.last_seen_at = utcnow()
    return session


SessionDep = Annotated[AdminSession, Depends(get_current_session)]


def get_current_admin(session: SessionDep, db: DbDep) -> AdminUser:
    admin = db.get(AdminUser, session.admin_id)
    if admin is None or not admin.is_active:
        # The account was disabled or deleted while the session was live.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Account unavailable"
        )
    return admin


AdminDep = Annotated[AdminUser, Depends(get_current_admin)]
