"""Retry an interrupted or failed source-processing attempt as a new Job and a new Run.

Persistence §15: "A retry creates a new Job with `previous_job_id`, not a state reset"; §12:
`parent_run_id` records this retry lineage (persistence 12.1: reprocessing lineage is
`supersedes_run_id`). Recovery never requeues the old job (decided
2026-10-01 and clarified 2026-10-06), and the old run's PENDING output stays private: the retry
starts from nothing and the old attempt is left exactly as it ended.

The new run freezes a *copy* of the old run's configuration snapshot (one immutable snapshot per
run, §13), so the retry executes the same semantic intent; it does not re-resolve mutable settings.

A video run (M6 D10) that stopped part way (`INTERRUPTED` or `FAILED`) with at least one chunk
checkpoint, and whose frozen snapshot can still be planned (the same models are installed: the
caller's `runnable`), is retried by RESUMING it: a new Job on the SAME run (API 15: "a retry may
continue the same logical ProcessingRun from a valid checkpoint with a new ExecutionSegment"), the
run back to `PENDING`, so it continues after its last chunk and nothing committed is redone. Any
other video retry is a new run as for an image, the old run's private output left untouched.

A retry keeps what it retries: the job type, and for a reprocess run the generation it replaces
(`supersedes_run_id`). A first run is not retried once its source has an accepted result, and a
reprocess run only while the generation it would replace is still current and nothing else of the
source is in flight: either way acceptance would have to refuse it.
"""

import uuid
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.jobs.models import SOURCE_JOB_TYPES, Job, JobState
from backend.app.jobs.repository import JobRepository
from backend.app.processing.models import ProcessingRun, ProcessingRunState
from backend.app.processing.process_source import (
    ProcessSourceError,
    ScheduledProcessing,
    SourceAlreadyProcessedError,
    require_no_run_in_flight,
    require_processable_source,
)
from backend.app.processing.repository import CheckpointRepository
from backend.app.processing.run_repository import ProcessingRunRepository, SnapshotRepository
from backend.app.sources.models import Source, SourceKind
from backend.infrastructure.db.optimistic import optimistic_locked_update
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
        runnable: Callable[[Session, ProcessingRun], bool] = lambda _session, _run: True,
    ) -> None:
        """`runnable`: whether a run's frozen snapshot can still be planned here (D10)."""
        self._runnable = runnable
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
        if old_job is None or old_job.type not in SOURCE_JOB_TYPES:
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
        kind = require_processable_source(session, old_run.source_id)
        current = session.scalar(
            select(Source.current_processing_run_id).where(Source.id == old_run.source_id)
        )
        if old_run.supersedes_run_id is None:
            if current is not None:
                raise SourceAlreadyProcessedError(
                    f"source {old_run.source_id} already has a result; reprocess it instead"
                )
        else:
            if current != old_run.supersedes_run_id:
                raise ProcessSourceError(
                    f"the generation run {old_run.id} would replace is no longer current"
                )
            require_no_run_in_flight(session, old_run.source_id)
        now = self._clock()
        if (
            kind == SourceKind.VIDEO
            and old_run.state in (ProcessingRunState.INTERRUPTED, ProcessingRunState.FAILED)
            and CheckpointRepository(session).latest_valid(old_run.id) is not None
            and self._runnable(session, old_run)
        ):
            return self._resume(session, old_job, old_run, now)
        old_snapshot = SnapshotRepository(session).get(old_run.configuration_snapshot_id)
        assert old_snapshot is not None  # the run's foreign key guarantees the snapshot

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
                supersedes_run_id=old_run.supersedes_run_id,
                state=ProcessingRunState.PENDING,
                requested_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        job_id = self._next_job(session, old_job, run.id, now)
        return ScheduledProcessing(old_run.source_id, run.id, job_id)

    def _resume(
        self, session: Session, old_job: Job, run: ProcessingRun, now: datetime
    ) -> ScheduledProcessing:
        """D10: the same run continues after its newest chunk checkpoint, under a new job."""
        changed = optimistic_locked_update(
            session,
            ProcessingRun,
            run.id,
            expected_revision=run.revision,
            values={
                "state": ProcessingRunState.PENDING,
                "failed_at": None,
                "failure_code": None,
                "failure_detail": None,
                "updated_at": now,
            },
        )
        assert changed == 1  # the run's write lock was taken by the caller
        job_id = self._next_job(session, old_job, run.id, now)
        return ScheduledProcessing(run.source_id, run.id, job_id)

    def _next_job(
        self, session: Session, old_job: Job, run_id: uuid.UUID, now: datetime
    ) -> uuid.UUID:
        return (
            JobRepository(session)
            .add(
                Job(
                    id=self._new_id(),
                    type=old_job.type,
                    processing_run_id=run_id,
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
            .id
        )
