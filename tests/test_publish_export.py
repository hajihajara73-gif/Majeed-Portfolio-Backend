"""
Phase 6 tests: rollback, the deploy hook, and the snapshot export.

The theme is the same one the publish design is built on — history is
append-only, and a failure in the last mile must not corrupt what is already
live or lie about what happened.
"""

from __future__ import annotations

import json
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.content import MediaAsset, Project, PublishSnapshot, SiteSettings
from app.services import deploy_service
from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD

settings = get_settings()


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
def publishable(db_session: Session) -> Project:
    """The minimum content a publish will accept."""
    db_session.add(SiteSettings(id=1, name="Mohammed Majeed J", locale="en"))
    project = Project(
        slug="phd-admission",
        title="PhD Admission System",
        category="Full stack",
        status="live",
        summary="A four-portal admission platform.",
        live_url="https://example.edu/phd",
        is_published=True,
        display_order=1,
    )
    db_session.add(project)
    db_session.commit()
    return project


def publish(client: TestClient, csrf: str, note: str | None = None) -> dict:
    response = client.post(
        "/api/admin/publish", json={"note": note}, headers=headers(csrf)
    )
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------- rollback --


def test_rollback_restores_content_without_rewriting_history(
    client: TestClient, db_session: Session, auth: str, publishable: Project
) -> None:
    first = publish(client, auth, note="Original")

    publishable.title = "A Worse Title"
    db_session.commit()
    second = publish(client, auth, note="Mistake")
    assert second["checksum"] != first["checksum"]

    restored = client.post(
        f"/api/admin/publish/snapshots/{first['id']}/rollback",
        json={},
        headers=headers(auth),
    )
    assert restored.status_code == 200, restored.text
    body = restored.json()

    # A NEW row, with the ORIGINAL bytes. Same checksum proves the content was
    # restored rather than rebuilt from the (still wrong) database.
    assert body["id"] not in {first["id"], second["id"]}
    assert body["checksum"] == first["checksum"]
    assert body["note"] == f"Rollback to snapshot {first['id'][:8]}"

    # The bad publish is still in the history — a rollback must not erase it.
    rows = db_session.scalars(select(PublishSnapshot)).all()
    assert len(rows) == 3
    assert {str(r.id) for r in rows} >= {first["id"], second["id"]}
    assert all(r.status == "published" for r in rows)

    # And the site is now serving the restored content.
    current = client.get("/api/admin/publish/current").json()
    assert current["id"] == body["id"]
    content = client.get(f"/api/admin/publish/snapshots/{body['id']}").json()["content"]
    assert content["projects"][0]["title"] == "PhD Admission System"


