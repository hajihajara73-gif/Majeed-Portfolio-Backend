from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.api.deps import AdminDep, DbDep, SessionDep, SettingsDep
from app.core import audit, security
from app.core.audit import AuditAction
from app.core.config import Settings
from app.models.admin import AdminSession, AdminUser
from app.schemas.auth import (
    AdminProfile,
    LoginRequest,
    LoginResponse,
    PasswordChangeRequest,
    RecoveryCodesResponse,
    SessionSummary,
    TwoFactorEnableRequest,
    TwoFactorRequest,
    TwoFactorSetupRequest,
    TwoFactorSetupResponse,
)
from app.services import auth_service
from app.services.auth_service import AuthError, IssuedSession

router = APIRouter(prefix="/auth", tags=["auth"])


def _profile(admin: AdminUser) -> AdminProfile:
    return AdminProfile(
        id=str(admin.id),
        email=admin.email,
        full_name=admin.full_name,
        role=admin.role,
        totp_enabled=admin.totp_enabled,
        last_login_at=admin.last_login_at,
    )


def _set_session_cookies(
    response: Response, settings: Settings, issued: IssuedSession
) -> None:
    max_age = settings.session_lifetime_hours * 3600

    # HttpOnly: unreadable from JavaScript, so an XSS flaw cannot exfiltrate it.
    response.set_cookie(
        settings.session_cookie_name,
        issued.token,
        max_age=max_age,
        httponly=True,
        secure=settings.cookies_secure,
        # `lax` unless configured otherwise. See `Settings.session_cookie_samesite`
        # — `none` is needed only when the admin and the API sit on different
        # registrable domains, and it is a genuine weakening.
        samesite=settings.session_cookie_samesite,
        path="/",
    )
    # The CSRF token is deliberately readable — the client must echo it in a
    # header, which is precisely what a cross-site page cannot do.
    response.set_cookie(
        settings.csrf_cookie_name,
        issued.csrf_token,
        max_age=max_age,
        httponly=False,
        secure=settings.cookies_secure,
        samesite=settings.session_cookie_samesite,
        path="/",
    )


def _clear_session_cookies(response: Response, settings: Settings) -> None:
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.delete_cookie(settings.csrf_cookie_name, path="/")


def _auth_error(error: AuthError) -> HTTPException:
    status_code = (
        status.HTTP_429_TOO_MANY_REQUESTS
        if error.code in {"rate_limited", "account_locked"}
        else status.HTTP_401_UNAUTHORIZED
    )
    headers = (
        {"Retry-After": str(error.retry_after)} if error.retry_after else None
    )
    return HTTPException(
        status_code=status_code,
        detail={"code": error.code, "message": error.message},
        headers=headers,
    )


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: DbDep,
    settings: SettingsDep,
) -> LoginResponse:
    ip = audit.client_ip(request)
    ua = audit.user_agent(request)

    try:
        auth_service.check_ip_rate_limit(db, settings, ip)
        admin = auth_service.authenticate_password(
            db, settings, email=payload.email, password=payload.password
        )
    except AuthError as error:
        auth_service.record_attempt(
            db,
            email=payload.email,
            ip=ip,
            ua=ua,
            successful=False,
            reason=error.code,
        )
        audit.record(
            db,
            request,
            action=(
                AuditAction.LOGIN_LOCKED
                if error.code == "account_locked"
                else AuditAction.LOGIN_FAILED
            ),
            actor_email=payload.email,
            details={"code": error.code},
        )
        # Commit so the failed attempt and lockout state persist — otherwise
        # rate limiting could be defeated simply by failing repeatedly.
        db.commit()
        raise _auth_error(error) from error

    if admin.totp_enabled:
        # Stop here. No session exists until the second factor succeeds.
        pending = security.issue_pending_2fa_token(
            settings.secret_key, str(admin.id)
        )
        db.commit()
        return LoginResponse(status="two_factor_required", pending_token=pending)

    issued = auth_service.create_session(db, settings, admin, ip=ip, ua=ua)
    auth_service.record_attempt(
        db, email=admin.email, ip=ip, ua=ua, successful=True
    )
    audit.record(
        db,
        request,
        action=AuditAction.LOGIN_SUCCESS,
        actor_id=admin.id,
        actor_email=admin.email,
    )
    db.commit()

    _set_session_cookies(response, settings, issued)
    return LoginResponse(status="authenticated", admin=_profile(admin))


