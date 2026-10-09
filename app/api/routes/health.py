from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from app.api.deps import DbDep

router = APIRouter(tags=["health"])

# Mounted at the domain root, so it is included WITHOUT the `/api` prefix.
root_router = APIRouter(tags=["health"])


@root_router.get("/")
def root() -> dict[str, str]:
    """
    A greeting at the root, instead of a bare 404.

    The API has no routes at `/` — everything real lives under `/api` — so this
    exists purely so that opening the service in a browser says something
    deliberate rather than looking broken.

    It stays a fixed string on purpose. No version, no environment, no link to
    the docs: an unauthenticated endpoint that anyone can find should not
    volunteer anything about what is running behind it.
    """
    return {"message": "Welcome to Majeed Portfolio Backend"}


@router.get("/health")
def health(db: DbDep) -> dict[str, str]:
    """
    Liveness plus a real database round trip.

    A health check that does not touch the database will happily report healthy
    while every request fails, which is worse than having no check at all.
    """
    db.execute(text("SELECT 1"))
    return {"status": "ok"}
