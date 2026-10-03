"""Create the durable, schedulable request to process one imported image."""

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
from backend.app.sources.models import Artifact, ArtifactState, Source, SourceKind, SourceState
from backend.infrastructure.db.unit_of_work import UnitOfWork


class ProcessSourceError(Exception):
    """The source cannot start a processing run in its present durable state."""


@dataclass(frozen=True, slots=True)
class ScheduledProcessing:
    source_id: uuid.UUID
    processing_run_id: uuid.UUID
    job_id: uuid.UUID


class ProcessSourceUseCase:
    """Create one snapshot, PENDING run and queued PROCESS_SOURCE job atomically.

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
        scheduled = self._uow.write(
            lambda session: self._schedule(
                session,
                source_id,
                processing_request,
                priority,
                created_by_user_action,
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
    ) -> ScheduledProcessing:
        source = session.execute(
            select(Source, Artifact.state)
            .join(Artifact, Artifact.id == Source.original_artifact_id)
            .where(Source.id == source_id)
        ).one_or_none()
        if source is None:
            raise ProcessSourceError(f"source {source_id} does not exist")
        row, artifact_state = source
        if row.kind != SourceKind.IMAGE:
            raise ProcessSourceError(f"source {source_id} is not an image")
        if row.state != SourceState.ACTIVE:
            raise ProcessSourceError(f"source {source_id} is not active")
        if artifact_state != ArtifactState.AVAILABLE:
            raise ProcessSourceError(f"source {source_id}'s original is not available")
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
            )
        )
        job = JobRepository(session).add(
            Job(
                id=self._new_id(),
                type=JobType.PROCESS_SOURCE,
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
