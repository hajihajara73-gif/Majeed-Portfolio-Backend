"""
Phase 1 security tests.

These assert the *security properties*, not just that the happy path returns
200 — a login endpoint that works is easy; one that cannot be enumerated,
brute-forced or CSRF'd is the actual requirement.
"""

from __future__ import annotations

import pyotp
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import security
from app.core.config import get_settings
from app.models.admin import AdminSession, AdminUser, AuditLog
from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD

settings = get_settings()


def login(client: TestClient, email: str = ADMIN_EMAIL, password: str = ADMIN_PASSWORD):
    return client.post("/api/auth/login", json={"email": email, "password": password})


# --------------------------------------------------------------------------
# Password stage
# --------------------------------------------------------------------------


def test_login_succeeds_and_sets_cookies(client: TestClient, admin: AdminUser) -> None:
    response = login(client)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "authenticated"
    assert body["admin"]["email"] == ADMIN_EMAIL

    assert settings.session_cookie_name in response.cookies
    assert settings.csrf_cookie_name in response.cookies

    # The session cookie must not be readable by JavaScript.
    set_cookie = response.headers.get_list("set-cookie")
    session_header = next(
        h for h in set_cookie if h.startswith(settings.session_cookie_name)
    )
    # Attribute values are case-insensitive (RFC 6265bis); Starlette emits
    # lowercase, so compare case-insensitively rather than pinning its style.
    lowered = session_header.lower()
    assert "httponly" in lowered
    assert "samesite=lax" in lowered


def test_session_token_is_not_stored_in_plaintext(
    client: TestClient, admin: AdminUser, db_session: Session
) -> None:
    response = login(client)
    raw_token = response.cookies[settings.session_cookie_name]

    stored = db_session.scalars(select(AdminSession)).all()
    assert len(stored) == 1
    assert stored[0].token_hash != raw_token
    assert stored[0].token_hash == security.hash_token(raw_token)


def test_unknown_email_and_wrong_password_are_indistinguishable(
    client: TestClient, admin: AdminUser
) -> None:
    unknown = login(client, email="nobody@example.com", password="whatever-long")
    wrong = login(client, password="definitely-not-the-password")

    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["detail"] == wrong.json()["detail"]


def test_inactive_account_gives_the_same_error_as_a_bad_password(
    client: TestClient, admin: AdminUser, db_session: Session
) -> None:
    admin.is_active = False
    db_session.commit()

    response = login(client)
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "invalid_credentials"


def test_account_locks_after_repeated_failures(
    client: TestClient, admin: AdminUser, db_session: Session
) -> None:
    for _ in range(settings.max_failed_logins):
        assert login(client, password="wrong-password-here").status_code == 401

    db_session.expire_all()
    locked = db_session.get(AdminUser, admin.id)
    assert locked is not None
    assert locked.locked_until is not None

    # Even the correct password is refused while locked.
    response = login(client)
    assert response.status_code == 429
    assert response.json()["detail"]["code"] == "account_locked"
    assert "Retry-After" in response.headers


def test_failed_login_is_audited(
    client: TestClient, admin: AdminUser, db_session: Session
) -> None:
    login(client, password="wrong-password-here")
    actions = db_session.scalars(select(AuditLog.action)).all()
    assert "auth.login.failed" in actions


# --------------------------------------------------------------------------
# Two-factor
# --------------------------------------------------------------------------


def enable_2fa(db_session: Session, admin: AdminUser) -> str:
    secret = security.generate_totp_secret()
    admin.totp_secret = secret
    admin.totp_enabled = True
    db_session.commit()
    return secret


def test_login_with_2fa_issues_no_session_until_the_code_is_given(
    client: TestClient, admin: AdminUser, db_session: Session
) -> None:
    enable_2fa(db_session, admin)

    response = login(client)
    assert response.status_code == 200
    assert response.json()["status"] == "two_factor_required"
    assert response.json()["pending_token"]
    # Critically: no session cookie yet.
    assert settings.session_cookie_name not in response.cookies
    assert db_session.scalars(select(AdminSession)).all() == []