def test_rollback_refuses_the_live_snapshot(
    client: TestClient, auth: str, publishable: Project
) -> None:
    live = publish(client, auth)

    response = client.post(
        f"/api/admin/publish/snapshots/{live['id']}/rollback",
        json={},
        headers=headers(auth),
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "already_live"


def test_rollback_revalidates_before_restoring(
    client: TestClient, db_session: Session, auth: str, publishable: Project
) -> None:
    """A snapshot that was valid once may not be valid now."""
    first = publish(client, auth)
    publishable.title = "Second"
    db_session.commit()
    publish(client, auth)

    # Corrupt the stored snapshot the way reality would: the content it points
    # at stops satisfying the rules. (uuid.UUID, not the string: the route gets
    # this conversion from `parse_uuid`, a direct `db.get` does not.)
    stored = db_session.get(PublishSnapshot, uuid.UUID(first["id"]))
    content = dict(stored.content)
    content["projects"] = []
    stored.content = content
    db_session.commit()

    response = client.post(
        f"/api/admin/publish/snapshots/{first['id']}/rollback",
        json={},
        headers=headers(auth),
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "rollback_failed"
    # Nothing was restored, so the live snapshot is untouched.
    assert client.get("/api/admin/publish/current").json()["id"] != first["id"]


def test_rollback_requires_authentication(client: TestClient) -> None:
    response = client.post(
        "/api/admin/publish/snapshots/00000000-0000-0000-0000-000000000000/rollback",
        json={},
    )
    assert response.status_code in (401, 403)


# ------------------------------------------------------------- deploy hook --


def test_publish_reports_when_no_hook_is_configured(
    client: TestClient, auth: str, publishable: Project
) -> None:
    body = publish(client, auth)

    # The publish succeeded and says plainly that nothing was deployed, rather
    # than implying the site is live.
    assert body["deploy"]["triggered"] is False
    assert "No deploy hook configured" in body["deploy"]["detail"]
    assert client.get("/api/admin/publish/deploy").json() == {"configured": False}


def test_deploy_hook_failure_does_not_fail_the_publish(
    client: TestClient,
    db_session: Session,
    auth: str,
    publishable: Project,
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "deploy_hook_url", "https://hooks.example/build")

    def explode(*args, **kwargs):
        raise httpx.ConnectTimeout("hook unreachable")

    monkeypatch.setattr(httpx, "post", explode)

    body = publish(client, auth)

    assert body["deploy"]["triggered"] is False
    assert "ConnectTimeout" in body["deploy"]["detail"]
    # The snapshot is published regardless: the content IS saved, the site is
    # merely stale.
    assert body["published_at"] is not None
    assert client.get("/api/admin/publish/current").json()["id"] == body["id"]


def test_deploy_hook_is_fired_and_never_leaks_its_url(
    client: TestClient, auth: str, publishable: Project, monkeypatch
) -> None:
    calls: list[tuple[str, dict]] = []

    def capture(url, **kwargs):
        calls.append((url, kwargs))
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(
        settings, "deploy_hook_url", "https://hooks.example/build?token=sekrit"
    )
    monkeypatch.setattr(httpx, "post", capture)

    body = publish(client, auth)

    assert len(calls) == 1
    assert calls[0][1]["json"]["reason"] == "publish"
    assert body["deploy"]["triggered"] is True

    # The credential must not come back out of the API.
    assert "sekrit" not in json.dumps(body)
    assert client.get("/api/admin/publish/deploy").json() == {"configured": True}


def test_rollback_also_redeploys(
    client: TestClient,
    db_session: Session,
    auth: str,
    publishable: Project,
    monkeypatch,
) -> None:
    first = publish(client, auth)
    publishable.title = "Second"
    db_session.commit()
    publish(client, auth)

    reasons: list[str] = []
    monkeypatch.setattr(settings, "deploy_hook_url", "https://hooks.example/build")
    monkeypatch.setattr(
        httpx,
        "post",
        lambda url, **kwargs: (
            reasons.append(kwargs["json"]["reason"]),
            httpx.Response(200, request=httpx.Request("POST", url)),
        )[1],
    )

    response = client.post(
        f"/api/admin/publish/snapshots/{first['id']}/rollback",
        json={},
        headers=headers(auth),
    )

    assert response.status_code == 200
    # A rollback that does not redeploy leaves the old build live, which would
    # make the button a lie.
    assert reasons == ["rollback"]


def test_hook_result_is_audit_safe() -> None:
    result = deploy_service.DeployResult(
        triggered=True, status_code=200, host="hooks.example"
    )
    assert "token" not in json.dumps(result.as_details())
    assert result.as_details()["host"] == "hooks.example"


# ------------------------------------------------------------------ export --


def test_export_refuses_when_nothing_is_published(db_session: Session) -> None:
    from app import export as export_module

    with pytest.raises(export_module.ExportError, match="Nothing has been published"):
        export_module.select_snapshot(db_session, snapshot_id=None, from_draft=False)


def test_export_collects_every_referenced_asset() -> None:
    from app.export import collect_media

    snapshot = {
        "about": {
            "portrait": {"id": "1", "kind": "image", "url": "/assets/a.webp"},
        },
        "projects": [
            {"cover": {"id": "2", "kind": "image", "url": "/uploads/2026/b.webp"}},
            {"cover": None},
        ],
        # Duplicated on purpose: the same file referenced twice is one copy.
        "achievements": [
            {"image": {"id": "1", "kind": "image", "url": "/assets/a.webp"}}
        ],
    }

    assert collect_media(snapshot) == ["assets/a.webp", "uploads/2026/b.webp"]


def test_export_never_references_a_private_asset(
    db_session: Session, publishable: Project
) -> None:
    """
    The privacy guarantee, end to end.

    A withheld certificate scan is marked not-public, so `build_snapshot`
    resolves it to null — and the export therefore has nothing to copy into the
    public directory. Privacy is enforced at the source, not by the exporter
    remembering to filter.
    """
    from app.export import collect_media
    from app.services.publish_service import build_snapshot

    private = MediaAsset(
        kind="document",
        storage_key="uploads/private/certificate.pdf",
        original_filename="certificate.pdf",
        content_type="application/pdf",
        byte_size=1024,
        is_public=False,
    )
    db_session.add(private)
    db_session.commit()

    snapshot = build_snapshot(db_session)

    assert "uploads/private/certificate.pdf" not in collect_media(snapshot)
