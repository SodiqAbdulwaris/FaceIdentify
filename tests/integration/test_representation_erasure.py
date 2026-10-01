"""The erasure use case on real SQLite, USearch and files (M2: TST-031; TESTING_STRATEGY INDEX-03,
INDEX-04, INDEX-05, PER-07, PER-08; persistence §6.2, §23, §25; GitHub issues 29 and 52).

Erasure is two-step: a representation moves to `ERASING` (excluded from retrieval at once), the
space's index is rebuilt without it and its old generations are retired, and only then are the
vector and key cleared, followed by a truncating checkpoint. Every crash point is reproduced and
recovery is shown to finish the erasure exactly once. "Gone" is verified by byte search, never by
assertion about state alone. None of this claims physical erasure from SSD storage.
"""

import threading
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.identities.models import EvidenceKind
from backend.app.identities.use_cases import (
    IdentityManagerError,
    assign_representation_to_identity,
    merge_identities,
    resolve_ann_candidates,
    split_identity,
)
from backend.app.memory import erasure
from backend.app.memory.erasure import ErasureReport, RepresentationEraser
from backend.app.memory.index_coordinator import IndexCoordinator, RetryPolicy
from backend.app.memory.models import (
    IndexOperation,
    Representation,
    RepresentationSpace,
)
from backend.app.settings.app_state import WAL_TRUNCATION_OWED, AppStateRepository
from backend.infrastructure.db import engine as db_engine
from backend.infrastructure.db.engine import create_session_factory
from backend.infrastructure.indexing import representation_index
from backend.infrastructure.indexing.representation_index import RepresentationIndex
from tests.factories.models import ModelFactory, float32_vector
from tests.fixtures.persistence import AppDirs

NDIM = 4


class SimulatedCrash(BaseException):
    """The process dying: no `except Exception` handler gets to tidy up after it."""


@pytest.fixture
def factory(sqlite_engine: Engine) -> sessionmaker[Session]:
    return create_session_factory(sqlite_engine)


def make_coordinator(
    factory: sessionmaker[Session], app_dirs: AppDirs, build: ModelFactory
) -> IndexCoordinator:
    return IndexCoordinator(
        factory, app_dirs.indexes, clock=build.clock, new_id=build.new_id,
        retry=RetryPolicy(max_attempts=3, backoff=lambda n: timedelta(minutes=n)),
    )  # fmt: skip


def make_eraser(
    factory: sessionmaker[Session], engine: Engine, coordinator: IndexCoordinator,
    build: ModelFactory, **kw: Any,
) -> RepresentationEraser:  # fmt: skip
    return RepresentationEraser(
        factory, engine, coordinator, clock=build.clock, new_id=build.new_id,
        checkpoint_timeout_ms=0, **kw,
    )  # fmt: skip


@pytest.fixture
def coordinator(
    factory: sessionmaker[Session], app_dirs: AppDirs, build: ModelFactory
) -> IndexCoordinator:
    return make_coordinator(factory, app_dirs, build)


@pytest.fixture
def eraser(
    factory: sessionmaker[Session], sqlite_engine: Engine, coordinator: IndexCoordinator,
    build: ModelFactory,
) -> RepresentationEraser:  # fmt: skip
    return make_eraser(factory, sqlite_engine, coordinator, build)


@pytest.fixture
def space(db_session: Session, build: ModelFactory) -> RepresentationSpace:
    space = build.representation_space(dimension=NDIM)
    db_session.commit()
    return space


def secret(index: int) -> list[float]:
    """A vector whose bytes are easy to search for and differ per representation."""
    return [100.25 + index, -7.5 - index, 99.125, 0.03125 * (index + 1)]


def active(
    build: ModelFactory, space: RepresentationSpace, key: int, **kw: Any
) -> Representation:  # fmt: skip
    fields: dict[str, Any] = dict(
        representation_space_id=space.id, state="ACTIVE", identity_id=build.identity().id,
        ann_key=key, vector=float32_vector(secret(key)),
    )  # fmt: skip
    return build.representation(**(fields | kw))


def indexed(
    build: ModelFactory, coordinator: IndexCoordinator, space: RepresentationSpace, *keys: int
) -> list[Representation]:
    """ACTIVE representations that the coordinator has put into the space's index."""
    reps = [active(build, space, key) for key in keys]
    for rep in reps:
        build.index_operation(rep, operation="ADD")
    build.session.commit()
    coordinator.apply_pending(limit=100)
    return reps


def row(factory: sessionmaker[Session], rep_id: uuid.UUID) -> tuple[Any, ...]:
    with factory() as session:
        found = session.execute(
            select(
                Representation.state, Representation.vector, Representation.ann_key,
                Representation.erased_at,
            ).where(Representation.id == rep_id)
        ).one()  # fmt: skip
        return tuple(found)


def contains_key(coordinator: IndexCoordinator, space: RepresentationSpace, key: int) -> bool:
    return RepresentationIndex.open(
        coordinator.index_directory(space.id), representation_space_id=space.id, ndim=NDIM,
        metric="cos",
    ).contains(key)  # fmt: skip


def index_files_with(
    coordinator: IndexCoordinator, space: RepresentationSpace, key: int
) -> list[Path]:
    needle = float32_vector(secret(key))
    directory = coordinator.index_directory(space.id)
    return [p for p in directory.rglob("*") if p.is_file() and needle in p.read_bytes()]


