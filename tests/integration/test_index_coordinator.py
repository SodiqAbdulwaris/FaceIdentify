"""Replaying durable IndexOperations into real USearch indexes (M2: TST-028; persistence §17, §23).

The coordinator re-reads the representation for every operation and applies it as a desired state,
so replaying is harmless; the index generation is persisted before any operation is marked APPLIED.
Each crash window between the two is reproduced.
"""

import uuid
from datetime import timedelta
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import Engine, update
from sqlalchemy.orm import Session, sessionmaker

from backend.app.memory.index_coordinator import (
    APPLY_ERROR,
    CoordinatorReport,
    IndexCoordinator,
    RetryPolicy,
)
from backend.app.memory.models import IndexOperation, Representation, RepresentationSpace
from backend.infrastructure.db.engine import create_session_factory
from backend.infrastructure.indexing.representation_index import RepresentationIndex
from tests.factories.models import ModelFactory, float32_vector
from tests.fixtures.persistence import AppDirs

NDIM = 4
MAX_ATTEMPTS = 3


class SimulatedCrash(BaseException):
    """The process dying: no `except Exception` handler gets to tidy up after it."""


@pytest.fixture
def factory(sqlite_engine: Engine) -> sessionmaker[Session]:
    return create_session_factory(sqlite_engine)


@pytest.fixture
def coordinator(
    factory: sessionmaker[Session], app_dirs: AppDirs, build: ModelFactory
) -> IndexCoordinator:
    return IndexCoordinator(
        factory, app_dirs.indexes, clock=build.clock, new_id=build.new_id,
        retry=RetryPolicy(max_attempts=MAX_ATTEMPTS, backoff=lambda n: timedelta(minutes=n)),
    )  # fmt: skip


@pytest.fixture
def space(db_session: Session, build: ModelFactory) -> RepresentationSpace:
    space = build.representation_space(dimension=NDIM)
    db_session.commit()
    return space


def active(
    build: ModelFactory, space: RepresentationSpace, key: int, values: list[float] | None = None,
    **kw: object,
) -> Representation:  # fmt: skip
    return build.representation(
        representation_space_id=space.id, state="ACTIVE", identity_id=build.identity().id,
        ann_key=key, vector=float32_vector(values or [float(key), 1.0, 0.0, 0.0]), **kw,
    )  # fmt: skip


def queue(build: ModelFactory, rep: Representation, kind: str, **kw: object) -> IndexOperation:
    return build.index_operation(rep, operation=kind, **kw)


def open_index(coordinator: IndexCoordinator, space: RepresentationSpace) -> RepresentationIndex:
    return RepresentationIndex.open(
        coordinator.index_directory(space.id), representation_space_id=space.id, ndim=NDIM,
        metric="cos",
    )  # fmt: skip


def load_op(factory: sessionmaker[Session], operation_id: uuid.UUID) -> IndexOperation:
    with factory() as session:
        operation = session.get(IndexOperation, operation_id)
        assert operation is not None
        return operation


def run(coordinator: IndexCoordinator, build: ModelFactory, limit: int = 100) -> CoordinatorReport:
    build.session.commit()
    return coordinator.apply_pending(limit=limit)


def generation(coordinator: IndexCoordinator, space: RepresentationSpace) -> uuid.UUID:
    manifest = open_index(coordinator, space).manifest
    assert manifest is not None
    return manifest.generation_id


# --- applying operations ---------------------------------------------------------------------


def test_an_add_puts_the_representation_in_the_index_and_marks_the_operation_applied(
    coordinator: IndexCoordinator, factory: sessionmaker[Session], space: RepresentationSpace,
    build: ModelFactory,
) -> None:  # fmt: skip
    rep = active(build, space, 7)
    operation = queue(build, rep, "ADD")
    build.clock.advance(minutes=5)

    report = run(coordinator, build)

    assert report.applied == [operation.id]
    assert (report.retrying, report.failed, report.rebuilt_spaces) == ([], [], [space.id])
    index = open_index(coordinator, space)
    assert index.contains(7)
    assert index.search(np.array([7.0, 1.0, 0.0, 0.0], dtype=np.float32), 1)[0].key == 7
    done = load_op(factory, operation.id)
    assert (done.state, done.attempt_count) == ("APPLIED", 1)
    assert done.applied_at == done.last_attempt_at == build.clock()
    assert (done.failure_code, done.failure_detail) == (None, None)


