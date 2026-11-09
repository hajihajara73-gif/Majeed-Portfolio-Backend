from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select

from app.api.admin import serialisers as ser
from app.api.admin.resource import count_rows, get_or_404
from app.api.deps import AdminDep, DbDep, SettingsDep
from app.core import audit
from app.models.admin import AuditLog
from app.models.base import utcnow
from app.models.content import (
    Achievement,
    AchievementCategory,
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
from app.services import contact_notifier, publish_service

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
            # Certificates and achievements are two separate sections, in the
            # admin and on the public site, and they are two rows of the SAME
            # table split by `achievement_type`. Counting the table gave one
            # "Achievements" figure that was really both added together — 11,
            # when there are 10 certificates and 1 achievement. Split here so
            # each card counts the thing it is named after.
            "certificates": count_rows(
                db, Achievement, Achievement.achievement_type == "certificate"
            ),
            "achievements": count_rows(
                db, Achievement, Achievement.achievement_type != "certificate"
            ),
            "achievement_categories": count_rows(db, AchievementCategory),
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


def _message_filters(
    stmt,
    *,
    q: str | None,
    unread_only: bool,
    status_filter: str,
    archived: bool,
):
    """Shared by the list and its count, so the two can never disagree."""
    # Archived messages are hidden by default rather than deleted: the
    # listing is an inbox, and an inbox that shows everything forever stops
    # being usable long before it stops being complete.
    stmt = stmt.where(ContactMessage.is_archived.is_(archived))

    if unread_only or status_filter == "unread":
        stmt = stmt.where(ContactMessage.is_read.is_(False))
    elif status_filter == "read":
        stmt = stmt.where(ContactMessage.is_read.is_(True))

    if q:
        # ILIKE with an escaped pattern. The value is bound, never
        # interpolated, so this is not an injection vector; escaping %, _ and
        # the escape character itself stops a search for "100%" from matching
        # everything.
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        stmt = stmt.where(
            or_(
                ContactMessage.name.ilike(pattern, escape="\\"),
                ContactMessage.email.ilike(pattern, escape="\\"),
                ContactMessage.subject.ilike(pattern, escape="\\"),
            )
        )
    return stmt


@messages_router.get("", response_model=s.MessagePage)
def list_messages(
    db: DbDep,
    admin: AdminDep,
    q: str | None = Query(None, max_length=200),
    status_filter: str = Query("all", pattern="^(all|read|unread)$", alias="status"),
    archived: bool = False,
    unread_only: bool = False,
    limit: int = Query(MESSAGES_PAGE_SIZE, ge=1, le=MESSAGES_MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0),
) -> dict:
    """
    Newest first, paged, with the counters the dashboard shows.

    Bounded deliberately: an unauthenticated endpoint feeds this table, so an
    unpaged query turns a spam flood into an inbox that cannot be opened. The
    ceiling is enforced by the parameter, not by the caller's good manners.

    `total` is the count for the CURRENT filter, so pagination is correct
    while searching. The unread/read/archived counters are unfiltered,
    because they are the inbox's headline figures and must not move when
    somebody types in the search box.
    """
    stmt = _message_filters(
        select(ContactMessage),
        q=q,
        unread_only=unread_only,
        status_filter=status_filter,
        archived=archived,
    ).order_by(ContactMessage.created_at.desc())

    total = db.scalar(
        _message_filters(
            select(func.count()).select_from(ContactMessage),
            q=q,
            unread_only=unread_only,
            status_filter=status_filter,
            archived=archived,
        )
    )

    rows = db.scalars(stmt.limit(limit).offset(offset)).all()

    def count(*where) -> int:
        return (
            db.scalar(select(func.count()).select_from(ContactMessage).where(*where))
            or 0
        )

    active = ContactMessage.is_archived.is_(False)
    return {
        "items": [ser.message_out(row) for row in rows],
        "total": total or 0,
        "limit": limit,
        "offset": offset,
        "counts": {
            "total": count(active),
            "unread": count(active, ContactMessage.is_read.is_(False)),
            "read": count(active, ContactMessage.is_read.is_(True)),
            "archived": count(ContactMessage.is_archived.is_(True)),
            "email_failed": count(
                ContactMessage.email_delivery_status == "failed"
            ),
        },
    }


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
    changed = False
    for field in ("is_read", "is_starred", "is_archived", "is_spam"):
        value = getattr(payload, field)
        if value is not None and getattr(row, field) != value:
            setattr(row, field, value)
            changed = True
    if changed:
        row.updated_at = utcnow()
    db.commit()
    return ser.message_out(row)


@messages_router.post("/{item_id}/resend", response_model=s.MessageOut)
def resend_notification(
    item_id: str,
    request: Request,
    db: DbDep,
    admin: AdminDep,
    settings: SettingsDep,
) -> dict:
    """
    Retry the notification for one message.

    Safe to press twice. `contact_notifier.notify` refuses to send when a
    Resend id is already recorded, so a second click reports the existing
    delivery rather than putting a second copy in the inbox.

    Returns the updated message either way; the caller reads
    `email_delivery_status` to see what happened. A failed retry is a
    recorded state, not an error response — the message itself is fine, and
    the admin needs to keep working.
    """
    row = get_or_404(db, ContactMessage, item_id)

    if not settings.email_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "email_not_configured",
                "message": (
                    "No email is configured, so there is nothing to retry. "
                    "Set RESEND_API_KEY, EMAIL_FROM and "
                    "CONTACT_NOTIFICATION_TO."
                ),
            },
        )

    result = contact_notifier.notify(settings, row.id, db=db)

    audit.record(
        db,
        request,
        action="contact.notification.resent",
        actor_id=admin.id,
        actor_email=admin.email,
        target_type="contact_message",
        target_id=str(row.id),
        # No addresses and no key: the audit log records that it happened.
        details={"status": result.status},
    )
    db.commit()
    db.refresh(row)
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
