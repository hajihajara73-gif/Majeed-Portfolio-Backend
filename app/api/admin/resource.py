"""
Generic CRUD router factory.

Ten resources need the same five endpoints with the same authorisation, the
same optimistic-locking rule, the same audit entry and the same error shapes.
Writing that ten times guarantees they drift — one forgets the version check,
another returns a different error body. So the behaviour is defined once here
and each resource supplies only what is genuinely specific to it.

Every router produced depends on `AdminDep`, so authorisation is enforced by
the backend on every request regardless of what the admin UI shows.
"""

# NOTE: deliberately no `from __future__ import annotations` in this module.
# The factory passes schema *classes* as parameter annotations
# (`payload: create_schema`). With postponed evaluation those become the string
# "create_schema", which Pydantic cannot resolve — it is a local variable of the
# factory, not a module global — and OpenAPI generation fails at import time.
import uuid
from collections.abc import Callable, Sequence
from typing import Any, TypeVar

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import Uuid, func, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

from app.api.deps import AdminDep, DbDep
from app.core import audit
from app.models.base import Base
from app.schemas.common import DeleteResponse, ReorderRequest

ModelT = TypeVar("ModelT", bound=Base)


def parse_uuid(value: str) -> uuid.UUID:
    """A malformed id is a 404, never a 500."""
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Not found"
        ) from None


def get_or_404(db: Session, model: type[ModelT], item_id: str) -> ModelT:
    row = db.get(model, parse_uuid(item_id))
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Not found"
        )
    return row


def check_version(row: Any, expected: Any) -> None:
    """
    Optimistic locking.

    If the client tells us which version it edited and the row has moved on,
    refuse rather than overwrite. Silently winning last-write is how two tabs
    quietly destroy each other's work.
    """
    if expected is None:
        return
    current = getattr(row, "updated_at", None)
    if current is None:
        return
    # Compare to the second: JSON round-tripping loses sub-second precision.
    if int(current.timestamp()) != int(expected.timestamp()):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "stale_write",
                "message": (
                    "This item changed since you opened it. "
                    "Reload to see the current version."
                ),
            },
        )


def _coerce(row: Any, key: str, value: Any) -> Any:
    """
    Convert incoming strings to UUID where the column expects one.

    The API contract is string ids, the schema uses real `uuid` columns, and
    SQLAlchemy will not bridge the two — it fails deep inside the driver with
    `'str' object has no attribute 'hex'`. Doing the conversion here means
    every `*_media_id` field on every resource is handled once rather than
    being forgotten on the next one added.
    """
    if not isinstance(value, str):
        return value
    column = sa_inspect(type(row)).columns.get(key)
    if column is None or not isinstance(column.type, Uuid):
        return value
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "invalid_reference",
                "message": f"'{key}' is not a valid id.",
            },
        ) from None


def apply_fields(row: Any, payload: BaseModel, exclude: Sequence[str] = ()) -> None:
    skip = {"expected_updated_at", *exclude}
    for key, value in payload.model_dump(exclude_unset=False).items():
        if key in skip:
            continue
        if hasattr(row, key):
            setattr(row, key, _coerce(row, key, value))


def build_resource_router(
    *,
    name: str,
    model: type[Base],
    create_schema: type[BaseModel],
    update_schema: type[BaseModel],
    out_schema: type[BaseModel],
    order_by: Sequence[Any],
    serialise: Callable[[Any], dict[str, Any]],
    unique_field: str | None = None,
    prefix: str | None = None,
) -> APIRouter:
    router = APIRouter(prefix=prefix or f"/admin/{name}", tags=[f"admin:{name}"])
    audit_target = name

    @router.get("", response_model=list[out_schema])  # type: ignore[valid-type]
    def list_items(db: DbDep, admin: AdminDep) -> list[Any]:
        rows = db.scalars(select(model).order_by(*order_by)).all()
        return [serialise(row) for row in rows]

    @router.get("/{item_id}", response_model=out_schema)  # type: ignore[valid-type]
    def get_item(item_id: str, db: DbDep, admin: AdminDep) -> Any:
        return serialise(get_or_404(db, model, item_id))

    @router.post(
        "", response_model=out_schema, status_code=status.HTTP_201_CREATED
    )  # type: ignore[valid-type]
    def create_item(
        payload: create_schema,  # type: ignore[valid-type]
        request: Request,
        db: DbDep,
        admin: AdminDep,
    ) -> Any:
        if unique_field:
            value = getattr(payload, unique_field, None)
            clash = db.scalar(
                select(model).where(getattr(model, unique_field) == value)
            )
            if clash is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": "duplicate",
                        "message": f"That {unique_field} is already in use.",
                    },
                )

        row = model()
        apply_fields(row, payload)
        db.add(row)
        db.flush()
        audit.record(
            db,
            request,
            action=f"content.{audit_target}.created",
            actor_id=admin.id,
            actor_email=admin.email,
            target_type=audit_target,
            target_id=str(row.id),
        )
        db.commit()
        return serialise(row)

    @router.put("/{item_id}", response_model=out_schema)  # type: ignore[valid-type]
    def update_item(
        item_id: str,
        payload: update_schema,  # type: ignore[valid-type]
        request: Request,
        db: DbDep,
        admin: AdminDep,
    ) -> Any:
        row = get_or_404(db, model, item_id)
        check_version(row, getattr(payload, "expected_updated_at", None))
        apply_fields(row, payload)
        audit.record(
            db,
            request,
            action=f"content.{audit_target}.updated",
            actor_id=admin.id,
            actor_email=admin.email,
            target_type=audit_target,
            target_id=str(row.id),
        )
        db.commit()
        return serialise(row)

    @router.delete("/{item_id}", response_model=DeleteResponse)
    def delete_item(
        item_id: str, request: Request, db: DbDep, admin: AdminDep
    ) -> DeleteResponse:
        row = get_or_404(db, model, item_id)
        db.delete(row)
        audit.record(
            db,
            request,
            action=f"content.{audit_target}.deleted",
            actor_id=admin.id,
            actor_email=admin.email,
            target_type=audit_target,
            target_id=item_id,
        )
        db.commit()
        return DeleteResponse(deleted=item_id)

    @router.post("/reorder", response_model=list[out_schema])  # type: ignore[valid-type]
    def reorder(
        payload: ReorderRequest, request: Request, db: DbDep, admin: AdminDep
    ) -> list[Any]:
        ids = [parse_uuid(item.id) for item in payload.items]
        rows = {
            row.id: row
            for row in db.scalars(select(model).where(model.id.in_(ids))).all()
        }
        if len(rows) != len(ids):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="One or more items do not exist",
            )
        for item in payload.items:
            rows[parse_uuid(item.id)].display_order = item.display_order
        audit.record(
            db,
            request,
            action=f"content.{audit_target}.reordered",
            actor_id=admin.id,
            actor_email=admin.email,
            target_type=audit_target,
            details={"count": len(ids)},
        )
        db.commit()
        return [
            serialise(row)
            for row in db.scalars(select(model).order_by(*order_by)).all()
        ]

    return router


def count_rows(db: Session, model: type[Base], *where: Any) -> int:
    stmt = select(func.count()).select_from(model)
    if where:
        stmt = stmt.where(*where)
    return db.scalar(stmt) or 0
