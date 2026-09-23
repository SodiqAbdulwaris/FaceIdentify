"""Job persistence (PERSISTENCE_IMPLEMENTATION.md §15)."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.infrastructure.db.engine import Base
from backend.infrastructure.db.types import UTCDateTime, enum_check, uuid_pk


class JobType(StrEnum):
    PROCESS_SOURCE = "PROCESS_SOURCE"
    REPROCESS_SOURCE = "REPROCESS_SOURCE"
    REBUILD_INDEX = "REBUILD_INDEX"
    RETRAIN_MODEL = "RETRAIN_MODEL"
    INSTALL_RUNTIME = "INSTALL_RUNTIME"
    CLEAN_STORAGE = "CLEAN_STORAGE"


class JobState(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    PAUSING = "PAUSING"
    PAUSED = "PAUSED"
    CANCELLING = "CANCELLING"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"


class JobPriority(StrEnum):
    INTERACTIVE = "INTERACTIVE"
    HIGH = "HIGH"
    NORMAL = "NORMAL"
    LOW = "LOW"
    MAINTENANCE = "MAINTENANCE"


class ProgressMode(StrEnum):
    DETERMINATE = "DETERMINATE"
    INDETERMINATE = "INDETERMINATE"


class Job(Base):
    """Schedulable execution state. A retry is a new Job linked by `previous_job_id`."""

    __tablename__ = "jobs"
    __table_args__ = (
        enum_check("type", JobType),
        enum_check("state", JobState),
        enum_check("priority", JobPriority),
        enum_check("progress_mode", ProgressMode),
        CheckConstraint(
            "progress_completed IS NULL OR progress_completed >= 0", name="completed_non_negative"
        ),
        CheckConstraint("progress_total IS NULL OR progress_total >= 0", name="total_non_negative"),
        CheckConstraint(
            "progress_completed IS NULL OR progress_total IS NULL"
            " OR progress_completed <= progress_total",
            name="completed_within_total",
        ),
        CheckConstraint("attempt_number >= 1", name="attempt_number_positive"),
        Index(None, "state", "priority", "created_at"),
        Index(None, "lease_expires_at"),
        Index(None, "processing_run_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    type: Mapped[str] = mapped_column(String)
    processing_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("processing_runs.id", ondelete="RESTRICT")
    )
    previous_job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="RESTRICT")
    )
    state: Mapped[str] = mapped_column(String)
    priority: Mapped[str] = mapped_column(String)
    payload_schema_version: Mapped[int] = mapped_column(Integer)
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    progress_mode: Mapped[str] = mapped_column(String)
    progress_completed: Mapped[int | None] = mapped_column(Integer)
    progress_total: Mapped[int | None] = mapped_column(Integer)
    lease_owner: Mapped[str | None] = mapped_column(String)
    lease_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    heartbeat_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    attempt_number: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    failure_code: Mapped[str | None] = mapped_column(String)
    failure_detail: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
