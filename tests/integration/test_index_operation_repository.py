"""IndexOperationRepository contract against real SQLite (M2: TST-022; persistence §17, §26).

A use case appends operations in the same transaction as the change they follow (INDEX-01); the
coordinator reads what is due and records outcomes. Proved here: nothing is committed on the
caller's behalf, a duplicate pending operation is skipped rather than an error, and every state
change is decided by the database.
"""

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.memory.index_operation_repository import (
    DueOperation,
    IndexOperationRepository,
    NewOperation,
)
from backend.app.memory.models import IndexOperation, Representation
from backend.infrastructure.db.engine import create_session_factory
from tests.factories.models import ModelFactory
from tests.fixtures.concurrency import rendezvous_before_write


@pytest.fixture
def factory(sqlite_engine: Engine) -> sessionmaker[Session]:
    return create_session_factory(sqlite_engine)


def wanted(rep: Representation, kind: str = "ADD") -> NewOperation:
    return NewOperation(rep.id, rep.representation_space_id, kind)


def rows(factory: sessionmaker[Session]) -> list[IndexOperation]:
    with factory() as session:
        return list(
            session.scalars(
                select(IndexOperation).order_by(IndexOperation.created_at, IndexOperation.id)
            )
        )


# --- append_batch -----------------------------------------------------------------------------


