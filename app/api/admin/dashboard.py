from __future__ import annotations

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select

from app.api.admin import serialisers as ser
from app.api.admin.resource import count_rows, get_or_404
from app.api.deps import AdminDep, DbDep
from app.core import audit
from app.models.admin import AuditLog
from app.models.content import (
    Achievement,
    CareerEntry,
    ContactMessage,
    EducationEntry,
    MediaAsset,
    Project,
    Skill,
    SkillCategory,
    SocialLink,
)
from app.schemas import content as s
from app.services import publish_service

router = APIRouter(prefix="/admin", tags=["admin:dashboard"])


@router.get("/dashboard")
def dashboard(db: DbDep, admin: AdminDep) -> dict:
    """
    Real numbers only.

    Every figure below is a live count. Nothing here is padded or estimated —
    a dashboard that invents a number teaches you to distrust all of them.
    """
    current = publish_service.current_snapshot(db)

    # Most recent content change across the tables that carry updated_at.
    last_updated = db.scalar(
        select(func.max(AuditLog.created_at)).where(
            AuditLog.action.like("content.%")
        )
    )

    return {
        "counts": {
            "projects": count_rows(db, Project, Project.archived_at.is_(None)),
            "projects_published": count_rows(
                db,
                Project,
                Project.is_published.is_(True),
                Project.archived_at.is_(None),
            ),
            "achievements": count_rows(db, Achievement),
            "skills": count_rows(db, Skill),
            "skill_categories": count_rows(db, SkillCategory),
            "media": count_rows(db, MediaAsset),
            "social_links": count_rows(db, SocialLink),
            "career": count_rows(db, CareerEntry),
            "education": count_rows(db, EducationEntry),
            "messages": count_rows(db, ContactMessage),
            "messages_unread": count_rows(
                db, ContactMessage, ContactMessage.is_read.is_(False)
            ),
        },
        "publish": {
            "published": current is not None,
            "checksum": current.checksum if current else None,
            "published_at": current.published_at if current else None,
            "snapshot_id": str(current.id) if current else None,
        },
        "last_content_update": last_updated,
    }


@router.get("/activity")
def activity(db: DbDep, admin: AdminDep, limit: int = 20) -> list[dict]:
    rows = db.scalars(
        select(AuditLog)
        .order_by(AuditLog.created_at.desc())
        .limit(min(max(limit, 1), 100))
    ).all()
    return [
        {
            "id": str(row.id),
            "action": row.action,
            "actor": row.actor_email,
            "target_type": row.target_type,
            "target_id": row.target_id,
            "created_at": row.created_at,
        }
        for row in rows
    ]


# --------------------------------------------------------------------------
# Messages
# --------------------------------------------------------------------------

messages_router = APIRouter(prefix="/admin/messages", tags=["admin:messages"])


MESSAGES_PAGE_SIZE = 50
MESSAGES_MAX_PAGE_SIZE = 200


@messages_router.get("", response_model=list[s.MessageOut])
def list_messages(
    db: DbDep,
    admin: AdminDep,
    unread_only: bool = False,
    limit: int = Query(MESSAGES_PAGE_SIZE, ge=1, le=MESSAGES_MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0),
) -> list[dict]:
    """
    Newest first, paged.

    Bounded deliberately: an unauthenticated endpoint feeds this table, so an
    unpaged query turns a spam flood into an inbox that cannot be opened. The
    ceiling is enforced by the parameter, not by the caller's good manners.
    """
    stmt = select(ContactMessage).order_by(ContactMessage.created_at.desc())
    if unread_only:
        stmt = stmt.where(ContactMessage.is_read.is_(False))
    stmt = stmt.limit(limit).offset(offset)
    return [ser.message_out(row) for row in db.scalars(stmt).all()]


@messages_router.get("/{item_id}", response_model=s.MessageOut)
def get_message(item_id: str, db: DbDep, admin: AdminDep) -> dict:
    return ser.message_out(get_or_404(db, ContactMessage, item_id))


@messages_router.put("/{item_id}", response_model=s.MessageOut)
def update_message(
    item_id: str,
    payload: s.MessageUpdate,
    request: Request,
    db: DbDep,
    admin: AdminDep,
) -> dict:
    row = get_or_404(db, ContactMessage, item_id)
    # Partial update: only the flags actually sent are applied.
    for field in ("is_read", "is_starred", "is_archived", "is_spam"):
        value = getattr(payload, field)
        if value is not None:
            setattr(row, field, value)
    db.commit()
    return ser.message_out(row)


@messages_router.delete("/{item_id}")
def delete_message(
    item_id: str, request: Request, db: DbDep, admin: AdminDep
) -> dict:
    row = get_or_404(db, ContactMessage, item_id)
    db.delete(row)
    audit.record(
        db,
        request,
        action="content.messages.deleted",
        actor_id=admin.id,
        actor_email=admin.email,
        target_type="messages",
        target_id=item_id,
    )
    db.commit()
    return {"deleted": item_id, "archived": False}
