"""Retry an interrupted or failed source-processing attempt as a new Job and a new Run.

Persistence §15: "A retry creates a new Job with `previous_job_id`, not a state reset"; §12:
`parent_run_id` records reprocessing lineage. Recovery never requeues the old job (decided
2026-10-01 and clarified 2026-10-06), and the old run's PENDING output stays private: the retry
starts from nothing and the old attempt is left exactly as it ended.

The new run freezes a *copy* of the old run's configuration snapshot (one immutable snapshot per
run, §13), so the retry executes the same semantic intent; it does not re-resolve mutable settings.
"""

import uuid
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.jobs.models import Job, JobState, JobType
from backend.app.jobs.repository import JobRepository
from backend.app.processing.models import ProcessingRun, ProcessingRunState
from backend.app.processing.process_source import (
    ProcessSourceError,
    ScheduledProcessing,
    require_processable_image,
)
from backend.app.processing.run_repository import ProcessingRunRepository, SnapshotRepository
from backend.infrastructure.db.unit_of_work import UnitOfWork

_RETRYABLE_JOB_STATES = (JobState.INTERRUPTED, JobState.FAILED)
_RETRYABLE_RUN_STATES = (
    ProcessingRunState.INTERRUPTED,
    ProcessingRunState.FAILED,
    ProcessingRunState.NOT_RESUMABLE,
)


class RetryProcessingUseCase:
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

    def retry(self, job_id: uuid.UUID) -> ScheduledProcessing:
        """Queue a new attempt for a finished-without-result job, once."""
        scheduled = self._uow.write(lambda session: self._retry(session, job_id))
        try:
            self._wake_scheduler()
        except Exception:
            pass  # the queued job is durable; the scheduler finds it (as for a first request)
        return scheduled

    def _retry(self, session: Session, job_id: uuid.UUID) -> ScheduledProcessing:
        old_job = JobRepository(session).get(job_id)
        if old_job is None or old_job.type != JobType.PROCESS_SOURCE:
            raise ProcessSourceError(f"job {job_id} is not a source-processing job")
        if old_job.state not in _RETRYABLE_JOB_STATES or old_job.processing_run_id is None:
            raise ProcessSourceError(f"job {job_id} is {old_job.state}, which cannot be retried")
        old_run = ProcessingRunRepository(session).lock(old_job.processing_run_id)
        assert old_run is not None  # the job's foreign key guarantees the run
        if old_run.state not in _RETRYABLE_RUN_STATES:
            raise ProcessSourceError(
                f"run {old_run.id} is {old_run.state}, which cannot be retried"
            )
        if session.scalar(select(Job.id).where(Job.previous_job_id == old_job.id).limit(1)):
            raise ProcessSourceError(f"job {job_id} has already been retried")
        require_processable_image(session, old_run.source_id)
        old_snapshot = SnapshotRepository(session).get(old_run.configuration_snapshot_id)
        assert old_snapshot is not None  # the run's foreign key guarantees the snapshot

        now = self._clock()
        snapshot = SnapshotRepository(session).create(
            snapshot_id=self._new_id(),
            schema_version=old_snapshot.schema_version,
            canonical_json=old_snapshot.canonical_json,
            now=now,
            created_by_user_action=old_snapshot.created_by_user_action,
        )
        run = ProcessingRunRepository(session).add(
            ProcessingRun(
                id=self._new_id(),
                source_id=old_run.source_id,
                configuration_snapshot_id=snapshot.id,
                parent_run_id=old_run.id,
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
                previous_job_id=old_job.id,
                state=JobState.QUEUED,
                priority=old_job.priority,
                payload_schema_version=old_job.payload_schema_version,
                payload_json=old_job.payload_json,
                progress_mode=old_job.progress_mode,
                attempt_number=old_job.attempt_number + 1,
                created_at=now,
                updated_at=now,
            )
        )
        return ScheduledProcessing(old_run.source_id, run.id, job.id)