@router.post("/2fa", response_model=LoginResponse)
def complete_two_factor(
    payload: TwoFactorRequest,
    request: Request,
    response: Response,
    db: DbDep,
    settings: SettingsDep,
) -> LoginResponse:
    ip = audit.client_ip(request)
    ua = audit.user_agent(request)

    admin_id = security.read_pending_2fa_token(
        settings.secret_key,
        payload.pending_token,
        settings.pending_2fa_lifetime_seconds,
    )
    if not admin_id:
        raise _auth_error(
            AuthError("invalid_pending_token", "Sign in again to continue.")
        )

    # The token carries the id as a string; the primary key is a real UUID
    # column. Parse explicitly — a malformed value here is an invalid token,
    # not a 500.
    try:
        admin_uuid = uuid.UUID(admin_id)
    except ValueError:
        raise _auth_error(
            AuthError("invalid_pending_token", "Sign in again to continue.")
        ) from None

    admin = db.get(AdminUser, admin_uuid)
    if admin is None or not admin.is_active:
        raise _auth_error(
            AuthError("invalid_pending_token", "Sign in again to continue.")
        )

    # The second factor needs its own limits. The password stage's lockout does
    # not protect this endpoint — the password already succeeded — so without
    # these a pending token is a licence to brute-force six digits.
    try:
        auth_service.check_ip_rate_limit(db, settings, ip)
        auth_service.check_second_factor_lockout(admin)
    except AuthError as error:
        auth_service.record_attempt(
            db, email=admin.email, ip=ip, ua=ua, successful=False, reason=error.code
        )
        db.commit()
        raise _auth_error(error) from error

    ok, used_recovery = auth_service.verify_second_factor(db, admin, payload.code)
    if not ok:
        auth_service.register_failed_second_factor(settings, admin)
        auth_service.record_attempt(
            db,
            email=admin.email,
            ip=ip,
            ua=ua,
            successful=False,
            reason="invalid_2fa",
        )
        audit.record(
            db,
            request,
            action=AuditAction.TWO_FACTOR_FAILED,
            actor_id=admin.id,
            actor_email=admin.email,
        )
        db.commit()
        raise _auth_error(
            AuthError("invalid_code", "That code is not valid.")
        )

    admin.failed_login_count = 0
    admin.locked_until = None
    issued = auth_service.create_session(db, settings, admin, ip=ip, ua=ua)
    auth_service.record_attempt(
        db, email=admin.email, ip=ip, ua=ua, successful=True
    )
    audit.record(
        db,
        request,
        action=(
            AuditAction.RECOVERY_CODE_USED
            if used_recovery
            else AuditAction.TWO_FACTOR_SUCCESS
        ),
        actor_id=admin.id,
        actor_email=admin.email,
    )
    db.commit()

    _set_session_cookies(response, settings, issued)
    return LoginResponse(status="authenticated", admin=_profile(admin))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    db: DbDep,
    settings: SettingsDep,
    session: SessionDep,
    admin: AdminDep,
) -> Response:
    auth_service.revoke_session(session)
    audit.record(
        db,
        request,
        action=AuditAction.LOGOUT,
        actor_id=admin.id,
        actor_email=admin.email,
    )
    db.commit()
    _clear_session_cookies(response, settings)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=AdminProfile)
def me(admin: AdminDep) -> AdminProfile:
    return _profile(admin)


