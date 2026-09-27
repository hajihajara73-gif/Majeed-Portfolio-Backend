from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from app.api.admin.resource import count_rows, parse_uuid
from app.api.deps import AdminDep, DbDep, SettingsDep
from app.core import audit
from app.models.base import utcnow
from app.models.content import (
    Achievement,
    CareerEntry,
    EducationEntry,
    MediaAsset,
    Project,
    PublishSnapshot,
    Skill,
    SocialLink,
)
from app.schemas import content as s
from app.services import deploy_service, publish_service

router = APIRouter(prefix="/admin/publish", tags=["admin:publish"])


def _counts(db) -> s.PublishDiff:
    return s.PublishDiff(
        projects=count_rows(
            db, Project, Project.is_published.is_(True), Project.archived_at.is_(None)
        ),
        achievements=count_rows(db, Achievement, Achievement.is_public.is_(True)),
        skills=count_rows(db, Skill, Skill.is_visible.is_(True)),
        career=count_rows(db, CareerEntry, CareerEntry.is_visible.is_(True)),
        education=count_rows(db, EducationEntry, EducationEntry.is_visible.is_(True)),
        social_links=count_rows(db, SocialLink, SocialLink.is_visible.is_(True)),
        media=count_rows(db, MediaAsset),
    )


@router.get("/preview", response_model=s.PublishPreview)
def preview(db: DbDep, admin: AdminDep) -> s.PublishPreview:
    """
    What would happen if you pressed Publish.

    Runs the same build and validation as a real publish but writes nothing,
    so the confirmation dialog can show real blocking errors and warnings
    rather than a guess.
    """
    snapshot = publish_service.build_snapshot(db)
    result = publish_service.validate_snapshot(snapshot)
    current = publish_service.current_snapshot(db)

    return s.PublishPreview(
        counts=_counts(db),
        warnings=result.warnings,
        blocking=result.blocking,
        last_published_at=current.published_at if current else None,
        last_checksum=current.checksum if current else None,
    )


def _fire_deploy_hook(
    db,
    request: Request,
    settings,
    admin,
    *,
    snapshot_id: str,
    reason: str,
) -> deploy_service.DeployResult:
    """
    Trigger the rebuild and record what happened.

    Called only AFTER the publish is committed. A hook failure is therefore
    never able to roll back a snapshot that genuinely exists — the site is
    merely stale, which is a different and much smaller problem.
    """
    outcome = deploy_service.trigger(settings, reason=reason, snapshot_id=snapshot_id)

    if deploy_service.hook_configured(settings):
        audit.record(
            db,
            request,
            action="deploy.triggered" if outcome.triggered else "deploy.failed",
            actor_id=admin.id,
            actor_email=admin.email,
            target_type="publish_snapshot",
            target_id=snapshot_id,
            details=outcome.as_details(),
        )
        db.commit()

    return outcome


def _snapshot_out(row: PublishSnapshot, deploy=None) -> s.SnapshotOut:
    return s.SnapshotOut(
        id=str(row.id),
        checksum=row.checksum,
        status=row.status,
        note=row.note,
        created_at=row.created_at,
        published_at=row.published_at,
        deploy=(
            s.DeployOut(
                triggered=deploy.triggered,
                status_code=deploy.status_code,
                detail=deploy.detail,
            )
            if deploy is not None
            else None
        ),
    )


@router.post("", response_model=s.SnapshotOut)
def publish(
    payload: s.PublishRequest,
    request: Request,
    db: DbDep,
    admin: AdminDep,
    settings: SettingsDep,
) -> s.SnapshotOut:
    previous = publish_service.current_snapshot(db)
    row, result = publish_service.create_snapshot(
        db, actor_id=admin.id, note=payload.note
    )

    audit.record(
        db,
        request,
        action="publish.attempted" if not result.ok else "publish.succeeded",
        actor_id=admin.id,
        actor_email=admin.email,
        target_type="publish_snapshot",
        target_id=str(row.id),
        details={"checksum": row.checksum, "blocking": result.blocking},
    )
    # Committed either way: a failed attempt is recorded as `failed`, and the
    # previously published row is never modified, so the site keeps serving it.
    db.commit()

    if not result.ok:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "publish_failed",
                "message": "Publish blocked — fix the issues and try again.",
                "blocking": result.blocking,
                "warnings": result.warnings,
                "still_published": (
                    {
                        "checksum": previous.checksum,
                        "published_at": previous.published_at.isoformat(),
                    }
                    if previous and previous.published_at
                    else None
                ),
            },
        )

    deploy = _fire_deploy_hook(
        db, request, settings, admin, snapshot_id=str(row.id), reason="publish"
    )
    return _snapshot_out(row, deploy)


