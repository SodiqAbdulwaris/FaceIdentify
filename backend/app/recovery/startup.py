"""Startup recovery: reconcile what a crash left half done (PERSISTENCE_IMPLEMENTATION.md §28,
IMPLEMENTATION_ARCHITECTURE.md §22-§23).

Startup order is database and migrations, storage, **recovery**, **indexes**, then the runtime, the
ML worker and the scheduler. `recover_on_startup` is the recovery and index steps, in that order:

1. Artifacts: settle every interrupted managed write and deletion (`recover_artifacts`), and mark
   an available managed artifact or a referenced original whose file is gone `MISSING` (existence
   only: nothing is hashed at startup).
2. In-flight work: a `RUNNING` job, processing run or execution segment belongs to a process that
   no longer exists, so it becomes `INTERRUPTED` and the job's lease is cleared (§23.2: "Interrupted
   active runs/segments become `INTERRUPTED`"; resuming creates new work, it does not reopen this).
   A job or run that was `PAUSING` becomes `PAUSED` (nothing runs; the worker pausing it is gone)
   and one that was `CANCELLING` becomes `CANCELLED` (the user's intent; its partial output stays
   private), decided 2026-10-01 (CONTEXT open question 26).
3. Workspaces: remove the temp workspace of every job that is over; keep those a job may resume.
4. Indexes: validate every active space's index and rebuild what is missing or unusable, and give
   every `FAILED` `IndexOperation` one fresh set of attempts (persistence §28: "pending/failed").
5. Erasures: every `ERASING` representation gets its missing `REMOVE`, is finished when its
   conditions hold (`RepresentationEraser.resume`), and an owed truncation of the write-ahead log is
   done; whatever cannot finish is reported as unresolved (persistence §6.2, §28).
6. Pending `IndexOperation`s: catch the indexes up, in bounded passes.

Recovery is idempotent and safe to repeat after another crash (§28, §23.8): each step only records
a durable repair, and after one completed run a second finds nothing left to repair. The exception
is a condition that keeps failing for an external reason (a locked file, an index operation that
keeps failing): it is retried once per start, bounded, and reported as *unresolved*, not as a
repair. It never turns a pending run's partial output into library memory, and it never assumes
anything in memory survived.

Not handled here, and left exactly as found: a run that was `FINALIZING` or the acceptance of a run
with a final checkpoint (needs the run lifecycle of M3), and the recovery of an interrupted runtime
installation (GitHub issue 34).

Precondition, like `recover_artifacts`: one process, no other user of the library, before workers
start. Single-instance is the desktop shell's job (tech-stack §2).
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session, sessionmaker

from backend.app.jobs.models import Job, JobState
from backend.app.jobs.repository import FINISHED_JOB_STATES
from backend.app.memory.erasure import ErasureReport, RepresentationEraser
from backend.app.memory.index_coordinator import CoordinatorReport, IndexCoordinator
from backend.app.processing.models import (
    TRANSIENT_RUN_STATES,
    ExecutionSegment,
    ExecutionSegmentState,
    ProcessingRun,
    ProcessingRunState,
)
from backend.app.sources.artifact_storage import (
    RecoveryReport,
    mark_missing_managed_files,
    recover_artifacts,
    require_library_root,
)
from backend.app.sources.referenced_artifacts import mark_missing_referenced_originals
from backend.infrastructure.storage.files import ManagedFileStore
from backend.infrastructure.storage.workspaces import WorkspaceCleanup, WorkspaceManager


@dataclass
class InterruptedWork:
    jobs: list[uuid.UUID] = field(default_factory=list)
    runs: list[uuid.UUID] = field(default_factory=list)
    segments: list[uuid.UUID] = field(default_factory=list)
    # Jobs not `RUNNING` that still held a lease (and so are not in `jobs`): their state is
    # untouched, only the lease nobody can hold any more is cleared.
    leases_cleared: list[uuid.UUID] = field(default_factory=list)
    # Work that was being paused or cancelled when the process died: `PAUSING` -> `PAUSED` and
    # `CANCELLING` -> `CANCELLED`, for jobs and for runs.
    jobs_paused: list[uuid.UUID] = field(default_factory=list)
    jobs_cancelled: list[uuid.UUID] = field(default_factory=list)
    runs_paused: list[uuid.UUID] = field(default_factory=list)
    runs_cancelled: list[uuid.UUID] = field(default_factory=list)


@dataclass
class StartupReport:
    artifacts: RecoveryReport
    missing_references: list[uuid.UUID]
    missing_managed: list[uuid.UUID]
    interrupted: InterruptedWork
    workspaces: WorkspaceCleanup
    indexes_rebuilt: list[uuid.UUID]
    requeued_operations: list[uuid.UUID]
    index_operations: CoordinatorReport
    index_passes: int
    erasure: ErasureReport

    @property
    def unresolved(self) -> list[str]:
        """What recovery tried and could not finish, or left for later, by name. A repair that
        needs another start (a locked file) or a decision (a corrupt vector) is not a clean run.
        Entries under `temp/jobs/` that are not workspaces are not listed: they are not
        recovery's work."""
        artifacts, operations = self.artifacts, self.index_operations
        counts = {
            "artifacts skipped": len(artifacts.skipped),
            "staging files left": len(artifacts.staging_left),
            "artifact deletions failed": len(artifacts.delete_failed),
            "workspaces not removed": len(self.workspaces.failed),
            "representations that cannot be indexed": len(operations.unindexable),
            "superseded index files not removed": len(operations.leftover_files),
            "index operations backing off": len(operations.retrying),
            "index operations out of attempts": len(operations.failed),
            "erasure steps outstanding": len(self.erasure.outstanding_cleanup),
        }
        return [f"{count} {what}" for what, count in counts.items() if count]

    @property
    def repaired_nothing(self) -> bool:
        """True when this run made no repair (the state a second run reaches once the first has
        converged). It says nothing about whether anything is still unresolved, and a condition that
        keeps failing is retried on every start: see `unresolved` and `clean`."""
        artifacts = self.artifacts
        operations = self.index_operations
        return not (
            artifacts.finalized
            or artifacts.write_not_completed
            or artifacts.deleted
            or artifacts.delete_failed
            or artifacts.staging_removed
            or self.missing_references
            or self.missing_managed
            or self.interrupted.jobs
            or self.interrupted.runs
            or self.interrupted.segments
            or self.interrupted.leases_cleared
            or self.interrupted.jobs_paused
            or self.interrupted.jobs_cancelled
            or self.interrupted.runs_paused
            or self.interrupted.runs_cancelled
            or self.workspaces.removed
            or self.indexes_rebuilt
            or self.requeued_operations
            or operations.applied
            or operations.retrying
            or operations.failed
            or operations.rebuilt_spaces
            or operations.purged_spaces
            or self.erasure.erased
            or self.erasure.truncated
        )

    @property
    def clean(self) -> bool:
        """No repair was needed and nothing is left unresolved."""
        return self.repaired_nothing and not self.unresolved


