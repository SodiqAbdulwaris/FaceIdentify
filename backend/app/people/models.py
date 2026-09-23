"""Person and Identity-Person association persistence (PERSISTENCE_IMPLEMENTATION.md §8-§9)."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.infrastructure.db.engine import Base
from backend.infrastructure.db.types import UTCDateTime, enum_check, uuid_pk

if TYPE_CHECKING:
    from backend.app.identities.models import Evidence, Identity


class PersonState(StrEnum):
    ACTIVE = "ACTIVE"
    RECYCLED = "RECYCLED"
    DELETED = "DELETED"


class Person(Base):
    """Semantic, named human identity; separate from visual Identity.

    Names are not unique: distinct people may share one. An unknown Identity never creates a
    placeholder Person.
    """

    __tablename__ = "people"
    __table_args__ = (
        enum_check("state", PersonState),
        CheckConstraint("length(trim(display_name)) > 0", name="display_name_not_empty"),
        CheckConstraint("revision >= 1", name="revision_positive"),
        Index(None, "state", "normalized_name"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    state: Mapped[str] = mapped_column(String)
    display_name: Mapped[str] = mapped_column(String)
    normalized_name: Mapped[str | None] = mapped_column(String)
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)
    recycled_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class AssociationState(StrEnum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"
    SUPERSEDED = "SUPERSEDED"


class IdentityPersonAssociation(Base):
    """Historical and current link between an Identity and a Person.

    At most one ACTIVE association per identity; a Person may have many active identities.
    Removing an association ends it, so `ended_at` is set exactly when it is no longer ACTIVE.
    """

    __tablename__ = "identity_person_associations"
    __table_args__ = (
        enum_check("state", AssociationState),
        CheckConstraint("(state = 'ACTIVE') = (ended_at IS NULL)", name="ended_when_inactive"),
        CheckConstraint("revision >= 1", name="revision_positive"),
        # Named exactly as in PERSISTENCE_IMPLEMENTATION.md §9.
        Index(
            "uq_identity_person_active",
            "identity_id",
            unique=True,
            sqlite_where=text("state = 'ACTIVE'"),
        ),
        Index(None, "person_id", "state"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    identity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("identities.id", ondelete="RESTRICT"))
    person_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("people.id", ondelete="RESTRICT"))
    state: Mapped[str] = mapped_column(String)
    evidence_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("evidence.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))

    # §22: bounded to-one navigation only.
    identity: Mapped["Identity"] = relationship()
    person: Mapped["Person"] = relationship()
    evidence: Mapped["Evidence | None"] = relationship()
