"""
Firing the static host's build hook after a publish.

A publish writes a snapshot to the database. Nothing on the public internet
changes until the static site is rebuilt from that snapshot, so without this
the Publish button is a half-truth: it records an intention and stops.

Two rules shape this module:

  * **A failed deploy must not fail the publish.** The snapshot is already
    committed and is the source of truth; a hook that times out means the site
    is stale, not that the publish was wrong. The outcome is reported back to
    the operator and written to the audit log instead of raised.

  * **The hook URL is a secret.** Most build hooks are bearer URLs — anyone
    holding one can trigger unlimited builds. It lives in the environment, is
    never returned by the API, and only its host appears in the audit log.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from app.core.config import Settings


@dataclass
class DeployResult:
    triggered: bool
    status_code: int | None = None
    detail: str | None = None
    host: str | None = None

    def as_details(self) -> dict[str, object]:
        """Audit-safe: host only, never the full URL with its token."""
        return {
            "triggered": self.triggered,
            "status_code": self.status_code,
            "host": self.host,
            "detail": self.detail,
        }


def hook_configured(settings: Settings) -> bool:
    return bool(settings.deploy_hook_url)


def trigger(settings: Settings, *, reason: str, snapshot_id: str) -> DeployResult:
    """
    Ask the static host to rebuild.

    Returns a result rather than raising, including when no hook is configured
    — "no hook set" is a normal state for a local install and the admin UI says
    so plainly rather than showing an error.
    """
    url = settings.deploy_hook_url
    if not url:
        return DeployResult(
            triggered=False,
            detail=(
                "No deploy hook configured; the site will rebuild on its next "
                "manual build."
            ),
        )

    host = urlparse(url).hostname

    try:
        response = httpx.post(
            url,
            # Netlify and Vercel ignore the body; it costs nothing and makes
            # the build log say which snapshot caused it.
            json={"reason": reason, "snapshot_id": snapshot_id},
            timeout=settings.deploy_hook_timeout_seconds,
            follow_redirects=True,
        )
    except httpx.HTTPError as error:
        # Includes timeouts, DNS failures and TLS errors. The publish stands.
        return DeployResult(
            triggered=False, host=host, detail=f"{type(error).__name__}: {error}"
        )

    if response.status_code >= 400:
        return DeployResult(
            triggered=False,
            status_code=response.status_code,
            host=host,
            detail=f"Build hook returned {response.status_code}.",
        )

    return DeployResult(triggered=True, status_code=response.status_code, host=host)
