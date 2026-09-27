from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlparse

from pydantic import Field, PostgresDsn, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Hostnames that only ever mean "this developer's machine". Any of them in a
# production origin or host allow-list is a misconfiguration, not a choice.
LOCAL_HOSTNAMES = frozenset(
    {"localhost", "127.0.0.1", "::1", "0.0.0.0"}  # noqa: S104 — a deny-list, not a bind address
)


class Settings(BaseSettings):
    """
    Application configuration, loaded from the environment.

    Nothing here has a usable default for a secret. `secret_key` has no default
    at all, so the application refuses to start rather than silently running on
    a predictable key — a default secret that reaches production is worse than
    a crash on boot, because it fails quietly.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    environment: Literal["development", "production", "test"] = "development"
    debug: bool = False

    # --- database -----------------------------------------------------------
    database_url: PostgresDsn

    # --- security -----------------------------------------------------------
    # Used to sign short-lived pending-2FA tokens. Required; no default.
    secret_key: str = Field(min_length=32)

    session_cookie_name: str = "mj_admin_session"
    csrf_cookie_name: str = "mj_admin_csrf"
    csrf_header_name: str = "X-CSRF-Token"

    # `SameSite` for the session and CSRF cookies.
    #
    # `lax` is correct and is the default. It keeps working when the admin and
    # the API share a registrable domain — `example.com` calling
    # `api.example.com` is same-SITE even though it is cross-ORIGIN, so the
    # cookie is still sent.
    #
    # `none` is required only when they are on different registrable domains,
    # e.g. an admin on `*.vercel.app` calling an API on `*.onrender.com`. It is
    # a real weakening: the browser stops enforcing any same-site restriction,
    # leaving the double-submit CSRF token as the only defence. Browsers are
    # also progressively blocking cookies in that position regardless, so a
    # shared parent domain is the configuration to aim for.
    session_cookie_samesite: Literal["lax", "strict", "none"] = "lax"

    # Sessions are absolute-expiry, not sliding, so a stolen cookie has a
    # bounded lifetime no matter how often it is used.
    session_lifetime_hours: int = 12
    # Window in which a password-verified login must complete its second factor.
    pending_2fa_lifetime_seconds: int = 300

    # --- lockout / rate limiting -------------------------------------------
    max_failed_logins: int = 5
    lockout_base_seconds: int = 60
    lockout_max_seconds: int = 3600
    # Failed attempts counted per IP within this window.
    ip_rate_limit_window_seconds: int = 300
    ip_rate_limit_max_attempts: int = 20

    # How many trusted proxies sit in front of this application.
    #
    # This decides whether `X-Forwarded-For` is believed, and which entry of it
    # is the real client. Every per-IP limit in the system depends on getting
    # this right:
    #
    #   0 (default) — direct exposure. XFF is ignored entirely and the socket
    #       peer is used, because a header a client can set is not evidence.
    #   1 — one appending proxy, which is the Render/Vercel/Cloudflare case. The
    #       client IP is the LAST entry, the one the proxy appended. The leftmost
    #       entry is whatever the client chose to send, so reading it would let
    #       anyone reset their own rate limit by adding a header.
    #
    # Left at 0 behind a proxy, every request appears to come from the proxy's
    # own address, so the contact-form limit would throttle all visitors
    # together. It must be set to 1 on Render.
    trusted_proxy_count: int = 0

    # --- storage ------------------------------------------------------------
    # Where uploaded media is written. Defaults to `backend/storage`.
    #
    # MUST point at a persistent volume in production. Render's filesystem is
    # ephemeral: every deploy and every restart starts from the image, so
    # uploads written to the default path are silently gone and the media
    # library fills with rows whose files no longer exist.
    storage_root: Path | None = None

    # Where the frontend application lives, as seen from this machine.
    #
    # The backend reaches into it for exactly two build-time jobs: reading the
    # assets that shipped with the site, and writing the content snapshot the
    # site is built from. Both are local operations — the deployed API never
    # touches it, because on Render the frontend is not there at all.
    #
    # Configurable rather than derived by counting `parents[N]`: that arithmetic
    # silently produced a path outside the repository the moment the directories
    # were reorganised, which is precisely the failure it is worth not having
    # twice.
    frontend_root: Path | None = None

    # --- app ----------------------------------------------------------------
    project_name: str = "MJ Admin API"
    api_prefix: str = "/api"
    # Browser origins allowed to call the API with credentials. A wildcard is
    # not permitted with credentialed requests, so this must be explicit.
    #
    # NoDecode is required: without it pydantic-settings tries to JSON-parse
    # any complex-typed value straight from the environment, before field
    # validators run — so a plain comma-separated string raises a JSONDecodeError
    # instead of reaching the splitter below.
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5174"]

    # Host header allow-list, enforced in production by TrustedHostMiddleware.
    # Empty in development, where the host is whatever the developer typed.
    #
    # This MUST be set for production. A Host header the application accepts
    # blindly can be reflected into absolute URLs and cache keys, and leaving it
    # hard-coded to localhost would reject every real request instead.
    allowed_hosts: Annotated[list[str], NoDecode] = []

    @field_validator("cors_origins", "allowed_hosts", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @model_validator(mode="after")
    def _cookie_policy_must_be_coherent(self) -> "Settings":
        """
        Checked in every environment, not just production.

        A browser rejects `SameSite=None` without `Secure` outright, so the
        session cookie is simply never stored — which presents as a login that
        appears to succeed and then behaves as though it never happened.
        """
        if self.session_cookie_samesite == "none" and not self.cookies_secure:
            raise ValueError(
                "SESSION_COOKIE_SAMESITE=none requires Secure cookies, which "
                "are only set when ENVIRONMENT=production. Browsers discard "
                "such a cookie, so the session would silently never persist."
            )
        return self

    @model_validator(mode="after")
    def _production_must_be_configured(self) -> "Settings":
        """
        Refuse to start a misconfigured production instance.

        Every check here is for a mistake that is silent at boot and only
        visible from a browser console, or from an audit months later. Failing
        loudly on startup is the cheapest possible place to catch them.
        """
        if self.environment != "production":
            return self

        problems: list[str] = []

        if self.debug:
            problems.append(
                "DEBUG is true. It enables SQL echo, which prints bound "
                "parameters — password hashes, session tokens and TOTP secrets "
                "— to stdout."
            )

        if not self.cors_origins:
            problems.append("CORS_ORIGINS is empty.")
        for origin in self.cors_origins:
            if origin == "*":
                problems.append(
                    "CORS_ORIGINS contains '*'. A wildcard is invalid with "
                    "credentialed requests and would expose the admin API to "
                    "any origin."
                )
                continue
            parsed = urlparse(origin)
            if parsed.scheme != "https":
                problems.append(f"CORS origin '{origin}' is not https.")
            if (parsed.hostname or "") in LOCAL_HOSTNAMES:
                problems.append(f"CORS origin '{origin}' is a localhost address.")

        if not self.allowed_hosts:
            problems.append(
                "ALLOWED_HOSTS is empty. Set it to the API's production hostname(s)."
            )
        for host in self.allowed_hosts:
            if host == "*":
                problems.append("ALLOWED_HOSTS contains '*', which disables the check.")
            if host.lstrip("*.") in LOCAL_HOSTNAMES:
                problems.append(f"ALLOWED_HOSTS entry '{host}' is a localhost address.")

        if self.trusted_proxy_count == 0:
            problems.append(
                "TRUSTED_PROXY_COUNT is 0. Behind a platform proxy every request "
                "appears to come from the proxy's own address, so all visitors "
                "share one rate-limit bucket. Set it to the number of proxies in "
                "front of the app (1 on Render)."
            )
        if self.storage_root is None:
            problems.append(
                "STORAGE_ROOT is not set. The default path is inside the "
                "application directory, which on Render is ephemeral — uploaded "
                "media would be lost on every deploy. Point it at a persistent "
                "disk."
            )

        if problems:
            raise ValueError(
                "Production configuration is not safe to start:\n  - "
                + "\n  - ".join(problems)
            )
        return self

    # --- deployment ---------------------------------------------------------
    # The static host's build hook, fired after a successful publish or
    # rollback. Optional: with no hook set, publishing still records the
    # snapshot and the site rebuilds on the next manual build.
    #
    # TREAT THIS AS A SECRET. A build hook URL is a bearer credential — anyone
    # who has it can trigger unlimited builds. It is never returned by the API.
    deploy_hook_url: str | None = None
    deploy_hook_timeout_seconds: int = 10

    # --- request limits -----------------------------------------------------
    # Hard ceiling on any request body, enforced before the body is buffered.
    # The public contact endpoint is reachable by anyone, so without this an
    # unbounded body is a free memory-exhaustion primitive — the field length
    # validators only run after the whole payload is already in memory.
    #
    # Sized above the largest legitimate upload (64 MB video) with headroom for
    # multipart framing.
    max_request_bytes: int = 72 * 1024 * 1024
    # Anything that is not a file upload has no business being large.
    max_json_bytes: int = 256 * 1024

    @property
    def cookies_secure(self) -> bool:
        """`Secure` cookies break plain-HTTP localhost, so only in production."""
        return self.environment == "production"

    @property
    def sqlalchemy_url(self) -> str:
        return str(self.database_url)

    @property
    def backend_root(self) -> Path:
        """The `backend/` directory: app/core/config.py -> core -> app -> backend."""
        return Path(__file__).resolve().parents[2]

    @property
    def resolved_storage_root(self) -> Path:
        """
        Where uploads live, as one answer for the whole application.

        This used to be derived from `__file__` in two separate modules, which
        only worked while both happened to agree. Now there is one definition,
        and it is configurable so a persistent volume can be mounted anywhere.
        """
        if self.storage_root is not None:
            return self.storage_root
        return self.backend_root / "storage"

    @property
    def resolved_frontend_root(self) -> Path:
        """
        The frontend application directory, for the two build-time jobs that
        legitimately cross the boundary: reading shipped assets, and writing the
        content snapshot.

        Defaults to a sibling of `backend/`, which is the repository layout. Set
        FRONTEND_ROOT if the two are checked out somewhere else relative to each
        other.
        """
        if self.frontend_root is not None:
            return self.frontend_root
        return self.backend_root.parent / "frontend"

    @property
    def frontend_public_root(self) -> Path:
        """`frontend/public` — assets that shipped with the site."""
        return self.resolved_frontend_root / "public"

    @property
    def snapshot_output_path(self) -> Path:
        """Where `python -m app.export` writes the published content."""
        return self.resolved_frontend_root / "src" / "content" / "snapshot.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
