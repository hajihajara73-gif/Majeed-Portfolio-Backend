from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator


class UtcDateTime(TypeDecorator[datetime]):
    """
    A timestamp that is always timezone-aware UTC in Python, on every backend.

    PostgreSQL's `timestamptz` returns aware datetimes; SQLite returns naive
    ones. Without normalising, an expiry check like `expires_at <= utcnow()`
    raises `can't compare offset-naive and offset-aware datetimes` — and it
    raises inside session validation, which is exactly where a crash is least
    welcome.

    Rather than sprinkle `.replace(tzinfo=...)` at every call site and hope none
    is missed, the guarantee is enforced once, here:

      - on the way in, a naive value is assumed UTC and made aware, and any
        aware value is converted to UTC
      - on the way out, a naive value from the driver is labelled UTC
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(
        self, value: datetime | None, dialect: Dialect
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(
        self, value: Any, dialect: Dialect
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
