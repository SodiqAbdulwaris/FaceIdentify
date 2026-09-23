"""Memory persistence (PERSISTENCE_IMPLEMENTATION.md §6)."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.infrastructure.db.engine import Base
from backend.infrastructure.db.types import UTCDateTime, enum_check, uuid_pk


class RepresentationSpaceState(StrEnum):
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"


class RepresentationMetric(StrEnum):
    COSINE = "COSINE"


class RepresentationSpace(Base):
    """A semantic vector space. Vectors are only comparable within the same space.

    `normalization` is a contract string such as `L2_NORMALIZED`; the spec gives no complete
    value set, so it is unconstrained (see .agents/CONTEXT.md).
    """

    __tablename__ = "representation_spaces"
    __table_args__ = (
        enum_check("state", RepresentationSpaceState),
        enum_check("metric", RepresentationMetric),
        CheckConstraint("dimension > 0", name="dimension_positive"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    semantic_key: Mapped[str] = mapped_column(String, unique=True)
    state: Mapped[str] = mapped_column(String)
    dimension: Mapped[int] = mapped_column(Integer)
    metric: Mapped[str] = mapped_column(String)
    normalization: Mapped[str] = mapped_column(String)
    component_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("component_versions.id", ondelete="RESTRICT")
    )
    contract_schema_version: Mapped[int] = mapped_column(Integer)
    contract_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    deprecated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
