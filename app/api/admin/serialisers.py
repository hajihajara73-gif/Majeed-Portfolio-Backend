"""
Row -> dict conversion.

Explicit rather than `from_attributes`, for one reason: every id in this schema
is a UUID column, and the API contract is strings. Converting in one place
means no endpoint can accidentally leak a `UUID` object into JSON and no
consumer has to handle two shapes.
"""

from __future__ import annotations

from typing import Any

from app.models.content import (
    AboutContent,
    Achievement,
    CareerEntry,
    ContactMessage,
    EducationEntry,
    ExpertiseItem,
    HomeContent,
    MediaAsset,
    Project,
    SiteSettings,
    Skill,
    SkillCategory,
    SocialLink,
)


def _id(value: Any) -> str | None:
    return str(value) if value is not None else None


def project_out(row: Project) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "slug": row.slug,
        "title": row.title,
        "short_title": row.short_title,
        "category": row.category,
        "organization": row.organization,
        "status": row.status,
        "deployment_note": row.deployment_note,
        "summary": row.summary,
        "description": row.description,
        "architecture": row.architecture,
        "problem": row.problem,
        "features": row.features,
        "challenges": row.challenges,
        "solutions": row.solutions,
        "results": row.results,
        "github_url": row.github_url,
        "live_url": row.live_url,
        "cover_media_id": _id(row.cover_media_id),
        "is_featured": row.is_featured,
        "is_published": row.is_published,
        "display_order": row.display_order,
        "archived_at": row.archived_at,
        "technologies": [
            t.name for t in sorted(row.technologies, key=lambda x: x.display_order)
        ],
        "highlights": [
            h.text for h in sorted(row.highlights, key=lambda x: x.display_order)
        ],
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def achievement_out(row: Achievement) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "slug": row.slug,
        "title": row.title,
        "achievement_type": row.achievement_type,
        "organization": row.organization,
        "date_label": row.date_label,
        "description": row.description,
        "credential_id": row.credential_id,
        "verification_url": row.verification_url,
        "document_media_id": _id(row.document_media_id),
        "image_media_id": _id(row.image_media_id),
        "is_featured": row.is_featured,
        "is_public": row.is_public,
        "allow_download": row.allow_download,
        "display_order": row.display_order,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def skill_out(row: Skill) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "category_id": str(row.category_id),
        "name": row.name,
        "note": row.note,
        "proficiency": row.proficiency,
        "icon": row.icon,
        "display_order": row.display_order,
        "is_visible": row.is_visible,
        "is_featured": row.is_featured,
    }


def skill_category_out(row: SkillCategory) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "slug": row.slug,
        "label": row.label,
        "summary": row.summary,
        "display_order": row.display_order,
        "is_visible": row.is_visible,
        "skills": [
            skill_out(s) for s in sorted(row.skills, key=lambda x: x.display_order)
        ],
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def career_out(row: CareerEntry) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "title": row.title,
        "organization": row.organization,
        "entry_type": row.entry_type,
        "start_label": row.start_label,
        "end_label": row.end_label,
        "is_current": row.is_current,
        "location": row.location,
        "description": row.description,
        "technologies": row.technologies,
        "display_order": row.display_order,
        "is_visible": row.is_visible,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def education_out(row: EducationEntry) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "degree": row.degree,
        "institution": row.institution,
        "start_label": row.start_label,
        "end_label": row.end_label,
        "location": row.location,
        "description": row.description,
        "display_order": row.display_order,
        "is_visible": row.is_visible,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def expertise_out(row: ExpertiseItem) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "title": row.title,
        "summary": row.summary,
        "display_order": row.display_order,
        "is_visible": row.is_visible,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def social_out(row: SocialLink) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "label": row.label,
        "href": row.href,
        "is_external": row.is_external,
        "display_order": row.display_order,
        "is_visible": row.is_visible,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def media_out(row: MediaAsset, reference_count: int = 0) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "kind": row.kind,
        "storage_key": row.storage_key,
        "original_filename": row.original_filename,
        "content_type": row.content_type,
        "byte_size": row.byte_size,
        "width": row.width,
        "height": row.height,
        "duration_seconds": row.duration_seconds,
        "alt_text": row.alt_text,
        "title": row.title,
        "folder": row.folder,
        "tags": row.tags,
        "is_public": row.is_public,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "reference_count": reference_count,
    }


def message_out(row: ContactMessage) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "name": row.name,
        "email": row.email,
        "subject": row.subject,
        "body": row.body,
        "is_read": row.is_read,
        "is_starred": row.is_starred,
        "is_archived": row.is_archived,
        "is_spam": row.is_spam,
        "replied_at": row.replied_at,
        "created_at": row.created_at,
    }


def site_out(row: SiteSettings) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "short_name": row.short_name,
        "monogram": row.monogram,
        "url": row.url,
        "locale": row.locale,
        "seo_title": row.seo_title,
        "seo_description": row.seo_description,
        "og_image_id": _id(row.og_image_id),
        "favicon_id": _id(row.favicon_id),
        "contact_email": row.contact_email,
        "contact_phone": row.contact_phone,
        "contact_location": row.contact_location,
        "footer_note": row.footer_note,
        "maintenance_mode": row.maintenance_mode,
        "updated_at": row.updated_at,
    }


def home_out(row: HomeContent) -> dict[str, Any]:
    return {
        "id": row.id,
        "greeting": row.greeting,
        "headline": row.headline,
        "introduction": row.introduction,
        "roles": row.roles,
        "technology_highlights": row.technology_highlights,
        "notes_label": row.notes_label,
        "notes_lines": row.notes_lines,
        "primary_cta_label": row.primary_cta_label,
        "primary_cta_href": row.primary_cta_href,
        "resume_media_id": _id(row.resume_media_id),
        "background_video_id": _id(row.background_video_id),
        "background_poster_id": _id(row.background_poster_id),
        "updated_at": row.updated_at,
    }


def about_out(row: AboutContent) -> dict[str, Any]:
    return {
        "id": row.id,
        "introduction": row.introduction,
        "biography": row.biography,
        "interests": row.interests,
        "facts": row.facts,
        "portrait_media_id": _id(row.portrait_media_id),
        "updated_at": row.updated_at,
    }
