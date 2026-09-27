from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from app.api.deps import DbDep

router = APIRouter(tags=["health"])


@router.get("/health")
def health(db: DbDep) -> dict[str, str]:
    """
    Liveness plus a real database round trip.

    A health check that does not touch the database will happily report healthy
    while every request fails, which is worse than having no check at all.
    """
    db.execute(text("SELECT 1"))
    return {"status": "ok"}
