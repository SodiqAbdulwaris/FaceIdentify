"""Identity, lineage and Evidence persistence (PERSISTENCE_IMPLEMENTATION.md §7, §10)."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.infrastructure.db.engine import Base
from backend.infrastructure.db.types import UTCDateTime, enum_check, uuid_pk


class IdentityState(StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    MERGED = "MERGED"
    SPLIT = "SPLIT"
    FORGOTTEN = "FORGOTTEN"
    DELETED = "DELETED"


class Identity(Base):
    """The persistent visual subject, named or unknown. Not a vector, Person or ANN entry.

    Merge is Identity-level (decision 2026-09-23): a merged identity keeps its row with
    `state = MERGED` and `merged_into_identity_id`, plus an `identity_lineage` edge.
    """

    __tablename__ = "identities"
    __table_args__ = (
        enum_check("state", IdentityState),
        CheckConstraint("revision >= 1", name="revision_positive"),
        # A MERGED identity must say where it went, and only a MERGED one may.
        CheckConstraint(
            "(state = 'MERGED') = (merged_into_identity_id IS NOT NULL)", name="merged_target"
        ),
        CheckConstraint("merged_into_identity_id != id", name="not_merged_into_self"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    state: Mapped[str] = mapped_column(String)
    created_by_processing_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("processing_runs.id", ondelete="RESTRICT")
    )
    representative_observation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("observations.id", ondelete="SET NULL")
    )
    merged_into_identity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("identities.id", ondelete="RESTRICT")
    )
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    activated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    forgotten_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class IdentityLineageKind(StrEnum):
    MERGED_INTO = "MERGED_INTO"
    SPLIT_FROM = "SPLIT_FROM"


class IdentityLineage(Base):
    """Structural history of merges and splits. Not a replacement for current identity state."""

    __tablename__ = "identity_lineage"
    __table_args__ = (
        enum_check("kind", IdentityLineageKind),
        CheckConstraint("from_identity_id != to_identity_id", name="distinct_endpoints"),
        UniqueConstraint("from_identity_id", "to_identity_id", "kind"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    from_identity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("identities.id", ondelete="RESTRICT")
    )
    to_identity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("identities.id", ondelete="RESTRICT")
    )
    kind: Mapped[str] = mapped_column(String)
    evidence_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evidence.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class EvidenceKind(StrEnum):
    IDENTITY_CREATED = "IDENTITY_CREATED"
    IDENTITY_MATCHED = "IDENTITY_MATCHED"
    IDENTITY_ASSIGNED_TO_PERSON = "IDENTITY_ASSIGNED_TO_PERSON"
    IDENTITY_REMOVED_FROM_PERSON = "IDENTITY_REMOVED_FROM_PERSON"
    IDENTITY_MERGED = "IDENTITY_MERGED"
    IDENTITY_SPLIT = "IDENTITY_SPLIT"
    IDENTITY_FORGOTTEN = "IDENTITY_FORGOTTEN"
    USER_CORRECTION = "USER_CORRECTION"


class Evidence(Base):
    """Immutable, append-only reason for an authoritative memory decision.

    It records why a decision was made, not that it is still current. `superseded_at` is an
    explanatory marker only; the payload is never rewritten.
    """

    __tablename__ = "evidence"
    __table_args__ = (
        enum_check("kind", EvidenceKind),
        Index(None, "subject_identity_id", "created_at"),
        Index(None, "processing_run_id", "created_at"),
        Index(None, "kind", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    kind: Mapped[str] = mapped_column(String)
    processing_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("processing_runs.id", ondelete="RESTRICT")
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sources.id", ondelete="RESTRICT")
    )
    subject_identity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("identities.id", ondelete="RESTRICT")
    )
    subject_person_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("people.id", ondelete="RESTRICT")
    )
    calibration_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("recognition_calibration_profiles.id", ondelete="RESTRICT")
    )
    payload_schema_version: Mapped[int] = mapped_column(Integer)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    superseded_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class EvidenceRepresentationRole(StrEnum):
    SUBJECT = "SUBJECT"
    SELECTED_CANDIDATE = "SELECTED_CANDIDATE"
    CANDIDATE = "CANDIDATE"
    SUPPORTING = "SUPPORTING"


class EvidenceRepresentation(Base):
    """Role-bearing link from Evidence to the representations it cites."""

    __tablename__ = "evidence_representations"
    __table_args__ = (enum_check("role", EvidenceRepresentationRole),)

    # CASCADE from evidence (owned link rows, §20); representations are history, so RESTRICT.
    evidence_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evidence.id", ondelete="CASCADE"), primary_key=True
    )
    representation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("representations.id", ondelete="RESTRICT"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String, primary_key=True)


class EvidenceCandidate(Base):
    """A bounded recognition candidate, kept in its original rank order.

    `decision` has no spec-defined value set yet, so it is an unconstrained string
    (decision 2026-09-23; see .agents/CONTEXT.md).
    """

    __tablename__ = "evidence_candidates"
    __table_args__ = (CheckConstraint("rank >= 0", name="rank_non_negative"),)

    evidence_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evidence.id", ondelete="CASCADE"), primary_key=True
    )
    rank: Mapped[int] = mapped_column(Integer, primary_key=True)
    representation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("representations.id", ondelete="RESTRICT")
    )
    identity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("identities.id", ondelete="RESTRICT")
    )
    raw_similarity: Mapped[float] = mapped_column(Float)
    calibrated_confidence: Mapped[float | None] = mapped_column(Float)
    decision: Mapped[str] = mapped_column(String)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON)