def sqlite_files_with(engine: Engine, key: int) -> list[str]:
    """Which of the database file and its write-ahead log contain the vector's bytes."""
    needle = float32_vector(secret(key))
    database = Path(str(engine.url.database))
    candidates = [database, database.with_name(database.name + "-wal")]
    return [p.name for p in candidates if p.exists() and needle in p.read_bytes()]


def wal_size(engine: Engine) -> int:
    database = Path(str(engine.url.database))
    return database.with_name(database.name + "-wal").stat().st_size


def marker(factory: sessionmaker[Session]) -> str | None:
    with factory() as session:
        return AppStateRepository(session).get(WAL_TRUNCATION_OWED)


def operations(factory: sessionmaker[Session], kind: str | None = None) -> list[tuple[str, str]]:
    with factory() as session:
        statement = select(IndexOperation.operation, IndexOperation.state)
        if kind is not None:
            statement = statement.where(IndexOperation.operation == kind)
        return [tuple(r) for r in session.execute(statement.order_by(IndexOperation.created_at))]


def assert_gone(
    factory: sessionmaker[Session], engine: Engine, coordinator: IndexCoordinator,
    space: RepresentationSpace, rep: Representation,
) -> None:  # fmt: skip
    """The representation is `ERASED` and its vector is in no row, index file or SQLite file."""
    state, vector, key, erased_at = row(factory, rep.id)
    assert (state, vector, key) == ("ERASED", None, None)
    assert erased_at is not None
    assert rep.ann_key is not None
    assert index_files_with(coordinator, space, rep.ann_key) == []
    assert sqlite_files_with(engine, rep.ann_key) == []


# --- the whole erasure --------------------------------------------------------------------------


def test_a_single_erasure_clears_the_row_the_index_the_files_and_the_log(
    eraser: RepresentationEraser, coordinator: IndexCoordinator, factory: sessionmaker[Session],
    sqlite_engine: Engine, space: RepresentationSpace, build: ModelFactory,
) -> None:  # fmt: skip
    victim, survivor = indexed(build, coordinator, space, 1, 2)
    assert index_files_with(coordinator, space, 1)  # it is in the index file now
    assert sqlite_files_with(sqlite_engine, 1)  # and in the database or its log

    report = eraser.erase([victim.id])

    assert report.complete, report.outstanding_cleanup
    assert report.erased == [victim.id]
    assert_gone(factory, sqlite_engine, coordinator, space, victim)
    # (clearing the marker after the truncation writes one non-sensitive frame to the log)
    assert marker(factory) is None  # the truncation was done, so nothing is owed
    assert not contains_key(coordinator, space, 1)
    assert contains_key(coordinator, space, 2)  # the survivor is untouched
    assert row(factory, survivor.id)[0] == "ACTIVE"
    assert index_files_with(coordinator, space, 2)