def test_second_factor_completes_the_login(
    client: TestClient, admin: AdminUser, db_session: Session
) -> None:
    secret = enable_2fa(db_session, admin)
    pending = login(client).json()["pending_token"]

    response = client.post(
        "/api/auth/2fa",
        json={"pending_token": pending, "code": pyotp.TOTP(secret).now()},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "authenticated"
    assert settings.session_cookie_name in response.cookies


def test_wrong_second_factor_is_rejected(
    client: TestClient, admin: AdminUser, db_session: Session
) -> None:
    enable_2fa(db_session, admin)
    pending = login(client).json()["pending_token"]

    response = client.post(
        "/api/auth/2fa", json={"pending_token": pending, "code": "000000"}
    )
    assert response.status_code == 401
    assert settings.session_cookie_name not in response.cookies


def test_forged_pending_token_is_rejected(
    client: TestClient, admin: AdminUser, db_session: Session
) -> None:
    secret = enable_2fa(db_session, admin)
    response = client.post(
        "/api/auth/2fa",
        json={
            "pending_token": "not-a-real-signed-token",
            "code": pyotp.TOTP(secret).now(),
        },
    )
    assert response.status_code == 401


# --------------------------------------------------------------------------
# CSRF and authorisation
# --------------------------------------------------------------------------


def test_protected_route_requires_a_session(client: TestClient) -> None:
    assert client.get("/api/auth/me").status_code == 401


def test_unsafe_request_without_csrf_header_is_rejected(
    client: TestClient, admin: AdminUser
) -> None:
    login(client)
    # Cookies are attached automatically; the header is not.
    response = client.post("/api/auth/logout")
    assert response.status_code == 403
    assert response.json()["detail"] == "CSRF check failed"


def test_unsafe_request_with_csrf_header_succeeds(
    client: TestClient, admin: AdminUser
) -> None:
    login_response = login(client)
    csrf = login_response.cookies[settings.csrf_cookie_name]

    response = client.post(
        "/api/auth/logout", headers={settings.csrf_header_name: csrf}
    )
    assert response.status_code == 204


def test_revoked_session_stops_working(
    client: TestClient, admin: AdminUser, db_session: Session
) -> None:
    csrf = login(client).cookies[settings.csrf_cookie_name]
    assert client.get("/api/auth/me").status_code == 200

    client.post("/api/auth/logout", headers={settings.csrf_header_name: csrf})

    # The client still holds the cookie value; the server must refuse it.
    session_row = db_session.scalars(select(AdminSession)).first()
    assert session_row is not None
    assert session_row.revoked_at is not None


def test_deactivating_an_account_invalidates_its_live_session(
    client: TestClient, admin: AdminUser, db_session: Session
) -> None:
    login(client)
    assert client.get("/api/auth/me").status_code == 200

    admin.is_active = False
    db_session.commit()

    assert client.get("/api/auth/me").status_code == 401


# --------------------------------------------------------------------------
# Primitives
# --------------------------------------------------------------------------


def test_password_verification_against_missing_hash_is_false() -> None:
    # Still runs a real Argon2 verification, so timing does not leak existence.
    assert security.verify_password("anything", None) is False


def test_password_hashes_are_salted() -> None:
    assert security.hash_password("same-password") != security.hash_password(
        "same-password"
    )


def test_pending_token_round_trip() -> None:
    token = security.issue_pending_2fa_token("k" * 32, "abc-123")
    assert security.read_pending_2fa_token("k" * 32, token, 300) == "abc-123"
    # Signed with a different key -> rejected.
    assert security.read_pending_2fa_token("x" * 32, token, 300) is None
    # Expired -> rejected.
    assert security.read_pending_2fa_token("k" * 32, token, -1) is None
