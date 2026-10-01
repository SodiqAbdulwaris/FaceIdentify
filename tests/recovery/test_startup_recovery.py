"""Startup recovery against explicitly constructed interrupted states (M2: TST-030; persistence §28,
architecture §22, §23 and §25.13).

Recovery must reconcile what a crash left half done, repair only what it owns, and be idempotent:
safe to run again, including after *another* crash part-way through.
"""

import io
import shutil
import sqlite3
import uuid
from collections.abc import Callable
from contextlib import closing
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, event, select, update
from sqlalchemy.orm import Session, sessionmaker

from backend.app.jobs.models import Job
from backend.app.memory.index_coordinator import (
    CoordinatorReport,
    IndexCoordinator,
    RetryPolicy,
)
from backend.app.memory.models import (
    IndexOperation,
    Observation,
    Representation,
    RepresentationSpace,
)
from backend.app.processing.models import ExecutionSegment, ProcessingRun
from backend.app.recovery import startup
from backend.app.recovery.startup import (
    InterruptedWork,
    StartupReport,
    interrupt_in_flight_work,
    jobs_that_may_resume,
    recover_on_startup,
)
from backend.app.sources import artifact_storage, referenced_artifacts
from backend.app.sources.artifact_storage import RecoveryReport, reserve_managed_artifact
from backend.app.sources.models import Artifact, Source
from backend.app.sources.referenced_artifacts import (
    REFERENCED_FILE_MISSING,
    mark_missing_referenced_originals,
)
from backend.infrastructure.db.engine import create_session_factory
from backend.infrastructure.indexing.representation_index import RepresentationIndex
from backend.infrastructure.storage.files import ManagedFileStore
from backend.infrastructure.storage.layout import StorageRoots
from backend.infrastructure.storage.workspaces import WorkspaceCleanup, WorkspaceManager
from tests.factories.models import ModelFactory, float32_vector
from tests.fixtures.persistence import AppDirs

NDIM = 4
DATA = b"a managed original whose final rename completed"


class SimulatedCrash(BaseException):
    """The process dying: no `except Exception` handler gets to tidy up after it."""


@pytest.fixture
def factory(sqlite_engine: Engine) -> sessionmaker[Session]:
    return create_session_factory(sqlite_engine)


@pytest.fixture
def workspaces(storage_roots: StorageRoots) -> WorkspaceManager:
    return WorkspaceManager(storage_roots)


@pytest.fixture
def coordinator(
    factory: sessionmaker[Session], app_dirs: AppDirs, build: ModelFactory
) -> IndexCoordinator:
    return IndexCoordinator(
        factory, app_dirs.indexes, clock=build.clock, new_id=build.new_id,
        retry=RetryPolicy(max_attempts=3, backoff=lambda n: timedelta(minutes=n)),
    )  # fmt: skip


def recover(
    factory: sessionmaker[Session], file_store: ManagedFileStore, workspaces: WorkspaceManager,
    coordinator: IndexCoordinator, build: ModelFactory, *, index_batch: int = 50,
    max_index_passes: int = 5,
) -> StartupReport:  # fmt: skip
    build.session.commit()
    return recover_on_startup(
        factory, file_store, workspaces, coordinator, clock=build.clock,
        index_batch=index_batch, max_index_passes=max_index_passes,
    )  # fmt: skip


def active(build: ModelFactory, space: RepresentationSpace, key: int) -> Representation:
    return build.representation(
        representation_space_id=space.id, state="ACTIVE", identity_id=build.identity().id,
        ann_key=key, vector=float32_vector([float(key), 1.0, 0.0, 0.0]),
    )  # fmt: skip


def open_index(coordinator: IndexCoordinator, space: RepresentationSpace) -> RepresentationIndex:
    return RepresentationIndex.open(
        coordinator.index_directory(space.id), representation_space_id=space.id, ndim=NDIM,
        metric="cos",
    )  # fmt: skip


def reload[T](factory: sessionmaker[Session], model: type[T], row_id: uuid.UUID) -> T:
    with factory() as session:
        row = session.get(model, row_id)
        assert row is not None
        return row


def ids_in_state(factory: sessionmaker[Session], model: Any, state: str) -> list[uuid.UUID]:
    with factory() as session:
        return sorted(session.scalars(select(model.id).where(model.state == state)))


