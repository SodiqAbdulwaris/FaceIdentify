"""Column types and constraint helpers shared by all persistence models.

Conventions from PERSISTENCE_IMPLEMENTATION.md §2-§3: application-generated uuid4 primary keys,
UTC timestamps, and finite values stored as strings guarded by CHECK constraints whose literals
match a Python StrEnum exactly.
"""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Dialect, Uuid
from sqlalchemy.orm import MappedColumn, mapped_column
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator[datetime]):
    """Timezone-aware UTC datetime.

    SQLite has no timezone type, so values are stored as naive UTC and re-tagged as UTC when
    loaded. Naive datetimes are rejected rather than guessed at.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("naive datetime: all timestamps must be timezone-aware UTC")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: Any, dialect: Dialect) -> datetime | None:
        return None if value is None else value.replace(tzinfo=UTC)


def uuid_pk() -> MappedColumn[uuid.UUID]:
    """UUID primary key; `Uuid` renders as CHAR(32) on SQLite (PERSISTENCE_IMPLEMENTATION.md §2)."""
    return mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)


def enum_check(column: str, values: type[StrEnum], *, nullable: bool = False) -> CheckConstraint:
    """CHECK that `column` holds one of the enum's literals; named `ck_<table>_<column>`."""
    literals = ", ".join(f"'{member.value}'" for member in values)
    condition = f"{column} IN ({literals})"
    if nullable:
        condition = f"{column} IS NULL OR {condition}"
    return CheckConstraint(condition, name=column)