def test_a_remove_takes_the_key_out_even_while_the_representation_is_still_active(
    coordinator: IndexCoordinator, space: RepresentationSpace, build: ModelFactory
) -> None:
    kept, dropped = active(build, space, 1), active(build, space, 2)
    queue(build, kept, "ADD")
    queue(build, dropped, "ADD")
    run(coordinator, build)
    queue(build, dropped, "REMOVE")

    run(coordinator, build)

    index = open_index(coordinator, space)
    assert (index.contains(1), index.contains(2)) == (True, False)


def test_removing_a_key_that_is_not_there_is_applied_not_an_error(
    coordinator: IndexCoordinator, factory: sessionmaker[Session], space: RepresentationSpace,
    build: ModelFactory,
) -> None:  # fmt: skip
    operation = queue(build, active(build, space, 3), "REMOVE")

    report = run(coordinator, build)

    assert report.applied == [operation.id]
    assert load_op(factory, operation.id).state == "APPLIED"


def test_replaying_an_operation_changes_nothing(
    coordinator: IndexCoordinator, factory: sessionmaker[Session], db_session: Session,
    space: RepresentationSpace, build: ModelFactory,
) -> None:  # fmt: skip
    rep = active(build, space, 5)
    operation = queue(build, rep, "ADD")
    run(coordinator, build)
    first = generation(coordinator, space)

    with factory() as session:  # the same durable operation is delivered again
        session.execute(
            update(IndexOperation).where(IndexOperation.id == operation.id)
            .values(state="PENDING", applied_at=None)
        )  # fmt: skip
        session.commit()
    report = run(coordinator, build)

    assert report.applied == [operation.id]
    assert len(open_index(coordinator, space)) == 1
    assert generation(coordinator, space) == first  # nothing changed, so no new generation


def test_a_batch_is_persisted_as_one_generation(
    coordinator: IndexCoordinator, space: RepresentationSpace, build: ModelFactory
) -> None:
    for key in (1, 2, 3):
        queue(build, active(build, space, key), "ADD")

    run(coordinator, build)
    index = open_index(coordinator, space)

    assert len(index) == 3
    assert sorted(p.name for p in coordinator.index_directory(space.id).iterdir()) == sorted(
        ["manifest.json", f"index.{generation(coordinator, space).hex}.usearch"]
    )


# --- re-reading the representation -----------------------------------------------------------


def test_an_add_for_a_representation_that_is_no_longer_active_is_applied_but_adds_nothing(
    coordinator: IndexCoordinator, factory: sessionmaker[Session], space: RepresentationSpace,
    build: ModelFactory,
) -> None:  # fmt: skip
    rep = active(build, space, 9)
    operation = queue(build, rep, "ADD")
    rep.state = "SUPERSEDED"  # it lost eligibility after the ADD was queued

    report = run(coordinator, build)

    assert report.applied == [operation.id]
    assert not open_index(coordinator, space).contains(9)


def files_containing(directory: Path, needle: bytes) -> list[Path]:
    return [p for p in directory.rglob("*") if p.is_file() and needle in p.read_bytes()]