def database_state(engine: Engine) -> dict[str, list[tuple[Any, ...]]]:
    """Every row of every table, as committed."""
    path = engine.url.database
    assert path is not None
    with closing(sqlite3.connect(path)) as connection:
        tables = [
            name
            for (name,) in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        return {
            table: sorted(connection.execute(f'SELECT * FROM "{table}"').fetchall(), key=repr)
            for table in tables
        }


def tree(*roots: Path) -> list[tuple[str, int]]:
    """Every file under the roots, with its size: what a repeat run must leave exactly as it is."""
    return sorted(
        (str(path), path.stat().st_size)
        for root in roots
        for path in root.rglob("*")
        if path.is_file()
    )


class World:
    """One of each interrupted state from IMPLEMENTATION_ARCHITECTURE.md §25.13."""

    def __init__(
        self, *, build: ModelFactory, factory: sessionmaker[Session], file_store: ManagedFileStore,
        workspaces: WorkspaceManager, coordinator: IndexCoordinator, external: Path,
    ) -> None:  # fmt: skip
        self.build = build
        # A referenced original that was deleted by the user, and one that is still there.
        self.present_file = external / "present.jpg"
        self.present_file.write_bytes(b"still here")
        self.vanished_file = external / "vanished.jpg"
        self.vanished_file.write_bytes(b"about to go")
        self.present_reference = build.artifact(
            storage_mode="REFERENCED", storage_key=None, external_path=str(self.present_file),
            sha256=None, size_bytes=None,
        )  # fmt: skip
        self.vanished_reference = build.artifact(
            storage_mode="REFERENCED", storage_key=None, external_path=str(self.vanished_file),
            sha256=None, size_bytes=None,
        )  # fmt: skip
        self.vanished_source = build.source(original_artifact_id=self.vanished_reference.id)
        self.vanished_file.unlink()
        self.space = build.representation_space(dimension=NDIM)
        # RUNNING job whose worker is dead, with its lease, and a workspace it may resume in.
        self.running_job = build.job(
            state="RUNNING", lease_owner="worker-1", lease_expires_at=build.clock(),
            heartbeat_at=build.clock(),
        )  # fmt: skip
        self.paused_job = build.job(state="PAUSED")
        # Work that was being paused or cancelled when the process died, each still holding a lease.
        self.pausing_job = build.job(
            state="PAUSING", lease_owner="worker-1", lease_expires_at=build.clock(),
            heartbeat_at=build.clock(),
        )  # fmt: skip
        self.cancelling_job = build.job(
            state="CANCELLING", lease_owner="worker-1", lease_expires_at=build.clock(),
            heartbeat_at=build.clock(),
        )  # fmt: skip
        self.queued_job = build.job(state="QUEUED")
        self.done_job = build.job(state="COMPLETED")
        self.failed_job = build.job(state="FAILED")
        for job in (
            self.running_job, self.paused_job, self.pausing_job, self.cancelling_job,
            self.done_job, self.failed_job,
        ):  # fmt: skip
            workspaces.allocate(job.id)
        self.unknown_workspace = uuid.uuid4()
        workspaces.allocate(self.unknown_workspace)
        # RUNNING run with an active segment; runs in other states that recovery must not touch.
        self.running_run = build.run(state="RUNNING")
        self.running_segment = build.segment(self.running_run, 0, "RUNNING")
        self.finalizing_run = build.run(state="FINALIZING")
        self.pausing_run = build.run(state="PAUSING")
        self.cancelling_run = build.run(state="CANCELLING")
        self.cancelling_segment = build.segment(self.cancelling_run, 0, "RUNNING")
        # Output the cancelled run produced so far: private, and recovery must not activate it.
        self.partial_observation = build.observation(
            self.cancelling_run, execution_segment_id=self.cancelling_segment.id
        )
        self.partial_representation = build.representation(
            self.partial_observation, representation_space_id=self.space.id
        )
        self.done_run = build.run(state="COMPLETED")
        self.done_segment = build.segment(self.done_run, 0, "COMPLETED")
        # PENDING artifact whose final file was renamed into place but never committed AVAILABLE.
        build.session.commit()  # one writer at a time: the factory's rows first
        with factory() as session:
            reserved = reserve_managed_artifact(
                session, "SOURCE_ORIGINAL", new_id=build.new_id, clock=build.clock
            )
            session.commit()
            self.artifact_id, key = reserved.id, reserved.storage_key
        assert key is not None
        file_store.store(key, io.BytesIO(DATA))
        # A pending IndexOperation, and a second space whose index is corrupt.
        self.rep = active(build, self.space, 1)
        self.op = build.index_operation(self.rep, operation="ADD")
        self.other_space = build.representation_space(dimension=NDIM)
        self.other_rep = active(build, self.other_space, 2)
        build.session.commit()
        coordinator.validate_indexes()  # both spaces get an (empty) index...
        (coordinator.index_directory(self.other_space.id) / "manifest.json").write_text("{broken")


@pytest.fixture
def world(
    build: ModelFactory, factory: sessionmaker[Session], file_store: ManagedFileStore,
    workspaces: WorkspaceManager, coordinator: IndexCoordinator, tmp_path: Path,
) -> World:  # fmt: skip
    external = tmp_path / "user photos"
    external.mkdir()
    return World(
        build=build, factory=factory, file_store=file_store, workspaces=workspaces,
        coordinator=coordinator, external=external,
    )  # fmt: skip


# --- every interrupted state is reconciled ---------------------------------------------------


def test_every_interrupted_state_is_reconciled(
    world: World, factory: sessionmaker[Session], file_store: ManagedFileStore,
    workspaces: WorkspaceManager, coordinator: IndexCoordinator, build: ModelFactory,
) -> None:  # fmt: skip
    build.session.commit()
    running = {
        "jobs": ids_in_state(factory, Job, "RUNNING"),
        "runs": ids_in_state(factory, ProcessingRun, "RUNNING"),
        "segments": ids_in_state(factory, ExecutionSegment, "RUNNING"),
    }
    assert world.running_run.id in running["runs"]  # the representations' own runs are there too

    report = recover(factory, file_store, workspaces, coordinator, build)

    # A dead worker's RUNNING job is INTERRUPTED and no longer holds a lease.
    job = reload(factory, Job, world.running_job.id)
    assert (job.state, job.lease_owner, job.lease_expires_at) == ("INTERRUPTED", None, None)
    assert job.heartbeat_at is not None  # the last sign of life is kept as evidence
    assert report.interrupted.jobs == running["jobs"] == [world.running_job.id]
    # Its RUNNING run and segment are INTERRUPTED; the segment ends now, for no known reason.
    run = reload(factory, ProcessingRun, world.running_run.id)
    assert (run.state, run.revision) == ("INTERRUPTED", 2)
    segment = reload(factory, ExecutionSegment, world.running_segment.id)
    assert (segment.state, segment.ended_at, segment.ended_reason) == (
        "INTERRUPTED", build.clock(), None,
    )  # fmt: skip
    assert report.interrupted.runs == running["runs"]  # every RUNNING run, however it got there
    assert report.interrupted.segments == running["segments"]
    assert ids_in_state(factory, ProcessingRun, "RUNNING") == []
    assert ids_in_state(factory, ExecutionSegment, "RUNNING") == []
    # Work being paused or cancelled: PAUSED or CANCELLED, no lease; a cancelled job ends now.
    pausing = reload(factory, Job, world.pausing_job.id)
    assert (pausing.state, pausing.lease_owner, pausing.lease_expires_at) == ("PAUSED", None, None)
    assert pausing.ended_at is None  # paused work is not over
    cancelling = reload(factory, Job, world.cancelling_job.id)
    assert (cancelling.state, cancelling.lease_owner, cancelling.lease_expires_at) == (
        "CANCELLED", None, None,
    )  # fmt: skip
    assert cancelling.ended_at == build.clock()
    paused_run = reload(factory, ProcessingRun, world.pausing_run.id)
    assert (paused_run.state, paused_run.revision) == ("PAUSED", 2)
    cancelled_run = reload(factory, ProcessingRun, world.cancelling_run.id)
    assert (cancelled_run.state, cancelled_run.revision) == ("CANCELLED", 2)
    assert report.interrupted.jobs_paused == [world.pausing_job.id]
    assert report.interrupted.jobs_cancelled == [world.cancelling_job.id]
    assert report.interrupted.runs_paused == [world.pausing_run.id]
    assert report.interrupted.runs_cancelled == [world.cancelling_run.id]
    assert report.interrupted.leases_cleared == []  # they moved on, they were not bare lease clears
    # The cancelled run's segment was RUNNING, so it is closed; its output stays private.
    assert reload(factory, ExecutionSegment, world.cancelling_segment.id).state == "INTERRUPTED"
    assert reload(factory, Observation, world.partial_observation.id).state == "PENDING"
    assert reload(factory, Representation, world.partial_representation.id).state == "PENDING"
    # The PENDING artifact whose file reached its final key is finalized.
    artifact = reload(factory, Artifact, world.artifact_id)
    assert (artifact.state, artifact.size_bytes) == ("AVAILABLE", len(DATA))
    assert report.artifacts.finalized == [world.artifact_id]
    # A referenced original the user deleted is MISSING, its Source kept; one still there is not.
    vanished = reload(factory, Artifact, world.vanished_reference.id)
    assert (vanished.state, vanished.failure_code) == ("MISSING", REFERENCED_FILE_MISSING)
    assert reload(factory, Artifact, world.present_reference.id).state == "AVAILABLE"
    assert reload(factory, Source, world.vanished_source.id).state == "ACTIVE"
    assert report.missing_references == [world.vanished_reference.id]
    # Workspaces: kept for jobs that may resume, removed for finished ones and for unknown ids.
    # (a job that was being paused is PAUSED and may resume; one that was cancelled is over)
    assert workspaces.existing() == sorted(
        [world.running_job.id, world.paused_job.id, world.pausing_job.id]
    )
    assert sorted(report.workspaces.removed) == sorted(
        [world.done_job.id, world.failed_job.id, world.cancelling_job.id, world.unknown_workspace]
    )
    # A corrupt index is rebuilt from SQLite, and the pending operation is applied to the right one.
    assert report.indexes_rebuilt == [world.other_space.id]
    assert open_index(coordinator, world.other_space).contains(2)
    assert open_index(coordinator, world.space).contains(1)
    assert reload(factory, IndexOperation, world.op.id).state == "APPLIED"
    assert report.index_operations.applied == [world.op.id]
    assert not report.repaired_nothing


def test_other_states_are_left_exactly_as_they_were(
    world: World, factory: sessionmaker[Session], file_store: ManagedFileStore,
    workspaces: WorkspaceManager, coordinator: IndexCoordinator, build: ModelFactory,
) -> None:  # fmt: skip
    """Only RUNNING, PAUSING and CANCELLING work is moved: a finalization, a pause that finished,
    queued work and finished work are not ours."""
    before = {
        job.id: reload(factory, Job, job.id).state
        for job in (world.paused_job, world.queued_job, world.done_job, world.failed_job)
    }
    runs = {
        run.id: reload(factory, ProcessingRun, run.id)
        for run in (world.finalizing_run, world.done_run)
    }
    states = {run_id: (run.state, run.revision) for run_id, run in runs.items()}

    recover(factory, file_store, workspaces, coordinator, build)

    assert before == {job_id: reload(factory, Job, job_id).state for job_id in before}
    assert states == {
        run_id: (reload(factory, ProcessingRun, run_id).state,
                 reload(factory, ProcessingRun, run_id).revision)
        for run_id in states
    }  # fmt: skip
    done_segment = reload(factory, ExecutionSegment, world.done_segment.id)
    assert (done_segment.state, done_segment.ended_at) == ("COMPLETED", None)


# --- idempotence -----------------------------------------------------------------------------


def test_a_second_run_finds_nothing_and_changes_nothing(
    world: World, factory: sessionmaker[Session], file_store: ManagedFileStore,
    workspaces: WorkspaceManager, coordinator: IndexCoordinator, build: ModelFactory,
    sqlite_engine: Engine, storage_roots: StorageRoots,
) -> None:  # fmt: skip
    recover(factory, file_store, workspaces, coordinator, build)
    build.clock.advance(hours=1)
    rows = database_state(sqlite_engine)
    files = tree(storage_roots.library_root, storage_roots.local_state_root)

    again = recover(factory, file_store, workspaces, coordinator, build)

    assert again.repaired_nothing
    assert database_state(sqlite_engine) == rows
    assert tree(storage_roots.library_root, storage_roots.local_state_root) == files


CRASH_POINTS = [
    ("artifacts", startup, "recover_artifacts"),
    ("in-flight work", startup, "interrupt_in_flight_work"),
    ("workspaces", WorkspaceManager, "remove_orphans"),
    ("index validation", IndexCoordinator, "validate_indexes"),
    ("index catch-up", IndexCoordinator, "apply_pending"),
]


@pytest.mark.parametrize(
    ("owner", "name"),
    [(owner, name) for _, owner, name in CRASH_POINTS],
    ids=[label for label, _, _ in CRASH_POINTS],
)
def test_a_crash_after_any_step_is_repaired_by_running_recovery_again(
    world: World, factory: sessionmaker[Session], file_store: ManagedFileStore,
    workspaces: WorkspaceManager, coordinator: IndexCoordinator, build: ModelFactory,
    monkeypatch: pytest.MonkeyPatch, sqlite_engine: Engine, owner: Any, name: str,
) -> None:  # fmt: skip
    """The process dies right after one step finishes; the next start must still converge."""
    real = getattr(owner, name)

    def completes_then_dies(*args: Any, **kwargs: Any) -> None:
        real(*args, **kwargs)
        raise SimulatedCrash

    monkeypatch.setattr(owner, name, completes_then_dies)
    with pytest.raises(SimulatedCrash):
        recover(factory, file_store, workspaces, coordinator, build)
    monkeypatch.undo()

    recover(factory, file_store, workspaces, coordinator, build)

    assert reload(factory, Job, world.running_job.id).state == "INTERRUPTED"
    assert reload(factory, ProcessingRun, world.running_run.id).state == "INTERRUPTED"
    assert reload(factory, ExecutionSegment, world.running_segment.id).state == "INTERRUPTED"
    assert reload(factory, Job, world.pausing_job.id).state == "PAUSED"
    assert reload(factory, Job, world.cancelling_job.id).state == "CANCELLED"
    assert reload(factory, ProcessingRun, world.pausing_run.id).state == "PAUSED"
    assert reload(factory, ProcessingRun, world.cancelling_run.id).state == "CANCELLED"
    assert reload(factory, Artifact, world.artifact_id).state == "AVAILABLE"
    assert reload(factory, IndexOperation, world.op.id).state == "APPLIED"
    assert workspaces.existing() == sorted(
        [world.running_job.id, world.paused_job.id, world.pausing_job.id]
    )
    assert open_index(coordinator, world.space).contains(1)
    assert open_index(coordinator, world.other_space).contains(2)
    rows = database_state(sqlite_engine)
    assert recover(factory, file_store, workspaces, coordinator, build).repaired_nothing
    assert database_state(sqlite_engine) == rows


# --- the steps ---------------------------------------------------------------------------------


def test_in_flight_work_is_interrupted_in_one_transaction_and_only_once(
    world: World, factory: sessionmaker[Session], build: ModelFactory
) -> None:
    build.session.commit()
    first = interrupt_in_flight_work(factory, clock=build.clock)
    second = interrupt_in_flight_work(factory, clock=build.clock)

    assert first.jobs == [world.running_job.id]
    assert world.running_run.id in first.runs
    assert world.running_segment.id in first.segments
    assert first.jobs_paused == [world.pausing_job.id]
    assert first.jobs_cancelled == [world.cancelling_job.id]
    assert first.runs_paused == [world.pausing_run.id]
    assert first.runs_cancelled == [world.cancelling_run.id]
    assert second == InterruptedWork()  # nothing left to move, nothing moved twice
    assert reload(factory, ProcessingRun, world.running_run.id).revision == 2  # bumped once
    assert reload(factory, ProcessingRun, world.pausing_run.id).revision == 2
    assert reload(factory, ProcessingRun, world.cancelling_run.id).revision == 2


def test_a_workspace_is_kept_for_every_job_that_is_not_over(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    states = {
        state: build.job(state=state).id
        for state in (
            "QUEUED", "RUNNING", "PAUSING", "PAUSED", "CANCELLING", "INTERRUPTED",
            "CANCELLED", "COMPLETED", "FAILED",
        )
    }  # fmt: skip
    build.session.commit()

    kept = jobs_that_may_resume(factory)

    assert kept == {job_id for state, job_id in states.items() if state not in
                    {"CANCELLED", "COMPLETED", "FAILED"}}  # fmt: skip


def clean_report() -> StartupReport:
    return StartupReport(
        RecoveryReport(),
        [],
        [],
        InterruptedWork(),
        WorkspaceCleanup(),
        [],
        [],
        CoordinatorReport(),
        1,
    )


def test_a_report_with_no_repairs_says_so() -> None:
    assert clean_report().repaired_nothing


@pytest.mark.parametrize(
    "repair",
    [
        lambda r: r.artifacts.finalized.append(uuid.uuid4()),
        lambda r: r.artifacts.write_not_completed.append(uuid.uuid4()),
        lambda r: r.artifacts.deleted.append(uuid.uuid4()),
        lambda r: r.artifacts.delete_failed.append(uuid.uuid4()),
        lambda r: r.artifacts.staging_removed.append("a.part"),
        lambda r: r.missing_references.append(uuid.uuid4()),
        lambda r: r.missing_managed.append(uuid.uuid4()),
        lambda r: r.interrupted.jobs.append(uuid.uuid4()),
        lambda r: r.interrupted.leases_cleared.append(uuid.uuid4()),
        lambda r: r.requeued_operations.append(uuid.uuid4()),
        lambda r: r.interrupted.runs.append(uuid.uuid4()),
        lambda r: r.interrupted.segments.append(uuid.uuid4()),
        lambda r: r.interrupted.jobs_paused.append(uuid.uuid4()),
        lambda r: r.interrupted.jobs_cancelled.append(uuid.uuid4()),
        lambda r: r.interrupted.runs_paused.append(uuid.uuid4()),
        lambda r: r.interrupted.runs_cancelled.append(uuid.uuid4()),
        lambda r: r.workspaces.removed.append(uuid.uuid4()),
        lambda r: r.indexes_rebuilt.append(uuid.uuid4()),
        lambda r: r.index_operations.applied.append(uuid.uuid4()),
        lambda r: r.index_operations.retrying.append((uuid.uuid4(), "x")),
        lambda r: r.index_operations.failed.append((uuid.uuid4(), "x")),
        lambda r: r.index_operations.rebuilt_spaces.append(uuid.uuid4()),
        lambda r: r.index_operations.purged_spaces.append(uuid.uuid4()),
    ],
    ids=[
        "artifact-finalized", "artifact-not-completed", "artifact-deleted",
        "artifact-delete-failed", "staging-removed", "missing-reference", "missing-managed",
        "job", "lease-cleared", "operation-requeued", "run", "segment", "job-paused",
        "job-cancelled", "run-paused", "run-cancelled", "workspace",
        "index-rebuilt", "operation-applied", "operation-retrying", "operation-failed",
        "coordinator-rebuilt", "coordinator-purged",
    ],
)  # fmt: skip
def test_any_repair_means_the_run_was_not_clean(repair: Callable[[StartupReport], object]) -> None:
    report = clean_report()
    repair(report)
    assert not report.repaired_nothing


# --- what is left unresolved ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("unresolved", "what"),
    [
        (lambda r: r.artifacts.skipped.append((uuid.uuid4(), "locked")), "artifacts skipped"),
        (lambda r: r.artifacts.staging_left.append("a.part"), "staging files left"),
        (lambda r: r.artifacts.delete_failed.append(uuid.uuid4()), "artifact deletions failed"),
        (lambda r: r.workspaces.failed.append((uuid.uuid4(), "locked")), "workspaces not removed"),
        (lambda r: r.index_operations.unindexable.append(uuid.uuid4()), "cannot be indexed"),
        (lambda r: r.index_operations.retrying.append((uuid.uuid4(), "x")), "backing off"),
        (lambda r: r.index_operations.failed.append((uuid.uuid4(), "x")), "out of attempts"),
    ],
    ids=["skipped", "staging", "delete-failed", "workspace", "unindexable", "retrying", "failed"],
)  # fmt: skip
def test_unresolved_work_means_the_run_is_not_clean(
    unresolved: Callable[[StartupReport], object], what: str
) -> None:
    assert clean_report().clean
    report = clean_report()
    unresolved(report)

    assert not report.clean
    assert any(what in item for item in report.unresolved)


def test_foreign_entries_under_the_workspace_folder_are_not_unresolved_work() -> None:
    report = clean_report()
    report.workspaces.unowned.append("notes.txt")

    assert report.clean


def test_a_repair_alone_is_not_unresolved() -> None:
    report = clean_report()
    report.interrupted.jobs.append(uuid.uuid4())

    assert not report.repaired_nothing
    assert report.unresolved == []
    assert not report.clean


# --- leases, linked state and failed operations ------------------------------------------------


@pytest.mark.parametrize("state", ["QUEUED", "PAUSED", "COMPLETED"])
@pytest.mark.parametrize("held", ["both", "owner-only", "expiry-only"])
def test_a_stale_lease_is_cleared_from_a_job_that_is_not_running_and_its_state_kept(
    factory: sessionmaker[Session], build: ModelFactory, state: str, held: str
) -> None:
    job = build.job(
        state=state,
        lease_owner=None if held == "expiry-only" else "worker-1",
        lease_expires_at=None if held == "owner-only" else build.clock(),
    )
    build.session.commit()

    cleared = interrupt_in_flight_work(factory, clock=build.clock)

    assert cleared.leases_cleared == [job.id]
    assert cleared.jobs == []  # not interrupted: only RUNNING work is
    after = reload(factory, Job, job.id)
    assert (after.state, after.lease_owner, after.lease_expires_at) == (state, None, None)
    assert interrupt_in_flight_work(factory, clock=build.clock).leases_cleared == []


@pytest.mark.parametrize(
    ("state", "becomes", "ends"), [("PAUSING", "PAUSED", False), ("CANCELLING", "CANCELLED", True)]
)
@pytest.mark.parametrize("held", ["both", "owner-only", "expiry-only"])
def test_a_job_being_paused_or_cancelled_moves_on_and_its_lease_is_cleared(
    factory: sessionmaker[Session], build: ModelFactory, state: str, becomes: str, ends: bool,
    held: str,
) -> None:  # fmt: skip
    job = build.job(
        state=state,
        lease_owner=None if held == "expiry-only" else "worker-1",
        lease_expires_at=None if held == "owner-only" else build.clock(),
    )
    build.session.commit()

    moved = interrupt_in_flight_work(factory, clock=build.clock)

    after = reload(factory, Job, job.id)
    assert (after.state, after.lease_owner, after.lease_expires_at) == (becomes, None, None)
    assert after.ended_at == (build.clock() if ends else None)
    assert moved.leases_cleared == []  # reported as moved, not as a bare lease clear
    assert (moved.jobs_paused, moved.jobs_cancelled) == (
        ([job.id], []) if becomes == "PAUSED" else ([], [job.id])
    )
    assert moved.jobs == []  # not interrupted
    assert interrupt_in_flight_work(factory, clock=build.clock) == InterruptedWork()


def test_what_was_moved_is_reported_in_id_order_whatever_order_it_was_stored_in(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    """Rows are inserted in descending id order, so insertion order cannot be what sorts them."""
    ids = sorted((build.new_id() for _ in range(3)), reverse=True)
    paused_jobs = [build.job(id=i, state="PAUSING") for i in ids]
    cancelled_jobs = [build.job(id=build.new_id(), state="CANCELLING") for _ in range(3)]
    cancelled_jobs.sort(key=lambda j: j.id, reverse=True)
    paused_runs = [
        build.run(id=i, state="PAUSING")
        for i in sorted((build.new_id() for _ in range(3)), reverse=True)
    ]
    cancelled_runs = [
        build.run(id=i, state="CANCELLING")
        for i in sorted((build.new_id() for _ in range(3)), reverse=True)
    ]
    build.session.commit()

    moved = interrupt_in_flight_work(factory, clock=build.clock)

    assert moved.jobs_paused == sorted(job.id for job in paused_jobs)
    assert moved.jobs_cancelled == sorted(job.id for job in cancelled_jobs)
    assert moved.runs_paused == sorted(run.id for run in paused_runs)
    assert moved.runs_cancelled == sorted(run.id for run in cancelled_runs)


def test_a_run_being_paused_or_cancelled_is_moved_by_its_own_state_whatever_its_job_says(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    pausing = build.run(state="PAUSING")
    cancelling = build.run(state="CANCELLING")
    queued_job_of_a_pausing_run = build.job(state="QUEUED", processing_run_id=pausing.id)
    done_job_of_a_cancelling_run = build.job(state="COMPLETED", processing_run_id=cancelling.id)
    build.session.commit()

    moved = interrupt_in_flight_work(factory, clock=build.clock)

    assert moved.runs_paused == [pausing.id]
    assert moved.runs_cancelled == [cancelling.id]
    assert reload(factory, Job, queued_job_of_a_pausing_run.id).state == "QUEUED"
    assert reload(factory, Job, done_job_of_a_cancelling_run.id).state == "COMPLETED"


def test_job_and_run_states_are_recovered_independently_of_each_other(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    """Each row is judged by its own state: contradictory combinations are all handled."""
    consistent_run = build.run(state="RUNNING")
    consistent_segment = build.segment(consistent_run, 0, "RUNNING")
    consistent = build.job(state="RUNNING", processing_run_id=consistent_run.id)
    finished_run = build.run(state="COMPLETED")
    running_job_of_a_finished_run = build.job(state="RUNNING", processing_run_id=finished_run.id)
    live_run = build.run(state="RUNNING")
    finished_job_of_a_live_run = build.job(state="COMPLETED", processing_run_id=live_run.id)
    build.session.commit()

    interrupted = interrupt_in_flight_work(factory, clock=build.clock)

    assert {consistent.id, running_job_of_a_finished_run.id} <= set(interrupted.jobs)
    assert finished_job_of_a_live_run.id not in interrupted.jobs
    assert {consistent_run.id, live_run.id} <= set(interrupted.runs)
    assert finished_run.id not in interrupted.runs
    assert consistent_segment.id in interrupted.segments
    assert reload(factory, ProcessingRun, finished_run.id).state == "COMPLETED"
    assert reload(factory, Job, finished_job_of_a_live_run.id).state == "COMPLETED"


def test_a_workspace_is_kept_for_a_finished_job_whose_run_is_still_live(
    factory: sessionmaker[Session], workspaces: WorkspaceManager, build: ModelFactory
) -> None:
    """Contradictory state is recoverable inconsistency, not permission to delete scratch data."""
    live_run = build.run(state="PAUSED")
    finished_run = build.run(state="COMPLETED")
    kept = build.job(state="COMPLETED", processing_run_id=live_run.id)
    removed = build.job(state="COMPLETED", processing_run_id=finished_run.id)
    unlinked = build.job(state="FAILED")
    for job in (kept, removed, unlinked):
        workspaces.allocate(job.id)
    build.session.commit()

    assert jobs_that_may_resume(factory) == {kept.id}
    cleanup = workspaces.remove_orphans(jobs_that_may_resume(factory))

    assert sorted(cleanup.removed) == sorted([removed.id, unlinked.id])
    assert workspaces.existing() == [kept.id]


def test_a_failed_index_operation_gets_one_fresh_set_of_attempts(
    factory: sessionmaker[Session], file_store: ManagedFileStore, workspaces: WorkspaceManager,
    coordinator: IndexCoordinator, build: ModelFactory,
) -> None:  # fmt: skip
    space = build.representation_space(dimension=NDIM)
    rep = active(build, space, 1)
    operation = build.index_operation(
        rep, operation="ADD", state="FAILED", attempt_count=3, failure_code="APPLY_ERROR",
        failure_detail="the disk was full",
    )  # fmt: skip

    report = recover(factory, file_store, workspaces, coordinator, build)

    assert report.requeued_operations == [operation.id]
    assert report.index_operations.applied == [operation.id]  # and it succeeded this time
    done = reload(factory, IndexOperation, operation.id)
    assert (done.state, done.attempt_count, done.failure_code) == ("APPLIED", 1, None)
    assert open_index(coordinator, space).contains(1)


def test_a_failed_operation_that_would_duplicate_a_pending_one_stays_failed(
    factory: sessionmaker[Session], coordinator: IndexCoordinator, build: ModelFactory
) -> None:
    space = build.representation_space(dimension=NDIM)
    rep = active(build, space, 1)
    failed = build.index_operation(rep, operation="ADD", state="FAILED", attempt_count=3)
    pending = build.index_operation(rep, operation="ADD", state="PENDING")
    other_kind = build.index_operation(rep, operation="REMOVE", state="FAILED", attempt_count=3)
    build.session.commit()

    requeued = coordinator.requeue_failed_operations()

    assert requeued == [other_kind.id]  # the REMOVE has no pending twin; the ADD does
    assert reload(factory, IndexOperation, failed.id).state == "FAILED"
    assert reload(factory, IndexOperation, pending.id).state == "PENDING"


def test_of_several_failed_twins_only_the_newest_is_requeued(
    factory: sessionmaker[Session], coordinator: IndexCoordinator, build: ModelFactory
) -> None:
    space = build.representation_space(dimension=NDIM)
    rep = active(build, space, 1)
    older = build.index_operation(rep, operation="ADD", state="FAILED")
    build.clock.advance(hours=1)
    newer = build.index_operation(rep, operation="ADD", state="FAILED")
    build.session.commit()

    assert coordinator.requeue_failed_operations() == [newer.id]
    assert reload(factory, IndexOperation, older.id).state == "FAILED"
    assert coordinator.requeue_failed_operations() == []  # the newer one is pending now


def test_an_operation_settled_while_requeueing_is_not_resurrected(
    factory: sessionmaker[Session], coordinator: IndexCoordinator, build: ModelFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    space = build.representation_space(dimension=NDIM)
    operation = build.index_operation(active(build, space, 1), operation="ADD", state="FAILED")
    build.session.commit()
    real = coordinator._sessions
    opened: list[int] = []

    def sessions() -> Session:
        opened.append(1)
        if len(opened) == 2:  # between choosing the failed operations and writing: it is settled
            with real() as other:
                other.execute(
                    update(IndexOperation).where(IndexOperation.id == operation.id)
                    .values(state="APPLIED", applied_at=build.clock())
                )  # fmt: skip
                other.commit()
        return real()

    monkeypatch.setattr(coordinator, "_sessions", sessions)

    assert coordinator.requeue_failed_operations() == []
    assert reload(factory, IndexOperation, operation.id).state == "APPLIED"


def test_requeueing_keeps_the_diagnostics_until_the_next_outcome(
    factory: sessionmaker[Session], coordinator: IndexCoordinator, build: ModelFactory
) -> None:
    space = build.representation_space(dimension=NDIM)
    operation = build.index_operation(
        active(build, space, 1), operation="ADD", state="FAILED", attempt_count=3,
        failure_code="APPLY_ERROR", failure_detail="OSError: locked",
    )  # fmt: skip
    build.session.commit()
    build.clock.advance(hours=1)

    coordinator.requeue_failed_operations()

    again = reload(factory, IndexOperation, operation.id)
    assert (again.state, again.attempt_count, again.not_before_at) == (
        "PENDING", 0, build.clock(),
    )  # fmt: skip
    assert (again.failure_code, again.failure_detail) == ("APPLY_ERROR", "OSError: locked")


# --- failures inside a step ----------------------------------------------------------------------


class InjectedFault(Exception):
    """Raised in place of a real SQL statement; never raised by production code."""


@pytest.mark.parametrize("which", [1, 2, 3], ids=["running", "pausing", "cancelling"])
def test_a_failure_part_way_through_interrupting_work_rolls_all_of_it_back(
    world: World, factory: sessionmaker[Session], build: ModelFactory, sqlite_engine: Engine,
    which: int,
) -> None:  # fmt: skip
    """The run updates come in three steps (RUNNING, PAUSING, CANCELLING); a failure at any of them
    leaves the database exactly as it was, jobs updated before it included."""
    build.session.commit()
    before = database_state(sqlite_engine)
    seen = 0

    def fail_on_runs(_c: object, _cur: object, statement: str, *_r: object) -> None:
        nonlocal seen
        if statement.lstrip().upper().startswith("UPDATE PROCESSING_RUNS"):
            seen += 1
            if seen == which:
                raise InjectedFault

    event.listen(sqlite_engine, "before_cursor_execute", fail_on_runs)
    try:
        with pytest.raises(InjectedFault):
            interrupt_in_flight_work(factory, clock=build.clock)
    finally:
        event.remove(sqlite_engine, "before_cursor_execute", fail_on_runs)

    assert database_state(sqlite_engine) == before  # the jobs updated first were rolled back too
    assert reload(factory, Job, world.running_job.id).state == "RUNNING"
    assert interrupt_in_flight_work(factory, clock=build.clock).jobs == [world.running_job.id]


def test_a_crash_inside_the_workspace_removal_is_repaired_by_running_recovery_again(
    world: World, factory: sessionmaker[Session], file_store: ManagedFileStore,
    workspaces: WorkspaceManager, coordinator: IndexCoordinator, build: ModelFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    real = shutil.rmtree
    calls: list[object] = []

    def dies_on_the_second_removal(path: Any, *args: Any, **kwargs: Any) -> None:
        calls.append(path)
        if len(calls) == 2:
            raise SimulatedCrash
        real(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", dies_on_the_second_removal)
    with pytest.raises(SimulatedCrash):
        recover(factory, file_store, workspaces, coordinator, build)
    monkeypatch.undo()
    assert len(workspaces.existing()) > 3  # some finished workspaces are still there

    recover(factory, file_store, workspaces, coordinator, build)

    assert workspaces.existing() == sorted(
        [world.running_job.id, world.paused_job.id, world.pausing_job.id]
    )
    assert recover(factory, file_store, workspaces, coordinator, build).repaired_nothing


# --- referenced originals ----------------------------------------------------------------------


def reference(build: ModelFactory, file: Path, **kw: Any) -> Artifact:
    return build.artifact(
        storage_mode="REFERENCED", storage_key=None, external_path=str(file), sha256=None,
        size_bytes=None, **kw,
    )  # fmt: skip


def test_a_deleted_referenced_original_becomes_missing_and_the_rest_do_not(
    factory: sessionmaker[Session], build: ModelFactory, tmp_path: Path
) -> None:
    present, deleted = tmp_path / "a.jpg", tmp_path / "b.jpg"
    present.write_bytes(b"x")
    kept, lost = reference(build, present), reference(build, deleted)
    managed = build.artifact()  # managed bytes are not this step's business
    build.session.commit()

    marked = mark_missing_referenced_originals(factory, clock=build.clock)

    assert marked == [lost.id]
    assert reload(factory, Artifact, lost.id).failure_code == REFERENCED_FILE_MISSING
    assert reload(factory, Artifact, kept.id).state == "AVAILABLE"
    assert reload(factory, Artifact, managed.id).state == "AVAILABLE"
    assert mark_missing_referenced_originals(factory, clock=build.clock) == []  # idempotent


def test_a_directory_where_the_file_was_counts_as_missing(
    factory: sessionmaker[Session], build: ModelFactory, tmp_path: Path
) -> None:
    folder = tmp_path / "now-a-folder"
    folder.mkdir()
    artifact = reference(build, folder)
    build.session.commit()

    assert mark_missing_referenced_originals(factory, clock=build.clock) == [artifact.id]


def test_a_file_that_returned_is_not_trusted_without_its_content_being_checked(
    factory: sessionmaker[Session], build: ModelFactory, tmp_path: Path
) -> None:
    """Only AVAILABLE moves to MISSING here. Whether a returned file is the same media needs
    hashing, which a startup scan must not do."""
    file = tmp_path / "back.jpg"
    file.write_bytes(b"a different file entirely")
    artifact = reference(build, file, state="MISSING", failure_code=REFERENCED_FILE_MISSING)
    build.session.commit()

    assert mark_missing_referenced_originals(factory, clock=build.clock) == []
    assert reload(factory, Artifact, artifact.id).state == "MISSING"


def test_a_file_that_cannot_be_examined_is_not_marked_missing(
    factory: sessionmaker[Session], build: ModelFactory, tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    file = tmp_path / "locked.jpg"
    file.write_bytes(b"x")
    artifact = reference(build, file)
    build.session.commit()
    real_stat = Path.stat

    def denied(self: Path, **kwargs: bool) -> Any:
        if self == file:
            raise PermissionError("access is denied")
        return real_stat(self, **kwargs)

    monkeypatch.setattr(Path, "stat", denied)

    assert mark_missing_referenced_originals(factory, clock=build.clock) == []
    assert reload(factory, Artifact, artifact.id).state == "AVAILABLE"


def test_an_artifact_settled_while_the_scan_ran_is_not_overwritten(
    factory: sessionmaker[Session], build: ModelFactory, tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    artifact = reference(build, tmp_path / "gone.jpg")
    build.session.commit()
    real = artifact_storage.transition_artifact

    def settled_first(session: Session, artifact_id: uuid.UUID, *args: Any, **kwargs: Any) -> None:
        with factory() as other:
            other.execute(
                update(Artifact).where(Artifact.id == artifact_id).values(state="DELETED")
            )
            other.commit()
        real(session, artifact_id, *args, **kwargs)

    monkeypatch.setattr(referenced_artifacts, "transition_artifact", settled_first, raising=True)

    assert mark_missing_referenced_originals(factory, clock=build.clock) == []
    assert reload(factory, Artifact, artifact.id).state == "DELETED"


# --- index validation ------------------------------------------------------------------------


def test_a_missing_index_is_built_and_a_sound_one_is_left_alone(
    factory: sessionmaker[Session], coordinator: IndexCoordinator, build: ModelFactory
) -> None:
    space = build.representation_space(dimension=NDIM)
    active(build, space, 1)
    build.session.commit()

    assert coordinator.validate_indexes() == [space.id]  # no index yet: built from SQLite
    assert open_index(coordinator, space).contains(1)
    manifest = open_index(coordinator, space).manifest
    assert coordinator.validate_indexes() == []  # sound: untouched
    assert open_index(coordinator, space).manifest == manifest


def test_a_deprecated_space_is_not_indexed(
    factory: sessionmaker[Session], coordinator: IndexCoordinator, build: ModelFactory
) -> None:
    deprecated = build.representation_space(dimension=NDIM, state="DEPRECATED")
    build.session.commit()

    assert coordinator.validate_indexes() == []
    assert not coordinator.index_directory(deprecated.id).exists()


# --- index catch-up is bounded ---------------------------------------------------------------


def test_index_catch_up_stops_at_the_pass_limit_and_leaves_the_rest_pending(
    factory: sessionmaker[Session], file_store: ManagedFileStore, workspaces: WorkspaceManager,
    coordinator: IndexCoordinator, build: ModelFactory,
) -> None:  # fmt: skip
    space = build.representation_space(dimension=NDIM)
    operations = []
    for key in (1, 2, 3):
        operations.append(build.index_operation(active(build, space, key), operation="ADD"))
        build.clock.advance(seconds=1)

    limited = recover(factory, file_store, workspaces, coordinator, build,
                      index_batch=1, max_index_passes=2)  # fmt: skip

    assert limited.index_passes == 2
    assert limited.index_operations.applied == [operations[0].id, operations[1].id]
    assert reload(factory, IndexOperation, operations[2].id).state == "PENDING"

    rest = recover(factory, file_store, workspaces, coordinator, build,
                   index_batch=1, max_index_passes=5)  # fmt: skip
    assert rest.index_operations.applied == [operations[2].id]
    assert rest.index_passes == 2  # the second pass found nothing due, so it stopped


def test_a_failing_operation_does_not_keep_startup_spinning(
    factory: sessionmaker[Session], file_store: ManagedFileStore, workspaces: WorkspaceManager,
    coordinator: IndexCoordinator, build: ModelFactory,
) -> None:  # fmt: skip
    space = build.representation_space(dimension=NDIM)
    bad = build.representation(
        representation_space_id=space.id, state="ACTIVE", identity_id=build.identity().id,
        ann_key=9, vector=float32_vector([1.0, 2.0, 3.0]), vector_dimension=3,
    )  # fmt: skip
    operation = build.index_operation(bad, operation="ADD")

    report = recover(factory, file_store, workspaces, coordinator, build,
                     index_batch=10, max_index_passes=50)  # fmt: skip

    assert [op for op, _ in report.index_operations.retrying] == [operation.id]
    assert report.index_passes == 2  # one failed attempt; the next pass found it backing off
    assert reload(factory, IndexOperation, operation.id).state == "PENDING"


def test_the_recovery_order_is_artifacts_work_workspaces_then_indexes(
    world: World, factory: sessionmaker[Session], file_store: ManagedFileStore,
    workspaces: WorkspaceManager, coordinator: IndexCoordinator, build: ModelFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    calls: list[str] = []

    def spy(owner: Any, name: str, label: str) -> None:
        real = getattr(owner, name)

        def wrapper(*args: Any, **kwargs: Any) -> Any:
            calls.append(label)
            return real(*args, **kwargs)

        monkeypatch.setattr(owner, name, wrapper)

    spy(startup, "recover_artifacts", "artifacts")
    spy(startup, "interrupt_in_flight_work", "work")
    spy(WorkspaceManager, "remove_orphans", "workspaces")
    spy(IndexCoordinator, "validate_indexes", "validate")
    spy(IndexCoordinator, "apply_pending", "catch-up")

    recover(factory, file_store, workspaces, coordinator, build)

    assert calls[:4] == ["artifacts", "work", "workspaces", "validate"]
    assert set(calls[4:]) == {"catch-up"}