def interrupt_in_flight_work(
    session_factory: sessionmaker[Session], *, clock: Callable[[], datetime]
) -> InterruptedWork:
    """Mark every `RUNNING` job, run and segment `INTERRUPTED`, a `PAUSING` job or run `PAUSED` and
    a `CANCELLING` one `CANCELLED`, in one transaction.

    Each is a guarded `UPDATE ... RETURNING`, so a repeated run matches nothing and the first
    statement of the transaction is a write. A job's lease is cleared, since nobody holds it now:
    for a `RUNNING`, `PAUSING` or `CANCELLING` job as it moves on, and for any *other* job still
    holding one (an expired or stale lease, persistence §28) with its state left alone. A cancelled
    job gets `ended_at`. A `PAUSING` or `CANCELLING` run's partial output is not touched: it stays
    private and is never activated by recovery (§28), and a paused one can be resumed in a new
    segment. The decision is the owner's (2026-10-01, CONTEXT open question 26).
    A segment ends at recovery time with no `ended_reason`: nothing recorded why it stopped, and the
    closest reasons (`WORKER_CRASH`, `SHUTDOWN`) would claim a cause that is not known.
    """
    now = clock()
    with session_factory() as session:
        jobs = (
            session.execute(
                update(Job)
                .where(Job.state == JobState.RUNNING)
                .values(
                    state=JobState.INTERRUPTED,
                    lease_owner=None,
                    lease_expires_at=None,
                    updated_at=now,
                )
                .returning(Job.id)
                .execution_options(synchronize_session=False)
            )
            .scalars()
            .all()
        )
        runs = (
            session.execute(
                update(ProcessingRun)
                .where(ProcessingRun.state == ProcessingRunState.RUNNING)
                .values(
                    state=ProcessingRunState.INTERRUPTED,
                    revision=ProcessingRun.revision + 1,
                    updated_at=now,
                )
                .returning(ProcessingRun.id)
                .execution_options(synchronize_session=False)
            )
            .scalars()
            .all()
        )
        segments = (
            session.execute(
                update(ExecutionSegment)
                .where(ExecutionSegment.state == ExecutionSegmentState.RUNNING)
                .values(state=ExecutionSegmentState.INTERRUPTED, ended_at=now)
                .returning(ExecutionSegment.id)
                .execution_options(synchronize_session=False)
            )
            .scalars()
            .all()
        )
        jobs_paused = _move_jobs(session, JobState.PAUSING, JobState.PAUSED, now)
        jobs_cancelled = _move_jobs(session, JobState.CANCELLING, JobState.CANCELLED, now)
        runs_paused = _move_runs(
            session, ProcessingRunState.PAUSING, ProcessingRunState.PAUSED, now
        )
        runs_cancelled = _move_runs(
            session, ProcessingRunState.CANCELLING, ProcessingRunState.CANCELLED, now
        )
        leased = (
            session.execute(
                update(Job)
                .where(or_(Job.lease_owner.is_not(None), Job.lease_expires_at.is_not(None)))
                .values(lease_owner=None, lease_expires_at=None, updated_at=now)
                .returning(Job.id)
                .execution_options(synchronize_session=False)
            )
            .scalars()
            .all()
        )
        session.commit()
    return InterruptedWork(
        sorted(jobs), sorted(runs), sorted(segments), sorted(leased),
        sorted(jobs_paused), sorted(jobs_cancelled), sorted(runs_paused), sorted(runs_cancelled),
    )  # fmt: skip


