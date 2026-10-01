"""Repositories for `execution_segments` and `processing_checkpoints`
(PERSISTENCE_IMPLEMENTATION.md §14, §16, §26: "append/get/list/close; latest valid/final checkpoint;
invalidate checkpoint").

Like `JobRepository` they join the caller's transaction and never commit, and every change is one
statement decided by the database. Two things the schema enforces are relied on, not re-checked in
Python, so they hold under concurrent writers: `UNIQUE(processing_run_id, ordinal)` on both tables,
and the partial unique indexes (one `RUNNING` segment per run, one `VALID` `FINAL` checkpoint per
run). A violation is the database's `IntegrityError`; deciding what it means is the use case's.

An ordinal is allocated inside the `INSERT` itself (`max(ordinal) + 1`), so allocating and inserting
cannot be separated by another writer. As with any repository, a caller that has read earlier in
the same transaction can still meet `SQLITE_BUSY_SNAPSHOT` (CONTEXT open question 20).

`close` and `invalidate` change the row in the database, not an object the caller already holds:
re-read it with `get` (which refreshes) rather than trusting the held copy.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, insert, select, update
from sqlalchemy.orm import Session

from backend.app.processing.models import (
    CheckpointKind,
    CheckpointState,
    ExecutionSegment,
    ExecutionSegmentState,
    ProcessingCheckpoint,
)

_CLOSED_SEGMENT_STATES = (
    ExecutionSegmentState.COMPLETED,
    ExecutionSegmentState.FAILED,
    ExecutionSegmentState.INTERRUPTED,
    ExecutionSegmentState.ABANDONED,
)


def _next_ordinal(
    model: type[ExecutionSegment] | type[ProcessingCheckpoint], run_id: uuid.UUID
) -> Any:
    return (
        select(func.coalesce(func.max(model.ordinal), -1) + 1)
        .where(model.processing_run_id == run_id)
        .scalar_subquery()
    )


class SegmentRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def append(
        self,
        run_id: uuid.UUID,
        *,
        segment_id: uuid.UUID,
        runtime_variant_id: uuid.UUID | None,
        runtime_details: dict[str, Any],
        now: datetime,
    ) -> ExecutionSegment:
        """Start a `RUNNING` segment as the run's next, ordinal 0 for the first. A run that already
        has a running segment refuses (`IntegrityError`): close it first."""
        self._session.execute(
            insert(ExecutionSegment).values(
                id=segment_id,
                processing_run_id=run_id,
                runtime_variant_id=runtime_variant_id,
                ordinal=_next_ordinal(ExecutionSegment, run_id),
                state=ExecutionSegmentState.RUNNING,
                started_at=now,
                runtime_details_json=runtime_details,
                created_at=now,
            )
        )
        segment = self.get(segment_id)
        assert segment is not None  # just inserted in this transaction
        return segment

    def get(self, segment_id: uuid.UUID) -> ExecutionSegment | None:
        return self._session.get(ExecutionSegment, segment_id, populate_existing=True)

    def list_for_run(self, run_id: uuid.UUID) -> list[ExecutionSegment]:
        """The run's segments in order."""
        return list(
            self._session.scalars(
                select(ExecutionSegment)
                .where(ExecutionSegment.processing_run_id == run_id)
                .order_by(ExecutionSegment.ordinal)
                .execution_options(populate_existing=True)
            )
        )

    def close(
        self, segment_id: uuid.UUID, state: str, *, reason: str | None, now: datetime
    ) -> bool:
        """End a `RUNNING` segment as `state` (`COMPLETED`, `FAILED`, `INTERRUPTED` or `ABANDONED`)
        with an optional `ended_reason`. False if it was not running: segments are closed, never
        reopened, so a closed one is left exactly as it is. Any other `state` is a `ValueError`."""
        if state not in _CLOSED_SEGMENT_STATES:
            raise ValueError(f"{state!r} does not close a segment")
        result = self._session.execute(
            update(ExecutionSegment)
            .where(ExecutionSegment.id == segment_id, ExecutionSegment.state == "RUNNING")
            .values(state=state, ended_reason=reason, ended_at=now)
            .execution_options(synchronize_session=False)
        )
        return bool(result.rowcount)  # type: ignore[attr-defined]


class CheckpointRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def append(
        self,
        run_id: uuid.UUID,
        *,
        checkpoint_id: uuid.UUID,
        segment_id: uuid.UUID | None,
        kind: str,
        payload_schema_version: int,
        payload: dict[str, Any],
        now: datetime,
    ) -> ProcessingCheckpoint:
        """Record a `VALID` checkpoint as the run's next ordinal. A second valid `FINAL` for the
        run refuses (`IntegrityError`): invalidate the first. Writing happens in the caller's short
        settlement transaction, after the work before the boundary is durably represented (§16)."""
        self._session.execute(
            insert(ProcessingCheckpoint).values(
                id=checkpoint_id,
                processing_run_id=run_id,
                execution_segment_id=segment_id,
                ordinal=_next_ordinal(ProcessingCheckpoint, run_id),
                kind=kind,
                state=CheckpointState.VALID,
                payload_schema_version=payload_schema_version,
                payload_json=payload,
                created_at=now,
            )
        )
        checkpoint = self.get(checkpoint_id)
        assert checkpoint is not None  # just inserted in this transaction
        return checkpoint

    def get(self, checkpoint_id: uuid.UUID) -> ProcessingCheckpoint | None:
        return self._session.get(ProcessingCheckpoint, checkpoint_id, populate_existing=True)

    def latest_valid(
        self, run_id: uuid.UUID, *, before_ordinal: int | None = None
    ) -> ProcessingCheckpoint | None:
        """The newest `VALID` checkpoint, or the newest one below `before_ordinal`. Recovery that
        finds a payload it cannot read asks again with that checkpoint's ordinal: "moves backward"
        (§16)."""
        query = (
            select(ProcessingCheckpoint)
            .where(
                ProcessingCheckpoint.processing_run_id == run_id,
                ProcessingCheckpoint.state == CheckpointState.VALID,
            )
            .order_by(ProcessingCheckpoint.ordinal.desc())
            .limit(1)
            .execution_options(populate_existing=True)
        )
        if before_ordinal is not None:
            query = query.where(ProcessingCheckpoint.ordinal < before_ordinal)
        return self._session.scalars(query).one_or_none()

    def final_valid(self, run_id: uuid.UUID) -> ProcessingCheckpoint | None:
        """The run's `VALID` `FINAL` checkpoint: outputs durably settled, acceptance may be
        completed without rerunning ML (it is not itself acceptance)."""
        return self._session.scalars(
            select(ProcessingCheckpoint)
            .where(
                ProcessingCheckpoint.processing_run_id == run_id,
                ProcessingCheckpoint.kind == CheckpointKind.FINAL,
                ProcessingCheckpoint.state == CheckpointState.VALID,
            )
            .execution_options(populate_existing=True)
        ).one_or_none()

    def invalidate(self, checkpoint_id: uuid.UUID, *, reason: str, now: datetime) -> bool:
        """Mark a `VALID` checkpoint `INVALIDATED`; False if it was not valid. Never reversed."""
        result = self._session.execute(
            update(ProcessingCheckpoint)
            .where(
                ProcessingCheckpoint.id == checkpoint_id,
                ProcessingCheckpoint.state == CheckpointState.VALID,
            )
            .values(
                state=CheckpointState.INVALIDATED, invalidated_at=now, invalidated_reason=reason
            )
            .execution_options(synchronize_session=False)
        )
        return bool(result.rowcount)  # type: ignore[attr-defined]
