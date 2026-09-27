"""
Serving media files back to the admin.

Two storage roots exist and the key tells them apart:

  * `assets/...`  — files that shipped with the public site, registered by the
                    seed. They live in `frontend/public/`.
  * `uploads/...` — files uploaded through the CMS. They live in
                    `backend/storage/`, or wherever STORAGE_ROOT points.

Both are resolved and then checked for containment, so a crafted key cannot
walk out of its root even if one ever reached the database.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from app.api.admin.resource import get_or_404
from app.api.deps import AdminDep, DbDep
from app.core.config import get_settings
from app.models.content import MediaAsset

router = APIRouter(prefix="/admin/media", tags=["admin:media"])

_settings = get_settings()

# Both roots come from configuration, with one definition each.
#
# `STORAGE_ROOT` must be a persistent volume in production — see
# `Settings.storage_root`. `PUBLIC_ROOT` is the frontend's shipped assets, and
# is only reachable when the two applications are checked out together; on
# Render the frontend is absent, and an `assets/...` key simply 404s there,
# which is correct because the public site serves those files itself.
STORAGE_ROOT = _settings.resolved_storage_root
PUBLIC_ROOT = _settings.frontend_public_root

ROOTS: dict[str, Path] = {
    "uploads": STORAGE_ROOT,
    "assets": PUBLIC_ROOT,
}


def resolve_path(storage_key: str) -> Path:
    key = storage_key.strip().lstrip("/")
    prefix = key.split("/", 1)[0] if "/" in key else ""
    root = ROOTS.get(prefix)
    if root is None:
        raise HTTPException(status_code=404, detail="Not found")

    candidate = (root / key).resolve()
    # Containment check. `is_relative_to` is the whole defence against
    # `../` in a stored key — never trust the key even though we wrote it.
    if not candidate.is_relative_to(root.resolve()):
        raise HTTPException(status_code=404, detail="Not found")
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="File missing from storage")
    return candidate


@router.get("/{item_id}/file")
def serve_media(item_id: str, db: DbDep, admin: AdminDep) -> FileResponse:
    """
    Stream a media file.

    Admin-authenticated regardless of the asset's public flag: this endpoint
    exists for previews inside the CMS. The public site serves its own copies
    as ordinary static files and never calls the API.
    """
    row = get_or_404(db, MediaAsset, item_id)
    path = resolve_path(row.storage_key)
    return FileResponse(
        path,
        media_type=row.content_type,
        # inline so images preview in the picker rather than downloading.
        headers={
            "Content-Disposition": f'inline; filename="{row.original_filename}"',
            # Private so no shared cache holds it, but long-lived: the id is
            # immutable and a replaced file gets a new id, so there is nothing
            # to invalidate. Without this, every thumbnail in the picker grid
            # re-hits a database 12,000 km away on each render.
            "Cache-Control": "private, max-age=86400",
        },
    )


@router.get("/{item_id}/missing")
def check_media(item_id: str, db: DbDep, admin: AdminDep) -> dict:
    """Whether the row still has a file behind it, for a library health view."""
    row = get_or_404(db, MediaAsset, item_id)
    try:
        resolve_path(row.storage_key)
    except HTTPException:
        return {"present": False, "storage_key": row.storage_key}
    return {"present": True, "storage_key": row.storage_key}


def register(app_router: APIRouter) -> None:  # pragma: no cover - wiring helper
    app_router.include_router(router)


__all__ = ["router", "resolve_path", "STORAGE_ROOT", "PUBLIC_ROOT", "status"]