def test_append_batch_records_pending_operations_due_now(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    first, second = build.representation(), build.representation()
    build.session.commit()
    now = build.clock()

    with factory() as session:
        ids = IndexOperationRepository(session).append_batch(
            [wanted(first), wanted(second, "REMOVE")], now=now, new_id=build.new_id
        )
        session.commit()

    stored = {row.id: row for row in rows(factory)}
    assert len(ids) == 2
    assert set(stored) == set(ids)
    by_rep = {row.representation_id: row for row in stored.values()}
    assert [stored[i].representation_id for i in ids] == [first.id, second.id]  # input order
    assert by_rep[first.id].representation_space_id == first.representation_space_id
    assert by_rep[first.id].operation == "ADD"
    assert by_rep[second.id].operation == "REMOVE"
    for row in stored.values():
        assert (row.state, row.attempt_count, row.not_before_at, row.created_at) == (
            "PENDING", 0, now, now,
        )  # fmt: skip
        assert row.last_attempt_at is None
        assert row.applied_at is None


def test_append_batch_of_nothing_records_nothing(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    with factory() as session:
        assert IndexOperationRepository(session).append_batch(
            [], now=build.clock(), new_id=build.new_id
        ) == []  # fmt: skip


def test_an_operation_already_pending_is_skipped_not_an_error(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    rep, other = build.representation(), build.representation()
    existing = build.index_operation(rep, operation="ADD")
    build.session.commit()

    with factory() as session:
        ids = IndexOperationRepository(session).append_batch(
            [wanted(rep, "ADD"), wanted(other, "ADD")], now=build.clock(), new_id=build.new_id
        )
        session.commit()

    assert len(ids) == 1  # only the one that was not already queued
    assert existing.id not in ids
    stored = {row.id: row for row in rows(factory)}
    assert len(stored) == 2
    assert stored[ids[0]].representation_id == other.id


def test_the_same_operation_twice_in_one_batch_is_recorded_once(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    rep = build.representation()
    build.session.commit()

    with factory() as session:
        ids = IndexOperationRepository(session).append_batch(
            [wanted(rep), wanted(rep)], now=build.clock(), new_id=build.new_id
        )
        session.commit()

    assert len(ids) == 1
    (row,) = rows(factory)
    assert row.id == ids[0]


def test_a_pending_operation_of_the_opposite_kind_is_superseded(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    rep = build.representation()
    build.index_operation(rep, operation="ADD")
    build.session.commit()

    with factory() as session:
        ids = IndexOperationRepository(session).append_batch(
            [wanted(rep, "REMOVE")], now=build.clock(), new_id=build.new_id
        )
        session.commit()

    (row,) = rows(factory)  # the obsolete ADD is gone; only the REMOVE is queued
    assert (row.id, row.operation, row.state) == (ids[0], "REMOVE", "PENDING")


def test_add_then_remove_then_add_leaves_the_representation_to_be_added(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    """The hazard that superseding prevents: REMOVE means absent whatever SQLite says, so a REMOVE
    left queued would run after, and undo, an ADD skipped as a duplicate of the first."""
    rep = build.representation()
    build.session.commit()

    with factory() as session:
        repository = IndexOperationRepository(session)
        for kind in ("ADD", "REMOVE", "ADD"):
            repository.append_batch([wanted(rep, kind)], now=build.clock(), new_id=build.new_id)
        session.commit()

    (row,) = rows(factory)
    assert (row.operation, row.state) == ("ADD", "PENDING")


def test_a_later_operation_in_one_batch_supersedes_an_earlier_one_for_the_same_representation(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    rep = build.representation()
    build.session.commit()

    with factory() as session:
        ids = IndexOperationRepository(session).append_batch(
            [wanted(rep, "ADD"), wanted(rep, "REMOVE")], now=build.clock(), new_id=build.new_id
        )
        session.commit()

    assert len(ids) == 2  # both were recorded, the first then removed
    (row,) = rows(factory)
    assert (row.id, row.operation) == (ids[1], "REMOVE")


def test_only_a_pending_opposite_operation_is_superseded(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    rep = build.representation()
    applied = build.index_operation(rep, operation="ADD", state="APPLIED", applied_at=build.clock())
    failed = build.index_operation(rep, operation="ADD", state="FAILED")
    other = build.representation()
    elsewhere = build.index_operation(other, operation="ADD")  # another representation's
    build.session.commit()

    with factory() as session:
        IndexOperationRepository(session).append_batch(
            [wanted(rep, "REMOVE")], now=build.clock(), new_id=build.new_id
        )
        session.commit()

    survivors = {row.id for row in rows(factory)}
    assert {applied.id, failed.id, elsewhere.id} <= survivors
    assert len(survivors) == 4


def test_an_unknown_kind_is_refused_before_anything_is_changed(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    rep = build.representation()
    build.index_operation(rep, operation="ADD")
    build.session.commit()

    with factory() as session, pytest.raises(ValueError, match="not an index operation"):
        IndexOperationRepository(session).append_batch(
            [wanted(rep, "REBUILD")], now=build.clock(), new_id=build.new_id
        )

    assert [row.operation for row in rows(factory)] == ["ADD"]


def test_two_writers_appending_the_same_operation_at_the_same_moment_record_it_once(
    sqlite_engine: Engine, factory: sessionmaker[Session], build: ModelFactory
) -> None:
    rep = build.representation()
    build.session.commit()
    now = build.clock()
    ids = [build.new_id(), build.new_id()]

    def append(index: int) -> list[uuid.UUID]:
        with factory() as session:
            recorded = IndexOperationRepository(session).append_batch(
                [wanted(rep)], now=now, new_id=lambda: ids[index]
            )
            session.commit()
            return recorded

    with (
        # Held at the first write (the DELETE): a held lock would stop the other writer arriving.
        rendezvous_before_write(sqlite_engine, "DELETE FROM index_operations", parties=2),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        results = list(pool.map(append, [0, 1]))

    assert sorted(len(recorded) for recorded in results) == [0, 1]
    (row,) = rows(factory)
    assert row.id in ids


def test_an_operation_may_be_queued_again_once_the_earlier_one_is_applied(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    rep = build.representation()
    build.index_operation(rep, operation="ADD", state="APPLIED", applied_at=build.clock())
    build.session.commit()

    with factory() as session:
        ids = IndexOperationRepository(session).append_batch(
            [wanted(rep)], now=build.clock(), new_id=build.new_id
        )
        session.commit()

    assert len(ids) == 1
    assert len(rows(factory)) == 2


def test_an_unknown_representation_is_refused_by_the_database(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    rep = build.representation()
    build.session.commit()

    with factory() as session, pytest.raises(IntegrityError):
        IndexOperationRepository(session).append_batch(
            [NewOperation(uuid.uuid4(), rep.representation_space_id, "ADD")],
            now=build.clock(), new_id=build.new_id,
        )  # fmt: skip


def test_append_batch_does_not_commit(factory: sessionmaker[Session], build: ModelFactory) -> None:
    rep = build.representation()
    build.session.commit()

    with factory() as session:
        IndexOperationRepository(session).append_batch(
            [wanted(rep)], now=build.clock(), new_id=build.new_id
        )
        assert rows(factory) == []  # not visible to another connection until the caller commits
        session.rollback()

    assert rows(factory) == []


# --- reading ----------------------------------------------------------------------------------


def test_due_returns_pending_operations_whose_time_has_come_in_order(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    now = build.clock()
    reps = [build.representation() for _ in range(5)]
    later = build.index_operation(reps[0], not_before_at=now - timedelta(minutes=1))
    earlier = build.index_operation(reps[1], not_before_at=now - timedelta(minutes=2))
    same_time_younger = build.index_operation(
        reps[2], not_before_at=now - timedelta(minutes=1), created_at=now + timedelta(seconds=1)
    )
    build.index_operation(reps[3], not_before_at=now + timedelta(minutes=1))  # not due yet
    build.index_operation(reps[4], state="FAILED")  # not pending
    build.session.commit()

    with factory() as session:
        repository = IndexOperationRepository(session)
        due = repository.due(now=now, limit=10)
        limited = repository.due(now=now, limit=2)

    assert [op.id for op in due] == [earlier.id, later.id, same_time_younger.id]
    assert [op.id for op in limited] == [earlier.id, later.id]
    assert due[0] == DueOperation(
        earlier.id, earlier.representation_id, earlier.representation_space_id, "ADD"
    )


def test_failed_ids_lists_only_failed_operations_newest_first(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    now = build.clock()
    old = build.index_operation(state="FAILED", created_at=now)
    new = build.index_operation(state="FAILED", created_at=now + timedelta(seconds=1))
    build.index_operation(state="PENDING")
    build.session.commit()

    with factory() as session:
        assert IndexOperationRepository(session).failed_ids() == [new.id, old.id]


def test_attempt_counts_reports_each_requested_operation(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    a = build.index_operation(attempt_count=2)
    b = build.index_operation(attempt_count=0)
    build.index_operation(attempt_count=9)  # not asked for
    build.session.commit()

    with factory() as session:
        counts = IndexOperationRepository(session).attempt_counts([a.id, b.id])

    assert counts == {a.id: 2, b.id: 0}


# --- requeue and settle -----------------------------------------------------------------------


def test_requeue_puts_a_failed_operation_back_with_a_fresh_count_and_keeps_its_failure(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    now = build.clock() + timedelta(hours=1)
    op = build.index_operation(
        state="FAILED", attempt_count=3, failure_code="APPLY_ERROR", failure_detail="disk full"
    )
    build.session.commit()

    with factory() as session:
        assert IndexOperationRepository(session).requeue(op.id, now=now)
        session.commit()

    (row,) = rows(factory)
    assert (row.state, row.attempt_count, row.not_before_at, row.updated_at) == (
        "PENDING", 0, now, now,
    )  # fmt: skip
    assert (row.failure_code, row.failure_detail) == ("APPLY_ERROR", "disk full")


def test_requeue_refuses_what_is_not_failed_or_would_duplicate_a_pending_one(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    rep = build.representation()
    pending = build.index_operation(state="PENDING")
    failed_duplicate = build.index_operation(rep, state="FAILED", operation="ADD")
    build.index_operation(rep, state="PENDING", operation="ADD")  # already says the same thing
    build.session.commit()

    with factory() as session:
        repository = IndexOperationRepository(session)
        assert not repository.requeue(pending.id, now=build.clock())
        assert not repository.requeue(failed_duplicate.id, now=build.clock())
        assert not repository.requeue(uuid.uuid4(), now=build.clock())


def test_requeue_leaves_an_applied_operation_alone(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    applied = build.index_operation(state="APPLIED", applied_at=build.clock(), attempt_count=1)
    build.session.commit()

    with factory() as session:
        assert not IndexOperationRepository(session).requeue(applied.id, now=build.clock())

    (row,) = rows(factory)
    assert (row.state, row.attempt_count) == ("APPLIED", 1)


def test_requeue_is_not_blocked_by_a_pending_operation_for_another_representation(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    failed = build.index_operation(build.representation(), state="FAILED", operation="ADD")
    build.index_operation(build.representation(), state="PENDING", operation="ADD")
    build.session.commit()

    with factory() as session:
        assert IndexOperationRepository(session).requeue(failed.id, now=build.clock())
        session.commit()


def test_requeue_is_not_blocked_by_a_pending_operation_of_the_opposite_kind(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    rep = build.representation()
    failed_add = build.index_operation(rep, state="FAILED", operation="ADD")
    build.index_operation(rep, state="PENDING", operation="REMOVE")
    build.session.commit()

    with factory() as session:
        assert IndexOperationRepository(session).requeue(failed_add.id, now=build.clock())
        session.commit()


def test_settle_records_the_outcome_only_while_the_operation_is_pending(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    now = build.clock() + timedelta(minutes=5)
    pending = build.index_operation()
    applied = build.index_operation(state="APPLIED", applied_at=build.clock())
    build.session.commit()

    with factory() as session:
        repository = IndexOperationRepository(session)
        done = repository.settle(
            pending.id, attempts=1, now=now,
            values={"state": "APPLIED", "applied_at": now, "failure_code": None},
        )  # fmt: skip
        again = repository.settle(
            applied.id, attempts=1, now=now, values={"state": "FAILED", "failure_code": "X"}
        )
        session.commit()

    assert (done, again) == (True, False)
    by_id = {row.id: row for row in rows(factory)}
    assert (by_id[pending.id].state, by_id[pending.id].attempt_count) == ("APPLIED", 1)
    assert (by_id[pending.id].last_attempt_at, by_id[pending.id].applied_at) == (now, now)
    assert (by_id[applied.id].state, by_id[applied.id].failure_code) == ("APPLIED", None)
