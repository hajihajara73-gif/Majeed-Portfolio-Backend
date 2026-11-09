from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
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
from app.services import (
    contact_notifier,
    conversation,
    inbound_email,
    publish_service,
)

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


@messages_router.get("/{item_id}/thread", response_model=list[s.EmailMessageOut])
def message_thread(item_id: str, db: DbDep, admin: AdminDep) -> list[dict]:
    """The conversation for one enquiry, oldest first."""
    row = get_or_404(db, ContactMessage, item_id)
    return [
        ser.email_message_out(m) for m in conversation.thread_for(db, row.id)
    ]


@messages_router.get("/{item_id}/attachments/{attachment_id}")
def download_attachment(
    item_id: str,
    attachment_id: str,
    request: Request,
    db: DbDep,
    admin: AdminDep,
    settings: SettingsDep,
) -> Response:
    """
    Download one attachment from a received reply.

    AUTHENTICATED, and the signed URL is never disclosed. Resend issues a
    temporary public download URL; redirecting the browser to it would mean
    publishing an unauthenticated link to private mail, so the bytes are
    fetched server-side and streamed back under this session instead.

    Three checks stand between a request and the bytes:

      1. The attachment id must belong to a message on THIS conversation.
         Without that, an authenticated caller could walk ids and read
         attachments from any other thread.
      2. Resend's own metadata must pass the type allowlist and the size
         cap — re-checked at download time rather than trusted from the row,
         because the row records what the sender claimed.
      3. The bytes are counted as they arrive and abandoned past the cap.
    """
    row = get_or_404(db, ContactMessage, item_id)

    # Which inbound message on this conversation holds this attachment?
    owner = None
    for message in conversation.thread_for(db, row.id):
        for item in message.attachments or []:
            if isinstance(item, dict) and item.get("id") == attachment_id:
                owner = message
                break
        if owner is not None:
            break

    if owner is None or not owner.resend_email_id:
        # Same answer for "no such attachment" and "not on this thread":
        # the difference would confirm that an id exists elsewhere.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "attachment_not_found"},
        )

    payload = inbound_email.download_attachment(
        settings, owner.resend_email_id, attachment_id
    )

    audit.record(
        db,
        request,
        action="contact.attachment.downloaded"
        if payload
        else "contact.attachment.refused",
        actor_id=admin.id,
        actor_email=admin.email,
        target_type="contact_message",
        target_id=str(row.id),
        # No filename and no URL: an attachment name is sender-supplied
        # content, and the audit log is not the place for it.
        details={"attachment": attachment_id[:64]},
    )
    db.commit()

    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "attachment_unavailable",
                "message": (
                    "That attachment could not be fetched. It may be too "
                    "large, of a type that is not allowed, or expired."
                ),
            },
        )

    return Response(
        content=payload.content,
        media_type=payload.content_type,
        headers={
            # `attachment` so nothing from an inbound email is ever rendered
            # in the admin's origin, whatever its declared type.
            "Content-Disposition": (
                f'attachment; filename="{payload.filename}"'
            ),
            "X-Content-Type-Options": "nosniff",
        },
    )


@messages_router.post("/{item_id}/reply", response_model=s.ReplyResult)
def reply_to_message(
    item_id: str,
    payload: s.ReplyIn,
    request: Request,
    db: DbDep,
    admin: AdminDep,
    settings: SettingsDep,
) -> dict:
    """
    Reply to the visitor.

    A failed send is NOT an error response. The reply is recorded either
    way, and returning 500 would lose the operator's typed text and tell
    them nothing useful. The result carries the status so the UI can say
    what happened and offer the row for retry.

    The only hard failure is email being unconfigured, which is a
    deployment problem rather than something to retry.
    """
    row = get_or_404(db, ContactMessage, item_id)

    if not settings.email_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "email_not_configured",
                "message": (
                    "No email is configured, so a reply cannot be sent. Set "
                    "RESEND_API_KEY, EMAIL_FROM and ADMIN_EMAIL."
                ),
            },
        )

    sent, result = conversation.send_reply(
        settings,
        db,
        contact_message_id=row.id,
        body=payload.body,
        admin_id=admin.id,
    )

    audit.record(
        db,
        request,
        action="contact.reply.sent"
        if result.ok
        else "contact.reply.failed",
        actor_id=admin.id,
        actor_email=admin.email,
        target_type="contact_message",
        target_id=str(row.id),
        # Status only. No addresses, no body, no key.
        details={"status": result.status},
    )
    db.commit()

    return {
        "status": result.status,
        "message": (
            "Reply sent."
            if result.ok
            else f"The reply was saved but not delivered: {result.error}"
        ),
        "email": ser.email_message_out(sent) if sent else None,
    }


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
