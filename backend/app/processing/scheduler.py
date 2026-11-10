"""Short transactional boundary for claiming and starting M3 source-processing work.

Claiming a Job and recording that its ProcessingRun has begun are durable state transitions.  They
finish before media decoding, worker calls, or any other expensive operation starts; the executor
that follows owns those external effects and later settlement transactions.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.jobs.models import SOURCE_JOB_TYPES, Job, JobState
from backend.app.jobs.repository import ClaimedJob, JobRepository
from backend.app.processing.models import ProcessingRun, ProcessingRunState
from backend.app.processing.repository import SegmentRepository
from backend.app.processing.run_repository import ProcessingRunRepository
from backend.app.sources.models import Source, SourceKind
from backend.infrastructure.db.optimistic import optimistic_locked_update
from backend.infrastructure.db.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True)
class StartedProcessingJob:
    """A claimed job with its run and lifecycle segment durably started."""

    job: ClaimedJob
    execution_segment_id: uuid.UUID


# A video run in these states holds the movie slot (a paused one does not: it waits for a person).
_HEAVY = (
    ProcessingRunState.RUNNING,
    ProcessingRunState.PAUSING,
    ProcessingRunState.CANCELLING,
    ProcessingRunState.FINALIZING,
)


class ProcessingScheduler:
    """Claims only source-processing work (a first run or a reprocess run) and starts its run in
    one short write transaction. `videos` True claims only video work and False everything else
    (M6 step 7): the backend runs one loop of each, so one heavy movie runs at a time while images
    keep being processed beside it, both sharing the one worker (`WorkerLease`)."""

    def __init__(
        self,
        uow: UnitOfWork,
        *,
        new_id: Callable[[], uuid.UUID],
        clock: Callable[[], datetime],
        lease_for: timedelta,
        videos: bool | None = None,
    ) -> None:
        self._videos = videos
        self._uow = uow
        self._new_id = new_id
        self._clock = clock
        self._lease_for = lease_for

    def claim_source_job(self, owner: str) -> StartedProcessingJob | None:
        """Claim and start one queued source job, or return None when none is eligible.

        A corrupt/stale job is made FAILED rather than left leased forever.  It cannot cause an
        ML call because the method returns None for it.
        """
        if not owner:
            raise ValueError("the scheduler owner must not be blank")
        now = self._clock()
        return self._uow.write(lambda session: self._claim(session, owner, now))

    def _claim(self, session: Session, owner: str, now: datetime) -> StartedProcessingJob | None:
        # Session is intentionally not stored: this transaction ends before the executor computes.
        repository = JobRepository(session)
        if self._videos and session.scalar(
            select(ProcessingRun.id)
            .where(
                ProcessingRun.id.in_(self._kind_runs()),
                ProcessingRun.state.in_(_HEAVY),
            )
            .limit(1)
        ):
            return None  # one heavy movie at a time (processing spec section 8)
        job = repository.claim_next(
            owner=owner,
            now=now,
            lease_for=self._lease_for,
            types=SOURCE_JOB_TYPES,
            where=() if self._videos is None else (Job.processing_run_id.in_(self._kind_runs()),),
        )
        if job is None:
            return None
        if job.processing_run_id is None:
            self._fail(repository, job, now, "PROCESSING_RUN_MISSING")
            return None
        run = ProcessingRunRepository(session).lock(job.processing_run_id)
        if run is None or run.state != ProcessingRunState.PENDING:
            self._fail(repository, job, now, "PROCESSING_RUN_NOT_PENDING")
            return None
        changed = optimistic_locked_update(
            session,
            ProcessingRun,
            run.id,
            expected_revision=run.revision,
            # (a resumed video run keeps when it first started)
            values={
                "state": ProcessingRunState.RUNNING,
                "started_at": run.started_at or now,
                "updated_at": now,
            },
            extra_where=(ProcessingRun.state == ProcessingRunState.PENDING,),
        )
        assert changed == 1  # the write lock taken by ProcessingRunRepository.lock prevents a race
        segment = SegmentRepository(session).append(
            run.id,
            segment_id=self._new_id(),
            runtime_variant_id=None,
            runtime_details={"schema_version": 1},
            now=now,
        )
        return StartedProcessingJob(job, segment.id)

    def _kind_runs(self) -> Any:
        kind = Source.kind == SourceKind.VIDEO if self._videos else Source.kind != SourceKind.VIDEO
        return (
            select(ProcessingRun.id).join(Source, Source.id == ProcessingRun.source_id).where(kind)
        )

    @staticmethod
    def _fail(repository: JobRepository, job: ClaimedJob, now: datetime, code: str) -> None:
        changed = repository.transition(
            job.id,
            (JobState.RUNNING,),
            JobState.FAILED,
            now=now,
            failure_code=code,
            failure_detail="the claimed job cannot start a pending processing run",
        )
        assert changed
