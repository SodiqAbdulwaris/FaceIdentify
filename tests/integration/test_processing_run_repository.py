"""ProcessingRun and snapshot repositories against real SQLite (M2: TST-022; persistence §12, §13,
§26).

Proved here: nothing is committed on the caller's behalf; `lock` really takes SQLite's one write
lock before it reads; the transient list is exactly the states recovery inspects; and a snapshot's
fingerprint is a stable SHA-256 of its canonical settings, never shared between runs.
"""

import hashlib
import json
import sqlite3
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, select, text, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.processing.models import (
    TRANSIENT_RUN_STATES,
    ProcessingConfigurationSnapshot,
    ProcessingRun,
    ProcessingRunState,
)
from backend.app.processing.run_repository import (
    ProcessingRunRepository,
    SnapshotRepository,
    canonical_json_bytes,
)
from backend.infrastructure.db.engine import create_session_factory
from tests.factories.models import ModelFactory


@pytest.fixture
def factory(sqlite_engine: Engine) -> sessionmaker[Session]:
    return create_session_factory(sqlite_engine)


# --- runs: add and get ------------------------------------------------------------------------


def test_add_flushes_but_does_not_commit(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    source = build.source()
    snapshot = build.snapshot()
    build.session.commit()
    run = ProcessingRun(
        id=build.new_id(), source_id=source.id, configuration_snapshot_id=snapshot.id,
        state="PENDING", requested_at=build.clock(), created_at=build.clock(),
        updated_at=build.clock(),
    )  # fmt: skip

    with factory() as session:
        ProcessingRunRepository(session).add(run)
        with factory() as other:  # not visible to another connection until the caller commits
            assert other.get(ProcessingRun, run.id) is None
        session.rollback()

    with factory() as session:
        assert session.get(ProcessingRun, run.id) is None


def test_add_checks_constraints_and_foreign_keys_at_once(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    source = build.source()
    snapshot = build.snapshot()
    build.session.commit()

    def run(**overrides: object) -> ProcessingRun:
        fields: dict[str, object] = dict(
            id=build.new_id(), source_id=source.id, configuration_snapshot_id=snapshot.id,
            state="PENDING", requested_at=build.clock(), created_at=build.clock(),
            updated_at=build.clock(),
        )  # fmt: skip
        return ProcessingRun(**(fields | overrides))

    with factory() as session:
        repository = ProcessingRunRepository(session)
        with pytest.raises(IntegrityError):
            repository.add(run(state="NOT_A_STATE"))
        session.rollback()
        with pytest.raises(IntegrityError):
            repository.add(run(configuration_snapshot_id=build.new_id()))  # no such snapshot


def test_get_returns_the_database_row_not_a_cached_one_in_a_new_transaction(
    sqlite_engine: Engine, factory: sessionmaker[Session], build: ModelFactory
) -> None:
    run = build.run(state="RUNNING")
    build.session.commit()
    with Session(sqlite_engine, expire_on_commit=False) as session:  # keeps what it has loaded
        repository = ProcessingRunRepository(session)
        held = repository.get(run.id)  # held, so the identity map keeps it
        assert held is not None
        assert held.state == "RUNNING"
        session.commit()
        with factory() as other:
            row = other.get(ProcessingRun, run.id)
            assert row is not None
            row.state = "PAUSED"
            other.commit()

        refreshed = repository.get(run.id)

        assert refreshed is not None
        assert refreshed.state == "PAUSED"
        assert repository.get(build.new_id()) is None


# --- lock -------------------------------------------------------------------------------------


def writers_are_refused(path: str) -> bool:
    """Whether another connection cannot start a write right now (it waits no time at all)."""
    connection = sqlite3.connect(path, timeout=0)
    try:
        connection.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError as error:
        return "locked" in str(error)
    else:
        connection.rollback()
        return False
    finally:
        connection.close()


def test_lock_takes_the_write_lock_and_returns_the_run_fresh(
    sqlite_engine: Engine, factory: sessionmaker[Session], build: ModelFactory
) -> None:
    run = build.run(state="RUNNING")
    build.session.commit()
    path = sqlite_engine.url.database
    assert path is not None
    assert not writers_are_refused(path)  # nothing is locked yet

    with factory() as session:
        locked = ProcessingRunRepository(session).lock(run.id)

        assert locked is not None
        assert (locked.id, locked.state, locked.revision) == (run.id, "RUNNING", 1)
        assert writers_are_refused(path)  # the lock is held until the caller ends the transaction
        session.rollback()

    assert not writers_are_refused(path)


def test_lock_changes_nothing(factory: sessionmaker[Session], build: ModelFactory) -> None:
    run = build.run(state="RUNNING")
    build.session.commit()

    with factory() as session:
        ProcessingRunRepository(session).lock(run.id)
        session.commit()

    with factory() as session:
        row = ProcessingRunRepository(session).get(run.id)
        assert row is not None
        assert (row.state, row.revision, row.updated_at) == ("RUNNING", 1, run.updated_at)


def test_lock_of_a_missing_run_still_takes_the_lock_and_returns_none(
    sqlite_engine: Engine, factory: sessionmaker[Session], build: ModelFactory
) -> None:
    build.session.commit()
    path = sqlite_engine.url.database
    assert path is not None

    with factory() as session:
        assert ProcessingRunRepository(session).lock(build.new_id()) is None
        assert writers_are_refused(path)
        session.rollback()


def test_another_writer_cannot_get_in_while_a_run_is_locked_and_can_afterwards(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    """The second writer is a `lock` of its own, told not to wait (`busy_timeout = 0`): while the
    first holds the write lock it is refused, and once the first ends it gets the committed row."""
    run = build.run(state="RUNNING")
    build.session.commit()

    with factory() as first, factory() as second:
        assert ProcessingRunRepository(first).lock(run.id) is not None
        first.execute(
            update(ProcessingRun).where(ProcessingRun.id == run.id).values(state="PAUSED")
        )
        second.execute(text("PRAGMA busy_timeout = 0"))
        with pytest.raises(OperationalError, match="locked"):
            ProcessingRunRepository(second).lock(run.id)
        second.rollback()

        first.commit()

        locked = ProcessingRunRepository(second).lock(run.id)
        assert locked is not None
        assert locked.state == "PAUSED"  # the committed row, not the one before it
        second.rollback()


def test_a_transaction_that_read_first_fails_on_a_stale_snapshot_which_locking_first_avoids(
    sqlite_engine: Engine, factory: sessionmaker[Session], build: ModelFactory
) -> None:
    """The failure that locking first avoids (open question 20): a transaction that read first and
    then writes fails at once when another writer commits in between. (A transaction that started
    with the lock could not be overtaken: see the test above.)"""
    run = build.run(state="RUNNING")
    build.session.commit()

    with factory() as session:
        locked = ProcessingRunRepository(session).lock(run.id)  # lock, then read
        assert locked is not None
        session.commit()

    with factory() as reader:
        reader.get(ProcessingRun, run.id)  # a read first: the transaction now holds a snapshot
        with factory() as other:
            other.execute(
                update(ProcessingRun).where(ProcessingRun.id == run.id).values(state="PAUSED")
            )
            other.commit()

        with pytest.raises(OperationalError):  # BUSY_SNAPSHOT: the read-then-write failure mode
            reader.execute(
                update(ProcessingRun).where(ProcessingRun.id == run.id).values(state="CANCELLED")
            )


# --- the transient list -----------------------------------------------------------------------


@pytest.mark.parametrize("state", [s.value for s in ProcessingRunState])
def test_a_run_is_listed_as_transient_exactly_when_recovery_must_inspect_it(
    factory: sessionmaker[Session], build: ModelFactory, state: str
) -> None:
    run = build.run(state=state)
    build.session.commit()

    with factory() as session:
        listed = [r.id for r in ProcessingRunRepository(session).list_transient()]

    assert (run.id in listed) == (state in TRANSIENT_RUN_STATES)


def test_the_transient_list_shows_database_rows_not_cached_ones_in_a_new_transaction(
    sqlite_engine: Engine, factory: sessionmaker[Session], build: ModelFactory
) -> None:
    run = build.run(state="RUNNING")
    build.session.commit()
    with Session(sqlite_engine, expire_on_commit=False) as session:  # keeps what it has loaded
        repository = ProcessingRunRepository(session)
        held = repository.get(run.id)  # held, so the identity map keeps it
        assert held is not None
        assert held.state == "RUNNING"
        session.commit()
        with factory() as other:
            row = other.get(ProcessingRun, run.id)
            assert row is not None
            row.state = "INTERRUPTED"  # still transient, so still listed
            other.commit()

        (listed,) = repository.list_transient()

        assert listed.state == "INTERRUPTED"


def test_transient_runs_are_listed_least_recently_updated_first(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    t0 = build.clock()
    newest = build.run(state="RUNNING", updated_at=t0 + timedelta(minutes=2))
    oldest = build.run(state="PAUSED", updated_at=t0)
    middle = build.run(state="INTERRUPTED", updated_at=t0 + timedelta(minutes=1))
    build.run(state="COMPLETED", updated_at=t0 - timedelta(hours=1))  # over: not listed
    build.session.commit()

    with factory() as session:
        listed = ProcessingRunRepository(session).list_transient()

    assert [run.id for run in listed] == [oldest.id, middle.id, newest.id]


# --- snapshots --------------------------------------------------------------------------------


def create(
    session: Session, build: ModelFactory, settings: dict[str, Any], **kw: Any
) -> ProcessingConfigurationSnapshot:
    return SnapshotRepository(session).create(
        snapshot_id=build.new_id(), schema_version=kw.pop("schema_version", 1),
        canonical_json=settings, now=build.clock(), **kw,
    )  # fmt: skip


def test_a_snapshot_records_the_settings_and_a_sha256_of_their_canonical_form(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    settings = {"detector": "yolo", "crop": {"margin": 0.2, "min_px": 64}, "name": "café"}
    build.session.commit()

    with factory() as session:
        snapshot = create(
            session, build, settings, schema_version=3, created_by_user_action="PROCESS_SOURCE"
        )
        session.commit()

    with factory() as session:
        row = SnapshotRepository(session).get(snapshot.id)
        assert row is not None
        assert row.canonical_json == settings
        assert row.schema_version == 3
        assert row.created_by_user_action == "PROCESS_SOURCE"
        assert row.created_at == build.clock()
        expected = json.dumps(
            settings, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        assert row.fingerprint_sha256 == hashlib.sha256(expected).digest()
        assert len(row.fingerprint_sha256) == 32


def test_the_fingerprint_does_not_depend_on_key_order_but_does_on_content() -> None:
    a = canonical_json_bytes({"x": 1, "y": {"b": 2, "a": 1}})
    b = canonical_json_bytes({"y": {"a": 1, "b": 2}, "x": 1})
    c = canonical_json_bytes({"x": 1, "y": {"a": 1, "b": 3}})

    assert a == b
    assert a != c
    assert canonical_json_bytes({"s": "é"}) == '{"s":"é"}'.encode()  # kept as UTF-8, not é


def test_runs_with_identical_settings_each_keep_their_own_snapshot(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    """§13 chooses one snapshot per run for unambiguous provenance: the fingerprint is not unique,
    so identical settings do not collide. (The database does not stop two runs from *sharing* one
    snapshot; that rests on the use cases, GitHub issue 51.)"""
    source = build.source()
    build.session.commit()

    with factory() as session:
        snapshots = [create(session, build, {"detector": "yolo"}) for _ in range(2)]
        runs = [
            ProcessingRunRepository(session).add(
                ProcessingRun(
                    id=build.new_id(),
                    source_id=source.id,
                    configuration_snapshot_id=snap.id,
                    state="PENDING",
                    requested_at=build.clock(),
                    created_at=build.clock(),
                    updated_at=build.clock(),
                )  # fmt: skip
            )
            for snap in snapshots
        ]
        session.commit()

    assert snapshots[0].id != snapshots[1].id
    assert snapshots[0].fingerprint_sha256 == snapshots[1].fingerprint_sha256
    assert [run.configuration_snapshot_id for run in runs] == [snap.id for snap in snapshots]


@pytest.mark.parametrize(
    "settings",
    [
        {"x": float("nan")},
        {"x": float("inf")},
        {"x": {"y": [1, float("-inf")]}},
        {1: "an integer key"},
        {"x": {2: "nested integer key"}},
        {"x": {1, 2}},
        {"x": (1, 2)},
        {"x": b"bytes"},
        {"x": object()},
    ],
    ids=[
        "nan",
        "inf",
        "nested-inf",
        "int-key",
        "nested-int-key",
        "set",
        "tuple",
        "bytes",
        "object",
    ],
)
def test_settings_json_cannot_represent_exactly_are_refused_before_anything_is_staged(
    factory: sessionmaker[Session], build: ModelFactory, settings: dict[Any, Any]
) -> None:
    build.session.commit()

    with factory() as session, pytest.raises(ValueError, match=r"\$"):
        create(session, build, settings)

    with factory() as session:
        assert session.scalars(select(ProcessingConfigurationSnapshot.id)).all() == []


def test_valid_json_of_every_kind_is_accepted(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    settings = {
        "s": "é",
        "i": 2**70,
        "f": 0.1,
        "t": True,
        "n": None,
        "l": [1, "a", [None]],
        "d": {"k": {}},
    }
    build.session.commit()

    with factory() as session:
        snapshot = create(session, build, settings)
        session.commit()

    with factory() as session:
        row = SnapshotRepository(session).get(snapshot.id)
        assert row is not None
        assert row.canonical_json == settings


def test_creating_a_snapshot_flushes_so_the_database_has_it_at_once(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    build.session.commit()

    with factory() as session:
        snapshot = create(session, build, {"detector": "yolo"})
        # a raw read in the same transaction, which the session would not flush for us
        found = session.execute(
            select(ProcessingConfigurationSnapshot.id).where(
                ProcessingConfigurationSnapshot.id == snapshot.id
            )
        ).scalar_one_or_none()
        assert found == snapshot.id


def test_creating_a_snapshot_does_not_commit_and_a_missing_one_is_none(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    build.session.commit()

    with factory() as session:
        snapshot = create(session, build, {"detector": "yolo"})
        with factory() as other:
            assert other.get(ProcessingConfigurationSnapshot, snapshot.id) is None
        session.rollback()

    with factory() as session:
        assert SnapshotRepository(session).get(snapshot.id) is None
