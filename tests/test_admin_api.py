"""
Phase 2 tests: authorisation, CRUD, validation, uploads and publishing.

Weighted toward the properties that are easy to get wrong and expensive to get
wrong — authorisation on every route, optimistic locking, upload sniffing, and
the guarantee that a failed publish leaves the live site alone.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.content import (
    Achievement,
    MediaAsset,
    Project,
    ProjectTechnology,
    PublishSnapshot,
    SiteSettings,
)
from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD

settings = get_settings()

# Every state-changing admin route, for the blanket authorisation sweep.
PROTECTED_GET = [
    "/api/admin/dashboard",
    "/api/admin/projects",
    "/api/admin/achievements",
    "/api/admin/skills",
    "/api/admin/skill-categories",
    "/api/admin/career",
    "/api/admin/education",
    "/api/admin/social",
    "/api/admin/media",
    "/api/admin/messages",
    "/api/admin/site",
    "/api/admin/home",
    "/api/admin/about",
    "/api/admin/publish/preview",
]


@pytest.fixture
def auth(client: TestClient, admin) -> str:
    """Sign in and return the CSRF token the client must echo on writes."""
    response = client.post(
        "/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    )
    assert response.status_code == 200
    return response.cookies[settings.csrf_cookie_name]


def headers(csrf: str) -> dict[str, str]:
    return {settings.csrf_header_name: csrf}


# --------------------------------------------------------------------------
# Authorisation — the admin UI is never the security boundary
# --------------------------------------------------------------------------


@pytest.mark.parametrize("path", PROTECTED_GET)
def test_every_admin_get_requires_authentication(
    client: TestClient, path: str
) -> None:
    assert client.get(path).status_code == 401


def test_admin_writes_require_authentication(client: TestClient) -> None:
    assert client.post("/api/admin/projects", json={}).status_code == 401
    assert client.put("/api/admin/site", json={}).status_code == 401
    assert client.delete("/api/admin/projects/x").status_code == 401
    assert client.post("/api/admin/publish", json={}).status_code == 401


def test_authenticated_write_without_csrf_is_rejected(
    client: TestClient, auth: str
) -> None:
    response = client.post(
        "/api/admin/projects",
        json={"slug": "x", "title": "X"},
    )
    assert response.status_code == 403


def test_authenticated_get_is_allowed(client: TestClient, auth: str) -> None:
    assert client.get("/api/admin/projects").status_code == 200


# --------------------------------------------------------------------------
# Projects CRUD
# --------------------------------------------------------------------------


def make_project(client: TestClient, csrf: str, **overrides):
    payload = {
        "slug": "test-project",
        "title": "Test Project",
        "status": "live",
        "summary": "A summary.",
        "live_url": "https://example.com",
        "github_url": "https://github.com/example/repo",
        "technologies": ["Python", "React"],
        "highlights": ["Does a thing"],
        **overrides,
    }
    return client.post("/api/admin/projects", json=payload, headers=headers(csrf))


def test_create_read_update_delete_project(
    client: TestClient, auth: str, db_session: Session
) -> None:
    created = make_project(client, auth)
    assert created.status_code == 201
    body = created.json()
    assert body["slug"] == "test-project"
    assert body["technologies"] == ["Python", "React"]
    assert body["highlights"] == ["Does a thing"]

    project_id = body["id"]
    fetched = client.get(f"/api/admin/projects/{project_id}")
    assert fetched.status_code == 200

    updated = client.put(
        f"/api/admin/projects/{project_id}",
        json={
            "title": "Renamed",
            "status": "local",
            "technologies": ["Go"],
            "highlights": [],
            "expected_updated_at": body["updated_at"],
        },
        headers=headers(auth),
    )
    assert updated.status_code == 200
    assert updated.json()["title"] == "Renamed"
    assert updated.json()["technologies"] == ["Go"]
    # Replacing the child list must not orphan the old rows.
    assert db_session.scalars(select(ProjectTechnology)).all().__len__() == 1

    deleted = client.delete(
        f"/api/admin/projects/{project_id}", headers=headers(auth)
    )
    assert deleted.status_code == 200
    assert client.get(f"/api/admin/projects/{project_id}").status_code == 404


def test_duplicate_slug_is_rejected(client: TestClient, auth: str) -> None:
    assert make_project(client, auth).status_code == 201
    clash = make_project(client, auth)
    assert clash.status_code == 409
    assert clash.json()["detail"]["code"] == "duplicate"


def test_nonexistent_project_is_404_not_500(client: TestClient, auth: str) -> None:
    # A malformed UUID must not blow up the handler.
    assert client.get("/api/admin/projects/not-a-uuid").status_code == 404
    assert (
        client.get("/api/admin/projects/00000000-0000-0000-0000-000000000000").status_code
        == 404
    )


def test_invalid_url_is_rejected(client: TestClient, auth: str) -> None:
    response = make_project(client, auth, live_url="javascript:alert(1)")
    assert response.status_code == 422


def test_invalid_slug_is_rejected(client: TestClient, auth: str) -> None:
    assert make_project(client, auth, slug="Not A Slug").status_code == 422


def test_invalid_status_is_rejected(client: TestClient, auth: str) -> None:
    assert make_project(client, auth, status="whatever").status_code == 422


def test_missing_title_is_rejected(client: TestClient, auth: str) -> None:
    response = client.post(
        "/api/admin/projects", json={"slug": "x"}, headers=headers(auth)
    )
    assert response.status_code == 422


def test_stale_update_is_rejected(client: TestClient, auth: str) -> None:
    created = make_project(client, auth).json()
    stale = "2020-01-01T00:00:00+00:00"
    response = client.put(
        f"/api/admin/projects/{created['id']}",
        json={"title": "Clobber", "technologies": [], "highlights": [],
              "expected_updated_at": stale},
        headers=headers(auth),
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "stale_write"


def test_archive_keeps_the_row_and_unpublishes_it(
    client: TestClient, auth: str
) -> None:
    created = make_project(client, auth).json()
    archived = client.post(
        f"/api/admin/projects/{created['id']}/archive", headers=headers(auth)
    )
    assert archived.status_code == 200
    assert archived.json()["archived_at"] is not None
    assert archived.json()["is_published"] is False
    # Still retrievable — archive is not delete.
    assert client.get(f"/api/admin/projects/{created['id']}").status_code == 200


def test_reorder_projects(client: TestClient, auth: str) -> None:
    a = make_project(client, auth, slug="a", title="A").json()
    b = make_project(client, auth, slug="b", title="B").json()
    response = client.post(
        "/api/admin/projects/reorder",
        json={"items": [{"id": b["id"], "display_order": 0},
                        {"id": a["id"], "display_order": 1}]},
        headers=headers(auth),
    )
    assert response.status_code == 200
    assert [p["slug"] for p in response.json()] == ["b", "a"]


def test_reorder_with_unknown_id_is_404(client: TestClient, auth: str) -> None:
    response = client.post(
        "/api/admin/projects/reorder",
        json={"items": [
            {"id": "00000000-0000-0000-0000-000000000000", "display_order": 0}
        ]},
        headers=headers(auth),
    )
    assert response.status_code == 404


# --------------------------------------------------------------------------
# Achievements
# --------------------------------------------------------------------------


def test_achievement_crud_and_type_validation(
    client: TestClient, auth: str
) -> None:
    created = client.post(
        "/api/admin/achievements",
        json={"slug": "a-cert", "title": "A Cert", "achievement_type": "certificate"},
        headers=headers(auth),
    )
    assert created.status_code == 201

    bad = client.post(
        "/api/admin/achievements",
        json={"slug": "b-cert", "title": "B", "achievement_type": "nonsense"},
        headers=headers(auth),
    )
    assert bad.status_code == 422


def test_privacy_withheld_achievement_stays_withheld(
    client: TestClient, auth: str, db_session: Session
) -> None:
    """
    The DOTE certificate is listed without its scan because that PDF carries a
    date of birth and a photograph. Creating it with no media must leave both
    references null — nothing may auto-attach a document.
    """
    created = client.post(
        "/api/admin/achievements",
        json={
            "slug": "dote-typewriting-english-junior",
            "title": "Typewriting English (Junior)",
            "allow_download": False,
        },
        headers=headers(auth),
    ).json()

    assert created["image_media_id"] is None
    assert created["document_media_id"] is None
    assert created["allow_download"] is False

    row = db_session.scalar(
        select(Achievement).where(Achievement.slug == created["slug"])
    )
    assert row is not None
    assert row.image_media_id is None
    assert row.document_media_id is None


# --------------------------------------------------------------------------
# Social links
# --------------------------------------------------------------------------


def test_social_link_rejects_dangerous_scheme(client: TestClient, auth: str) -> None:
    response = client.post(
        "/api/admin/social",
        json={"label": "Bad", "href": "javascript:alert(1)"},
        headers=headers(auth),
    )
    assert response.status_code == 422


def test_social_link_accepts_mailto(client: TestClient, auth: str) -> None:
    response = client.post(
        "/api/admin/social",
        json={"label": "Email", "href": "mailto:a@b.com"},
        headers=headers(auth),
    )
    assert response.status_code == 201


# --------------------------------------------------------------------------
# Media upload validation
# --------------------------------------------------------------------------

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def test_upload_accepts_a_real_png(client: TestClient, auth: str) -> None:
    response = client.post(
        "/api/admin/media",
        files={"file": ("shot.png", PNG, "image/png")},
        headers=headers(auth),
    )
    assert response.status_code == 201
    assert response.json()["kind"] == "image"


def test_upload_rejects_executable_disguised_as_image(
    client: TestClient, auth: str
) -> None:
    """The classic attack: a script announced as an image."""
    response = client.post(
        "/api/admin/media",
        files={"file": ("evil.png", b"<?php system($_GET['c']); ?>", "image/png")},
        headers=headers(auth),
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] in {
        "unrecognised_content",
        "content_mismatch",
    }


def test_upload_rejects_disallowed_type(client: TestClient, auth: str) -> None:
    response = client.post(
        "/api/admin/media",
        files={"file": ("x.svg", b"<svg onload=alert(1)>", "image/svg+xml")},
        headers=headers(auth),
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "type_not_allowed"


def test_upload_strips_path_traversal_from_filename(
    client: TestClient, auth: str
) -> None:
    response = client.post(
        "/api/admin/media",
        files={"file": ("../../../etc/passwd.png", PNG, "image/png")},
        headers=headers(auth),
    )
    assert response.status_code == 201
    stored = response.json()
    # The original name is kept only as display metadata, with traversal stripped.
    assert ".." not in stored["original_filename"]
    # The key on disk is generated, never derived from the client's name.
    assert stored["storage_key"].startswith("uploads/image/")
    assert "passwd" not in stored["storage_key"]


def test_media_in_use_cannot_be_deleted(
    client: TestClient, auth: str, db_session: Session
) -> None:
    uploaded = client.post(
        "/api/admin/media",
        files={"file": ("cover.png", PNG, "image/png")},
        headers=headers(auth),
    ).json()

    make_project(client, auth, cover_media_id=uploaded["id"])

    response = client.delete(
        f"/api/admin/media/{uploaded['id']}", headers=headers(auth)
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "in_use"
    # Still present — a refused delete must not have removed anything.
    import uuid as _uuid

    assert db_session.get(MediaAsset, _uuid.UUID(uploaded["id"])) is not None


# --------------------------------------------------------------------------
# Publish
# --------------------------------------------------------------------------


def seed_minimum(client: TestClient, auth: str) -> None:
    """Enough content for a publish to pass validation."""
    client.put(
        "/api/admin/site",
        json={"name": "Mohammed Majeed J", "url": "https://example.com"},
        headers=headers(auth),
    )
    make_project(client, auth)


def test_publish_preview_reports_blocking_issues(
    client: TestClient, auth: str
) -> None:
    response = client.get("/api/admin/publish/preview")
    assert response.status_code == 200
    body = response.json()
    # Empty database: no projects, so publishing is blocked.
    assert "At least one published project is required." in body["blocking"]
    assert body["last_published_at"] is None


def test_publish_succeeds_with_valid_content(
    client: TestClient, auth: str, db_session: Session
) -> None:
    seed_minimum(client, auth)
    response = client.post(
        "/api/admin/publish", json={"note": "first"}, headers=headers(auth)
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "published"
    assert body["published_at"] is not None
    assert len(body["checksum"]) == 64

    current = client.get("/api/admin/publish/current").json()
    assert current["published"] is True
    assert current["checksum"] == body["checksum"]


def test_failed_publish_preserves_the_live_snapshot(
    client: TestClient, auth: str, db_session: Session
) -> None:
    """
    The property that matters most: a bad publish must not take the site down.
    """
    seed_minimum(client, auth)
    good = client.post(
        "/api/admin/publish", json={"note": "good"}, headers=headers(auth)
    ).json()

    # Break the content: remove every project.
    for project in db_session.scalars(select(Project)).all():
        db_session.delete(project)
    db_session.commit()

    failed = client.post(
        "/api/admin/publish", json={"note": "bad"}, headers=headers(auth)
    )
    assert failed.status_code == 422
    detail = failed.json()["detail"]
    assert detail["code"] == "publish_failed"
    assert detail["blocking"]
    # It tells the caller what is still live.
    assert detail["still_published"]["checksum"] == good["checksum"]

    # And the live snapshot really is unchanged.
    current = client.get("/api/admin/publish/current").json()
    assert current["checksum"] == good["checksum"]

    # The failed attempt is recorded, not hidden.
    snapshots = client.get("/api/admin/publish/snapshots").json()
    assert any(s["status"] == "failed" for s in snapshots)
    assert any(s["status"] == "published" for s in snapshots)


def test_publish_blocks_on_todo_placeholders(
    client: TestClient, auth: str
) -> None:
    seed_minimum(client, auth)
    make_project(
        client, auth, slug="todo-one", title="TODO_REPLACE_PROJECT_TITLE"
    )
    response = client.post("/api/admin/publish", json={}, headers=headers(auth))
    assert response.status_code == 422
    assert any(
        "TODO_REPLACE_" in message
        for message in response.json()["detail"]["blocking"]
    )


def test_private_media_never_reaches_the_snapshot(
    client: TestClient, auth: str, db_session: Session
) -> None:
    seed_minimum(client, auth)
    uploaded = client.post(
        "/api/admin/media",
        files={"file": ("private.png", PNG, "image/png")},
        headers=headers(auth),
    ).json()
    client.put(
        f"/api/admin/media/{uploaded['id']}",
        json={"is_public": False, "alt_text": None, "title": None,
              "folder": None, "tags": None},
        headers=headers(auth),
    )
    client.put(
        "/api/admin/about",
        json={"portrait_media_id": uploaded["id"]},
        headers=headers(auth),
    )

    published = client.post(
        "/api/admin/publish", json={}, headers=headers(auth)
    ).json()
    snapshot = db_session.scalar(
        select(PublishSnapshot).where(PublishSnapshot.checksum == published["checksum"])
    )
    assert snapshot is not None
    assert snapshot.content["about"]["portrait"] is None


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------


def test_dashboard_numbers_come_from_the_database(
    client: TestClient, auth: str
) -> None:
    make_project(client, auth, slug="one", title="One")
    make_project(client, auth, slug="two", title="Two")

    body = client.get("/api/admin/dashboard").json()
    assert body["counts"]["projects"] == 2
    assert body["counts"]["messages"] == 0
    assert body["publish"]["published"] is False


# --------------------------------------------------------------------------
# Singletons
# --------------------------------------------------------------------------


def test_site_settings_round_trip(
    client: TestClient, auth: str, db_session: Session
) -> None:
    response = client.put(
        "/api/admin/site",
        json={"name": "Portfolio", "url": "https://example.com",
              "maintenance_mode": True},
        headers=headers(auth),
    )
    assert response.status_code == 200
    assert response.json()["maintenance_mode"] is True

    row = db_session.get(SiteSettings, 1)
    assert row is not None and row.name == "Portfolio"


def test_site_settings_rejects_bad_url(client: TestClient, auth: str) -> None:
    response = client.put(
        "/api/admin/site",
        json={"name": "Portfolio", "url": "javascript:alert(1)"},
        headers=headers(auth),
    )
    assert response.status_code == 422
