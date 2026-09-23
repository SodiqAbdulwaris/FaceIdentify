"""Memory persistence (PERSISTENCE_IMPLEMENTATION.md §5, §6, §11, §17)."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    text,
)
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


class AnnKeySequence(Base):
    """Per-space ANN key allocator. Keys are never reused; gaps are harmless (§6.3)."""

    __tablename__ = "ann_key_sequences"
    __table_args__ = (CheckConstraint("next_ann_key > 0", name="next_ann_key_positive"),)

    representation_space_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("representation_spaces.id", ondelete="RESTRICT"), primary_key=True
    )
    next_ann_key: Mapped[int] = mapped_column(BigInteger)


class ObservationState(StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    REJECTED = "REJECTED"
    DELETED = "DELETED"


class Observation(Base):
    """A concrete detected face in one source. Not a person and not an occurrence (§5).

    `landmarks_json` and `quality_json` realise the spec's "optional landmark/quality JSON"
    (decision 2026-09-23). Their contents are not yet defined.
    """

    __tablename__ = "observations"
    __table_args__ = (
        enum_check("state", ObservationState),
        CheckConstraint(
            "bbox_x >= 0 AND bbox_y >= 0 AND bbox_width > 0 AND bbox_height > 0"
            " AND bbox_x + bbox_width <= 1 AND bbox_y + bbox_height <= 1",
            name="bbox_normalized",
        ),
        # Images carry neither frame nor time; video observations carry both. The source kind
        # lives in another table, so which case applies is checked by the use case.
        CheckConstraint("(frame_index IS NULL) = (timestamp_ms IS NULL)", name="frame_time_paired"),
        CheckConstraint(
            "frame_index IS NULL OR (frame_index >= 0 AND timestamp_ms >= 0)",
            name="frame_time_non_negative",
        ),
        CheckConstraint("sequence_in_run >= 0", name="sequence_non_negative"),
        UniqueConstraint("processing_run_id", "sequence_in_run"),
        Index(None, "source_id", "state", "created_at"),
        Index(None, "face_crop_artifact_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id", ondelete="RESTRICT"))
    processing_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("processing_runs.id", ondelete="RESTRICT")
    )
    execution_segment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("execution_segments.id", ondelete="RESTRICT")
    )
    # SET NULL: cleanup may remove a derivative crop without invalidating the observation.
    face_crop_artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("artifacts.id", ondelete="SET NULL")
    )
    state: Mapped[str] = mapped_column(String)
    sequence_in_run: Mapped[int] = mapped_column(Integer)
    frame_index: Mapped[int | None] = mapped_column(BigInteger)
    timestamp_ms: Mapped[int | None] = mapped_column(BigInteger)
    bbox_x: Mapped[float] = mapped_column(Float)
    bbox_y: Mapped[float] = mapped_column(Float)
    bbox_width: Mapped[float] = mapped_column(Float)
    bbox_height: Mapped[float] = mapped_column(Float)
    landmarks_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    quality_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    detector_component_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("component_versions.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    superseded_by_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("processing_runs.id", ondelete="RESTRICT")
    )


class RepresentationState(StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    ERASED = "ERASED"
    DELETED = "DELETED"


class Representation(Base):
    """A canonical face vector with provenance; the USearch entry is derived from it (§6.2).

    `vector` is little-endian float32 bytes, NULL only once ERASED (decision 2026-09-23).
    """

    __tablename__ = "representations"
    __table_args__ = (
        enum_check("state", RepresentationState),
        CheckConstraint("ann_key IS NULL OR ann_key > 0", name="ann_key_positive"),
        CheckConstraint("vector_dimension > 0", name="vector_dimension_positive"),
        # Erasure removes the biometric bytes and the ANN key; nothing else may lack a vector.
        CheckConstraint(
            "(state = 'ERASED' AND vector IS NULL AND ann_key IS NULL)"
            " OR (state != 'ERASED' AND vector IS NOT NULL)",
            name="erasure",
        ),
        CheckConstraint(
            "vector IS NULL OR length(vector) = 4 * vector_dimension", name="vector_length"
        ),
        # An active representation is ANN-eligible: identity and key are required. That the
        # identity itself is ACTIVE is a cross-row rule enforced by the use case (§20).
        CheckConstraint(
            "state != 'ACTIVE' OR (identity_id IS NOT NULL AND ann_key IS NOT NULL)",
            name="active_eligible",
        ),
        UniqueConstraint("observation_id", "representation_space_id"),
        Index(None, "representation_space_id", "state", "ann_key"),
        Index(None, "identity_id", "state"),
        Index(None, "processing_run_id", "state"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    # CASCADE: a representation is owned by its observation.
    observation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("observations.id", ondelete="CASCADE")
    )
    identity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("identities.id", ondelete="RESTRICT")
    )
    processing_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("processing_runs.id", ondelete="RESTRICT")
    )
    execution_segment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("execution_segments.id", ondelete="RESTRICT")
    )
    representation_space_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("representation_spaces.id", ondelete="RESTRICT")
    )
    state: Mapped[str] = mapped_column(String)
    ann_key: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    vector: Mapped[bytes | None] = mapped_column(LargeBinary)
    vector_dimension: Mapped[int] = mapped_column(Integer)
    quality_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    activated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    erased_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class OccurrenceKind(StrEnum):
    IMAGE = "IMAGE"
    TRACK = "TRACK"
    SEGMENT = "SEGMENT"


class OccurrenceState(StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    DELETED = "DELETED"


class Occurrence(Base):
    """A meaningful appearance of an Identity within a Source (§11)."""

    __tablename__ = "occurrences"
    __table_args__ = (
        enum_check("kind", OccurrenceKind),
        enum_check("state", OccurrenceState),
        CheckConstraint(
            "kind != 'IMAGE' OR (start_frame IS NULL AND end_frame IS NULL"
            " AND start_timestamp_ms IS NULL AND end_timestamp_ms IS NULL)",
            name="image_has_no_range",
        ),
        CheckConstraint(
            "start_frame IS NULL OR end_frame IS NULL OR start_frame <= end_frame",
            name="frame_range_ordered",
        ),
        CheckConstraint(
            "start_timestamp_ms IS NULL OR end_timestamp_ms IS NULL"
            " OR start_timestamp_ms <= end_timestamp_ms",
            name="time_range_ordered",
        ),
        Index(None, "source_id", "state", "created_at"),
        Index(None, "identity_id", "state", "created_at"),
        Index(None, "processing_run_id", "state"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id", ondelete="RESTRICT"))
    identity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("identities.id", ondelete="RESTRICT"))
    processing_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("processing_runs.id", ondelete="RESTRICT")
    )
    representative_observation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("observations.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(String)
    state: Mapped[str] = mapped_column(String)
    start_frame: Mapped[int | None] = mapped_column(BigInteger)
    end_frame: Mapped[int | None] = mapped_column(BigInteger)
    start_timestamp_ms: Mapped[int | None] = mapped_column(BigInteger)
    end_timestamp_ms: Mapped[int | None] = mapped_column(BigInteger)
    confidence_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    # "Lifecycle timestamps" (§11), decision 2026-09-23: creation and acceptance.
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    activated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class OccurrenceObservation(Base):
    """Ordered membership of observations in an occurrence."""

    __tablename__ = "occurrence_observations"
    __table_args__ = (
        UniqueConstraint("occurrence_id", "ordinal"),
        CheckConstraint("ordinal >= 0", name="ordinal_non_negative"),
    )

    # CASCADE from the occurrence (owned membership rows, §20). Observations are provenance.
    occurrence_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("occurrences.id", ondelete="CASCADE"), primary_key=True
    )
    observation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("observations.id", ondelete="RESTRICT"), primary_key=True
    )
    ordinal: Mapped[int] = mapped_column(Integer)


class IndexOperationKind(StrEnum):
    ADD = "ADD"
    REMOVE = "REMOVE"


class IndexOperationState(StrEnum):
    PENDING = "PENDING"
    APPLIED = "APPLIED"
    FAILED = "FAILED"


class IndexOperation(Base):
    """Durable reconciliation queue between SQLite and USearch (§17).

    Written in the same transaction as the authoritative change; the IndexCoordinator is the
    normal sole writer to USearch and marks an operation APPLIED only after the index settles.
    """

    __tablename__ = "index_operations"
    __table_args__ = (
        enum_check("operation", IndexOperationKind),
        enum_check("state", IndexOperationState),
        CheckConstraint("attempt_count >= 0", name="attempt_count_non_negative"),
        CheckConstraint("state != 'APPLIED' OR applied_at IS NOT NULL", name="applied_has_time"),
        # No duplicate pending desired state for the same representation.
        Index(
            "uq_index_operations_one_pending_per_representation_operation",
            "representation_id",
            "operation",
            unique=True,
            sqlite_where=text("state = 'PENDING'"),
        ),
        Index(None, "state", "not_before_at", "created_at"),
        Index(None, "representation_space_id", "state"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    representation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("representations.id", ondelete="RESTRICT")
    )
    representation_space_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("representation_spaces.id", ondelete="RESTRICT")
    )
    operation: Mapped[str] = mapped_column(String)
    state: Mapped[str] = mapped_column(String)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    not_before_at: Mapped[datetime] = mapped_column(UTCDateTime)
    # Nullable because they only exist after an event (decision 2026-09-23).
    last_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    applied_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    failure_code: Mapped[str | None] = mapped_column(String)
    failure_detail: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)