def test_an_erased_vector_is_gone_from_every_file_of_the_index(
    coordinator: IndexCoordinator, factory: sessionmaker[Session], space: RepresentationSpace,
    build: ModelFactory,
) -> None:  # fmt: skip
    """Erasure clears `ann_key`, so a REMOVE cannot name a key: the space is rebuilt from SQLite
    and the superseded generation's file, which still held the vector, must be gone (CONTEXT 25)."""
    secret = [123.25, -7.5, 99.125, 0.03125]
    erased = active(build, space, 4, secret)
    survivor = active(build, space, 5, [1.0, 2.0, 3.0, 4.0])
    queue(build, erased, "ADD")
    queue(build, survivor, "ADD")
    run(coordinator, build)
    directory = coordinator.index_directory(space.id)
    assert open_index(coordinator, space).contains(4)
    assert files_containing(directory, float32_vector(secret))  # it is in the index file now
    erased.state, erased.vector, erased.ann_key = "ERASED", None, None
    operation = queue(build, erased, "REMOVE")

    report = run(coordinator, build)

    assert report.applied == [operation.id]
    assert report.purged_spaces == [space.id]
    assert files_containing(directory, float32_vector(secret)) == []  # nowhere on disk
    index = open_index(coordinator, space)
    assert (index.contains(4), index.contains(5)) == (False, True)
    assert not (directory / "quarantine").exists()  # quarantine would have kept the old file
    assert load_op(factory, operation.id).state == "APPLIED"


def test_a_purge_still_honours_a_remove_for_a_representation_that_is_active(
    coordinator: IndexCoordinator, space: RepresentationSpace, build: ModelFactory
) -> None:
    """REMOVE means absent, even where SQLite still calls the representation active."""
    erased, removed, kept = (active(build, space, key) for key in (1, 2, 3))
    for rep in (erased, removed, kept):
        queue(build, rep, "ADD")
    run(coordinator, build)
    erased.state, erased.vector, erased.ann_key = "ERASED", None, None
    queue(build, erased, "REMOVE")
    queue(build, removed, "REMOVE")

    run(coordinator, build)

    index = open_index(coordinator, space)
    assert [index.contains(key) for key in (1, 2, 3)] == [False, False, True]


def test_an_operation_that_failed_is_not_applied_again_by_a_purge(
    coordinator: IndexCoordinator, factory: sessionmaker[Session], space: RepresentationSpace,
    build: ModelFactory,
) -> None:  # fmt: skip
    erased = active(build, space, 1)
    queue(build, erased, "ADD")
    run(coordinator, build)
    erased.state, erased.vector, erased.ann_key = "ERASED", None, None
    purge = queue(build, erased, "REMOVE")
    bad = queue(build, bad_vector(build, space, 2), "ADD")

    report = run(coordinator, build)

    assert report.applied == [purge.id]
    assert [op for op, _ in report.retrying] == [bad.id]
    assert report.purged_spaces == [space.id]


def test_a_purge_that_cannot_delete_the_old_file_fails_instead_of_reporting_it_gone(
    coordinator: IndexCoordinator, factory: sessionmaker[Session], space: RepresentationSpace,
    build: ModelFactory,
) -> None:  # fmt: skip
    erased = active(build, space, 4, [123.25, -7.5, 99.125, 0.03125])
    queue(build, erased, "ADD")
    run(coordinator, build)
    directory = coordinator.index_directory(space.id)
    old_generation = next(directory.glob("index.*.usearch"))
    erased.state, erased.vector, erased.ann_key = "ERASED", None, None
    operation = queue(build, erased, "REMOVE")
    build.clock.advance(minutes=1)

    with old_generation.open("rb"):  # an open handle: Windows refuses to delete the file
        report = run(coordinator, build)

    assert report.applied == []
    assert "could not be removed" in report.retrying[0][1]
    assert load_op(factory, operation.id).state == "PENDING"  # not reported applied
    build.clock.advance(minutes=5)
    assert run(coordinator, build).applied == [operation.id]  # the lock is gone
    assert files_containing(directory, float32_vector([123.25, -7.5, 99.125, 0.03125])) == []


def test_operations_are_applied_in_the_order_they_were_queued(
    coordinator: IndexCoordinator, space: RepresentationSpace, build: ModelFactory
) -> None:
    add_then_remove = active(build, space, 11)
    remove_then_add = active(build, space, 12)
    queue(build, add_then_remove, "ADD")
    build.clock.advance(seconds=1)
    queue(build, add_then_remove, "REMOVE")
    build.clock.advance(seconds=1)
    queue(build, remove_then_add, "REMOVE")
    build.clock.advance(seconds=1)
    queue(build, remove_then_add, "ADD")
    build.clock.advance(seconds=1)

    run(coordinator, build)

    index = open_index(coordinator, space)
    assert (index.contains(11), index.contains(12)) == (False, True)


