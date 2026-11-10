"""Request the cancellation of a source-processing run (the command boundary; Persistence §15, §28).

The executor never writes the *request*: it only observes it between external work units and then
settles `CANCELLED` (`ExecuteProcessingJob`), and recovery settles a request a crash left behind.
This use case writes it, in one transaction that takes the run's write lock first:

* a **queued** job (its run `PENDING`) is cancelled outright: job and run `CANCELLED` together, so
  the scheduler never claims it;
* a **running** job asks to stop: job and run `CANCELLING`; the executor settles `CANCELLED` at its
  next safe boundary, and its private output stays private;
* a run already `CANCELLING` or `CANCELLED` is a repeat: nothing changes, so a double click is safe;
* a **paused** video run (M6 step 7) is cancelled outright, job and run `CANCELLED`; one still
  **pausing** (its chunk in hand) asks to stop instead, job and run `CANCELLING`, settled at the
  next boundary like any running one;
* a request naming a job (`job_id`) acts only if it is the run's current attempt (a resumed video
  run has an older, finished job: commands to it must not reach the newer one);
* anything else (`FINALIZING`, whose FINAL result is being made authoritative, or a run that is
  over or interrupted) cannot be cancelled here.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from sqlalchemy.orm import Session

from backend.app.jobs.models import Job, JobState
from backend.app.jobs.repository import JobRepository
from backend.app.processing.models import ProcessingRun, ProcessingRunState
from backend.app.processing.run_repository import ProcessingRunRepository
from backend.infrastructure.db.optimistic import optimistic_locked_update
from backend.infrastructure.db.unit_of_work import UnitOfWork


class CancelError(Exception):
    """The run does not exist or is not in a state that can be cancelled."""


class RunNotFoundError(CancelError):
    pass


class CancelOutcome(StrEnum):
    CANCELLED = "CANCELLED"  # it had not started: cancelled now
    REQUESTED = "REQUESTED"  # it is running: it will stop at its next safe boundary
    ALREADY = "ALREADY"  # a repeat: it was already being, or had been, cancelled


@dataclass(frozen=True, slots=True)
class CancelResult:
    run_id: uuid.UUID
    outcome: CancelOutcome


class CancelProcessingUseCase:
    def __init__(self, unit_of_work: UnitOfWork, *, clock: Callable[[], datetime]) -> None:
        self._uow = unit_of_work
        self._clock = clock

    def cancel(self, run_id: uuid.UUID, *, job_id: uuid.UUID | None = None) -> CancelResult:
        return self._uow.write(lambda session: self._cancel(session, run_id, job_id))

    def _cancel(
        self, session: Session, run_id: uuid.UUID, job_id: uuid.UUID | None = None
    ) -> CancelResult:
        run = ProcessingRunRepository(session).lock(run_id)
        if run is None:
            raise RunNotFoundError(f"run {run_id} does not exist")
        job = JobRepository(session).current_for_run(run_id)
        if job_id is not None and (job is None or job.id != job_id):  # (before any repeat answer)
            raise CancelError(f"job {job_id} is not the current attempt of run {run_id}")
        if run.state in (ProcessingRunState.CANCELLING, ProcessingRunState.CANCELLED):
            return CancelResult(run_id, CancelOutcome.ALREADY)
        if job and job.state == JobState.QUEUED:  # its run is PENDING: nothing has started
            self._settle(
                session, run, job, JobState.QUEUED, JobState.CANCELLED, ProcessingRunState.CANCELLED
            )
            return CancelResult(run_id, CancelOutcome.CANCELLED)
        if run.state == ProcessingRunState.PAUSING and job and job.state == JobState.PAUSING:
            self._settle(
                session,
                run,
                job,
                JobState.PAUSING,
                JobState.CANCELLING,
                ProcessingRunState.CANCELLING,
            )
            return CancelResult(run_id, CancelOutcome.REQUESTED)
        if run.state == ProcessingRunState.PAUSED and job and job.state == JobState.PAUSED:
            self._settle(
                session, run, job, JobState.PAUSED, JobState.CANCELLED, ProcessingRunState.CANCELLED
            )
            return CancelResult(run_id, CancelOutcome.CANCELLED)
        if run.state == ProcessingRunState.RUNNING and job and job.state == JobState.RUNNING:
            self._settle(
                session,
                run,
                job,
                JobState.RUNNING,
                JobState.CANCELLING,
                ProcessingRunState.CANCELLING,
            )
            return CancelResult(run_id, CancelOutcome.REQUESTED)
        raise CancelError(f"run {run_id} is {run.state}, which cannot be cancelled")

    def _settle(
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
        # Both hold: the write lock was taken first, so nothing moved the rows since they were read.
        assert moved
        assert updated == 1
