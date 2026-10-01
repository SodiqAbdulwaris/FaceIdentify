"""Startup recovery: reconcile what a crash left half done (PERSISTENCE_IMPLEMENTATION.md §28,
IMPLEMENTATION_ARCHITECTURE.md §22-§23).

Startup order is database and migrations, storage, **recovery**, **indexes**, then the runtime, the
ML worker and the scheduler. `recover_on_startup` is the recovery and index steps, in that order:

1. Artifacts: settle every interrupted managed write and deletion (`recover_artifacts`), and mark a
   referenced original whose file is gone `MISSING` (existence only: nothing is hashed at startup).
2. In-flight work: a `RUNNING` job, processing run or execution segment belongs to a process that
   no longer exists, so it becomes `INTERRUPTED` and the job's lease is cleared (§23.2: "Interrupted
   active runs/segments become `INTERRUPTED`"; resuming creates new work, it does not reopen this).
3. Workspaces: remove the temp workspace of every job that is over; keep those a job may resume.
4. Indexes: validate every active space's index and rebuild what is missing or unusable, and give
   every `FAILED` `IndexOperation` one fresh set of attempts (persistence §28: "pending/failed").
5. Pending `IndexOperation`s: catch the indexes up, in bounded passes.

Recovery is idempotent and safe to repeat after another crash (§28, §23.8): each step only records a
durable repair, and a second run finds nothing left to repair. It never turns a pending run's
partial output into library memory, and it never assumes anything in memory survived.

Not handled here, and left exactly as found: a run that was `PAUSING`, `CANCELLING` or `FINALIZING`
when the process died (what should finish or roll back needs the run lifecycle of M3: CONTEXT open
question 26), the acceptance of a run with a final checkpoint, and the recovery of an interrupted
runtime installation.

Precondition, like `recover_artifacts`: one process, no other user of the library, before workers
start. Single-instance is the desktop shell's job (tech-stack §2).
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session, sessionmaker

from backend.app.jobs.models import Job, JobState
from backend.app.memory.index_coordinator import CoordinatorReport, IndexCoordinator
from backend.app.processing.models import (
    TRANSIENT_RUN_STATES,
    ExecutionSegment,
    ExecutionSegmentState,
    ProcessingRun,
    ProcessingRunState,
)
from backend.app.sources.artifact_storage import RecoveryReport, recover_artifacts
from backend.app.sources.referenced_artifacts import mark_missing_referenced_originals
from backend.infrastructure.storage.files import ManagedFileStore
from backend.infrastructure.storage.workspaces import WorkspaceCleanup, WorkspaceManager

# A job in one of these states is over: nothing will resume it, so its workspace is scratch.
FINISHED_JOB_STATES = (JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED)


@dataclass
class InterruptedWork:
    jobs: list[uuid.UUID] = field(default_factory=list)
    runs: list[uuid.UUID] = field(default_factory=list)
    segments: list[uuid.UUID] = field(default_factory=list)
    # Jobs not `RUNNING` that still held a lease (and so are not in `jobs`): their state is
    # untouched, only the lease nobody can hold any more is cleared.
    leases_cleared: list[uuid.UUID] = field(default_factory=list)


@dataclass
class StartupReport:
    artifacts: RecoveryReport
    missing_references: list[uuid.UUID]
    interrupted: InterruptedWork
    workspaces: WorkspaceCleanup
    indexes_rebuilt: list[uuid.UUID]
    requeued_operations: list[uuid.UUID]
    index_operations: CoordinatorReport
    index_passes: int

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
            "index operations backing off": len(operations.retrying),
            "index operations out of attempts": len(operations.failed),
        }
        return [f"{count} {what}" for what, count in counts.items() if count]

    @property
    def repaired_nothing(self) -> bool:
        """True when this run made no repair (the state a second run should reach). It says
        nothing about whether anything is still unresolved: see `unresolved` and `clean`."""
        artifacts = self.artifacts
        operations = self.index_operations
        return not (
            artifacts.finalized
            or artifacts.write_not_completed
            or artifacts.deleted
            or artifacts.delete_failed
            or artifacts.staging_removed
            or self.missing_references
            or self.interrupted.jobs
            or self.interrupted.runs
            or self.interrupted.segments
            or self.interrupted.leases_cleared
            or self.workspaces.removed
            or self.indexes_rebuilt
            or self.requeued_operations
            or operations.applied
            or operations.retrying
            or operations.failed
            or operations.rebuilt_spaces
            or operations.purged_spaces
        )

    @property
    def clean(self) -> bool:
        """No repair was needed and nothing is left unresolved."""
        return self.repaired_nothing and not self.unresolved


def interrupt_in_flight_work(
    session_factory: sessionmaker[Session], *, clock: Callable[[], datetime]
) -> InterruptedWork:
    """Mark every `RUNNING` job, run and segment `INTERRUPTED`, in one transaction.

    Each is a guarded `UPDATE ... RETURNING`, so a repeated run matches nothing and the first
    statement of the transaction is a write. A job's lease is cleared, since nobody holds it now:
    for a `RUNNING` job as it is interrupted, and for any *other* job still holding one (an expired
    or stale lease, persistence §28) with its state left alone.
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
    return InterruptedWork(sorted(jobs), sorted(runs), sorted(segments), sorted(leased))


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
    *,
    clock: Callable[[], datetime],
    index_batch: int,
    max_index_passes: int,
) -> StartupReport:
    """Run the recovery and index steps once, in order. Both limits are required, with no default:
    they bound how much index catch-up startup does before it gives way to readiness, and choosing
    them would be an unmeasured threshold. Operations not reached stay `PENDING` for the
    scheduler."""
    artifacts = recover_artifacts(session_factory, store, clock=clock)
    missing = mark_missing_referenced_originals(session_factory, clock=clock)
    interrupted = interrupt_in_flight_work(session_factory, clock=clock)
    cleanup = workspaces.remove_orphans(jobs_that_may_resume(session_factory))
    rebuilt = coordinator.validate_indexes()
    requeued = coordinator.requeue_failed_operations()

    merged = CoordinatorReport()
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
        artifacts, missing, interrupted, cleanup, rebuilt, requeued, merged, passes
    )
