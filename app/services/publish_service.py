"""
Publish: turn the current database state into an immutable content snapshot.

The public site never queries this database. A publish builds a complete JSON
snapshot, validates it, stores it in `publish_snapshots`, and only then is it
eligible to become the content the static build reads.

The safety property that matters: **a failed publish must not disturb the
currently published snapshot.** That is achieved by never mutating an existing
snapshot row. A new attempt inserts a new row; if validation or the build fails
it is marked `failed` and the previous `published` row is untouched, so
`current_snapshot()` keeps returning the last good one.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.base import utcnow
from app.models.content import (
    AboutContent,
    Achievement,
    CareerEntry,
    EducationEntry,
    ExpertiseItem,
    HomeContent,
    MediaAsset,
    MusicSettings,
    MusicTrack,
    Project,
    PublishSnapshot,
    SiteSettings,
    SkillCategory,
    SocialLink,
)


@dataclass
class ValidationResult:
    """`blocking` prevents a publish; `warnings` are shown but allowed."""

    blocking: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.blocking


class PublishError(Exception):
    def __init__(self, result: ValidationResult):
        super().__init__("Publish validation failed")
        self.result = result


def _media_map(db: Session) -> dict[str, dict[str, Any]]:
    """Public assets only — a private file must never reach a snapshot."""
    rows = db.scalars(select(MediaAsset)).all()
    return {
        str(row.id): {
            "id": str(row.id),
            "kind": row.kind,
            "url": f"/{row.storage_key}",
            "alt": row.alt_text,
            "width": row.width,
            "height": row.height,
            "is_public": row.is_public,
        }
        for row in rows
    }


def _asset(media: dict[str, dict[str, Any]], key: Any) -> dict[str, Any] | None:
    if key is None:
        return None
    entry = media.get(str(key))
    if entry is None or not entry["is_public"]:
        return None
    return {k: v for k, v in entry.items() if k != "is_public"}


def build_snapshot(db: Session) -> dict[str, Any]:
    """Assemble the full public content payload."""
    media = _media_map(db)

    site = db.get(SiteSettings, 1)
    home = db.get(HomeContent, 1)
    about = db.get(AboutContent, 1)
    music_settings = db.get(MusicSettings, 1)

    projects = db.scalars(
        select(Project)
        .where(Project.is_published.is_(True), Project.archived_at.is_(None))
        .order_by(Project.display_order, Project.title)
    ).all()

    achievements = db.scalars(
        select(Achievement)
        .where(Achievement.is_public.is_(True))
        .order_by(Achievement.display_order)
    ).all()

    categories = db.scalars(
        select(SkillCategory)
        .where(SkillCategory.is_visible.is_(True))
        .order_by(SkillCategory.display_order)
    ).all()

    career = db.scalars(
        select(CareerEntry)
        .where(CareerEntry.is_visible.is_(True))
        .order_by(CareerEntry.display_order)
    ).all()

    education = db.scalars(
        select(EducationEntry)
        .where(EducationEntry.is_visible.is_(True))
        .order_by(EducationEntry.display_order)
    ).all()

    expertise = db.scalars(
        select(ExpertiseItem)
        .where(ExpertiseItem.is_visible.is_(True))
        .order_by(ExpertiseItem.display_order)
    ).all()

    social = db.scalars(
        select(SocialLink)
        .where(SocialLink.is_visible.is_(True))
        .order_by(SocialLink.display_order)
    ).all()

    track = db.scalar(
        select(MusicTrack)
        .where(MusicTrack.is_enabled.is_(True))
        .order_by(MusicTrack.display_order)
    )

    return {
        "site": {
            "name": site.name if site else None,
            "shortName": site.short_name if site else None,
            "monogram": site.monogram if site else None,
            "url": site.url if site else None,
            "locale": site.locale if site else "en",
            "seo": {
                "title": site.seo_title if site else None,
                "description": site.seo_description if site else None,
                "ogImage": _asset(media, site.og_image_id) if site else None,
            },
            "footerNote": site.footer_note if site else None,
            "maintenanceMode": site.maintenance_mode if site else False,
            "social": [
                {"label": s.label, "href": s.href, "external": s.is_external}
                for s in social
            ],
        },
        "home": {
            "greeting": home.greeting if home else None,
            "headline": home.headline if home else None,
            "introduction": home.introduction if home else None,
            "roles": (home.roles or []) if home else [],
            "technologyHighlights": (home.technology_highlights or []) if home else [],
            "notes": {
                "label": home.notes_label if home else None,
                "lines": (home.notes_lines or []) if home else [],
            },
            "primaryCta": {
                "label": home.primary_cta_label if home else None,
                "href": home.primary_cta_href if home else None,
            },
            "resume": _asset(media, home.resume_media_id) if home else None,
            "background": {
                "video": _asset(media, home.background_video_id) if home else None,
                "poster": _asset(media, home.background_poster_id) if home else None,
            },
            "music": (
                {
                    "title": track.title,
                    "artist": track.artist,
                    "audio": _asset(media, track.audio_media_id),
                    "isPlaceholder": track.is_placeholder,
                    "defaultVolume": (
                        music_settings.default_volume / 100
                        if music_settings
                        else 0.4
                    ),
                    "enabled": music_settings.is_enabled if music_settings else True,
                }
                if track
                else None
            ),
        },
        "about": {
            "introduction": about.introduction if about else None,
            "biography": (about.biography or []) if about else [],
            "interests": (about.interests or []) if about else [],
            "facts": (about.facts or []) if about else [],
            "portrait": _asset(media, about.portrait_media_id) if about else None,
            "education": [
                {
                    "degree": e.degree,
                    "institution": e.institution,
                    "start": e.start_label,
                    "end": e.end_label,
                    "location": e.location,
                    "description": e.description,
                }
                for e in education
            ],
            "expertise": [
                {"title": x.title, "summary": x.summary} for x in expertise
            ],
        },
        "skills": [
            {
                "id": c.slug,
                "label": c.label,
                "summary": c.summary,
                "skills": [
                    {"name": sk.name, "note": sk.note}
                    for sk in sorted(c.skills, key=lambda x: x.display_order)
                    if sk.is_visible
                ],
            }
            for c in categories
        ],
        "projects": [
            {
                "slug": p.slug,
                "title": p.title,
                "shortTitle": p.short_title,
                "category": p.category,
                "organization": p.organization,
                "status": p.status,
                "deploymentNote": p.deployment_note,
                "summary": p.summary,
                "description": p.description or [],
                "architecture": p.architecture,
                "problem": p.problem,
                "features": p.features or [],
                "challenges": p.challenges or [],
                "solutions": p.solutions or [],
                "results": p.results or [],
                "githubUrl": p.github_url,
                "liveUrl": p.live_url,
                "cover": _asset(media, p.cover_media_id),
                "featured": p.is_featured,
                "order": p.display_order,
                "technologies": [
                    t.name
                    for t in sorted(p.technologies, key=lambda x: x.display_order)
                ],
                "highlights": [
                    h.text for h in sorted(p.highlights, key=lambda x: x.display_order)
                ],
            }
            for p in projects
        ],
        "career": [
            {
                "id": str(c.id),
                "title": c.title,
                "organization": c.organization,
                "type": c.entry_type,
                "start": c.start_label,
                "end": "present" if c.is_current else c.end_label,
                "location": c.location,
                "description": c.description,
                "technologies": c.technologies or [],
            }
            for c in career
        ],
        "achievements": [
            {
                "id": a.slug,
                "title": a.title,
                "type": a.achievement_type,
                "organization": a.organization,
                "date": a.date_label,
                "description": a.description,
                "credentialId": a.credential_id,
                "verificationUrl": a.verification_url,
                # Both resolve to None when the asset is private or absent —
                # which is how a credential stays listed while its scan is
                # withheld.
                "image": _asset(media, a.image_media_id),
                "document": (
                    _asset(media, a.document_media_id) if a.allow_download else None
                ),
                "featured": a.is_featured,
            }
            for a in achievements
        ],
    }


def validate_snapshot(snapshot: dict[str, Any]) -> ValidationResult:
    result = ValidationResult()

    site = snapshot.get("site") or {}
    if not site.get("name"):
        result.blocking.append("Site name is required.")
    if not site.get("url"):
        result.warnings.append(
            "No site URL set — canonical links, sitemap and social cards will be wrong."
        )

    projects = snapshot.get("projects") or []
    if not projects:
        result.blocking.append("At least one published project is required.")
    seen_slugs: set[str] = set()
    for project in projects:
        slug = project.get("slug")
        if slug in seen_slugs:
            result.blocking.append(f"Duplicate project slug: {slug}")
        seen_slugs.add(slug)
        if not project.get("summary"):
            result.warnings.append(f"Project '{slug}' has no summary.")
        if project.get("status") != "local" and not project.get("liveUrl"):
            result.warnings.append(
                f"Project '{slug}' is not marked local but has no live URL."
            )

    if not (snapshot.get("about") or {}).get("introduction"):
        result.warnings.append("About has no introduction.")

    home = snapshot.get("home") or {}
    if not (home.get("background") or {}).get("poster"):
        result.warnings.append(
            "No background poster — the hero will have no first paint image."
        )

    # Anything still carrying a placeholder marker must not go live.
    serialised = json.dumps(snapshot)
    if "TODO_REPLACE_" in serialised:
        result.blocking.append(
            "Content still contains TODO_REPLACE_ placeholders."
        )

    return result


def checksum(snapshot: dict[str, Any]) -> str:
    """Stable hash: sorted keys so an unchanged snapshot hashes identically."""
    payload = json.dumps(
        snapshot, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def current_snapshot(db: Session) -> PublishSnapshot | None:
    """The last successfully published snapshot — what the site is serving."""
    return db.scalar(
        select(PublishSnapshot)
        .where(PublishSnapshot.status == "published")
        .order_by(PublishSnapshot.published_at.desc())
        .limit(1)
    )


def create_snapshot(
    db: Session, *, actor_id: Any, note: str | None
) -> tuple[PublishSnapshot, ValidationResult]:
    """
    Build, validate and record a publish attempt.

    A failed attempt is still recorded, with status `failed`, so there is a
    trail of what was tried. Crucially it never touches the existing
    `published` row.
    """
    snapshot = build_snapshot(db)
    result = validate_snapshot(snapshot)
    digest = checksum(snapshot)
    now = utcnow()

    row = PublishSnapshot(
        created_by_id=actor_id,
        content=snapshot,
        checksum=digest,
        status="published" if result.ok else "failed",
        note=note,
        created_at=now,
        published_at=now if result.ok else None,
    )
    db.add(row)
    return row, result
