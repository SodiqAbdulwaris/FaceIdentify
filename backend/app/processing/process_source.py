"""Create the durable, schedulable request to process one imported image, or to reprocess one
that already has an accepted result (persistence 12.1 item 2; API and Contracts 5.4)."""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.jobs.models import Job, JobPriority, JobState, JobType, ProgressMode
from backend.app.jobs.repository import JobRepository
from backend.app.processing.configuration import (
    ProcessingConfigurationError,
    ProcessingRequestV1,
    resolve,
)
from backend.app.processing.models import ProcessingRun, ProcessingRunState
from backend.app.processing.run_repository import ProcessingRunRepository, SnapshotRepository
from backend.app.sources.lifecycle import IN_FLIGHT
from backend.app.sources.models import Artifact, ArtifactState, Source, SourceKind, SourceState
from backend.infrastructure.db.unit_of_work import UnitOfWork


class ProcessSourceError(Exception):
    """The source cannot start a processing run in its present durable state."""


class SourceAlreadyProcessedError(ProcessSourceError):
    """`process` on a source that already has an accepted result: reprocess it instead."""


class SourceNotProcessedError(ProcessSourceError):
    """`reprocess` on a source with no accepted result: process it first."""


class SourceBusyError(ProcessSourceError):
    """A run of the source is in flight; it must end (or be cancelled) first."""


@dataclass(frozen=True, slots=True)
class ScheduledProcessing:
    source_id: uuid.UUID
    processing_run_id: uuid.UUID
    job_id: uuid.UUID


def require_processable_source(session: Session, source_id: uuid.UUID) -> SourceKind:
    """The source must be ACTIVE with an AVAILABLE original, else `ProcessSourceError`. An image
    or, since M6 step 5, a video; returns which."""
    source = session.execute(
        select(Source, Artifact.state)
        .join(Artifact, Artifact.id == Source.original_artifact_id)
        .where(Source.id == source_id)
    ).one_or_none()
    if source is None:
        raise ProcessSourceError(f"source {source_id} does not exist")
    row, artifact_state = source
    if row.state != SourceState.ACTIVE:
        raise ProcessSourceError(f"source {source_id} is not active")
    if artifact_state != ArtifactState.AVAILABLE:
        raise ProcessSourceError(f"source {source_id}'s original is not available")
    return SourceKind(row.kind)


def require_no_run_in_flight(session: Session, source_id: uuid.UUID) -> None:
    """`SourceBusyError` while any run of the source is still in flight."""
    if session.scalar(
        select(ProcessingRun.id)
        .where(
            ProcessingRun.source_id == source_id,
            ProcessingRun.state.in_(IN_FLIGHT),
        )
        .limit(1)
    ):
        raise SourceBusyError(f"a run of source {source_id} is still in flight")


class ProcessSourceUseCase:
    """Create one snapshot, PENDING run and queued job atomically: `process` makes a source's first
    generation (a `PROCESS_SOURCE` job), `reprocess` a new one that will replace the current
    generation once accepted (a `REPROCESS_SOURCE` job whose run names it in `supersedes_run_id`).

    It resolves the caller's strict `ProcessingRequestV1` inside that transaction, freezing
    catalog-backed semantic intent rather than an arbitrary mutable-settings object.
    """

    def __init__(
        self,
        unit_of_work: UnitOfWork,
        *,
        new_id: Callable[[], uuid.UUID],
        clock: Callable[[], datetime],
        wake_scheduler: Callable[[], None],
    ) -> None:
        self._uow = unit_of_work
        self._new_id = new_id
        self._clock = clock
        self._wake_scheduler = wake_scheduler

    def process(
        self,
        source_id: uuid.UUID,
        *,
        processing_request: dict[str, Any],
        priority: str,
        created_by_user_action: str | None,
    ) -> ScheduledProcessing:
        """Commit the request, then best-effort wake its scheduler.

        A lost wake is safe: the queued job is durable and scheduler recovery rediscovers it.
        """
        return self._commit_and_wake(
            source_id, processing_request, priority, created_by_user_action, reprocess=False
        )

    def reprocess(
        self,
        source_id: uuid.UUID,
        *,
        processing_request: dict[str, Any],
        priority: str,
        created_by_user_action: str | None,
    ) -> ScheduledProcessing:
        """Commit a reprocessing request, then best-effort wake the scheduler. The current
        generation is not touched: it stays authoritative until the new run is accepted."""
        return self._commit_and_wake(
            source_id, processing_request, priority, created_by_user_action, reprocess=True
        )

    def _commit_and_wake(
        self,
        source_id: uuid.UUID,
        processing_request: dict[str, Any],
        priority: str,
        created_by_user_action: str | None,
        *,
        reprocess: bool,
    ) -> ScheduledProcessing:
        scheduled = self._uow.write(
            lambda session: self._schedule(
                session,
                source_id,
                processing_request,
                priority,
                created_by_user_action,
                reprocess=reprocess,
            )
        )
        try:
            self._wake_scheduler()
        except Exception:
            # API and Contracts §110: a scheduler wake is recoverable from the queued row.
            pass
        return scheduled

    def _schedule(
        self,
        session: Session,
        source_id: uuid.UUID,
        processing_request: dict[str, Any],
        priority: str,
        created_by_user_action: str | None,
        *,
        reprocess: bool,
    ) -> ScheduledProcessing:
        require_processable_source(session, source_id)
        current = session.scalar(
            select(Source.current_processing_run_id).where(Source.id == source_id)
        )
        if reprocess:
            if current is None:
                raise SourceNotProcessedError(f"source {source_id} has no accepted result")
            require_no_run_in_flight(session, source_id)
        elif current is not None:
            raise SourceAlreadyProcessedError(f"source {source_id} already has a result")
        try:
            JobPriority(priority)
        except ValueError:
            raise ProcessSourceError(f"{priority!r} is not a job priority") from None
        try:
            request = ProcessingRequestV1.parse(processing_request)
            resolved_configuration = resolve(session, request)
        except ProcessingConfigurationError as error:
            raise ProcessSourceError(str(error)) from None

        now = self._clock()
        snapshot = SnapshotRepository(session).create(
            snapshot_id=self._new_id(),
            schema_version=1,
            canonical_json=resolved_configuration,
            now=now,
            created_by_user_action=created_by_user_action,
        )
        run = ProcessingRunRepository(session).add(
            ProcessingRun(
                id=self._new_id(),
                source_id=source_id,
                configuration_snapshot_id=snapshot.id,
                state=ProcessingRunState.PENDING,
                requested_at=now,
                created_at=now,
                updated_at=now,
                supersedes_run_id=current if reprocess else None,
            )
        )
        job = JobRepository(session).add(
            Job(
                id=self._new_id(),
                type=JobType.REPROCESS_SOURCE if reprocess else JobType.PROCESS_SOURCE,
                processing_run_id=run.id,
                state=JobState.QUEUED,
                priority=priority,
                payload_schema_version=1,
                payload_json=None,
                progress_mode=ProgressMode.INDETERMINATE,
                created_at=now,
                updated_at=now,
            )
        )
        return ScheduledProcessing(source_id, run.id, job.id)