@router.get("/sessions", response_model=list[SessionSummary])
def list_sessions(
    db: DbDep, admin: AdminDep, session: SessionDep
) -> list[SessionSummary]:
    from sqlalchemy import select

    from app.models.base import utcnow

    rows = db.scalars(
        select(AdminSession)
        .where(
            AdminSession.admin_id == admin.id,
            AdminSession.revoked_at.is_(None),
            AdminSession.expires_at > utcnow(),
        )
        .order_by(AdminSession.last_seen_at.desc())
    ).all()

    return [
        SessionSummary(
            id=str(row.id),
            ip_address=row.ip_address,
            user_agent=row.user_agent,
            created_at=row.created_at,
            last_seen_at=row.last_seen_at,
            expires_at=row.expires_at,
            current=row.id == session.id,
        )
        for row in rows
    ]


@router.post("/sessions/revoke-others", status_code=status.HTTP_200_OK)
def revoke_other_sessions(
    request: Request, db: DbDep, admin: AdminDep, session: SessionDep
) -> dict[str, int]:
    revoked = auth_service.revoke_all_sessions(
        db, admin.id, except_session_id=session.id
    )
    audit.record(
        db,
        request,
        action=AuditAction.LOGOUT_ALL,
        actor_id=admin.id,
        actor_email=admin.email,
        details={"revoked": revoked},
    )
    db.commit()
    return {"revoked": revoked}


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: PasswordChangeRequest,
    request: Request,
    response: Response,
    db: DbDep,
    admin: AdminDep,
    session: SessionDep,
) -> Response:
    if not security.verify_password(payload.current_password, admin.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "invalid_password",
                "message": "Current password is incorrect.",
            },
        )

    admin.password_hash = security.hash_password(payload.new_password)
    # A password change invalidates every other session — that is the whole
    # point of changing it when you suspect compromise.
    auth_service.revoke_all_sessions(db, admin.id, except_session_id=session.id)
    audit.record(
        db,
        request,
        action=AuditAction.PASSWORD_CHANGED,
        actor_id=admin.id,
        actor_email=admin.email,
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/2fa/setup", response_model=TwoFactorSetupResponse)
def begin_two_factor_setup(
    payload: TwoFactorSetupRequest,
    db: DbDep,
    settings: SettingsDep,
    admin: AdminDep,
) -> TwoFactorSetupResponse:
    """
    Start enrolment.

    The new secret is staged in `totp_pending_secret` and becomes live only once
    a valid code proves the authenticator works. An abandoned enrolment
    therefore changes nothing — the account keeps exactly what it had.

    Re-enrolling while 2FA is already on additionally requires the current
    password. Without that, a hijacked session could quietly move the second
    factor to the attacker's own device, which defeats the point of having one.
    """
    if admin.totp_enabled:
        if not payload.current_password or not security.verify_password(
            payload.current_password, admin.password_hash
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "password_required",
                    "message": (
                        "Enter your current password to move two-factor "
                        "authentication to a new device."
                    ),
                },
            )

    secret = security.generate_totp_secret()
    admin.totp_pending_secret = secret
    db.commit()
    return TwoFactorSetupResponse(
        secret=secret,
        provisioning_uri=security.totp_provisioning_uri(
            secret, admin.email, settings.project_name
        ),
    )


@router.post("/2fa/enable", response_model=RecoveryCodesResponse)
def enable_two_factor(
    payload: TwoFactorEnableRequest,
    request: Request,
    db: DbDep,
    admin: AdminDep,
) -> RecoveryCodesResponse:
    pending = admin.totp_pending_secret
    if not pending:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "not_started", "message": "Start 2FA setup first."},
        )
    if not security.verify_totp(pending, payload.code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_code", "message": "That code is not valid."},
        )

    # Promote the staged secret now that the authenticator has proved itself.
    # The replay counter resets with it — steps from the old secret say nothing
    # about the new one — and so do the recovery codes.
    admin.totp_secret = pending
    admin.totp_pending_secret = None
    admin.totp_last_counter = None
    admin.totp_enabled = True
    codes = auth_service.issue_recovery_codes(db, admin)
    audit.record(
        db,
        request,
        action=AuditAction.TWO_FACTOR_ENABLED,
        actor_id=admin.id,
        actor_email=admin.email,
    )
    db.commit()
    # The only time these are ever visible.
    return RecoveryCodesResponse(codes=codes)
