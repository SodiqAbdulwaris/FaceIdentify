"""Processing provenance persistence (PERSISTENCE_IMPLEMENTATION.md §12-§14, §16)."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, Integer, LargeBinary, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.infrastructure.db.engine import Base
from backend.infrastructure.db.types import UTCDateTime, enum_check, uuid_pk

if TYPE_CHECKING:
    from backend.app.runtime.models import RuntimeVariant
    from backend.app.sources.models import Source


class ProcessingConfigurationSnapshot(Base):
    """Immutable resolved semantic intent for exactly one run; never updated."""

    __tablename__ = "processing_configuration_snapshots"
    __table_args__ = (
        CheckConstraint("length(fingerprint_sha256) = 32", name="fingerprint_length"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    schema_version: Mapped[int] = mapped_column(Integer)
    canonical_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    # Not unique: the design keeps one snapshot row per run for unambiguous provenance.
    fingerprint_sha256: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    created_by_user_action: Mapped[str | None] = mapped_column(String)


class ProcessingRunState(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PAUSING = "PAUSING"
    PAUSED = "PAUSED"
    CANCELLING = "CANCELLING"
    CANCELLED = "CANCELLED"
    FINALIZING = "FINALIZING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"
    NOT_RESUMABLE = "NOT_RESUMABLE"


# Non-terminal states that startup recovery must inspect ("partial transient state index", §21).
TRANSIENT_RUN_STATES = (
    ProcessingRunState.PENDING,
    ProcessingRunState.RUNNING,
    ProcessingRunState.PAUSING,
    ProcessingRunState.PAUSED,
    ProcessingRunState.CANCELLING,
    ProcessingRunState.FINALIZING,
    ProcessingRunState.INTERRUPTED,
)


class ProcessingRun(Base):
    """The logical, provenance-bearing attempt to process a source."""

    __tablename__ = "processing_runs"
    __table_args__ = (
        enum_check("state", ProcessingRunState),
        CheckConstraint("revision >= 1", name="revision_positive"),
        Index(None, "source_id", "created_at"),
        Index(None, "state", "updated_at"),
        Index(
            "ix_processing_runs_transient_state",
            "state",
            sqlite_where=text(
                "state IN (" + ", ".join(f"'{s.value}'" for s in TRANSIENT_RUN_STATES) + ")"
            ),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id", ondelete="RESTRICT"))
    # One immutable snapshot per run.
    configuration_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("processing_configuration_snapshots.id", ondelete="RESTRICT"), unique=True
    )
    parent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("processing_runs.id", ondelete="RESTRICT")
    )
    state: Mapped[str] = mapped_column(String)
    requested_at: Mapped[datetime] = mapped_column(UTCDateTime)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    failed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    failure_code: Mapped[str | None] = mapped_column(String)
    failure_detail: Mapped[str | None] = mapped_column(String)
    # Circular with processing_checkpoints.processing_run_id.
    current_checkpoint_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("processing_checkpoints.id", ondelete="SET NULL", use_alter=True)
    )
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)

    # §22: bounded to-one navigation only. `source_id` is named explicitly because
    # sources.current_processing_run_id links the same two tables the other way.
    source: Mapped["Source"] = relationship(foreign_keys=[source_id])
    configuration_snapshot: Mapped["ProcessingConfigurationSnapshot"] = relationship()


class ExecutionSegmentState(StrEnum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"
    ABANDONED = "ABANDONED"


class ExecutionSegmentEndReason(StrEnum):
    NORMAL = "NORMAL"
    FALLBACK = "FALLBACK"
    CUDA_OOM = "CUDA_OOM"
    WORKER_CRASH = "WORKER_CRASH"
    CANCELLED = "CANCELLED"
    SHUTDOWN = "SHUTDOWN"


class ExecutionSegment(Base):
    """What actually ran during a bounded stretch of a run. Closed, never reopened."""

    __tablename__ = "execution_segments"
    __table_args__ = (
        enum_check("state", ExecutionSegmentState),
        enum_check("ended_reason", ExecutionSegmentEndReason, nullable=True),
        CheckConstraint("ordinal >= 0", name="ordinal_non_negative"),
        Index(None, "processing_run_id", "ordinal", unique=True),
        # At most one running segment per run.
        Index(
            "uq_execution_segments_one_running_per_run",
            "processing_run_id",
            unique=True,
            sqlite_where=text("state = 'RUNNING'"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    processing_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("processing_runs.id", ondelete="RESTRICT")
    )
    runtime_variant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("runtime_variants.id", ondelete="RESTRICT")
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    ended_reason: Mapped[str | None] = mapped_column(String)
    runtime_details_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)

    # §22: bounded to-one navigation only.
    processing_run: Mapped["ProcessingRun"] = relationship()
    runtime_variant: Mapped["RuntimeVariant | None"] = relationship()


class CheckpointKind(StrEnum):
    INTERMEDIATE = "INTERMEDIATE"
    FINAL = "FINAL"


class CheckpointState(StrEnum):
    VALID = "VALID"
    INVALIDATED = "INVALIDATED"


class ProcessingCheckpoint(Base):
    """A durable resume boundary. A FINAL checkpoint is not itself acceptance."""

    __tablename__ = "processing_checkpoints"
    __table_args__ = (
        enum_check("kind", CheckpointKind),
        enum_check("state", CheckpointState),
        CheckConstraint("ordinal >= 0", name="ordinal_non_negative"),
        # Serves both UNIQUE(run, ordinal) and the (run, ordinal DESC) lookup: SQLite scans
        # an index in either direction.
        Index(None, "processing_run_id", "ordinal", unique=True),
        # At most one valid FINAL checkpoint per run.
        Index(
            "uq_processing_checkpoints_one_valid_final_per_run",
            "processing_run_id",
            unique=True,
            sqlite_where=text("kind = 'FINAL' AND state = 'VALID'"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    # CASCADE: checkpoints are owned by their run (only relevant if a run is permanently removed).
    processing_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("processing_runs.id", ondelete="CASCADE")
    )
    execution_segment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("execution_segments.id", ondelete="RESTRICT")
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String)
    state: Mapped[str] = mapped_column(String)
    payload_schema_version: Mapped[int] = mapped_column(Integer)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    invalidated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    invalidated_reason: Mapped[str | None] = mapped_column(String)
