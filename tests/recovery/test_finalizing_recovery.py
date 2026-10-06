"""Startup recovery of source-processing runs (M3 step 12, issue #34; persistence §16, §28).

The state matrix: a run found FINALIZING is accepted from its valid FINAL checkpoint without any ML;
a run that died before FINAL is only INTERRUPTED and its PENDING output stays private; a retry is a
new Job and Run linked to the old ones. Recovery never runs perception and never makes private
output visible except through acceptance.
"""

from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from backend.app.identities.models import Evidence
from backend.app.jobs.models import Job
from backend.app.memory.erasure import RepresentationEraser
from backend.app.memory.index_coordinator import IndexCoordinator, RetryPolicy
from backend.app.memory.models import (
    IndexOperation,
    Observation,
    Occurrence,
    Representation,
)
from backend.app.processing import execute_job
from backend.app.processing.accept_run import AcceptProcessingRunUseCase
from backend.app.processing.models import ExecutionSegment, ProcessingCheckpoint, ProcessingRun
from backend.app.processing.process_source import ProcessSourceError
from backend.app.processing.retry import RetryProcessingUseCase
from backend.app.processing.scheduler import ProcessingScheduler
from backend.app.recovery.startup import (
    StartupReport,
    interrupt_in_flight_work,
    recover_on_startup,
)
from backend.app.runtime import perception_client
from backend.app.runtime.package_store import RuntimePackageStore
from backend.infrastructure.db.engine import create_session_factory
from backend.infrastructure.db.unit_of_work import TransactionRetry, UnitOfWork
from backend.infrastructure.storage.files import ManagedFileStore
from backend.infrastructure.storage.layout import StorageRoots
from backend.infrastructure.storage.workspaces import WorkspaceManager
from tests.factories.models import ModelFactory
from tests.fixtures.deterministic import FrozenClock, SeededUUIDs
from tests.fixtures.final_checkpoint import finalizing
from tests.fixtures.persistence import AppDirs, uow_for


class Harness:
    def __init__(
        self,
        engine: Engine,
        build: ModelFactory,
        app_dirs: AppDirs,
        file_store: ManagedFileStore,
        storage_roots: StorageRoots,
    ) -> None:
        self.engine = engine
        self.build = build
        self.factory: sessionmaker[Session] = create_session_factory(engine)
        self.file_store = file_store
        self.storage_roots = storage_roots
        self.workspaces = WorkspaceManager(storage_roots)
        self.uow = UnitOfWork(engine, retry=TransactionRetry(1, lambda _: 0), sleep=lambda _: None)
        self.coordinator = IndexCoordinator(
            self.factory,
            self.uow,
            app_dirs.indexes,
            clock=build.clock,
            new_id=build.new_id,
            retry=RetryPolicy(max_attempts=3, backoff=lambda n: timedelta(minutes=n)),
        )
        self.wake: Callable[[], None] | None = None

    def recover(self) -> StartupReport:
        self.build.session.commit()
        eraser = RepresentationEraser(
            self.factory,
            self.engine,
            self.coordinator,
            unit_of_work=self.uow,
            clock=self.build.clock,
            new_id=self.build.new_id,
            checkpoint_timeout_ms=0,
        )
        return recover_on_startup(
            self.factory,
            self.file_store,
            self.workspaces,
            self.coordinator,
            eraser,
            RuntimePackageStore(self.storage_roots, new_id=self.build.new_id),
            AcceptProcessingRunUseCase(
                self.uow, new_id=self.build.new_id, clock=self.build.clock, wake_index=self.wake
            ),
            unit_of_work=self.uow,
            clock=self.build.clock,
            index_batch=50,
            max_index_passes=5,
        )

    def row[T](self, model: type[T], row_id: Any) -> T:
        with self.factory() as session:
            row = session.get(model, row_id)
            assert row is not None
            return row

    def count(self, model: Any) -> int:
        with self.factory() as session:
            return session.scalar(select(func.count()).select_from(model)) or 0


