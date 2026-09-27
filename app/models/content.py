"""
Content schema for the CMS.

Mirrors `src/types/content.ts`, which is already the public site's only content
contract — so Phase 6 can export a snapshot straight into `src/content/*.ts`
with no component changes.

Two conventions used throughout:

* **Singletons** (site, home, about, music settings) are one-row tables pinned
  by `CHECK (id = 1)`. A key/value settings blob would be looser but loses every
  column type and constraint, and "there is exactly one" is then only a
  convention rather than something the database enforces.
* **Short ordered string lists** (roles, note lines, technology highlights) are
  JSONB arrays rather than child tables. They are always read and written whole
  by one form field; a table per list would add joins and migrations for no
  editing benefit. Lists whose items carry their own fields DO get real tables.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.admin import JSONType
from app.models.base import Base, Timestamps, UUIDPrimaryKey
from app.models.types import UtcDateTime

SINGLETON_ID = 1


class _Singleton:
    """One row, enforced by the database rather than by good intentions."""

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=SINGLETON_ID)

    @classmethod
    def __declare_last__(cls) -> None:  # pragma: no cover - declarative hook
        pass


# ---------------------------------------------------------------------------
# Media library — one table for every uploaded file
# ---------------------------------------------------------------------------


class MediaKind:
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    DOCUMENT = "document"


class MediaAsset(UUIDPrimaryKey, Timestamps, Base):
    """
    Every uploaded file: images, the cabin video, audio, résumé, certificates.

    Deliberately ONE table rather than separate `documents` and `images` tables.
    The brief asks for a reusable file library, and that only works if an asset
    has a single identity that several records can point at — otherwise the same
    résumé gets uploaded twice and the two copies drift.
    """

    __tablename__ = "media_assets"

    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    # Path/key in object storage, not a URL — the storage backend can change.
    storage_key: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(127), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)

    # Populated for images and video; null for audio and documents.
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # SHA-256 of the bytes, so re-uploading an identical file can be detected
    # instead of silently duplicating it.
    checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)

    alt_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    folder: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(JSONType, nullable=True)

    # Private assets are never served publicly and never reach a snapshot.
    is_public: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        Index("ix_media_assets_kind", "kind"),
        Index("ix_media_assets_folder", "folder"),
        Index("ix_media_assets_checksum", "checksum"),
        CheckConstraint(
            "kind in ('image','video','audio','document')",
            name="media_kind_valid",
        ),
    )


# ---------------------------------------------------------------------------
# Site-wide
# ---------------------------------------------------------------------------


class SiteSettings(_Singleton, Timestamps, Base):
    __tablename__ = "site_settings"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    short_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    monogram: Mapped[str | None] = mapped_column(String(8), nullable=True)
    url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    locale: Mapped[str] = mapped_column(String(16), default="en", nullable=False)

    seo_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    seo_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    og_image_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="SET NULL"), nullable=True
    )
    favicon_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="SET NULL"), nullable=True
    )

    contact_email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    contact_location: Mapped[str | None] = mapped_column(String(255), nullable=True)

    footer_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    maintenance_mode: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    __table_args__ = (CheckConstraint("id = 1", name="single_row"),)


class SocialLink(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "social_links"

    label: Mapped[str] = mapped_column(String(64), nullable=False)
    href: Mapped[str] = mapped_column(String(512), nullable=False)
    is_external: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_visible: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


# ---------------------------------------------------------------------------
# Home
# ---------------------------------------------------------------------------


class HomeContent(_Singleton, Timestamps, Base):
    __tablename__ = "home_content"

    greeting: Mapped[str | None] = mapped_column(String(128), nullable=True)
    headline: Mapped[str | None] = mapped_column(Text, nullable=True)
    introduction: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Simple ordered string lists — see the module docstring.
    roles: Mapped[list[str] | None] = mapped_column(JSONType, nullable=True)
    technology_highlights: Mapped[list[str] | None] = mapped_column(
        JSONType, nullable=True
    )
    notes_label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    notes_lines: Mapped[list[str] | None] = mapped_column(JSONType, nullable=True)

    primary_cta_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    primary_cta_href: Mapped[str | None] = mapped_column(String(512), nullable=True)
    resume_media_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="SET NULL"), nullable=True
    )

    background_video_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="SET NULL"), nullable=True
    )
    background_poster_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (CheckConstraint("id = 1", name="single_row"),)


# ---------------------------------------------------------------------------
# About
# ---------------------------------------------------------------------------


class AboutContent(_Singleton, Timestamps, Base):
    __tablename__ = "about_content"

    introduction: Mapped[str | None] = mapped_column(Text, nullable=True)
    biography: Mapped[list[str] | None] = mapped_column(JSONType, nullable=True)
    interests: Mapped[list[str] | None] = mapped_column(JSONType, nullable=True)
    # [{label, value}] — verified facts only, never a computed vanity metric.
    facts: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONType, nullable=True
    )
    portrait_media_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (CheckConstraint("id = 1", name="single_row"),)


class EducationEntry(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "education_entries"

    degree: Mapped[str] = mapped_column(String(255), nullable=False)
    institution: Mapped[str] = mapped_column(String(255), nullable=False)
    # Free text, not dates: the certificates give "July 2023" and "Aug 2023",
    # and coercing those into a DATE invents a precision that does not exist.
    start_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    end_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_visible: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class ExpertiseItem(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "expertise_items"

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_visible: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------


class SkillCategory(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "skill_categories"

    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_visible: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    skills: Mapped[list[Skill]] = relationship(
        back_populates="category", cascade="all, delete-orphan"
    )


class Skill(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "skills"

    category_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("skill_categories.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Nullable on purpose. The public site shows no proficiency bars, and a
    # non-null default would invite inventing a number for every skill.
    proficiency: Mapped[int | None] = mapped_column(Integer, nullable=True)
    icon: Mapped[str | None] = mapped_column(String(64), nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_visible: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    category: Mapped[SkillCategory] = relationship(back_populates="skills")

    __table_args__ = (
        Index("ix_skills_category_id", "category_id"),
        CheckConstraint(
            "proficiency is null or (proficiency between 0 and 100)",
            name="proficiency_range",
        ),
    )


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


class Project(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "projects"

    slug: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    short_title: Mapped[str | None] = mapped_column(String(128), nullable=True)
    category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    organization: Mapped[str | None] = mapped_column(String(255), nullable=True)

    status: Mapped[str] = mapped_column(String(32), default="live", nullable=False)
    # Shown instead of a live link when there is no public deployment.
    deployment_note: Mapped[str | None] = mapped_column(String(128), nullable=True)

    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[list[str] | None] = mapped_column(JSONType, nullable=True)
    architecture: Mapped[str | None] = mapped_column(Text, nullable=True)
    problem: Mapped[str | None] = mapped_column(Text, nullable=True)
    challenges: Mapped[list[str] | None] = mapped_column(JSONType, nullable=True)
    solutions: Mapped[list[str] | None] = mapped_column(JSONType, nullable=True)
    results: Mapped[list[str] | None] = mapped_column(JSONType, nullable=True)
    features: Mapped[list[str] | None] = mapped_column(JSONType, nullable=True)

    github_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    live_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    cover_media_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="SET NULL"), nullable=True
    )

    is_featured: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Archive rather than delete, so a removed project can come back.
    archived_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    technologies: Mapped[list[ProjectTechnology]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    highlights: Mapped[list[ProjectHighlight]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    gallery: Mapped[list[ProjectMedia]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_projects_display_order", "display_order"),
        CheckConstraint(
            "status in ('live','local','in-progress','archived')",
            name="project_status_valid",
        ),
    )


class ProjectTechnology(UUIDPrimaryKey, Base):
    __tablename__ = "project_technologies"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    project: Mapped[Project] = relationship(back_populates="technologies")

    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_project_technology"),
    )


class ProjectHighlight(UUIDPrimaryKey, Base):
    __tablename__ = "project_highlights"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    project: Mapped[Project] = relationship(back_populates="highlights")

    __table_args__ = (Index("ix_project_highlights_project_id", "project_id"),)


class ProjectMedia(UUIDPrimaryKey, Base):
    """Screenshots. Points at the shared library rather than owning a file."""

    __tablename__ = "project_media"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    media_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("media_assets.id", ondelete="CASCADE"), nullable=False
    )
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    project: Mapped[Project] = relationship(back_populates="gallery")

    __table_args__ = (
        UniqueConstraint("project_id", "media_id", name="uq_project_media"),
    )


# ---------------------------------------------------------------------------
# Career
# ---------------------------------------------------------------------------


class CareerEntry(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "career_entries"

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    organization: Mapped[str | None] = mapped_column(String(255), nullable=True)
    entry_type: Mapped[str] = mapped_column(
        String(32), default="education", nullable=False
    )
    start_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    end_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    technologies: Mapped[list[str] | None] = mapped_column(JSONType, nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_visible: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "entry_type in ('education','experience','milestone')",
            name="career_type_valid",
        ),
    )


# ---------------------------------------------------------------------------
# Achievements
# ---------------------------------------------------------------------------


class Achievement(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "achievements"

    slug: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    achievement_type: Mapped[str] = mapped_column(
        String(32), default="certificate", nullable=False
    )
    organization: Mapped[str | None] = mapped_column(String(255), nullable=True)
    date_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    credential_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    verification_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Both nullable, and independently so: a credential can be listed without
    # publishing its scan. The DOTE typewriting certificate is exactly this —
    # real, but its PDF carries a date of birth and a photograph.
    document_media_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="SET NULL"), nullable=True
    )
    image_media_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="SET NULL"), nullable=True
    )

    is_featured: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_public: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    allow_download: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "achievement_type in "
            "('certificate','award','competition','presentation','milestone')",
            name="achievement_type_valid",
        ),
    )


# ---------------------------------------------------------------------------
# Music
# ---------------------------------------------------------------------------


class MusicTrack(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "music_tracks"

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    artist: Mapped[str | None] = mapped_column(String(255), nullable=True)
    album: Mapped[str | None] = mapped_column(String(255), nullable=True)
    genre: Mapped[str | None] = mapped_column(String(64), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    audio_media_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="SET NULL"), nullable=True
    )
    cover_media_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="SET NULL"), nullable=True
    )

    # Surfaced in the UI so stand-in audio can never be mistaken for a choice.
    is_placeholder: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class MusicSettings(_Singleton, Timestamps, Base):
    __tablename__ = "music_settings"

    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Kept for completeness, but the player never force-starts audio: browsers
    # block it and a UI that claims to be playing silence is a lie.
    autoplay: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    default_volume: Mapped[int] = mapped_column(Integer, default=40, nullable=False)
    loop: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    position: Mapped[str] = mapped_column(
        String(32), default="footer", nullable=False
    )

    __table_args__ = (
        CheckConstraint("id = 1", name="single_row"),
        CheckConstraint(
            "default_volume between 0 and 100", name="volume_range"
        ),
    )


# ---------------------------------------------------------------------------
# Contact messages
# ---------------------------------------------------------------------------


class ContactMessage(UUIDPrimaryKey, Base):
    __tablename__ = "contact_messages"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)

    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_starred: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_spam: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    replied_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

    __table_args__ = (
        Index("ix_contact_messages_created_at", "created_at"),
        Index("ix_contact_messages_is_read", "is_read"),
    )


# ---------------------------------------------------------------------------
# Publishing
# ---------------------------------------------------------------------------


class PublishSnapshot(UUIDPrimaryKey, Base):
    """
    One "Publish" press: the exact content the public site was built from.

    Storing the whole snapshot rather than a pointer to "current" state means a
    bad publish can be rolled back to a byte-identical earlier version, and it
    is always possible to answer "what did the site say on this date".
    """

    __tablename__ = "publish_snapshots"

    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True
    )
    content: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="pending", nullable=False
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(
        UtcDateTime, nullable=True
    )

    __table_args__ = (
        Index("ix_publish_snapshots_created_at", "created_at"),
        CheckConstraint(
            "status in ('pending','building','published','failed')",
            name="snapshot_status_valid",
        ),
    )
