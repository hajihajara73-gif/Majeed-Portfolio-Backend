"""
Phase 8 tests: the things that only break once the app is behind a platform.

Local development hides all of this. There is no proxy in front, the filesystem
persists, and the browser treats everything as same-origin — so every one of
these behaviours is untested until it is wrong in production.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.core.config import Settings, get_settings
from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD

settings = get_settings()


def production_settings(**overrides) -> Settings:
    base = {
        "environment": "production",
        "database_url": "postgresql+psycopg://u:p@h/db",
        "secret_key": "x" * 40,
        "cors_origins": "https://portfolio.invalid",
        "allowed_hosts": "api.portfolio.invalid",
        "trusted_proxy_count": 1,
        "storage_root": "/var/data/storage",
    }
    return Settings(**{**base, **overrides})


# ------------------------------------------------- forwarded client address --


def ip_for(headers: dict[str, str], *, hops: int) -> str | None:
    """Resolve the client IP the way a request behind `hops` proxies would."""
    from starlette.requests import Request

    from app.core import audit

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": ("10.0.0.1", 1234),
    }
    original = get_settings().trusted_proxy_count
    object.__setattr__(get_settings(), "trusted_proxy_count", hops)
    try:
        return audit.client_ip(Request(scope))
    finally:
        object.__setattr__(get_settings(), "trusted_proxy_count", original)


def test_forwarded_header_is_ignored_when_no_proxy_is_trusted() -> None:
    """The default. A header a client can set is not evidence of anything."""
    assert ip_for({"x-forwarded-for": "9.9.9.9"}, hops=0) == "10.0.0.1"


def test_one_trusted_proxy_uses_the_address_the_proxy_appended() -> None:
    """
    Render appends the peer it saw, so the trustworthy entry is on the RIGHT.

    `203.0.113.7` is the real client here; `9.9.9.9` is what the client put in
    the header itself, hoping to be believed.
    """
    assert (
        ip_for({"x-forwarded-for": "9.9.9.9, 203.0.113.7"}, hops=1) == "203.0.113.7"
    )


def test_a_client_cannot_mint_itself_a_fresh_rate_limit_bucket() -> None:
    """
    The bug this replaced: reading the leftmost entry meant anyone could reset
    their own per-IP limit by adding a header.
    """
    spoofed = [
        "1.1.1.1, 203.0.113.7",
        "2.2.2.2, 203.0.113.7",
        "3.3.3.3, 4.4.4.4, 203.0.113.7",
    ]
    resolved = {ip_for({"x-forwarded-for": value}, hops=1) for value in spoofed}
    assert resolved == {"203.0.113.7"}, (
        "different spoofed prefixes produced different buckets: " f"{resolved}"
    )


def test_missing_forwarded_header_falls_back_to_the_socket_peer() -> None:
    assert ip_for({}, hops=1) == "10.0.0.1"


def test_short_forwarded_header_does_not_raise() -> None:
    """Fewer entries than expected is a misconfiguration, not a crash."""
    assert ip_for({"x-forwarded-for": "203.0.113.7"}, hops=2) == "203.0.113.7"


# --------------------------------------------------------- production config --


def test_production_requires_a_trusted_proxy_count() -> None:
    """
    Left at 0 behind Render, every request carries the proxy's address and all
    visitors share one rate-limit bucket.
    """
    with pytest.raises(ValueError, match="TRUSTED_PROXY_COUNT"):
        production_settings(trusted_proxy_count=0)


def test_production_requires_a_persistent_storage_root() -> None:
    """The default path is inside the app directory, which Render wipes."""
    with pytest.raises(ValueError, match="STORAGE_ROOT"):
        production_settings(storage_root=None)


def test_samesite_none_without_secure_is_refused() -> None:
    """Browsers drop such a cookie outright, which looks like a broken login."""
    with pytest.raises(ValueError, match="SESSION_COOKIE_SAMESITE"):
        Settings(
            environment="development",
            database_url="postgresql+psycopg://u:p@h/db",
            secret_key="x" * 40,
            session_cookie_samesite="none",
        )


def test_production_accepts_a_full_deployment_configuration() -> None:
    configured = production_settings(
        cors_origins="https://portfolio.invalid,https://www.portfolio.invalid",
        allowed_hosts="api.portfolio.invalid",
        session_cookie_samesite="lax",
    )
    assert configured.cookies_secure is True
    assert configured.trusted_proxy_count == 1
    assert str(configured.resolved_storage_root) in (
        "/var/data/storage",
        "\\var\\data\\storage",
    )


def test_paths_default_to_the_repository_layout() -> None:
    """
    Development keeps working with no configuration at all, and the defaults
    describe a frontend checked out beside the backend.

    Deliberately asserts RELATIONSHIPS, not directory names. An earlier version
    checked `backend_root.name == "backend"` and failed in every checkout that
    was not called exactly that — which is every clone from GitHub, where the
    directory takes the repository's name.
    """
    import app.core.config as config_module

    development = Settings(
        environment="development",
        database_url="postgresql+psycopg://u:p@h/db",
        secret_key="x" * 40,
    )

    # The backend root is whatever directory contains the `app` package.
    assert (development.backend_root / "app" / "core" / "config.py").is_file()
    assert development.backend_root == Path(config_module.__file__).resolve().parents[2]

    assert development.resolved_storage_root == development.backend_root / "storage"

    frontend = development.resolved_frontend_root
    # `frontend` IS a fixed default name in the code, unlike the backend's own
    # directory, so this one is fair to assert.
    assert frontend.name == "frontend"
    assert frontend.parent == development.backend_root.parent
    assert development.frontend_public_root == frontend / "public"
    assert (
        development.snapshot_output_path
        == frontend / "src" / "content" / "snapshot.json"
    )


def test_frontend_root_is_overridable() -> None:
    """So the two applications need not sit in any particular relative position."""
    configured = Settings(
        environment="development",
        database_url="postgresql+psycopg://u:p@h/db",
        secret_key="x" * 40,
        frontend_root="/srv/site",
    )
    assert configured.frontend_public_root.as_posix().endswith("srv/site/public")
    assert configured.snapshot_output_path.as_posix().endswith(
        "srv/site/src/content/snapshot.json"
    )


def test_storage_root_has_one_definition() -> None:
    """
    It used to be derived from `__file__` in two modules, which only worked
    while both agreed and made a persistent volume impossible.
    """
    from app.api.admin import files, media

    assert media.STORAGE_ROOT is files.STORAGE_ROOT


# ------------------------------------------------------------ trusted hosts --


def test_host_header_allow_list_rejects_an_unknown_host() -> None:
    """
    Exercised against a real middleware stack rather than asserted from config,
    because this is the check that took the API down in Phase 7.
    """
    from fastapi import FastAPI

    app = FastAPI()
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["api.portfolio.invalid"]
    )

    @app.get("/probe")
    def probe() -> dict[str, bool]:
        return {"ok": True}

    client = TestClient(app, base_url="https://api.portfolio.invalid")
    assert client.get("/probe").status_code == 200

    attacker = TestClient(app, base_url="https://evil.invalid")
    assert attacker.get("/probe").status_code == 400


# ------------------------------------------------------------------- CORS ---


def test_preflight_from_an_allowed_origin_permits_credentials(
    client: TestClient,
) -> None:
    """
    The admin's requests are credentialed and cross-origin in production, so a
    preflight that omits `allow-credentials` breaks every admin action.
    """
    origin = settings.cors_origins[0]
    response = client.options(
        "/api/admin/projects",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "content-type,x-csrf-token",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert response.headers["access-control-allow-credentials"] == "true"
    allowed = response.headers["access-control-allow-headers"].lower()
    assert "x-csrf-token" in allowed
    assert "content-type" in allowed


def test_preflight_from_an_unknown_origin_is_not_allowed(
    client: TestClient,
) -> None:
    response = client.options(
        "/api/admin/projects",
        headers={
            "Origin": "https://evil.invalid",
            "Access-Control-Request-Method": "PUT",
        },
    )
    assert "access-control-allow-origin" not in response.headers


def test_no_wildcard_origin_is_ever_returned(client: TestClient) -> None:
    response = client.get(
        "/api/health", headers={"Origin": settings.cors_origins[0]}
    )
    assert response.headers.get("access-control-allow-origin") != "*"


# ------------------------------------------------------------ health check --


def test_root_greets_without_volunteering_anything(client: TestClient) -> None:
    """
    `/` returns a greeting rather than a bare 404, so opening the service in a
    browser does not look broken.

    It must stay a fixed string. Anyone can reach this, so a version number, an
    environment name or a pointer to the docs would be free reconnaissance.
    """
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Welcome to Majeed Portfolio Backend"}

    body = response.text.lower()
    for leak in ("version", "environment", "/docs", "openapi", "python", "fastapi"):
        assert leak not in body


def test_root_is_outside_the_api_prefix(client: TestClient) -> None:
    """The greeting is at `/`, and must not shadow or duplicate under `/api`."""
    from app.main import app

    paths = list(app.openapi()["paths"])
    assert "/" in paths
    assert "/api/" not in paths
    assert "/api" not in paths


def test_health_is_unauthenticated_and_says_nothing_useful_to_an_attacker(
    client: TestClient,
) -> None:
    """Render polls this. It must be reachable, and it must be boring."""
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    body = response.text
    for leak in ("postgres", "psycopg", "Traceback", "/app/", "\\backend\\"):
        assert leak not in body
    # No environment or version detail either.
    assert set(response.json().keys()) == {"status"}


def test_only_one_health_endpoint_exists() -> None:
    """
    Guard against a duplicate being added for a platform's convenience.

    Read from the OpenAPI schema rather than `app.router.routes`: this FastAPI
    version keeps included routers nested instead of flattening them, so walking
    the route list silently finds nothing.
    """
    from app.main import app

    paths = [path for path in app.openapi()["paths"] if "health" in path]
    assert paths == ["/api/health"], paths


# --------------------------------------------------- cookies in production --


def test_session_cookie_samesite_is_configurable_end_to_end(
    client: TestClient, admin, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "session_cookie_samesite", "none")
    response = client.post(
        "/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    )
    assert response.status_code == 200
    raw = "; ".join(response.headers.get_list("set-cookie")).lower()
    assert "samesite=none" in raw
