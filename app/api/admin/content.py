"""
Resource routers.

The simple resources come straight from the factory. Projects and skill
categories are bespoke because they own child rows, and the singletons are
bespoke because there is exactly one of each — a POST/DELETE pair would be
meaningless.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from app.api.admin import serialisers as ser
from app.api.admin.resource import (
    apply_fields,
    build_resource_router,
    check_version,
    get_or_404,
    parse_uuid,
)
from app.api.deps import AdminDep, DbDep
from app.core import audit
from app.models.content import (
    AboutContent,
    Achievement,
    CareerEntry,
    EducationEntry,
    ExpertiseItem,
    HomeContent,
    MusicSettings,
    Project,
    ProjectHighlight,
    ProjectTechnology,
    SiteSettings,
    Skill,
    SkillCategory,
    SocialLink,
)
from app.schemas import content as s
from app.schemas.common import ReorderRequest

# --------------------------------------------------------------------------
# Simple resources
# --------------------------------------------------------------------------

achievements_router = build_resource_router(
    name="achievements",
    model=Achievement,
    create_schema=s.AchievementCreate,
    update_schema=s.AchievementUpdate,
    out_schema=s.AchievementOut,
    order_by=(Achievement.display_order, Achievement.title),
    serialise=ser.achievement_out,
    unique_field="slug",
)

career_router = build_resource_router(
    name="career",
    model=CareerEntry,
    create_schema=s.CareerCreate,
    update_schema=s.CareerUpdate,
    out_schema=s.CareerOut,
    order_by=(CareerEntry.display_order,),
    serialise=ser.career_out,
)

education_router = build_resource_router(
    name="education",
    model=EducationEntry,
    create_schema=s.EducationCreate,
    update_schema=s.EducationUpdate,
    out_schema=s.EducationOut,
    order_by=(EducationEntry.display_order,),
    serialise=ser.education_out,
)

expertise_router = build_resource_router(
    name="expertise",
    model=ExpertiseItem,
    create_schema=s.ExpertiseCreate,
    update_schema=s.ExpertiseUpdate,
    out_schema=s.ExpertiseOut,
    order_by=(ExpertiseItem.display_order,),
    serialise=ser.expertise_out,
)

social_router = build_resource_router(
    name="social",
    model=SocialLink,
    create_schema=s.SocialCreate,
    update_schema=s.SocialUpdate,
    out_schema=s.SocialOut,
    order_by=(SocialLink.display_order,),
    serialise=ser.social_out,
)

skills_router = build_resource_router(
    name="skills",
    model=Skill,
    create_schema=s.SkillCreate,
    update_schema=s.SkillUpdate,
    out_schema=s.SkillOut,
    order_by=(Skill.display_order, Skill.name),
    serialise=ser.skill_out,
)


# --------------------------------------------------------------------------
# Projects — owns technology and highlight child rows
# --------------------------------------------------------------------------

projects_router = APIRouter(prefix="/admin/projects", tags=["admin:projects"])


def _sync_children(db, row: Project, technologies, highlights) -> None:
    """
    Replace the child lists wholesale.

    Diffing would be more surgical, but these lists are a handful of items
    edited as a single form field. Replacing is easier to reason about and
    cannot leave an orphan behind.
    """
    # Go through the relationship collections rather than inserting by foreign
    # key. Inserting directly leaves the already-loaded collection on `row`
    # stale, so the response serialises as empty even though the rows exist.
    row.technologies.clear()
    row.highlights.clear()
    db.flush()
    for i, name in enumerate(technologies):
        row.technologies.append(ProjectTechnology(name=name, display_order=i))
    for i, text in enumerate(highlights):
        row.highlights.append(ProjectHighlight(text=text, display_order=i))
    db.flush()


@projects_router.get("", response_model=list[s.ProjectOut])
def list_projects(db: DbDep, admin: AdminDep) -> list[dict]:
    rows = db.scalars(
        select(Project).order_by(Project.display_order, Project.title)
    ).all()
    return [ser.project_out(row) for row in rows]


@projects_router.get("/{item_id}", response_model=s.ProjectOut)
def get_project(item_id: str, db: DbDep, admin: AdminDep) -> dict:
    return ser.project_out(get_or_404(db, Project, item_id))


@projects_router.post(
    "", response_model=s.ProjectOut, status_code=status.HTTP_201_CREATED
)
def create_project(
    payload: s.ProjectCreate, request: Request, db: DbDep, admin: AdminDep
) -> dict:
    clash = db.scalar(select(Project).where(Project.slug == payload.slug))
    if clash is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "duplicate", "message": "That slug is already in use."},
        )
    row = Project(slug=payload.slug, title=payload.title)
    apply_fields(row, payload, exclude=("technologies", "highlights"))
    db.add(row)
    db.flush()
    _sync_children(db, row, payload.technologies, payload.highlights)
    audit.record(
        db,
        request,
        action="content.projects.created",
        actor_id=admin.id,
        actor_email=admin.email,
        target_type="projects",
        target_id=str(row.id),
    )
    db.commit()
    return ser.project_out(row)


@projects_router.put("/{item_id}", response_model=s.ProjectOut)
def update_project(
    item_id: str,
    payload: s.ProjectUpdate,
    request: Request,
    db: DbDep,
    admin: AdminDep,
) -> dict:
    row = get_or_404(db, Project, item_id)
    check_version(row, payload.expected_updated_at)
    apply_fields(row, payload, exclude=("technologies", "highlights"))
    _sync_children(db, row, payload.technologies, payload.highlights)
    audit.record(
        db,
        request,
        action="content.projects.updated",
        actor_id=admin.id,
        actor_email=admin.email,
        target_type="projects",
        target_id=str(row.id),
    )
    db.commit()
    db.refresh(row)
    return ser.project_out(row)


@projects_router.post("/{item_id}/archive", response_model=s.ProjectOut)
def archive_project(
    item_id: str, request: Request, db: DbDep, admin: AdminDep
) -> dict:
    """
    Archive rather than delete.

    A project that disappears takes its screenshots, highlights and history
    with it. Archiving unpublishes it and keeps everything recoverable.
    """
    from app.models.base import utcnow

    row = get_or_404(db, Project, item_id)
    row.archived_at = utcnow()
    row.is_published = False
    row.is_featured = False
    audit.record(
        db,
        request,
        action="content.projects.archived",
        actor_id=admin.id,
        actor_email=admin.email,
        target_type="projects",
        target_id=item_id,
    )
    db.commit()
    return ser.project_out(row)


@projects_router.post("/{item_id}/restore", response_model=s.ProjectOut)
def restore_project(
    item_id: str, request: Request, db: DbDep, admin: AdminDep
) -> dict:
    row = get_or_404(db, Project, item_id)
    row.archived_at = None
    audit.record(
        db,
        request,
        action="content.projects.restored",
        actor_id=admin.id,
        actor_email=admin.email,
        target_type="projects",
        target_id=item_id,
    )
    db.commit()
    return ser.project_out(row)


@projects_router.delete("/{item_id}")
def delete_project(
    item_id: str, request: Request, db: DbDep, admin: AdminDep
) -> dict:
    row = get_or_404(db, Project, item_id)
    db.delete(row)  # children cascade
    audit.record(
        db,
        request,
        action="content.projects.deleted",
        actor_id=admin.id,
        actor_email=admin.email,
        target_type="projects",
        target_id=item_id,
    )
    db.commit()
    return {"deleted": item_id, "archived": False}


@projects_router.post("/reorder", response_model=list[s.ProjectOut])
def reorder_projects(
    parsed: ReorderRequest, request: Request, db: DbDep, admin: AdminDep
) -> list[dict]:
    ids = [parse_uuid(i.id) for i in parsed.items]
    rows = {
        r.id: r for r in db.scalars(select(Project).where(Project.id.in_(ids))).all()
    }
    if len(rows) != len(ids):
        raise HTTPException(status_code=404, detail="One or more items do not exist")
    for item in parsed.items:
        rows[parse_uuid(item.id)].display_order = item.display_order
    audit.record(
        db,
        request,
        action="content.projects.reordered",
        actor_id=admin.id,
        actor_email=admin.email,
        target_type="projects",
        details={"count": len(ids)},
    )
    db.commit()
    return [
        ser.project_out(r)
        for r in db.scalars(
            select(Project).order_by(Project.display_order, Project.title)
        ).all()
    ]


# --------------------------------------------------------------------------
# Skill categories — owns skills
# --------------------------------------------------------------------------

skill_categories_router = build_resource_router(
    name="skill-categories",
    model=SkillCategory,
    create_schema=s.SkillCategoryCreate,
    update_schema=s.SkillCategoryUpdate,
    out_schema=s.SkillCategoryOut,
    order_by=(SkillCategory.display_order,),
    serialise=ser.skill_category_out,
    unique_field="slug",
)


# --------------------------------------------------------------------------
# Singletons
# --------------------------------------------------------------------------

singleton_router = APIRouter(prefix="/admin", tags=["admin:singletons"])


def _get_singleton(db, model, factory):
    row = db.get(model, 1)
    if row is None:
        row = factory()
        db.add(row)
        db.flush()
    return row


@singleton_router.get("/site", response_model=s.SiteSettingsOut)
def get_site(db: DbDep, admin: AdminDep) -> dict:
    return ser.site_out(
        _get_singleton(db, SiteSettings, lambda: SiteSettings(id=1, name="Untitled"))
    )


@singleton_router.put("/site", response_model=s.SiteSettingsOut)
def update_site(
    payload: s.SiteSettingsIn, request: Request, db: DbDep, admin: AdminDep
) -> dict:
    row = _get_singleton(
        db, SiteSettings, lambda: SiteSettings(id=1, name=payload.name)
    )
    check_version(row, payload.expected_updated_at)
    apply_fields(row, payload)
    audit.record(
        db,
        request,
        action="content.site.updated",
        actor_id=admin.id,
        actor_email=admin.email,
        target_type="site",
    )
    db.commit()
    return ser.site_out(row)


@singleton_router.get("/home", response_model=s.HomeOut)
def get_home(db: DbDep, admin: AdminDep) -> dict:
    return ser.home_out(_get_singleton(db, HomeContent, lambda: HomeContent(id=1)))


@singleton_router.put("/home", response_model=s.HomeOut)
def update_home(
    payload: s.HomeIn, request: Request, db: DbDep, admin: AdminDep
) -> dict:
    row = _get_singleton(db, HomeContent, lambda: HomeContent(id=1))
    check_version(row, payload.expected_updated_at)
    apply_fields(row, payload)
    audit.record(
        db,
        request,
        action="content.home.updated",
        actor_id=admin.id,
        actor_email=admin.email,
        target_type="home",
    )
    db.commit()
    return ser.home_out(row)


@singleton_router.get("/about", response_model=s.AboutOut)
def get_about(db: DbDep, admin: AdminDep) -> dict:
    return ser.about_out(_get_singleton(db, AboutContent, lambda: AboutContent(id=1)))


@singleton_router.put("/about", response_model=s.AboutOut)
def update_about(
    payload: s.AboutIn, request: Request, db: DbDep, admin: AdminDep
) -> dict:
    row = _get_singleton(db, AboutContent, lambda: AboutContent(id=1))
    check_version(row, payload.expected_updated_at)
    apply_fields(row, payload)
    audit.record(
        db,
        request,
        action="content.about.updated",
        actor_id=admin.id,
        actor_email=admin.email,
        target_type="about",
    )
    db.commit()
    return ser.about_out(row)


@singleton_router.get("/music-settings")
def get_music_settings(db: DbDep, admin: AdminDep) -> dict:
    row = _get_singleton(db, MusicSettings, lambda: MusicSettings(id=1))
    return {
        "id": row.id,
        "is_enabled": row.is_enabled,
        "autoplay": row.autoplay,
        "default_volume": row.default_volume,
        "loop": row.loop,
        "position": row.position,
        "updated_at": row.updated_at,
    }
