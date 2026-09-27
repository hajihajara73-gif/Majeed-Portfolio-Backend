from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
# Deliberately not a general URL validator. Only these schemes may ever reach an
# href we render: `javascript:` and `data:` in an anchor are an XSS vector.
ALLOWED_SCHEMES = ("http://", "https://", "mailto:", "tel:", "/", "#")


def validate_public_url(value: str | None) -> str | None:
    if value is None:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    if not candidate.startswith(ALLOWED_SCHEMES):
        raise ValueError(
            "URL must start with http://, https://, mailto:, tel:, / or #"
        )
    return candidate


def validate_slug(value: str) -> str:
    candidate = value.strip().lower()
    if not SLUG_RE.match(candidate):
        raise ValueError(
            "Slug must be lowercase letters, numbers and single hyphens"
        )
    return candidate


Slug = Annotated[str, Field(min_length=1, max_length=128)]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Versioned(BaseModel):
    """
    Optimistic locking.

    Every update may carry the `updated_at` the client last saw. If the row has
    moved on since, the write is rejected with 409 rather than silently
    clobbering whatever changed in between. Omitting it is allowed — the field
    is opt-in — but the admin UI always sends it.
    """

    expected_updated_at: datetime | None = None


class ReorderItem(BaseModel):
    id: str
    display_order: int = Field(ge=0, le=10_000)


class ReorderRequest(BaseModel):
    items: list[ReorderItem] = Field(min_length=1, max_length=500)

    @field_validator("items")
    @classmethod
    def _unique_ids(cls, items: list[ReorderItem]) -> list[ReorderItem]:
        seen = {item.id for item in items}
        if len(seen) != len(items):
            raise ValueError("Duplicate ids in reorder request")
        return items


class ListResponse(BaseModel):
    items: list[Any]
    total: int


class DeleteResponse(BaseModel):
    deleted: str
    archived: bool = False