def _move_jobs(
    session: Session, from_state: JobState, to_state: JobState, now: datetime
) -> list[uuid.UUID]:
    """Move every job in `from_state` to `to_state`, clear its lease, and end it if `to_state` is
    a finished state. `heartbeat_at` is kept: the worker died, so unlike `JobRepository.transition`
    (a cooperating worker leaving a leased state) this leaves its last sign of life as evidence, as
    for a `RUNNING` job.
    """
    values: dict[str, Any] = {
        "state": to_state, "lease_owner": None, "lease_expires_at": None, "updated_at": now,
    }  # fmt: skip
    if to_state in FINISHED_JOB_STATES:
        values["ended_at"] = now
    return list(
        session.execute(
            update(Job)
            .where(Job.state == from_state)
            .values(**values)
            .returning(Job.id)
            .execution_options(synchronize_session=False)
        ).scalars()
    )


def _move_runs(
    session: Session, from_state: ProcessingRunState, to_state: ProcessingRunState, now: datetime
) -> list[uuid.UUID]:
    return list(
        session.execute(
            update(ProcessingRun)
            .where(ProcessingRun.state == from_state)
            .values(state=to_state, revision=ProcessingRun.revision + 1, updated_at=now)
            .returning(ProcessingRun.id)
            .execution_options(synchronize_session=False)
        ).scalars()
    )


def jobs_that_may_resume(session_factory: sessionmaker[Session]) -> set[uuid.UUID]:
    """The jobs whose temp workspace must be kept: every job that is not over, and every job whose
    linked processing run is not over either. A finished job with a live run is contradictory
    state; it is recoverable inconsistency, not permission to delete scratch data a run may need
    ("after verifying no live run needs it", persistence §28)."""
    with session_factory() as session:
        rows = session.execute(
            select(Job.id, Job.state, ProcessingRun.state).outerjoin(
                ProcessingRun, ProcessingRun.id == Job.processing_run_id
            )
        ).all()
    return {
        job_id
        for job_id, job_state, run_state in rows
        if job_state not in FINISHED_JOB_STATES or run_state in TRANSIENT_RUN_STATES
    }


def recover_on_startup(
    session_factory: sessionmaker[Session],
    store: ManagedFileStore,
    workspaces: WorkspaceManager,
    coordinator: IndexCoordinator,
    eraser: RepresentationEraser,
    *,
    clock: Callable[[], datetime],
    index_batch: int,
    max_index_passes: int,
) -> StartupReport:
    """Run the recovery and index steps once, in order. Both limits are required, with no default:
    they bound how much index catch-up startup does before it gives way to readiness, and choosing
    them would be an unmeasured threshold. Operations not reached stay `PENDING` for the
    scheduler."""
    require_library_root(store)  # before any step reads an absent file as a lost one
    artifacts = recover_artifacts(session_factory, store, clock=clock)
    missing = mark_missing_referenced_originals(session_factory, clock=clock)
    missing_managed = mark_missing_managed_files(session_factory, store)
    interrupted = interrupt_in_flight_work(session_factory, clock=clock)
    cleanup = workspaces.remove_orphans(jobs_that_may_resume(session_factory))
    merged = CoordinatorReport()
    rebuilt = coordinator.validate_indexes(merged)
    requeued = coordinator.requeue_failed_operations()
    erasure = eraser.resume()  # finish every erasure a crash interrupted, and an owed truncation

    passes = 0
    for _ in range(max_index_passes):
        result = coordinator.apply_pending(limit=index_batch)
        passes += 1
        merged.applied += result.applied
        merged.retrying += result.retrying
        merged.failed += result.failed
        merged.rebuilt_spaces += result.rebuilt_spaces
        merged.unindexable += result.unindexable
        merged.purged_spaces += result.purged_spaces
        if not (result.applied or result.retrying or result.failed):
            break  # nothing was due: the queue is caught up (or every remaining one is backing off)
    return StartupReport(
        artifacts,
        missing,
        missing_managed,
        interrupted,
        cleanup,
        rebuilt,
        requeued,
        merged,
        passes,
        erasure,
    )
