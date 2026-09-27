from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, Request, UploadFile, status
from sqlalchemy import func, select

from app.api.admin import serialisers as ser
from app.api.admin.files import STORAGE_ROOT
from app.api.admin.resource import check_version, get_or_404
from app.api.deps import AdminDep, DbDep
from app.core import audit
from app.models.content import (
    AboutContent,
    Achievement,
    HomeContent,
    MediaAsset,
    MusicTrack,
    Project,
    ProjectMedia,
    SiteSettings,
)
from app.schemas import content as s
from app.services import storage
from app.services.storage import UploadRejected

router = APIRouter(prefix="/admin/media", tags=["admin:media"])

# STORAGE_ROOT is imported from `files`, not recomputed here. It used to be
# derived from `__file__` in both modules, which only worked as long as both
# copies happened to agree — and it made the path impossible to move onto a
# persistent volume.

# Every column that can point at a media asset. Used to block deletion of a
# file something still references — a broken image on the live site is a much
# worse outcome than an un-deleted file.
REFERENCES: list[tuple[type, str]] = [
    (Project, "cover_media_id"),
    (ProjectMedia, "media_id"),
    (Achievement, "image_media_id"),
    (Achievement, "document_media_id"),
    (HomeContent, "resume_media_id"),
    (HomeContent, "background_video_id"),
    (HomeContent, "background_poster_id"),
    (AboutContent, "portrait_media_id"),
    (SiteSettings, "og_image_id"),
    (SiteSettings, "favicon_id"),
    (MusicTrack, "audio_media_id"),
    (MusicTrack, "cover_media_id"),
]


def reference_count(db, media_id) -> int:
    """Reference count for ONE asset. Fine for a single row; never in a loop."""
    total = 0
    for model, column in REFERENCES:
        total += (
            db.scalar(
                select(func.count())
                .select_from(model)
                .where(getattr(model, column) == media_id)
            )
            or 0
        )
    return total


def reference_counts(db) -> dict[str, int]:
    """
    Reference counts for EVERY asset, in 12 queries total rather than 12 per
    asset.

    The per-row version above is an N+1: with 27 assets it fired 324 queries,
    and against a remote database that took long enough for the Media page to
    never finish loading. One grouped count per referencing column collapses it
    to a fixed cost regardless of library size.
    """
    counts: dict[str, int] = {}
    for model, column in REFERENCES:
        target = getattr(model, column)
        rows = db.execute(
            select(target, func.count())
            .where(target.is_not(None))
            .group_by(target)
        ).all()
        for media_id, count in rows:
            key = str(media_id)
            counts[key] = counts.get(key, 0) + count
    return counts


@router.get("", response_model=list[s.MediaOut])
def list_media(db: DbDep, admin: AdminDep, kind: str | None = None) -> list[dict]:
    stmt = select(MediaAsset).order_by(MediaAsset.created_at.desc())
    if kind:
        stmt = stmt.where(MediaAsset.kind == kind)
    rows = db.scalars(stmt).all()
    counts = reference_counts(db)
    return [ser.media_out(row, counts.get(str(row.id), 0)) for row in rows]


@router.get("/{item_id}", response_model=s.MediaOut)
def get_media(item_id: str, db: DbDep, admin: AdminDep) -> dict:
    row = get_or_404(db, MediaAsset, item_id)
    return ser.media_out(row, reference_count(db, row.id))


@router.post("", response_model=s.MediaOut, status_code=status.HTTP_201_CREATED)
async def upload_media(
    request: Request,
    db: DbDep,
    admin: AdminDep,
    file: UploadFile = File(...),  # noqa: B008 — FastAPI's documented idiom
) -> dict:
    data = await file.read()
    try:
        content_type, kind = storage.validate(
            file.filename or "file", file.content_type or "", data
        )
        stored = storage.store(
            STORAGE_ROOT, file.filename or "file", data, content_type, kind
        )
    except UploadRejected as rejected:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": rejected.code, "message": rejected.message},
        ) from rejected

    # Re-uploading an identical file returns the existing asset instead of
    # creating a duplicate the library would have to show twice.
    existing = db.scalar(
        select(MediaAsset).where(MediaAsset.checksum == stored.checksum)
    )
    if existing is not None:
        return ser.media_out(existing, reference_count(db, existing.id))

    row = MediaAsset(
        kind=stored.kind,
        storage_key=stored.storage_key,
        original_filename=stored.original_filename,
        content_type=stored.content_type,
        byte_size=stored.byte_size,
        checksum=stored.checksum,
        is_public=True,
        uploaded_by_id=admin.id,
    )
    db.add(row)
    db.flush()
    audit.record(
        db,
        request,
        action="media.uploaded",
        actor_id=admin.id,
        actor_email=admin.email,
        target_type="media",
        target_id=str(row.id),
        details={"filename": stored.original_filename, "bytes": stored.byte_size},
    )
    db.commit()
    return ser.media_out(row, 0)


@router.put("/{item_id}", response_model=s.MediaOut)
def update_media(
    item_id: str,
    payload: s.MediaUpdate,
    request: Request,
    db: DbDep,
    admin: AdminDep,
) -> dict:
    row = get_or_404(db, MediaAsset, item_id)
    check_version(row, payload.expected_updated_at)
    row.alt_text = payload.alt_text
    row.title = payload.title
    row.folder = payload.folder
    row.tags = payload.tags
    row.is_public = payload.is_public
    audit.record(
        db,
        request,
        action="media.updated",
        actor_id=admin.id,
        actor_email=admin.email,
        target_type="media",
        target_id=item_id,
    )
    db.commit()
    return ser.media_out(row, reference_count(db, row.id))


@router.delete("/{item_id}")
def delete_media(
    item_id: str, request: Request, db: DbDep, admin: AdminDep
) -> dict:
    row = get_or_404(db, MediaAsset, item_id)
    used = reference_count(db, row.id)
    if used:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "in_use",
                "message": (
                    f"This file is used in {used} place"
                    f"{'s' if used != 1 else ''}. Remove those references first."
                ),
            },
        )

    # Remove the row first; only unlink the file once the delete has committed,
    # so a failed transaction cannot leave a record pointing at nothing.
    storage_key = row.storage_key
    db.delete(row)
    audit.record(
        db,
        request,
        action="media.deleted",
        actor_id=admin.id,
        actor_email=admin.email,
        target_type="media",
        target_id=item_id,
        details={"storage_key": storage_key},
    )
    db.commit()

    path = (STORAGE_ROOT / storage_key).resolve()
    if path.is_relative_to(STORAGE_ROOT.resolve()) and path.is_file():
        path.unlink(missing_ok=True)

    return {"deleted": item_id, "archived": False}
