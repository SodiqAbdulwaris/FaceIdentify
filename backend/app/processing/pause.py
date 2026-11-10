"""Pause and resume a video run (M6 step 7; API 13 to 15; the command boundary).

Like cancellation (`cancel.py`), the request is written here and the executor settles it: a
**running** video run and its job become `PAUSING`, and the executor stops at the end of the chunk
in hand, its checkpoint written, with run and job `PAUSED` (`ExecuteProcessingJob`); a crash while
`PAUSING` is settled `PAUSED` by startup recovery. **Resume** puts a `PAUSED` job back in the queue
(`QUEUED`, its run `PENDING`); the scheduler claims it as any job, a new execution segment starts,
and the run continues after its newest chunk checkpoint, never from the start and never twice.

Only a video run can be paused: an image takes one detection and one representation, so it has no
boundary worth pausing at. A repeat (pausing a run already pausing or paused, resuming one already
queued or running) changes nothing, so a double click is safe.
"""

import uuid
from collections.abc import Callable
from datetime import datetime
from enum import StrEnum

from sqlalchemy.orm import Session

from backend.app.jobs.models import Job, JobState
from backend.app.jobs.repository import JobRepository
from backend.app.processing.cancel import CancelError, RunNotFoundError
from backend.app.processing.models import ProcessingRun, ProcessingRunState
from backend.app.processing.run_repository import ProcessingRunRepository
from backend.app.sources.models import Source, SourceKind
from backend.infrastructure.db.optimistic import optimistic_locked_update
from backend.infrastructure.db.unit_of_work import UnitOfWork


class PauseError(CancelError):
    """The run cannot be paused or resumed from its current state."""


class PauseOutcome(StrEnum):
    REQUESTED = "REQUESTED"  # it will pause at the end of its chunk
    RESUMED = "RESUMED"  # back in the queue
    ALREADY = "ALREADY"  # a repeat


class PauseProcessingUseCase:
    def __init__(self, unit_of_work: UnitOfWork, *, clock: Callable[[], datetime]) -> None:
        self._uow = unit_of_work
        self._clock = clock

    def pause(self, run_id: uuid.UUID) -> PauseOutcome:
        return self._uow.write(lambda session: self._pause(session, run_id))

    def resume(self, run_id: uuid.UUID) -> PauseOutcome:
        return self._uow.write(lambda session: self._resume(session, run_id))

    def _pause(self, session: Session, run_id: uuid.UUID) -> PauseOutcome:
        run, job = self._load(session, run_id)
        if run.state in (ProcessingRunState.PAUSING, ProcessingRunState.PAUSED):
            return PauseOutcome.ALREADY
        if session.get(Source, run.source_id).kind != SourceKind.VIDEO:  # type: ignore[union-attr]
            raise PauseError(f"run {run_id} is not a video run: only a video can be paused")
        if run.state != ProcessingRunState.RUNNING or job.state != JobState.RUNNING:
            raise PauseError(f"run {run_id} is {run.state}, which cannot be paused")
        self._move(
            session, run, job, JobState.RUNNING, JobState.PAUSING, ProcessingRunState.PAUSING
        )
        return PauseOutcome.REQUESTED

    def _resume(self, session: Session, run_id: uuid.UUID) -> PauseOutcome:
        run, job = self._load(session, run_id)
        if run.state in (ProcessingRunState.PENDING, ProcessingRunState.RUNNING) and job.state in (
            JobState.QUEUED,
            JobState.RUNNING,
        ):
            return PauseOutcome.ALREADY
        if run.state != ProcessingRunState.PAUSED or job.state != JobState.PAUSED:
            raise PauseError(f"run {run_id} is {run.state}, which cannot be resumed")
        self._move(session, run, job, JobState.PAUSED, JobState.QUEUED, ProcessingRunState.PENDING)
        return PauseOutcome.RESUMED

    @staticmethod
    def _load(session: Session, run_id: uuid.UUID) -> tuple[ProcessingRun, Job]:
        run = ProcessingRunRepository(session).lock(run_id)
        if run is None:
            raise RunNotFoundError(f"run {run_id} does not exist")
        job = JobRepository(session).current_for_run(run_id)
        assert job is not None  # (every source run is created with its job)
        return run, job

    def _move(
        self,
        session: Session,
        run: ProcessingRun,
        job: Job,
        job_from: JobState,
        job_to: JobState,
        run_to: ProcessingRunState,
    ) -> None:
        now = self._clock()
        moved = JobRepository(session).transition(job.id, (job_from,), job_to, now=now)
        updated = optimistic_locked_update(
            session,
            ProcessingRun,
            run.id,
            expected_revision=run.revision,
            values={"state": run_to, "updated_at": now},
        )
        # Both hold: the run's write lock was taken first, so nothing moved the rows meanwhile.
        assert moved
        assert updated == 1
