"""Run one queued source-processing job end to end: claim, execute privately, accept (M4 W2).

`ProcessingRunner.run_once` is the unit a scheduler loop repeats. It composes the pieces that
already own their own invariants: `ProcessingScheduler` claims and starts the run,
`ExecuteProcessingJob` does the work outside any write transaction and leaves a FINAL checkpoint,
and `AcceptProcessingRunUseCase` makes the result authoritative in one transaction. Nothing here
decides anything about identity.

Failures end in one of a few outcomes and never in a half-state this runner leaves behind:

* a failure the executor already settled (`SETTLED_FAILURES`: the run and job are `FAILED`);
* a cancellation, settled by the executor (`CANCELLED`);
* a FINAL that acceptance refuses: the run becomes `NOT_RESUMABLE` and the job `FAILED` in one
  transaction, and the private output stays private (the same decision startup recovery applies);
* an error after the acceptance committed (the index wake): the run is read back, and `COMPLETED`
  counts as accepted, the error is reported, never an undone run;
* anything else is a defect: the claimed work is settled `FAILED` (best effort) and the error is
  raised to the caller, which must not retry it blindly.

Whether recovery has finished is the caller's responsibility: the scheduler loop is created only
after the library is reported open (`backend.api.startup`), so this never races startup recovery.
"""

import uuid
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from sqlalchemy.orm import Session

from backend.app.jobs.models import JobState
from backend.app.jobs.repository import JobRepository
from backend.app.processing.accept_run import AcceptanceError, AcceptProcessingRunUseCase
from backend.app.processing.execute_job import (
    SETTLED_FAILURES,
    ExecuteProcessingJob,
    ProcessingCancelledError,
)
from backend.app.processing.models import ProcessingRunState
from backend.app.processing.scheduler import ProcessingScheduler
from backend.app.recovery.startup import mark_run_not_resumable, run_state
from backend.infrastructure.db.unit_of_work import UnitOfWork

REFUSED_FINAL_CODE = "FINAL_NOT_ACCEPTABLE"
UNEXPECTED_CODE = "UNEXPECTED_ERROR"


class RunOutcomeKind(StrEnum):
    IDLE = "IDLE"  # nothing was queued
    ACCEPTED = "ACCEPTED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"  # a failure the executor settled
    NOT_ACCEPTABLE = "NOT_ACCEPTABLE"  # a refused FINAL


@dataclass(frozen=True, slots=True)
class RunOutcome:
    kind: RunOutcomeKind
    processing_run_id: uuid.UUID | None = None
    # An exception class name (never a message: it could carry a path), when there was an error.
    error: str | None = None
    # The index wake raised after a committed acceptance; the durable ADDs are replayed later.
    wake_error: str | None = None


class ProcessingRunner:
    def __init__(
        self,
        unit_of_work: UnitOfWork,
        scheduler: ProcessingScheduler,
        executor: ExecuteProcessingJob,
        accept: AcceptProcessingRunUseCase,
        *,
        owner: str,
        clock: Callable[[], datetime],
        on_started: Callable[[uuid.UUID], None] | None = None,
    ) -> None:
        self._on_started = on_started
        self._uow = unit_of_work
        self._scheduler = scheduler
        self._executor = executor
        self._accept = accept
        self._owner = owner
        self._clock = clock

    def run_once(self) -> RunOutcome:
        """Process at most one queued job. Returns `IDLE` when there was none. `on_started` is told
        the run's id once its job is claimed (best effort: it is a notification)."""
        started = self._scheduler.claim_source_job(self._owner)
        if started is None:
            return RunOutcome(RunOutcomeKind.IDLE)
        run_id = started.job.processing_run_id
        assert run_id is not None  # the scheduler fails a claim without a run: never returned
        if self._on_started is not None:
            with suppress(Exception):  # a failed notification must never fail the work
                self._on_started(run_id)
        try:
            self._executor.execute(started)
        except ProcessingCancelledError:
            return RunOutcome(RunOutcomeKind.CANCELLED, run_id)
        except SETTLED_FAILURES as error:
            return RunOutcome(RunOutcomeKind.FAILED, run_id, type(error).__name__)
        except Exception as error:
            with suppress(Exception):  # best effort: the defect itself must not be masked
                self._executor.fail_claimed(started, UNEXPECTED_CODE)
            raise RuntimeError(f"unexpected {type(error).__name__} while processing") from error
        try:
            self._accept.accept(run_id)
        except AcceptanceError as error:
            self._refuse_final(run_id, started.job.id, str(error))
            return RunOutcome(RunOutcomeKind.NOT_ACCEPTABLE, run_id, type(error).__name__)
        except Exception as error:
            if run_state(self._uow, run_id) != ProcessingRunState.COMPLETED:
                raise  # the acceptance did not commit: the run stays FINALIZING for recovery
            return RunOutcome(RunOutcomeKind.ACCEPTED, run_id, wake_error=type(error).__name__)
        return RunOutcome(RunOutcomeKind.ACCEPTED, run_id)

    def _refuse_final(self, run_id: uuid.UUID, job_id: uuid.UUID, detail: str) -> None:
        now = self._clock()

        def refuse(session: Session) -> None:
            mark_run_not_resumable(session, run_id, detail, now)
            JobRepository(session).transition(
                job_id,
                (JobState.RUNNING,),
                JobState.FAILED,
                now=now,
                failure_code=REFUSED_FINAL_CODE,
                failure_detail="the FINAL checkpoint was not acceptable",
            )

        self._uow.write(refuse)