def test_a_limit_takes_the_oldest_due_operations_first(
    coordinator: IndexCoordinator, factory: sessionmaker[Session], space: RepresentationSpace,
    build: ModelFactory,
) -> None:  # fmt: skip
    operations = []
    for key in (1, 2, 3):
        operations.append(queue(build, active(build, space, key), "ADD"))
        build.clock.advance(seconds=1)

    report = run(coordinator, build, limit=2)

    assert report.applied == [operations[0].id, operations[1].id]
    assert load_op(factory, operations[2].id).state == "PENDING"


def test_an_operation_that_is_not_yet_due_waits(
    coordinator: IndexCoordinator, factory: sessionmaker[Session], space: RepresentationSpace,
    build: ModelFactory,
) -> None:  # fmt: skip
    operation = queue(
        build, active(build, space, 1), "ADD", not_before_at=build.clock() + timedelta(hours=1)
    )

    assert run(coordinator, build).applied == []
    build.clock.advance(hours=2)
    assert run(coordinator, build).applied == [operation.id]


# --- crash windows ---------------------------------------------------------------------------


def test_a_crash_after_the_index_is_persisted_but_before_the_operations_are_settled(
    coordinator: IndexCoordinator, factory: sessionmaker[Session], space: RepresentationSpace,
    build: ModelFactory, monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    """The index is ahead of SQLite: the operation is still PENDING and its replay finds it done."""
    operation = queue(build, active(build, space, 6), "ADD")

    def die(*_: object, **__: object) -> None:
        raise SimulatedCrash

    monkeypatch.setattr(coordinator, "_settle", die)
    with pytest.raises(SimulatedCrash):
        run(coordinator, build)
    monkeypatch.undo()
    assert open_index(coordinator, space).contains(6)  # persisted
    assert load_op(factory, operation.id).state == "PENDING"  # but never settled
    crashed_generation = generation(coordinator, space)

    report = run(coordinator, build)

    assert report.applied == [operation.id]
    assert len(open_index(coordinator, space)) == 1
    assert generation(coordinator, space) == crashed_generation  # replay changed nothing


def test_a_failure_to_persist_leaves_every_operation_pending_and_backs_off(
    coordinator: IndexCoordinator, factory: sessionmaker[Session], space: RepresentationSpace,
    build: ModelFactory, monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    first = queue(build, active(build, space, 1), "ADD")
    run(coordinator, build)  # the space's first generation exists
    queued = [queue(build, active(build, space, key), "ADD") for key in (2, 3)]
    build.clock.advance(minutes=1)

    def full_disk(*_: object, **__: object) -> None:
        raise OSError("no space left on device")

    monkeypatch.setattr(RepresentationIndex, "persist", full_disk)
    report = run(coordinator, build)
    monkeypatch.undo()

    assert report.applied == []
    assert sorted(op for op, _ in report.retrying) == sorted(op.id for op in queued)
    assert all("no space left on device" in message for _, message in report.retrying)
    for operation in queued:
        pending = load_op(factory, operation.id)
        assert (pending.state, pending.attempt_count, pending.failure_code) == (
            "PENDING", 1, APPLY_ERROR,
        )  # fmt: skip
        assert pending.not_before_at == build.clock() + timedelta(minutes=1)  # backoff(1)
    assert load_op(factory, first.id).state == "APPLIED"
    assert len(open_index(coordinator, space)) == 1  # the old generation is untouched

    build.clock.advance(minutes=2)
    assert len(run(coordinator, build).applied) == 2
    assert len(open_index(coordinator, space)) == 3


# --- failures and retries --------------------------------------------------------------------


def bad_vector(build: ModelFactory, space: RepresentationSpace, key: int) -> Representation:
    """A representation whose stored vector is not the space's dimension (corrupt data)."""
    return build.representation(
        representation_space_id=space.id, state="ACTIVE", identity_id=build.identity().id,
        ann_key=key, vector=float32_vector([1.0, 2.0, 3.0]), vector_dimension=3,
    )  # fmt: skip


def test_one_bad_operation_does_not_stop_the_others_in_its_batch(
    coordinator: IndexCoordinator, factory: sessionmaker[Session], space: RepresentationSpace,
    build: ModelFactory,
) -> None:  # fmt: skip
    good = queue(build, active(build, space, 1), "ADD")
    corrupt = bad_vector(build, space, 2)
    bad = queue(build, corrupt, "ADD")
    also_good = queue(build, active(build, space, 3), "ADD")

    report = run(coordinator, build)

    assert report.applied == [good.id, also_good.id]
    assert [op for op, _ in report.retrying] == [bad.id]
    assert report.unindexable == [corrupt.id]  # the first build left it out, and said so
    assert "not 4 float32 values" in report.retrying[0][1]
    index = open_index(coordinator, space)
    assert (index.contains(1), index.contains(2), index.contains(3)) == (True, False, True)


def test_an_operation_that_keeps_failing_is_marked_failed_after_its_attempts(
    coordinator: IndexCoordinator, factory: sessionmaker[Session], space: RepresentationSpace,
    build: ModelFactory,
) -> None:  # fmt: skip
    bad = queue(build, bad_vector(build, space, 2), "ADD")
    outcomes = []
    for _ in range(MAX_ATTEMPTS):
        outcomes.append(run(coordinator, build))
        build.clock.advance(hours=1)

    assert [len(o.retrying) for o in outcomes] == [1, 1, 0]
    assert [op for op, _ in outcomes[-1].failed] == [bad.id]
    failed = load_op(factory, bad.id)
    assert (failed.state, failed.attempt_count, failed.failure_code) == (
        "FAILED", MAX_ATTEMPTS, APPLY_ERROR,
    )  # fmt: skip
    assert run(coordinator, build).failed == []  # a FAILED operation is not picked up again


def test_an_operation_settled_by_someone_else_meanwhile_is_not_counted(
    coordinator: IndexCoordinator, factory: sessionmaker[Session], space: RepresentationSpace,
    build: ModelFactory, monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    operation = queue(build, active(build, space, 1), "ADD")
    real = coordinator._apply_one

    def apply_and_get_settled_elsewhere(*args: object, **kwargs: object) -> object:
        with factory() as other:
            other.execute(
                update(IndexOperation).where(IndexOperation.id == operation.id)
                .values(state="APPLIED", applied_at=build.clock())
            )  # fmt: skip
            other.commit()
        return real(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(coordinator, "_apply_one", apply_and_get_settled_elsewhere)

    report = run(coordinator, build)

    assert report.applied == []
    assert load_op(factory, operation.id).attempt_count == 0  # untouched by this pass


def test_a_rebuild_leaves_out_a_vector_that_is_not_finite_and_says_so(
    coordinator: IndexCoordinator, space: RepresentationSpace, build: ModelFactory
) -> None:
    nan = active(build, space, 1, [float("nan"), 0.0, 0.0, 0.0])
    infinite = active(build, space, 2, [float("inf"), 0.0, 0.0, 0.0])
    fine = active(build, space, 3)
    queue(build, fine, "ADD")

    report = run(coordinator, build)

    assert sorted(report.unindexable) == sorted([nan.id, infinite.id])
    assert report.applied != []
    index = open_index(coordinator, space)
    assert [index.contains(key) for key in (1, 2, 3)] == [False, False, True]


def test_a_representation_whose_identity_is_not_active_is_not_indexed(
    coordinator: IndexCoordinator, space: RepresentationSpace, build: ModelFactory
) -> None:
    """§6.2: an active representation needs an active identity, which no constraint can check."""
    not_active = build.identity(state="PENDING")
    orphan = active(build, space, 1)
    orphan.identity_id = not_active.id
    healthy = active(build, space, 2)
    queue(build, orphan, "ADD")
    queue(build, healthy, "ADD")

    run(coordinator, build)

    index = open_index(coordinator, space)
    assert (index.contains(1), index.contains(2)) == (False, True)  # not by ADD, not by rebuild


def test_a_remove_does_not_depend_on_the_identity(
    coordinator: IndexCoordinator, space: RepresentationSpace, build: ModelFactory
) -> None:
    rep = active(build, space, 1)
    queue(build, rep, "ADD")
    run(coordinator, build)
    rep.identity_id = build.identity(state="PENDING").id
    queue(build, rep, "REMOVE")

    run(coordinator, build)

    assert not open_index(coordinator, space).contains(1)


def test_passes_are_serialized(
    coordinator: IndexCoordinator, space: RepresentationSpace, build: ModelFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    """Two threads must not both load, change and persist one index: the last writer would win."""
    queue(build, active(build, space, 1), "ADD")
    real = coordinator._apply_space
    held: list[bool] = []

    def while_applying(*args: object, **kwargs: object) -> None:
        held.append(coordinator._lock.locked())
        real(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(coordinator, "_apply_space", while_applying)

    run(coordinator, build)

    assert held == [True]
    assert not coordinator._lock.locked()


# --- spaces ----------------------------------------------------------------------------------


def test_an_operation_naming_another_space_than_its_representation_is_refused(
    coordinator: IndexCoordinator, factory: sessionmaker[Session], db_session: Session,
    space: RepresentationSpace, build: ModelFactory,
) -> None:  # fmt: skip
    other = build.representation_space(dimension=NDIM)
    db_session.commit()
    operation = queue(build, active(build, space, 1), "ADD", representation_space_id=other.id)

    report = run(coordinator, build)

    assert report.applied == []
    assert "different spaces" in report.retrying[0][1]
    assert not open_index(coordinator, other).contains(1)
    assert load_op(factory, operation.id).attempt_count == 1


def test_each_space_has_its_own_index(
    coordinator: IndexCoordinator, db_session: Session, space: RepresentationSpace,
    build: ModelFactory,
) -> None:  # fmt: skip
    other = build.representation_space(dimension=NDIM)
    db_session.commit()
    queue(build, active(build, space, 1), "ADD")
    queue(build, active(build, other, 2), "ADD")

    report = run(coordinator, build)

    assert sorted(report.rebuilt_spaces) == sorted([space.id, other.id])
    assert coordinator.index_directory(space.id) != coordinator.index_directory(other.id)
    mine, theirs = open_index(coordinator, space), open_index(coordinator, other)
    assert (mine.contains(1), mine.contains(2)) == (True, False)
    assert (theirs.contains(1), theirs.contains(2)) == (False, True)


def test_an_unusable_index_is_rebuilt_from_every_active_representation_in_sqlite(
    coordinator: IndexCoordinator, space: RepresentationSpace, build: ModelFactory
) -> None:
    for key in (1, 2):
        queue(build, active(build, space, key), "ADD")
    run(coordinator, build)
    (coordinator.index_directory(space.id) / "manifest.json").write_text("{broken")
    # Active in SQLite but never queued here, and one that must not be in a rebuild:
    active(build, space, 3)
    active(build, space, 4).state = "SUPERSEDED"
    queue(build, active(build, space, 5), "ADD")

    report = run(coordinator, build)

    assert report.rebuilt_spaces == [space.id]
    index = open_index(coordinator, space)
    assert [index.contains(key) for key in (1, 2, 3, 4, 5)] == [True, True, True, False, True]
    assert (coordinator.index_directory(space.id) / "quarantine" / "1").is_dir()


def test_nothing_due_does_nothing(
    coordinator: IndexCoordinator, space: RepresentationSpace, build: ModelFactory
) -> None:
    report = run(coordinator, build)

    assert report == CoordinatorReport()
    assert not coordinator.index_directory(space.id).exists()