def test_a_bulk_erasure_rebuilds_each_space_once(
    eraser: RepresentationEraser, coordinator: IndexCoordinator, factory: sessionmaker[Session],
    sqlite_engine: Engine, space: RepresentationSpace, build: ModelFactory,
    db_session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    other = build.representation_space(dimension=NDIM)
    db_session.commit()
    first = indexed(build, coordinator, space, 1, 2, 3, 4)
    second = indexed(build, coordinator, other, 11, 12)  # other keys: other bytes
    calls: list[int] = []
    real_build = RepresentationIndex.build.__func__  # type: ignore[attr-defined]

    def counting(cls: type[RepresentationIndex], /, *args: object, **kwargs: object) -> object:
        calls.append(1)
        return real_build(cls, *args, **kwargs)

    monkeypatch.setattr(RepresentationIndex, "build", classmethod(counting))
    victims = [first[0], first[1], first[2], second[0]]

    report = eraser.erase([rep.id for rep in victims])

    assert report.complete, report.outstanding_cleanup
    assert sorted(report.erased) == sorted(rep.id for rep in victims)
    assert len(calls) == 2  # one rebuild per space, not one per representation
    for rep in victims[:3]:
        assert_gone(factory, sqlite_engine, coordinator, space, rep)
    assert_gone(factory, sqlite_engine, coordinator, other, victims[3])
    assert contains_key(coordinator, space, 4)
    assert contains_key(coordinator, other, 12)


def test_representations_that_were_never_indexed_are_erased_without_any_index_work(
    eraser: RepresentationEraser, factory: sessionmaker[Session], sqlite_engine: Engine,
    space: RepresentationSpace, build: ModelFactory, coordinator: IndexCoordinator,
) -> None:  # fmt: skip
    """A `PENDING` or `SUPERSEDED` representation with no key holds a vector but was never in the
    index, so there is nothing to remove and no REMOVE is queued."""
    pending = build.representation(
        representation_space_id=space.id, vector=float32_vector(secret(7)), ann_key=None
    )
    superseded = build.representation(
        representation_space_id=space.id, state="SUPERSEDED",
        vector=float32_vector(secret(8)), ann_key=None,
    )  # fmt: skip
    build.session.commit()
    assert sqlite_files_with(sqlite_engine, 7)

    report = eraser.erase([pending.id, superseded.id])

    assert report.complete, report.outstanding_cleanup
    assert sorted(report.erased) == sorted([pending.id, superseded.id])
    assert operations(factory) == []
    for rep, key in ((pending, 7), (superseded, 8)):
        assert row(factory, rep.id)[:3] == ("ERASED", None, None)
        assert sqlite_files_with(sqlite_engine, key) == []
    assert not coordinator.index_directory(space.id).exists()  # no index was ever touched


def test_ids_that_cannot_be_erased_are_ignored_and_an_erased_one_stays_erased(
    eraser: RepresentationEraser, factory: sessionmaker[Session], space: RepresentationSpace,
    build: ModelFactory, coordinator: IndexCoordinator,
) -> None:  # fmt: skip
    (victim,) = indexed(build, coordinator, space, 1)
    deleted = build.representation(representation_space_id=space.id, state="DELETED")
    build.session.commit()
    unknown = uuid.UUID(int=12345)
    assert eraser.erase([victim.id]).complete
    before = (row(factory, victim.id), operations(factory))

    report = eraser.erase([victim.id, deleted.id, unknown, victim.id])

    assert report.erased == [victim.id]  # a repeat is a no-op, and a duplicate id counts once
    assert report.ignored == [deleted.id, unknown]
    assert report.complete
    assert row(factory, deleted.id)[0] == "DELETED"
    assert (row(factory, victim.id), operations(factory)) == before  # nothing was queued again


# --- INDEX-03: a queued erasure is excluded from retrieval at once ------------------------------


def test_a_queued_erasure_is_excluded_from_retrieval_before_the_index_changes(
    eraser: RepresentationEraser, coordinator: IndexCoordinator, factory: sessionmaker[Session],
    space: RepresentationSpace, build: ModelFactory,
) -> None:  # fmt: skip
    victim, _ = indexed(build, coordinator, space, 1, 2)

    eraser.queue([victim.id])  # step one only

    assert contains_key(coordinator, space, 1)  # the stale index still holds the vector
    with factory() as session:
        kept = resolve_ann_candidates(session, space.id, [1, 2])
    # the ERASING row is rejected although its identity is ACTIVE
    assert [candidate.ann_key for candidate in kept] == [2]
    assert row(factory, victim.id)[0] == "ERASING"
    assert row(factory, victim.id)[1] is not None  # vector and key are kept until step two
    coordinator.validate_indexes()  # a rebuild from SQLite leaves it out
    assert not contains_key(coordinator, space, 1)
    assert contains_key(coordinator, space, 2)


# --- INDEX-04: superseded and quarantined generations are retired -------------------------------


def test_a_locked_superseded_generation_keeps_the_erasure_unfinished_until_it_is_released(
    eraser: RepresentationEraser, coordinator: IndexCoordinator, factory: sessionmaker[Session],
    sqlite_engine: Engine, space: RepresentationSpace, build: ModelFactory,
) -> None:  # fmt: skip
    victim, _ = indexed(build, coordinator, space, 1, 2)
    old_generation = next(coordinator.index_directory(space.id).glob("index.*.usearch"))
    build.clock.advance(minutes=1)

    with old_generation.open("rb"):  # an open handle: Windows refuses to delete the file
        report = eraser.erase([victim.id])

        assert not report.complete
        assert report.pending == [victim.id]
        assert report.errors  # the REMOVE is backing off, reported
        assert row(factory, victim.id)[0] == "ERASING"  # not cleared while the old file is there
        assert operations(factory, "REMOVE") == [("REMOVE", "PENDING")]  # and not applied
        assert marker(factory) is None  # nothing was cleared, so no truncation is owed yet

    build.clock.advance(minutes=10)
    resumed = eraser.resume()

    assert resumed.complete, resumed.outstanding_cleanup
    assert_gone(factory, sqlite_engine, coordinator, space, victim)


def test_a_quarantined_copy_is_deleted_when_the_erasure_finishes(
    eraser: RepresentationEraser, coordinator: IndexCoordinator, factory: sessionmaker[Session],
    sqlite_engine: Engine, space: RepresentationSpace, build: ModelFactory,
) -> None:  # fmt: skip
    victim, _ = indexed(build, coordinator, space, 1, 2)
    directory = coordinator.index_directory(space.id)
    quarantined = directory / "quarantine" / "1"
    quarantined.mkdir(parents=True)
    for source in directory.glob("index.*.usearch"):  # a copy of the generation that holds it
        (quarantined / source.name).write_bytes(source.read_bytes())
    assert index_files_with(coordinator, space, 1)

    report = eraser.erase([victim.id])

    assert report.complete, report.outstanding_cleanup
    assert not (directory / "quarantine").exists()
    assert_gone(factory, sqlite_engine, coordinator, space, victim)


def test_a_locked_quarantined_copy_blocks_only_its_own_space(
    eraser: RepresentationEraser, coordinator: IndexCoordinator, factory: sessionmaker[Session],
    sqlite_engine: Engine, space: RepresentationSpace, build: ModelFactory, db_session: Session,
) -> None:  # fmt: skip
    other = build.representation_space(dimension=NDIM)
    db_session.commit()
    (blocked_victim,) = indexed(build, coordinator, space, 1)
    (free_victim,) = indexed(build, coordinator, other, 1)
    quarantined = coordinator.index_directory(space.id) / "quarantine" / "1"
    quarantined.mkdir(parents=True)
    copy = quarantined / f"index.{uuid.UUID(int=9).hex}.usearch"
    copy.write_bytes(float32_vector(secret(1)))

    with copy.open("rb"):  # an open handle: Windows refuses to delete the file
        report = eraser.erase([blocked_victim.id, free_victim.id])

        assert not report.complete
        assert list(report.blocked) == [space.id]  # the other space was not stopped
        assert report.pending == [blocked_victim.id]
        assert report.erased == [free_victim.id]
        assert row(factory, blocked_victim.id)[0] == "ERASING"
        assert row(factory, free_victim.id)[:3] == ("ERASED", None, None)
        assert marker(factory) is None or report.wal_truncated  # the cleared one was handled

        removes = operations(factory, "REMOVE")

    resumed = eraser.resume()

    assert resumed.complete, resumed.outstanding_cleanup
    assert_gone(factory, sqlite_engine, coordinator, space, blocked_victim)
    assert not copy.exists()
    assert operations(factory, "REMOVE") == removes  # recovery queued no second REMOVE


# --- PER-08: no residue in SQLite ---------------------------------------------------------------


def test_a_checkpoint_blocked_by_a_reader_is_reported_owed_and_completed_later(
    eraser: RepresentationEraser, coordinator: IndexCoordinator, factory: sessionmaker[Session],
    sqlite_engine: Engine, space: RepresentationSpace, build: ModelFactory,
) -> None:  # fmt: skip
    victim, _ = indexed(build, coordinator, space, 1, 2)

    with sqlite_engine.connect() as reader:
        reader.exec_driver_sql("SELECT count(*) FROM representations").all()  # an old snapshot
        report = eraser.erase([victim.id])

        assert report.wal_truncated is False
        assert not report.complete
        assert "the write-ahead log has not been truncated" in report.outstanding_cleanup
        assert row(factory, victim.id)[:3] == ("ERASED", None, None)  # cleared, cleanup owed
        assert marker(factory) is not None  # recorded durably
        assert wal_size(sqlite_engine) > 0
        reader.rollback()

    resumed = eraser.resume()

    assert resumed.complete, resumed.outstanding_cleanup
    assert marker(factory) is None
    assert_gone(factory, sqlite_engine, coordinator, space, victim)


def test_a_truncation_that_raises_is_owed_not_complete(
    eraser: RepresentationEraser, coordinator: IndexCoordinator, factory: sessionmaker[Session],
    space: RepresentationSpace, build: ModelFactory, monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    (victim,) = indexed(build, coordinator, space, 1)

    def broken(*args: object, **kwargs: object) -> bool:
        raise OSError("disk error")

    monkeypatch.setattr(erasure, "truncate_wal", broken)

    report = eraser.erase([victim.id])

    assert not report.complete
    assert report.wal_truncated is False
    assert any("truncate_wal: OSError: disk error" in item for item in report.outstanding_cleanup)
    assert marker(factory) is not None


def test_a_marker_set_again_meanwhile_survives_an_earlier_checkpoint(
    eraser: RepresentationEraser, coordinator: IndexCoordinator, factory: sessionmaker[Session],
    space: RepresentationSpace, build: ModelFactory, monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    """Another erasure commits while this one's checkpoint runs: its frames may not be covered, so
    its marker must stay."""
    (victim,) = indexed(build, coordinator, space, 1)
    real = db_engine.truncate_wal

    def with_a_later_erasure(*args: Any, **kwargs: Any) -> bool:
        with factory() as session:
            AppStateRepository(session).set(WAL_TRUNCATION_OWED, "later", now=build.clock())
            session.commit()
        return real(*args, **kwargs)

    monkeypatch.setattr(erasure, "truncate_wal", with_a_later_erasure)

    report = eraser.erase([victim.id])

    assert report.complete  # this erasure's own cleanup is done
    assert marker(factory) == "later"  # but the later one's is still owed


# --- PER-07: crash-safe, idempotent recovery ----------------------------------------------------


def dump_tables(factory: sessionmaker[Session]) -> list[list[tuple[Any, ...]]]:
    with factory() as session:
        return [
            [tuple(r) for r in session.execute(statement)]
            for statement in (
                select(Representation.id, Representation.state, Representation.ann_key,
                       Representation.vector, Representation.erased_at).order_by(Representation.id),
                select(IndexOperation.id, IndexOperation.operation, IndexOperation.state,
                       IndexOperation.attempt_count).order_by(IndexOperation.id),
            )
        ]  # fmt: skip


CRASH_POINTS = (
    "queued",
    "before_the_new_generation",
    "persisted_not_settled",
    "removal_applied_not_cleared",
    "cleared_not_truncated",
)


@pytest.mark.parametrize("crash", CRASH_POINTS)
def test_stopping_after_any_step_and_rerunning_recovery_completes_the_erasure_once(
    crash: str, eraser: RepresentationEraser, coordinator: IndexCoordinator,
    factory: sessionmaker[Session], sqlite_engine: Engine, app_dirs: AppDirs,
    space: RepresentationSpace, build: ModelFactory, monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    victim, survivor = indexed(build, coordinator, space, 1, 2)
    old_build = RepresentationIndex.build

    def crashing(*args: object, **kwargs: object) -> Any:
        raise SimulatedCrash(crash)

    if crash == "queued":
        eraser.queue([victim.id])
    else:
        if crash == "before_the_new_generation":
            monkeypatch.setattr(RepresentationIndex, "build", classmethod(crashing))
        elif crash == "persisted_not_settled":
            monkeypatch.setattr(IndexCoordinator, "_settle", crashing)
        elif crash == "removal_applied_not_cleared":
            monkeypatch.setattr(erasure, "retire_quarantine", crashing)
        else:
            monkeypatch.setattr(erasure, "truncate_wal", crashing)
        with pytest.raises(SimulatedCrash):
            eraser.erase([victim.id])
        monkeypatch.undo()
    assert RepresentationIndex.build == old_build  # the patch is gone: this is a restart
    if crash == "cleared_not_truncated":
        assert marker(factory) is not None  # the database says the cleanup is still owed
        assert row(factory, victim.id)[:3] == ("ERASED", None, None)
    else:
        assert row(factory, victim.id)[0] == "ERASING"  # never reactivated, never half cleared
    build.clock.advance(minutes=10)  # past any backoff the interrupted pass recorded

    restarted = make_eraser(
        factory, sqlite_engine, make_coordinator(factory, app_dirs, build), build
    )
    report = restarted.resume()

    assert report.complete, report.outstanding_cleanup
    assert_gone(factory, sqlite_engine, coordinator, space, victim)
    assert marker(factory) is None
    assert not contains_key(coordinator, space, 1)
    assert contains_key(coordinator, space, 2)
    assert row(factory, survivor.id)[0] == "ACTIVE"
    with factory() as session:
        assert resolve_ann_candidates(session, space.id, [1]) == []
    assert operations(factory, "REMOVE")[-1] == ("REMOVE", "APPLIED")
    snapshot = dump_tables(factory)

    again = restarted.resume()  # a second recovery finds nothing to repair

    assert again.complete
    assert (again.pending, again.erased) == ([], [])
    assert dump_tables(factory) == snapshot


def test_recovery_queues_the_remove_an_erasing_representation_lacks(
    eraser: RepresentationEraser, coordinator: IndexCoordinator, factory: sessionmaker[Session],
    sqlite_engine: Engine, space: RepresentationSpace, build: ModelFactory,
) -> None:  # fmt: skip
    (victim,) = indexed(build, coordinator, space, 1)
    with factory() as session:  # moved to ERASING by something that did not queue the REMOVE
        session.execute(
            Representation.__table__.update()  # type: ignore[attr-defined]
            .where(Representation.id == victim.id)
            .values(state="ERASING")
        )
        session.commit()
    assert operations(factory, "REMOVE") == []

    report = eraser.resume()

    assert report.complete, report.outstanding_cleanup
    assert_gone(factory, sqlite_engine, coordinator, space, victim)


def test_resume_with_nothing_to_do_does_nothing(
    eraser: RepresentationEraser, factory: sessionmaker[Session], space: RepresentationSpace
) -> None:
    before = dump_tables(factory)

    report = eraser.resume()

    assert report == ErasureReport()
    assert report.complete
    assert dump_tables(factory) == before


# --- INDEX-05: erasure and the coordinator do not race ------------------------------------------


def test_an_add_claimed_before_the_erasure_is_queued_re_reads_the_row_and_does_nothing(
    eraser: RepresentationEraser, coordinator: IndexCoordinator, factory: sessionmaker[Session],
    sqlite_engine: Engine, space: RepresentationSpace, build: ModelFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    victim = active(build, space, 1)
    add = build.index_operation(victim, operation="ADD")
    build.session.commit()
    real = IndexCoordinator._apply_one
    fired: list[int] = []

    def erasure_commits_mid_pass(self: IndexCoordinator, *args: Any) -> Any:
        if not fired:
            fired.append(1)
            eraser.queue([victim.id])  # commits after the pass claimed the ADD
        return real(self, *args)

    monkeypatch.setattr(IndexCoordinator, "_apply_one", erasure_commits_mid_pass)

    report = coordinator.apply_pending(limit=10)

    assert report.applied == []  # the ADD was deleted by the erasure; settlement tolerates that
    with factory() as session:
        assert session.get(IndexOperation, add.id) is None
    assert row(factory, victim.id)[0] == "ERASING"
    monkeypatch.undo()
    finished = eraser.resume()
    assert finished.complete, finished.outstanding_cleanup
    assert_gone(factory, sqlite_engine, coordinator, space, victim)
    assert not contains_key(coordinator, space, 1)


def test_an_add_applied_before_the_erasure_commits_is_removed_by_the_erasure(
    eraser: RepresentationEraser, coordinator: IndexCoordinator, factory: sessionmaker[Session],
    sqlite_engine: Engine, space: RepresentationSpace, build: ModelFactory,
) -> None:  # fmt: skip
    (victim,) = indexed(build, coordinator, space, 1)
    assert contains_key(coordinator, space, 1)

    report = eraser.erase([victim.id])

    assert report.complete, report.outstanding_cleanup
    assert_gone(factory, sqlite_engine, coordinator, space, victim)


def test_a_second_erasure_of_the_same_representation_queues_nothing_more(
    eraser: RepresentationEraser, coordinator: IndexCoordinator, factory: sessionmaker[Session],
    space: RepresentationSpace, build: ModelFactory,
) -> None:  # fmt: skip
    (victim,) = indexed(build, coordinator, space, 1)
    eraser.queue([victim.id])
    after_the_first = operations(factory, "REMOVE")

    eraser.queue([victim.id])

    assert operations(factory, "REMOVE") == after_the_first == [("REMOVE", "PENDING")]
    assert eraser.erase([victim.id]).complete
    assert operations(factory, "REMOVE") == [("REMOVE", "APPLIED")]


def test_a_bulk_erasure_that_overlaps_a_coordinator_pass_converges(
    eraser: RepresentationEraser, coordinator: IndexCoordinator, factory: sessionmaker[Session],
    sqlite_engine: Engine, space: RepresentationSpace, build: ModelFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    victims = indexed(build, coordinator, space, 1, 2, 3)
    bystander = active(build, space, 4)
    build.index_operation(bystander, operation="ADD")
    build.session.commit()
    real = IndexCoordinator._apply_one
    started: list[threading.Thread] = []
    reports: list[ErasureReport] = []

    def bulk_forget_starts_mid_pass(self: IndexCoordinator, *args: Any) -> Any:
        if not started:
            thread = threading.Thread(
                target=lambda: reports.append(eraser.erase([v.id for v in victims]))
            )
            started.append(thread)
            thread.start()  # blocks on the coordinator's lock until this pass is over
        return real(self, *args)

    monkeypatch.setattr(IndexCoordinator, "_apply_one", bulk_forget_starts_mid_pass)

    coordinator.apply_pending(limit=10)
    started[0].join(timeout=60)
    monkeypatch.undo()

    assert not started[0].is_alive()
    final = reports[0] if reports[0].complete else eraser.resume()
    assert final.complete, final.outstanding_cleanup
    for victim in victims:
        assert_gone(factory, sqlite_engine, coordinator, space, victim)
    assert contains_key(coordinator, space, 4)


def test_an_erasing_representation_cannot_be_reactivated_split_or_moved_by_a_merge(
    eraser: RepresentationEraser, coordinator: IndexCoordinator, factory: sessionmaker[Session],
    sqlite_engine: Engine, space: RepresentationSpace, build: ModelFactory,
) -> None:  # fmt: skip
    keeper, victim = indexed(build, coordinator, space, 1, 2)
    victim_identity = build.identity()
    build.session.commit()
    with factory() as session:
        session.execute(
            Representation.__table__.update()  # type: ignore[attr-defined]
            .where(Representation.id.in_([keeper.id, victim.id]))
            .values(identity_id=victim_identity.id)
        )
        session.commit()
    eraser.queue([victim.id])
    survivor_identity = build.identity()
    build.session.commit()

    with factory() as session:
        with pytest.raises(IdentityManagerError, match="not PENDING"):
            assign_representation_to_identity(
                session, victim.id, survivor_identity.id, new_id=build.new_id,
                clock=build.clock, evidence_kind=EvidenceKind.IDENTITY_MATCHED,
            )  # fmt: skip
        session.rollback()
        with pytest.raises(IdentityManagerError, match="not ACTIVE"):
            split_identity(
                session, victim_identity.id, [victim.id], new_id=build.new_id, clock=build.clock
            )
        session.rollback()
        merge_identities(
            session, victim_identity.id, survivor_identity.id,
            expected_revision=victim_identity.revision, new_id=build.new_id, clock=build.clock,
        )  # fmt: skip
        session.commit()

    assert row(factory, victim.id)[0] == "ERASING"  # a merge leaves it alone
    assert row(factory, keeper.id)[0] == "ACTIVE"
    report = eraser.resume()
    assert report.complete, report.outstanding_cleanup
    assert_gone(factory, sqlite_engine, coordinator, space, victim)
    with factory() as session:
        count = session.scalar(select(func.count()).select_from(Representation))
    assert count == 2


# --- the guards of the use case itself ----------------------------------------------------------


def test_the_clearing_update_is_guarded_by_the_state_it_expects(
    eraser: RepresentationEraser, coordinator: IndexCoordinator, factory: sessionmaker[Session],
    sqlite_engine: Engine, space: RepresentationSpace, build: ModelFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    """Between reading what is ready and clearing it, something else finishes the erasure: the
    transition is `UPDATE ... WHERE state = 'ERASING'`, so nothing is cleared or counted twice."""
    (victim,) = indexed(build, coordinator, space, 1)
    stamp = build.clock()
    real = representation_index.retire_quarantine

    def finished_by_someone_else(directory: Path) -> list[Path]:
        with factory() as session:
            session.execute(
                Representation.__table__.update()  # type: ignore[attr-defined]
                .where(Representation.id == victim.id)
                .values(state="ERASED", vector=None, ann_key=None, erased_at=stamp)
            )
            session.commit()
        return real(directory)

    monkeypatch.setattr(erasure, "retire_quarantine", finished_by_someone_else)
    build.clock.advance(minutes=1)

    report = eraser.erase([victim.id])

    assert row(factory, victim.id)[3] == stamp  # not overwritten by a second clearing
    assert report.unverified == []
    assert marker(factory) is None  # nothing was cleared by this call, so nothing is owed


def test_nothing_is_truncated_when_nothing_is_owed(
    eraser: RepresentationEraser, sqlite_engine: Engine, space: RepresentationSpace
) -> None:
    """A reader that blocks the checkpoint must not make an idle recovery report cleanup owed."""
    with sqlite_engine.connect() as reader:
        reader.exec_driver_sql("SELECT count(*) FROM representations").all()

        report = eraser.resume()

        assert report.wal_truncated is True
        assert report.complete


def test_verification_reports_a_cleared_representation_that_still_holds_a_vector(
    eraser: RepresentationEraser, coordinator: IndexCoordinator, space: RepresentationSpace,
    build: ModelFactory, monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    (liar,) = indexed(build, coordinator, space, 1)
    (victim,) = indexed(build, coordinator, space, 2)
    real = RepresentationEraser._finalize_space

    def claims_to_have_cleared_it(
        self: RepresentationEraser, space_id: uuid.UUID
    ) -> tuple[list[uuid.UUID], str | None]:
        cleared, reason = real(self, space_id)
        return [*cleared, liar.id], reason  # still ACTIVE, still holding its vector

    monkeypatch.setattr(RepresentationEraser, "_finalize_space", claims_to_have_cleared_it)

    report = eraser.erase([victim.id])

    assert report.unverified == [liar.id]
    assert not report.complete


def test_one_space_failing_unexpectedly_does_not_stop_the_others(
    eraser: RepresentationEraser, coordinator: IndexCoordinator, factory: sessionmaker[Session],
    sqlite_engine: Engine, space: RepresentationSpace, build: ModelFactory, db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    other = build.representation_space(dimension=NDIM)
    db_session.commit()
    (broken,) = indexed(build, coordinator, space, 1)
    (fine,) = indexed(build, coordinator, other, 11)
    real = representation_index.superseded_files

    def fails_for_one_space(directory: Path) -> list[Path]:
        if directory == coordinator.index_directory(space.id):
            raise RuntimeError("disk on fire")
        return real(directory)

    monkeypatch.setattr(erasure, "superseded_files", fails_for_one_space)

    report = eraser.erase([broken.id, fine.id])

    assert report.blocked == {space.id: "RuntimeError: disk on fire"}
    assert report.erased == [fine.id]
    assert report.pending == [broken.id]
    assert not report.complete
    monkeypatch.undo()
    assert eraser.resume().complete


def test_finalization_holds_the_coordinators_lock(
    eraser: RepresentationEraser, coordinator: IndexCoordinator, space: RepresentationSpace,
    build: ModelFactory, monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    """No pass may quarantine a copy of the vector between the check that none remains and the
    commit that clears it."""
    (victim,) = indexed(build, coordinator, space, 1)
    held: list[bool] = []
    real = representation_index.retire_quarantine

    def records_the_lock(directory: Path) -> list[Path]:
        held.append(coordinator._lock.locked())
        return real(directory)

    monkeypatch.setattr(erasure, "retire_quarantine", records_the_lock)

    assert eraser.erase([victim.id]).complete
    assert held == [True]


# --- findings of the independent review of PR 58 -------------------------------------------------


def test_an_ordinary_remove_in_flight_when_the_erasure_is_queued_does_not_leave_the_vector(
    eraser: RepresentationEraser, coordinator: IndexCoordinator, factory: sessionmaker[Session],
    sqlite_engine: Engine, space: RepresentationSpace, build: ModelFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    """The in-place removal of an ordinary REMOVE leaves the vector's bytes in the live file; the
    erasure committing before that REMOVE settles must not take it for its own."""
    victim, _ = indexed(build, coordinator, space, 1, 2)
    build.index_operation(victim, operation="REMOVE")
    build.session.commit()
    real = IndexCoordinator._apply_one
    fired: list[int] = []

    def erasure_commits_after_the_removal(self: IndexCoordinator, *args: Any) -> Any:
        result = real(self, *args)
        if not fired:
            fired.append(1)
            eraser.queue([victim.id])  # after the in-place removal, before it is settled
        return result

    monkeypatch.setattr(IndexCoordinator, "_apply_one", erasure_commits_after_the_removal)
    coordinator.apply_pending(limit=10)
    monkeypatch.undo()
    assert index_files_with(coordinator, space, 1)  # the live file still holds the bytes

    report = eraser.resume()

    assert report.complete, report.outstanding_cleanup
    assert_gone(factory, sqlite_engine, coordinator, space, victim)


def test_a_keyed_superseded_representation_whose_earlier_remove_was_applied_is_still_purged(
    eraser: RepresentationEraser, coordinator: IndexCoordinator, factory: sessionmaker[Session],
    sqlite_engine: Engine, space: RepresentationSpace, build: ModelFactory,
) -> None:  # fmt: skip
    victim, _ = indexed(build, coordinator, space, 1, 2)
    victim.state = "SUPERSEDED"
    build.index_operation(victim, operation="REMOVE")
    build.session.commit()
    coordinator.apply_pending(limit=10)  # applied in place: the bytes stay in the live file
    assert index_files_with(coordinator, space, 1)

    report = eraser.erase([victim.id])

    assert report.complete, report.outstanding_cleanup
    assert_gone(factory, sqlite_engine, coordinator, space, victim)


def test_a_failed_remove_is_given_a_fresh_set_of_attempts_by_the_next_erase(
    eraser: RepresentationEraser, coordinator: IndexCoordinator, factory: sessionmaker[Session],
    sqlite_engine: Engine, space: RepresentationSpace, build: ModelFactory,
) -> None:  # fmt: skip
    (victim,) = indexed(build, coordinator, space, 1)
    eraser.queue([victim.id])
    with factory() as session:
        session.execute(
            IndexOperation.__table__.update()  # type: ignore[attr-defined]
            .where(IndexOperation.representation_id == victim.id)
            .values(state="FAILED", attempt_count=3)
        )
        session.commit()

    report = eraser.erase([victim.id])

    assert report.complete, report.outstanding_cleanup
    assert_gone(factory, sqlite_engine, coordinator, space, victim)


def test_another_erasers_owed_truncation_is_not_hidden_by_a_complete_report(
    eraser: RepresentationEraser, coordinator: IndexCoordinator, factory: sessionmaker[Session],
    sqlite_engine: Engine, space: RepresentationSpace, build: ModelFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    """A's erasure of X waits (its REMOVE is not due: no error, nothing blocked). B then finishes X
    after A looked at the marker, and B's checkpoint is blocked by a reader. A must not report X
    erased and the erasure complete while B's truncation is owed."""
    (victim,) = indexed(build, coordinator, space, 1)
    eraser.queue([victim.id])
    later = build.clock() + timedelta(hours=1)
    with factory() as session:
        session.execute(
            IndexOperation.__table__.update()  # type: ignore[attr-defined]
            .where(IndexOperation.representation_id == victim.id)
            .values(not_before_at=later)
        )
        session.commit()
    other = make_eraser(factory, sqlite_engine, coordinator, build)
    real = RepresentationEraser._verify
    finished: list[ErasureReport] = []
    started: list[int] = []

    def second_eraser_finishes_meanwhile(
        self: RepresentationEraser, *args: Any, **kwargs: Any
    ) -> Any:
        if not started:
            started.append(1)  # (`other.resume()` calls this too)
            build.clock.advance(hours=2)  # the REMOVE is due now
            finished.append(other.resume())
        return real(self, *args, **kwargs)

    monkeypatch.setattr(RepresentationEraser, "_verify", second_eraser_finishes_meanwhile)

    with sqlite_engine.connect() as reader:
        reader.exec_driver_sql("SELECT count(*) FROM representations").all()
        report = eraser.erase([victim.id])
        monkeypatch.undo()

        assert finished[0].erased == [victim.id]  # B finished X ...
        assert not finished[0].wal_truncated  # ... but its truncation is owed
        assert report.complete is False  # so A cannot call the erasure complete
        assert marker(factory) is not None
        reader.rollback()

    assert eraser.resume().complete
    assert marker(factory) is None


def test_startup_recovery_reports_an_unexpected_failure_instead_of_aborting(
    eraser: RepresentationEraser, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(self: RepresentationEraser, ids: Any) -> None:
        raise RuntimeError("database is locked")

    monkeypatch.setattr(RepresentationEraser, "queue", broken)

    report = eraser.resume()

    assert report.errors == ["RuntimeError: database is locked"]
    assert not report.complete


def test_an_unrelated_operation_backing_off_does_not_make_an_erasure_incomplete(
    eraser: RepresentationEraser, coordinator: IndexCoordinator, factory: sessionmaker[Session],
    sqlite_engine: Engine, space: RepresentationSpace, build: ModelFactory,
) -> None:  # fmt: skip
    (victim,) = indexed(build, coordinator, space, 1)
    corrupt = build.representation(
        representation_space_id=space.id, state="ACTIVE", identity_id=build.identity().id,
        ann_key=9, vector=float32_vector([1.0, 2.0, 3.0]), vector_dimension=3,
    )  # fmt: skip
    build.index_operation(corrupt, operation="ADD")  # fails every attempt, unrelated to the erasure
    build.session.commit()

    report = eraser.erase([victim.id])

    assert report.errors == []
    assert report.complete, report.outstanding_cleanup
    assert_gone(factory, sqlite_engine, coordinator, space, victim)


# --- findings of the re-review ------------------------------------------------------------------


def test_every_clearing_commit_sets_a_marker_value_of_its_own(
    eraser: RepresentationEraser, coordinator: IndexCoordinator, space: RepresentationSpace,
    build: ModelFactory, db_session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    """Two spaces finalized by one call: a checkpoint that ran between the two commits must not be
    able to clear the marker the second sets, which a shared value would allow."""
    other = build.representation_space(dimension=NDIM)
    db_session.commit()
    (first,) = indexed(build, coordinator, space, 1)
    (second,) = indexed(build, coordinator, other, 11)
    values: list[str] = []
    real = AppStateRepository.set

    def spy(self: AppStateRepository, key: str, value: str, **kwargs: Any) -> None:
        values.append(value)
        real(self, key, value, **kwargs)

    monkeypatch.setattr(AppStateRepository, "set", spy)

    assert eraser.erase([first.id, second.id]).complete

    assert len(values) == 2
    assert len(set(values)) == 2


def test_a_failed_remove_from_before_the_erasure_does_not_hold_it_up(
    eraser: RepresentationEraser, coordinator: IndexCoordinator, factory: sessionmaker[Session],
    sqlite_engine: Engine, space: RepresentationSpace, build: ModelFactory,
) -> None:  # fmt: skip
    (victim,) = indexed(build, coordinator, space, 1)
    build.index_operation(victim, operation="REMOVE", state="FAILED", attempt_count=3)
    build.session.commit()

    report = eraser.erase([victim.id])  # one call is enough

    assert report.complete, report.outstanding_cleanup
    assert_gone(factory, sqlite_engine, coordinator, space, victim)


def test_queueing_a_bulk_binds_only_one_chunk_of_ids_per_statement(
    eraser: RepresentationEraser, coordinator: IndexCoordinator, factory: sessionmaker[Session],
    sqlite_engine: Engine, space: RepresentationSpace, build: ModelFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    monkeypatch.setattr(erasure, "CHUNK", 2)
    victims = indexed(build, coordinator, space, 1, 2, 3, 4, 5)
    bound: list[int] = []

    @event.listens_for(sqlite_engine, "before_cursor_execute")
    def record(conn: Any, cursor: Any, statement: str, parameters: Any, *rest: Any) -> None:
        if statement.startswith("DELETE FROM index_operations"):
            bound.append(len(parameters))

    try:
        eraser.queue([v.id for v in victims])
    finally:
        event.remove(sqlite_engine, "before_cursor_execute", record)

    assert bound
    assert max(bound) <= 2 + 3  # a chunk of ids, the operation and the two states