@router.post("/snapshots/{snapshot_id}/rollback", response_model=s.SnapshotOut)
def rollback(
    snapshot_id: str,
    payload: s.RollbackRequest,
    request: Request,
    db: DbDep,
    admin: AdminDep,
    settings: SettingsDep,
) -> s.SnapshotOut:
    """
    Re-publish an earlier snapshot.

    This does NOT flip the old row back to `published`. It copies that row's
    content into a NEW published snapshot, because the history of what was live
    and when is only trustworthy if it is append-only — a rollback that mutated
    the past would make the audit trail claim the bad publish never happened.

    The content is re-validated first. It passed once, but a media asset it
    points at may have been made private or deleted since, and shipping a
    rollback that 404s would be a worse failure than the one being undone.
    """
    target = db.get(PublishSnapshot, parse_uuid(snapshot_id))
    if target is None:
        raise HTTPException(status_code=404, detail="Not found")

    current = publish_service.current_snapshot(db)
    if current is not None and str(current.id) == str(target.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "already_live",
                "message": "That snapshot is already the published one.",
            },
        )

    content = dict(target.content)
    result = publish_service.validate_snapshot(content)
    if not result.ok:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "rollback_failed",
                "message": (
                    "That snapshot is no longer valid, so it was not restored."
                ),
                "blocking": result.blocking,
            },
        )

    now = utcnow()
    short = str(target.id)[:8]
    row = PublishSnapshot(
        created_by_id=admin.id,
        content=content,
        # Same content, therefore the same checksum — which is how you can
        # verify a rollback restored the bytes rather than rebuilt from the
        # current database.
        checksum=target.checksum,
        status="published",
        note=payload.note or f"Rollback to snapshot {short}",
        created_at=now,
        published_at=now,
    )
    db.add(row)
    db.flush()

    audit.record(
        db,
        request,
        action="publish.rolled_back",
        actor_id=admin.id,
        actor_email=admin.email,
        target_type="publish_snapshot",
        target_id=str(row.id),
        details={
            "restored_from": str(target.id),
            "checksum": row.checksum,
            "replaced": str(current.id) if current else None,
        },
    )
    db.commit()

    deploy = _fire_deploy_hook(
        db, request, settings, admin, snapshot_id=str(row.id), reason="rollback"
    )
    return _snapshot_out(row, deploy)


@router.get("/deploy", response_model=s.DeployStatus)
def deploy_status(admin: AdminDep, settings: SettingsDep) -> s.DeployStatus:
    """
    Whether a build hook is configured — never the URL itself.

    The admin needs to know whether pressing Publish will actually rebuild the
    site. It does not need the credential to tell the operator that.
    """
    return s.DeployStatus(configured=deploy_service.hook_configured(settings))


@router.get("/snapshots", response_model=list[s.SnapshotOut])
def list_snapshots(db: DbDep, admin: AdminDep) -> list[s.SnapshotOut]:
    rows = db.scalars(
        select(PublishSnapshot)
        .order_by(PublishSnapshot.created_at.desc())
        .limit(50)
    ).all()
    return [
        s.SnapshotOut(
            id=str(r.id),
            checksum=r.checksum,
            status=r.status,
            note=r.note,
            created_at=r.created_at,
            published_at=r.published_at,
        )
        for r in rows
    ]


@router.get("/snapshots/{snapshot_id}")
def get_snapshot(snapshot_id: str, db: DbDep, admin: AdminDep) -> dict:
    """
    Read a snapshot's full content.

    This is what the rollback confirmation reads, so an operator can see what
    they are about to restore before restoring it.
    """
    row = db.get(PublishSnapshot, parse_uuid(snapshot_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    return {
        "id": str(row.id),
        "checksum": row.checksum,
        "status": row.status,
        "note": row.note,
        "created_at": row.created_at,
        "published_at": row.published_at,
        "content": row.content,
    }


@router.get("/current")
def current(db: DbDep, admin: AdminDep) -> dict:
    row = publish_service.current_snapshot(db)
    if row is None:
        return {"published": False}
    return {
        "published": True,
        "id": str(row.id),
        "checksum": row.checksum,
        "published_at": row.published_at,
    }