@pytest.fixture
def harness(
    sqlite_engine: Engine,
    build: ModelFactory,
    app_dirs: AppDirs,
    file_store: ManagedFileStore,
    storage_roots: StorageRoots,
    monkeypatch: pytest.MonkeyPatch,
) -> Harness:
    def no_ml(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("startup recovery must never run perception")

    # Recovery has no perception client; these make a future regression loud rather than silent.
    monkeypatch.setattr(execute_job.ExecuteProcessingJob, "execute", no_ml)
    monkeypatch.setattr(perception_client.PerceptionClient, "detect", no_ml)
    monkeypatch.setattr(perception_client.PerceptionClient, "represent", no_ml)
    return Harness(sqlite_engine, build, app_dirs, file_store, storage_roots)


def pre_final_run(build: ModelFactory) -> tuple[ProcessingRun, Job, Observation, Representation]:
    """A run that died after settling private output but before FINAL (job and run RUNNING)."""
    run = build.run(state="RUNNING")
    build.checkpoint(run, 0, "INTERMEDIATE", "VALID")
    job = build.job(
        processing_run_id=run.id,
        type="PROCESS_SOURCE",
        state="RUNNING",
        lease_owner="dead-worker",
        lease_expires_at=build.clock() + timedelta(minutes=5),
    )
    observation = build.observation(run)
    representation = build.representation(observation)
    return run, job, observation, representation


# --- FINALIZING: accepted from FINAL, without ML -----------------------------------------------


@pytest.mark.parametrize("outcome", ["CREATE_NEW", "MATCH_EXISTING", "ABSTAIN", "NO_FACE"])
def test_a_finalizing_run_is_accepted_without_running_ml(
    harness: Harness, clock: FrozenClock, new_id: SeededUUIDs, outcome: str
) -> None:
    run, observation, representation, _identity, job = finalizing(
        harness.build.session, clock, new_id, outcome
    )

    report = harness.recover()

    assert report.finalizing.accepted == [run.id]
    assert report.finalizing.not_resumable == report.finalizing.wake_failures == []
    assert harness.row(ProcessingRun, run.id).state == "COMPLETED"
    assert harness.row(Job, job.id).state == "COMPLETED"
    if observation is not None and representation is not None:
        assert harness.row(Observation, observation.id).state == "ACTIVE"
        accepted = harness.row(Representation, representation.id)
        assert accepted.state == "ACTIVE"
        assert (accepted.identity_id is None) == (outcome == "ABSTAIN")
        # recovery's own index pass applied the ADD that acceptance queued
        with harness.factory() as session:
            states = list(session.scalars(select(IndexOperation.state)))
        assert states == ["APPLIED"]
    assert (harness.count(Occurrence) == 0) == (outcome in ("ABSTAIN", "NO_FACE"))
    assert not report.clean  # it repaired something


def test_a_stale_lease_is_cleared_while_the_job_stays_running_for_acceptance(
    harness: Harness, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    run, _o, _r, _i, job = finalizing(harness.build.session, clock, new_id, "ABSTAIN")
    job.lease_owner = "dead-worker"
    job.lease_expires_at = clock() + timedelta(minutes=5)
    harness.build.session.commit()

    harness.recover()

    completed = harness.row(Job, job.id)
    assert completed.state == "COMPLETED"
    assert completed.lease_owner is None
    assert completed.lease_expires_at is None


def test_interruption_alone_leaves_a_finalizing_runs_job_running(
    harness: Harness, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    """Acceptance requires a RUNNING job, so the interruption step must not take it first. A
    RUNNING job with no run at all is still interrupted."""
    run, _o, _r, _i, finalizing_job = finalizing(harness.build.session, clock, new_id, "NO_FACE")
    _run, dead_job, _obs, _rep = pre_final_run(harness.build)
    unlinked = harness.build.job(type="PROCESS_SOURCE", state="RUNNING")
    harness.build.session.commit()

    interrupted = interrupt_in_flight_work(uow_for(harness.factory), clock=clock)

    assert harness.row(Job, finalizing_job.id).state == "RUNNING"
    assert harness.row(ProcessingRun, run.id).state == "FINALIZING"
    assert sorted(interrupted.jobs) == sorted([dead_job.id, unlinked.id])


# --- invalid FINAL ---------------------------------------------------------------------------


def corrupt_final(session: Session, run: ProcessingRun) -> None:
    checkpoint = session.get(ProcessingCheckpoint, run.current_checkpoint_id)
    assert checkpoint is not None
    checkpoint.payload_json = {**checkpoint.payload_json, "decisions": []}
    session.commit()


def drop_final(session: Session, run: ProcessingRun) -> None:
    run.current_checkpoint_id = None
    session.commit()


@pytest.mark.parametrize("damage", [corrupt_final, drop_final])
def test_a_refused_final_is_not_resumable_and_its_output_stays_private(
    harness: Harness,
    clock: FrozenClock,
    new_id: SeededUUIDs,
    damage: Callable[[Session, ProcessingRun], None],
) -> None:
    run, observation, representation, _identity, job = finalizing(
        harness.build.session, clock, new_id, "CREATE_NEW"
    )
    assert observation is not None
    assert representation is not None
    damage(harness.build.session, run)

    report = harness.recover()

    assert report.finalizing.not_resumable == [run.id]
    assert report.finalizing.accepted == []
    refused = harness.row(ProcessingRun, run.id)
    assert refused.state == "NOT_RESUMABLE"
    assert refused.failure_code == "FINAL_NOT_ACCEPTABLE"
    refused_job = harness.row(Job, job.id)
    assert refused_job.state == "INTERRUPTED"
    assert refused_job.lease_owner is None
    assert refused_job.lease_expires_at is None
    assert harness.row(Observation, observation.id).state == "PENDING"
    assert harness.row(Representation, representation.id).state == "PENDING"
    assert harness.count(Evidence) == harness.count(Occurrence) == 0
    assert harness.count(IndexOperation) == 0


# --- pre-FINAL crash ------------------------------------------------------------------------


def test_a_pre_final_crash_is_interrupted_and_nothing_is_requeued_or_exposed(
    harness: Harness,
) -> None:
    run, job, observation, representation = pre_final_run(harness.build)
    segment = harness.build.session.scalar(
        select(ExecutionSegment).where(ExecutionSegment.processing_run_id == run.id)
    )
    assert segment is not None
    harness.build.session.commit()
    jobs, runs = harness.count(Job), harness.count(ProcessingRun)

    report = harness.recover()

    assert report.finalizing.accepted == report.finalizing.not_resumable == []
    interrupted_run = harness.row(ProcessingRun, run.id)
    assert interrupted_run.state == "INTERRUPTED"
    interrupted_job = harness.row(Job, job.id)
    assert interrupted_job.state == "INTERRUPTED"
    assert interrupted_job.lease_owner is None
    assert interrupted_job.lease_expires_at is None
    assert harness.row(ExecutionSegment, segment.id).state == "INTERRUPTED"
    # private output is kept, still private
    assert harness.row(Observation, observation.id).state == "PENDING"
    assert harness.row(Representation, representation.id).state == "PENDING"
    assert (
        harness.count(Evidence) == harness.count(Occurrence) == harness.count(IndexOperation) == 0
    )
    # never requeued: no new job or run, and the old job did not return to QUEUED
    assert (harness.count(Job), harness.count(ProcessingRun)) == (jobs, runs)


def test_recovery_handles_every_kind_of_run_in_one_start(
    harness: Harness, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    finalizing_run, _o, accepted_rep, _i, finalizing_job = finalizing(
        harness.build.session, clock, new_id, "ABSTAIN"
    )
    dead_run, dead_job, dead_observation, dead_rep = pre_final_run(harness.build)
    refused_run, _o2, refused_rep, _i2, refused_job = finalizing(
        harness.build.session, clock, new_id, "CREATE_NEW"
    )
    drop_final(harness.build.session, refused_run)

    harness.recover()

    assert harness.row(ProcessingRun, refused_run.id).state == "NOT_RESUMABLE"
    assert harness.row(Job, refused_job.id).state == "INTERRUPTED"
    assert refused_rep is not None
    assert harness.row(Representation, refused_rep.id).state == "PENDING"

    assert harness.row(ProcessingRun, finalizing_run.id).state == "COMPLETED"
    assert harness.row(Job, finalizing_job.id).state == "COMPLETED"
    assert accepted_rep is not None
    assert harness.row(Representation, accepted_rep.id).state == "ACTIVE"
    assert harness.row(ProcessingRun, dead_run.id).state == "INTERRUPTED"
    assert harness.row(Job, dead_job.id).state == "INTERRUPTED"
    # the dead run's output is not swept up by the other run's acceptance
    assert harness.row(Observation, dead_observation.id).state == "PENDING"
    assert harness.row(Representation, dead_rep.id).state == "PENDING"


# --- wake failure after commit ----------------------------------------------------------------


def test_a_wake_failure_after_commit_does_not_undo_or_fail_the_run(
    harness: Harness, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    run, _o, representation, _i, job = finalizing(harness.build.session, clock, new_id, "ABSTAIN")
    assert representation is not None

    def broken_wake() -> None:
        raise RuntimeError("index wake failed")

    harness.wake = broken_wake

    report = harness.recover()

    assert report.finalizing.accepted == report.finalizing.wake_failures == [run.id]
    assert harness.row(ProcessingRun, run.id).state == "COMPLETED"
    assert harness.row(Job, job.id).state == "COMPLETED"
    assert harness.row(Representation, representation.id).state == "ACTIVE"
    with harness.factory() as session:
        operations = list(session.scalars(select(IndexOperation)))
    assert [(op.state, op.representation_id) for op in operations] == [
        ("APPLIED", representation.id)
    ]


def test_a_failure_before_acceptance_commits_propagates_and_leaves_the_run_finalizing(
    harness: Harness, clock: FrozenClock, new_id: SeededUUIDs, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, _o, representation, _i, job = finalizing(harness.build.session, clock, new_id, "ABSTAIN")
    assert representation is not None

    def broken(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("database went away")

    monkeypatch.setattr(AcceptProcessingRunUseCase, "_accept", broken)

    with pytest.raises(RuntimeError, match="database went away"):
        harness.recover()

    assert harness.row(ProcessingRun, run.id).state == "FINALIZING"
    assert harness.row(Job, job.id).state == "RUNNING"  # not interrupted: the next start retries
    assert harness.row(Representation, representation.id).state == "PENDING"


# --- idempotency -----------------------------------------------------------------------------


def test_repeated_recovery_changes_nothing_further(
    harness: Harness, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    finalizing(harness.build.session, clock, new_id, "CREATE_NEW")
    pre_final_run(harness.build)
    refused_run, *_ = finalizing(harness.build.session, clock, new_id, "ABSTAIN")
    drop_final(harness.build.session, refused_run)

    first = harness.recover()
    counts = {model: harness.count(model) for model in (Evidence, Occurrence, IndexOperation, Job)}
    second = harness.recover()

    assert not first.repaired_nothing
    assert second.repaired_nothing
    assert second.finalizing.accepted == second.finalizing.not_resumable == []
    assert counts == {
        model: harness.count(model) for model in (Evidence, Occurrence, IndexOperation, Job)
    }


def test_a_crash_after_acceptance_committed_is_a_no_op_on_the_next_start(
    harness: Harness, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    """Accept, then 'crash' before recovery's index pass (a second start finds it all done)."""
    run, observation, representation, _i, job = finalizing(
        harness.build.session, clock, new_id, "MATCH_EXISTING"
    )
    assert observation is not None
    assert representation is not None
    harness.build.session.commit()
    AcceptProcessingRunUseCase(harness.uow, new_id=new_id, clock=clock).accept(run.id)

    report = harness.recover()

    assert report.finalizing.accepted == []
    assert harness.row(ProcessingRun, run.id).state == "COMPLETED"
    assert harness.row(Job, job.id).state == "COMPLETED"
    assert harness.row(Observation, observation.id).state == "ACTIVE"
    assert harness.row(Representation, representation.id).state == "ACTIVE"
    assert harness.count(Occurrence) == 1


# --- the writes are a unit of work: safe to run again whole -----------------------------------


def test_recovery_writes_are_safe_to_run_again_whole(
    harness: Harness, clock: FrozenClock, new_id: SeededUUIDs, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A SQLITE_BUSY retry reruns the whole write. Each recovery write (interrupting work, marking a
    refused FINAL) must therefore leave the same state and report no row twice."""
    refused_run, _o, _r, _i, refused_job = finalizing(
        harness.build.session, clock, new_id, "ABSTAIN"
    )
    drop_final(harness.build.session, refused_run)
    dead_run, dead_job, _obs, _rep = pre_final_run(harness.build)
    harness.build.session.commit()
    real_write = harness.uow.write
    attempts = 0

    def retry_once(work: Callable[[Session], Any]) -> Any:
        nonlocal attempts
        attempts += 1
        with harness.factory() as rolled_back:
            work(rolled_back)
            rolled_back.rollback()
        return real_write(work)

    monkeypatch.setattr(harness.uow, "write", retry_once)

    report = harness.recover()

    assert attempts >= 2  # at least the NOT_RESUMABLE write and the interruption, each run twice
    assert report.finalizing.not_resumable == [refused_run.id]
    assert report.interrupted.jobs == sorted([refused_job.id, dead_job.id])
    assert report.interrupted.runs == [dead_run.id]
    assert harness.row(ProcessingRun, refused_run.id).state == "NOT_RESUMABLE"
    assert harness.row(ProcessingRun, dead_run.id).state == "INTERRUPTED"


def test_the_interruption_write_goes_through_the_unit_of_work_and_reruns_cleanly(
    harness: Harness, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, job, _obs, _rep = pre_final_run(harness.build)
    harness.build.session.commit()
    real_write = harness.uow.write
    attempts = 0

    def retry_once(work: Callable[[Session], Any]) -> Any:
        nonlocal attempts
        attempts += 1
        with harness.factory() as rolled_back:
            work(rolled_back)
            rolled_back.rollback()
        return real_write(work)

    monkeypatch.setattr(harness.uow, "write", retry_once)

    interrupted = interrupt_in_flight_work(harness.uow, clock=clock)

    assert attempts == 1  # one write unit of work for the whole interruption
    assert interrupted.jobs == [job.id]
    assert interrupted.runs == [run.id]
    assert harness.row(Job, job.id).state == "INTERRUPTED"


# --- retry lineage ---------------------------------------------------------------------------


def snapshot_json(session: Session, run: ProcessingRun) -> Any:
    from backend.app.processing.models import ProcessingConfigurationSnapshot

    snapshot = session.get(ProcessingConfigurationSnapshot, run.configuration_snapshot_id)
    assert snapshot is not None
    return snapshot.canonical_json


def test_a_retry_after_recovery_is_a_new_linked_job_and_run(
    harness: Harness, new_id: SeededUUIDs, clock: FrozenClock
) -> None:
    run, job, observation, _representation = pre_final_run(harness.build)
    harness.recover()
    wakes: list[None] = []
    retry = RetryProcessingUseCase(
        harness.uow, new_id=new_id, clock=clock, wake_scheduler=lambda: wakes.append(None)
    )

    scheduled = retry.retry(job.id)

    assert wakes == [None]
    new_job = harness.row(Job, scheduled.job_id)
    new_run = harness.row(ProcessingRun, scheduled.processing_run_id)
    assert (new_job.previous_job_id, new_job.attempt_number, new_job.state) == (
        job.id,
        2,
        "QUEUED",
    )
    assert new_job.processing_run_id == new_run.id
    assert (new_run.parent_run_id, new_run.state, new_run.source_id) == (
        run.id,
        "PENDING",
        run.source_id,
    )
    # a copy of the same frozen intent, in its own immutable snapshot
    assert new_run.configuration_snapshot_id != run.configuration_snapshot_id
    with harness.factory() as session:
        assert snapshot_json(session, new_run) == snapshot_json(session, run)
    # the old attempt is left exactly as it ended, its output still private
    assert harness.row(Job, job.id).state == "INTERRUPTED"
    assert harness.row(ProcessingRun, run.id).state == "INTERRUPTED"
    assert harness.row(Observation, observation.id).state == "PENDING"
    # the scheduler can claim the retry and start the new run
    started = ProcessingScheduler(
        harness.uow, new_id=new_id, clock=clock, lease_for=timedelta(minutes=1)
    ).claim_source_job("worker")
    assert started is not None
    assert started.job.id == scheduled.job_id
    assert harness.row(ProcessingRun, new_run.id).state == "RUNNING"


def test_a_not_resumable_run_can_be_retried_once(
    harness: Harness, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    run, _o, _r, _i, job = finalizing(harness.build.session, clock, new_id, "ABSTAIN")
    drop_final(harness.build.session, run)
    harness.recover()
    retry = RetryProcessingUseCase(
        harness.uow, new_id=new_id, clock=clock, wake_scheduler=lambda: None
    )

    scheduled = retry.retry(job.id)

    assert harness.row(Job, scheduled.job_id).previous_job_id == job.id
    assert harness.row(ProcessingRun, run.id).state == "NOT_RESUMABLE"
    with pytest.raises(ProcessSourceError, match="already been retried"):
        retry.retry(job.id)


def test_a_finished_or_unrelated_job_cannot_be_retried(
    harness: Harness, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    run, _o, _r, _i, job = finalizing(harness.build.session, clock, new_id, "NO_FACE")
    other = harness.build.job(type="REBUILD_INDEX", state="INTERRUPTED")
    harness.recover()  # the run is accepted: its job is COMPLETED
    retry = RetryProcessingUseCase(
        harness.uow, new_id=new_id, clock=clock, wake_scheduler=lambda: None
    )

    with pytest.raises(ProcessSourceError, match="cannot be retried"):
        retry.retry(job.id)
    with pytest.raises(ProcessSourceError, match="not a source-processing job"):
        retry.retry(other.id)
    with pytest.raises(ProcessSourceError, match="not a source-processing job"):
        retry.retry(new_id())
    assert harness.row(ProcessingRun, run.id).state == "COMPLETED"


def test_a_job_whose_run_is_not_retryable_is_refused(
    harness: Harness, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    run, job, _o, _r = pre_final_run(harness.build)
    harness.recover()
    with harness.factory() as session:  # contradictory state: an interrupted job of a live run
        session.execute(
            update(ProcessingRun).where(ProcessingRun.id == run.id).values(state="RUNNING")
        )
        session.commit()
    retry = RetryProcessingUseCase(
        harness.uow, new_id=new_id, clock=clock, wake_scheduler=lambda: None
    )

    with pytest.raises(ProcessSourceError, match="cannot be retried"):
        retry.retry(job.id)


def test_a_lost_scheduler_wake_does_not_lose_the_retry(
    harness: Harness, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    _run, job, _o, _r = pre_final_run(harness.build)
    harness.recover()

    def unavailable() -> None:
        raise RuntimeError("scheduler unavailable")

    scheduled = RetryProcessingUseCase(
        harness.uow, new_id=new_id, clock=clock, wake_scheduler=unavailable
    ).retry(job.id)

    assert harness.row(Job, scheduled.job_id).state == "QUEUED"
