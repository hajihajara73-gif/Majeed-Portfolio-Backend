"""Request/response schemas for the CMS resources."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from app.schemas.common import (
    ORMModel,
    Versioned,
    validate_public_url,
    validate_slug,
)

ProjectStatus = Literal["live", "local", "in-progress", "archived"]
AchievementType = Literal[
    "certificate", "award", "competition", "presentation", "milestone"
]
CareerType = Literal["education", "experience", "milestone"]


# ---------------------------------------------------------------- projects --


class ProjectChildIn(ORMModel):
    name: str = Field(min_length=1, max_length=64)
    display_order: int = Field(default=0, ge=0, le=10_000)


class ProjectHighlightIn(ORMModel):
    text: str = Field(min_length=1, max_length=2000)
    display_order: int = Field(default=0, ge=0, le=10_000)


class ProjectBase(Versioned):
    title: str = Field(min_length=1, max_length=255)
    short_title: str | None = Field(default=None, max_length=128)
    category: str | None = Field(default=None, max_length=128)
    organization: str | None = Field(default=None, max_length=255)
    status: ProjectStatus = "live"
    deployment_note: str | None = Field(default=None, max_length=128)

    summary: str | None = None
    description: list[str] | None = None
    architecture: str | None = None
    problem: str | None = None
    features: list[str] | None = None
    challenges: list[str] | None = None
    solutions: list[str] | None = None
    results: list[str] | None = None

    github_url: str | None = Field(default=None, max_length=512)
    live_url: str | None = Field(default=None, max_length=512)
    cover_media_id: str | None = None

    is_featured: bool = False
    is_published: bool = True
    display_order: int = Field(default=0, ge=0, le=10_000)

    technologies: list[str] = Field(default_factory=list, max_length=100)
    highlights: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("github_url", "live_url")
    @classmethod
    def _urls(cls, value: str | None) -> str | None:
        return validate_public_url(value)

    @field_validator("technologies", "highlights")
    @classmethod
    def _no_blank_entries(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item and item.strip()]


class ProjectCreate(ProjectBase):
    slug: str = Field(min_length=1, max_length=128)

    @field_validator("slug")
    @classmethod
    def _slug(cls, value: str) -> str:
        return validate_slug(value)


class ProjectUpdate(ProjectBase):
    """Slug is intentionally absent: changing it breaks any published link."""


class ProjectOut(ORMModel):
    id: str
    slug: str
    title: str
    short_title: str | None
    category: str | None
    organization: str | None
    status: str
    deployment_note: str | None
    summary: str | None
    description: list[str] | None
    architecture: str | None
    problem: str | None
    features: list[str] | None
    challenges: list[str] | None
    solutions: list[str] | None
    results: list[str] | None
    github_url: str | None
    live_url: str | None
    cover_media_id: str | None
    is_featured: bool
    is_published: bool
    display_order: int
    archived_at: datetime | None
    technologies: list[str]
    highlights: list[str]
    created_at: datetime
    updated_at: datetime


# ------------------------------------------------------------ achievements --


class AchievementBase(Versioned):
    title: str = Field(min_length=1, max_length=255)
    achievement_type: AchievementType = "certificate"
    organization: str | None = Field(default=None, max_length=255)
    date_label: str | None = Field(default=None, max_length=64)
    description: str | None = None
    credential_id: str | None = Field(default=None, max_length=128)
    verification_url: str | None = Field(default=None, max_length=512)
    document_media_id: str | None = None
    image_media_id: str | None = None
    is_featured: bool = False
    is_public: bool = True
    allow_download: bool = True
    display_order: int = Field(default=0, ge=0, le=10_000)

    @field_validator("verification_url")
    @classmethod
    def _url(cls, value: str | None) -> str | None:
        return validate_public_url(value)


class AchievementCreate(AchievementBase):
    slug: str = Field(min_length=1, max_length=128)

    @field_validator("slug")
    @classmethod
    def _slug(cls, value: str) -> str:
        return validate_slug(value)


class AchievementUpdate(AchievementBase):
    pass


class AchievementOut(ORMModel):
    id: str
    slug: str
    title: str
    achievement_type: str
    organization: str | None
    date_label: str | None
    description: str | None
    credential_id: str | None
    verification_url: str | None
    document_media_id: str | None
    image_media_id: str | None
    is_featured: bool
    is_public: bool
    allow_download: bool
    display_order: int
    created_at: datetime
    updated_at: datetime


# ------------------------------------------------------------------ skills --


class SkillCategoryBase(Versioned):
    label: str = Field(min_length=1, max_length=128)
    summary: str | None = None
    display_order: int = Field(default=0, ge=0, le=10_000)
    is_visible: bool = True


class SkillCategoryCreate(SkillCategoryBase):
    slug: str = Field(min_length=1, max_length=64)

    @field_validator("slug")
    @classmethod
    def _slug(cls, value: str) -> str:
        return validate_slug(value)


class SkillCategoryUpdate(SkillCategoryBase):
    pass


class SkillOut(ORMModel):
    id: str
    category_id: str
    name: str
    note: str | None
    proficiency: int | None
    icon: str | None
    display_order: int
    is_visible: bool
    is_featured: bool


class SkillCategoryOut(ORMModel):
    id: str
    slug: str
    label: str
    summary: str | None
    display_order: int
    is_visible: bool
    skills: list[SkillOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class SkillBase(Versioned):
    category_id: str
    name: str = Field(min_length=1, max_length=128)
    note: str | None = None
    # Nullable on purpose: the public site shows no proficiency bars, and a
    # default would invite inventing a number.
    proficiency: int | None = Field(default=None, ge=0, le=100)
    icon: str | None = Field(default=None, max_length=64)
    display_order: int = Field(default=0, ge=0, le=10_000)
    is_visible: bool = True
    is_featured: bool = False


class SkillCreate(SkillBase):
    pass


class SkillUpdate(SkillBase):
    pass


# ------------------------------------------------------- career / education --


class CareerBase(Versioned):
    title: str = Field(min_length=1, max_length=255)
    organization: str | None = Field(default=None, max_length=255)
    entry_type: CareerType = "education"
    start_label: str | None = Field(default=None, max_length=64)
    end_label: str | None = Field(default=None, max_length=64)
    is_current: bool = False
    location: str | None = Field(default=None, max_length=255)
    description: str | None = None
    technologies: list[str] | None = None
    display_order: int = Field(default=0, ge=0, le=10_000)
    is_visible: bool = True


class CareerCreate(CareerBase):
    pass


class CareerUpdate(CareerBase):
    pass


class CareerOut(ORMModel):
    id: str
    title: str
    organization: str | None
    entry_type: str
    start_label: str | None
    end_label: str | None
    is_current: bool
    location: str | None
    description: str | None
    technologies: list[str] | None
    display_order: int
    is_visible: bool
    created_at: datetime
    updated_at: datetime


class EducationBase(Versioned):
    degree: str = Field(min_length=1, max_length=255)
    institution: str = Field(min_length=1, max_length=255)
    start_label: str | None = Field(default=None, max_length=64)
    end_label: str | None = Field(default=None, max_length=64)
    location: str | None = Field(default=None, max_length=255)
    description: str | None = None
    display_order: int = Field(default=0, ge=0, le=10_000)
    is_visible: bool = True


class EducationCreate(EducationBase):
    pass


class EducationUpdate(EducationBase):
    pass


class EducationOut(ORMModel):
    id: str
    degree: str
    institution: str
    start_label: str | None
    end_label: str | None
    location: str | None
    description: str | None
    display_order: int
    is_visible: bool
    created_at: datetime
    updated_at: datetime


# ------------------------------------------------------------ expertise -----


class ExpertiseBase(Versioned):
    title: str = Field(min_length=1, max_length=255)
    summary: str | None = None
    display_order: int = Field(default=0, ge=0, le=10_000)
    is_visible: bool = True


class ExpertiseCreate(ExpertiseBase):
    pass


class ExpertiseUpdate(ExpertiseBase):
    pass


class ExpertiseOut(ORMModel):
    id: str
    title: str
    summary: str | None
    display_order: int
    is_visible: bool
    created_at: datetime
    updated_at: datetime


# ------------------------------------------------------------ social links --


class SocialBase(Versioned):
    label: str = Field(min_length=1, max_length=64)
    href: str = Field(min_length=1, max_length=512)
    is_external: bool = True
    display_order: int = Field(default=0, ge=0, le=10_000)
    is_visible: bool = True

    @field_validator("href")
    @classmethod
    def _url(cls, value: str) -> str:
        result = validate_public_url(value)
        if result is None:
            raise ValueError("A link is required")
        return result


class SocialCreate(SocialBase):
    pass


class SocialUpdate(SocialBase):
    pass


class SocialOut(ORMModel):
    id: str
    label: str
    href: str
    is_external: bool
    display_order: int
    is_visible: bool
    created_at: datetime
    updated_at: datetime


# ------------------------------------------------------------------- media --


class MediaOut(ORMModel):
    id: str
    kind: str
    storage_key: str
    original_filename: str
    content_type: str
    byte_size: int
    width: int | None
    height: int | None
    duration_seconds: int | None
    alt_text: str | None
    title: str | None
    folder: str | None
    tags: list[str] | None
    is_public: bool
    created_at: datetime
    updated_at: datetime
    # Populated by the list endpoint so the UI can refuse to delete a file
    # something still points at.
    reference_count: int = 0


class MediaUpdate(Versioned):
    alt_text: str | None = None
    title: str | None = Field(default=None, max_length=255)
    folder: str | None = Field(default=None, max_length=128)
    tags: list[str] | None = None
    is_public: bool = True


# ---------------------------------------------------------------- messages --


class MessageOut(ORMModel):
    id: str
    name: str
    email: str
    subject: str | None
    body: str
    is_read: bool
    is_starred: bool
    is_archived: bool
    is_spam: bool
    replied_at: datetime | None
    created_at: datetime


class MessageUpdate(Versioned):
    is_read: bool | None = None
    is_starred: bool | None = None
    is_archived: bool | None = None
    is_spam: bool | None = None


# -------------------------------------------------------------- singletons --


class SiteSettingsIn(Versioned):
    name: str = Field(min_length=1, max_length=255)
    short_name: str | None = Field(default=None, max_length=128)
    monogram: str | None = Field(default=None, max_length=8)
    url: str | None = Field(default=None, max_length=512)
    locale: str = Field(default="en", max_length=16)
    seo_title: str | None = Field(default=None, max_length=255)
    seo_description: str | None = None
    og_image_id: str | None = None
    favicon_id: str | None = None
    contact_email: str | None = Field(default=None, max_length=254)
    contact_phone: str | None = Field(default=None, max_length=64)
    contact_location: str | None = Field(default=None, max_length=255)
    footer_note: str | None = None
    maintenance_mode: bool = False

    @field_validator("url")
    @classmethod
    def _url(cls, value: str | None) -> str | None:
        return validate_public_url(value)


class SiteSettingsOut(ORMModel):
    id: int
    name: str
    short_name: str | None
    monogram: str | None
    url: str | None
    locale: str
    seo_title: str | None
    seo_description: str | None
    og_image_id: str | None
    favicon_id: str | None
    contact_email: str | None
    contact_phone: str | None
    contact_location: str | None
    footer_note: str | None
    maintenance_mode: bool
    updated_at: datetime


class HomeIn(Versioned):
    greeting: str | None = Field(default=None, max_length=128)
    headline: str | None = None
    introduction: str | None = None
    roles: list[str] | None = None
    technology_highlights: list[str] | None = None
    notes_label: str | None = Field(default=None, max_length=128)
    notes_lines: list[str] | None = None
    primary_cta_label: str | None = Field(default=None, max_length=64)
    primary_cta_href: str | None = Field(default=None, max_length=512)
    resume_media_id: str | None = None
    background_video_id: str | None = None
    background_poster_id: str | None = None

    @field_validator("primary_cta_href")
    @classmethod
    def _url(cls, value: str | None) -> str | None:
        return validate_public_url(value)


class HomeOut(ORMModel):
    id: int
    greeting: str | None
    headline: str | None
    introduction: str | None
    roles: list[str] | None
    technology_highlights: list[str] | None
    notes_label: str | None
    notes_lines: list[str] | None
    primary_cta_label: str | None
    primary_cta_href: str | None
    resume_media_id: str | None
    background_video_id: str | None
    background_poster_id: str | None
    updated_at: datetime


class AboutIn(Versioned):
    introduction: str | None = None
    biography: list[str] | None = None
    interests: list[str] | None = None
    facts: list[dict[str, str]] | None = None
    portrait_media_id: str | None = None


class AboutOut(ORMModel):
    id: int
    introduction: str | None
    biography: list[str] | None
    interests: list[str] | None
    facts: list[dict[str, str]] | None
    portrait_media_id: str | None
    updated_at: datetime


# ------------------------------------------------------------------ publish --


class PublishRequest(Versioned):
    note: str | None = Field(default=None, max_length=500)


class PublishDiff(ORMModel):
    projects: int
    achievements: int
    skills: int
    career: int
    education: int
    social_links: int
    media: int


class PublishPreview(ORMModel):
    counts: PublishDiff
    warnings: list[str]
    blocking: list[str]
    last_published_at: datetime | None
    last_checksum: str | None


class RollbackRequest(ORMModel):
    note: str | None = Field(default=None, max_length=500)


class DeployOut(ORMModel):
    """
    Outcome of the build hook. Never carries the hook URL.

    `triggered=False` with a published snapshot is a normal, reportable state:
    the content is saved and the site simply has not rebuilt yet.
    """

    triggered: bool
    status_code: int | None = None
    detail: str | None = None


class DeployStatus(ORMModel):
    configured: bool


class SnapshotOut(ORMModel):
    id: str
    checksum: str
    status: str
    note: str | None
    created_at: datetime
    published_at: datetime | None
    # Present only on the response to a publish or rollback — listing old
    # snapshots says nothing about deploys that happened at the time.
    deploy: DeployOut | None = None
