"""Segment and checkpoint repositories against real SQLite (M2: TST-022; persistence §14, §16, §26).

The repositories lean on what the schema enforces (unique ordinals, one running segment, one valid
final checkpoint) and allocate ordinals inside the INSERT. These prove it with separate sessions and
threads: ordinals never collide, the constraints refuse the second writer, and nothing is committed
on the caller's behalf.
"""

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlalchemy import Engine, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.processing.models import ExecutionSegment, ProcessingCheckpoint
from backend.app.processing.repository import CheckpointRepository, SegmentRepository
from backend.infrastructure.db.engine import create_session_factory
from tests.factories.models import ModelFactory


@pytest.fixture
def factory(sqlite_engine: Engine) -> sessionmaker[Session]:
    return create_session_factory(sqlite_engine)


def start_segment(
    repository: SegmentRepository, build: ModelFactory, run_id: uuid.UUID
) -> ExecutionSegment:
    return repository.append(
        run_id, segment_id=build.new_id(), runtime_variant_id=None,
        runtime_details={"provider": "cpu"}, now=build.clock(),
    )  # fmt: skip


def write_checkpoint(
    repository: CheckpointRepository,
    build: ModelFactory,
    run_id: uuid.UUID,
    kind: str = "INTERMEDIATE",
) -> ProcessingCheckpoint:
    return repository.append(
        run_id, checkpoint_id=build.new_id(), segment_id=None, kind=kind,
        payload_schema_version=1, payload={"frames": 10}, now=build.clock(),
    )  # fmt: skip


# --- segments ---------------------------------------------------------------------------------


def test_segments_get_the_next_ordinal_one_running_at_a_time(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    run = build.run()
    other = build.run()
    build.session.commit()

    with factory() as session:
        repository = SegmentRepository(session)
        first = start_segment(repository, build, run.id)
        assert repository.close(first.id, "COMPLETED", reason="FALLBACK", now=build.clock())
        second = start_segment(repository, build, run.id)
        elsewhere = start_segment(repository, build, other.id)
        session.commit()

    assert (first.ordinal, second.ordinal, elsewhere.ordinal) == (0, 1, 0)
    with factory() as session:  # `close` updates in the database, not the object held
        states = [row.state for row in SegmentRepository(session).list_for_run(run.id)]
    assert states == ["COMPLETED", "RUNNING"]
    assert first.runtime_details_json == {"provider": "cpu"}


def test_a_second_running_segment_is_refused_and_leaves_nothing_behind(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    run = build.run()
    build.session.commit()
    with factory() as session:
        start_segment(SegmentRepository(session), build, run.id)
        session.commit()

    with factory() as session:
        with pytest.raises(IntegrityError):
            start_segment(SegmentRepository(session), build, run.id)
        session.rollback()

    with factory() as session:
        assert len(SegmentRepository(session).list_for_run(run.id)) == 1


def test_append_does_not_commit(factory: sessionmaker[Session], build: ModelFactory) -> None:
    run = build.run()
    build.session.commit()

    with factory() as session:
        segment = start_segment(SegmentRepository(session), build, run.id)
        with factory() as other:
            assert other.get(ExecutionSegment, segment.id) is None
        session.rollback()

    with factory() as session:
        assert SegmentRepository(session).list_for_run(run.id) == []


def test_closing_records_the_end_and_a_closed_segment_is_never_reopened_or_changed(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    run = build.run()
    build.session.commit()
    later = build.clock() + timedelta(minutes=1)

    with factory() as session:
        repository = SegmentRepository(session)
        segment = start_segment(repository, build, run.id)
        assert repository.close(segment.id, "INTERRUPTED", reason="WORKER_CRASH", now=later)
        assert not repository.close(segment.id, "COMPLETED", reason="NORMAL", now=build.clock())
        assert not repository.close(build.new_id(), "COMPLETED", reason=None, now=build.clock())
        session.commit()

    with factory() as session:
        row = SegmentRepository(session).get(segment.id)
        assert row is not None
        assert (row.state, row.ended_reason, row.ended_at) == ("INTERRUPTED", "WORKER_CRASH", later)


@pytest.mark.parametrize("state", ["RUNNING", "PAUSED", ""])
def test_only_a_closing_state_closes_a_segment(
    factory: sessionmaker[Session], build: ModelFactory, state: str
) -> None:
    run = build.run()
    build.session.commit()
    with factory() as session:
        repository = SegmentRepository(session)
        segment = start_segment(repository, build, run.id)
        with pytest.raises(ValueError, match="does not close"):
            repository.close(segment.id, state, reason=None, now=build.clock())


def test_list_for_run_is_in_order_and_only_that_runs(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    run = build.run()
    other = build.run()
    build.session.commit()
    with factory() as session:
        repository = SegmentRepository(session)
        ids = []
        for _ in range(3):
            segment = start_segment(repository, build, run.id)
            repository.close(segment.id, "COMPLETED", reason="NORMAL", now=build.clock())
            ids.append(segment.id)
        start_segment(repository, build, other.id)
        session.commit()

    with factory() as session:
        listed = SegmentRepository(session).list_for_run(run.id)

    assert [s.id for s in listed] == ids
    assert [s.ordinal for s in listed] == [0, 1, 2]


def test_two_writers_starting_a_segment_at_once_get_one_segment_and_one_refusal(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    run = build.run()
    build.session.commit()
    now = build.clock()

    def attempt(segment_id: uuid.UUID) -> bool:
        with factory() as session:
            try:
                SegmentRepository(session).append(
                    run.id, segment_id=segment_id, runtime_variant_id=None,
                    runtime_details={}, now=now,
                )  # fmt: skip
                session.commit()
            except IntegrityError:
                session.rollback()
                return False
            return True

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, [build.new_id(), build.new_id()]))

    assert sorted(outcomes) == [False, True]
    with factory() as session:
        assert [s.ordinal for s in SegmentRepository(session).list_for_run(run.id)] == [0]


# --- checkpoints ------------------------------------------------------------------------------


def test_checkpoints_get_monotonic_ordinals_and_start_valid(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    run = build.run()
    other = build.run()
    build.session.commit()

    with factory() as session:
        repository = CheckpointRepository(session)
        first = write_checkpoint(repository, build, run.id)
        second = write_checkpoint(repository, build, run.id)
        elsewhere = write_checkpoint(repository, build, other.id)
        session.commit()

    assert (first.ordinal, second.ordinal, elsewhere.ordinal) == (0, 1, 0)
    assert (first.kind, first.state, first.payload_json) == (
        "INTERMEDIATE",
        "VALID",
        {"frames": 10},
    )


def test_a_checkpoint_may_name_the_segment_that_wrote_it(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    run = build.run()
    segment = build.segment(run)
    build.session.commit()

    with factory() as session:
        checkpoint = CheckpointRepository(session).append(
            run.id, checkpoint_id=build.new_id(), segment_id=segment.id, kind="INTERMEDIATE",
            payload_schema_version=1, payload={}, now=build.clock(),
        )  # fmt: skip
        session.commit()

    assert checkpoint.execution_segment_id == segment.id


def test_concurrent_checkpoint_writers_never_share_an_ordinal(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    run = build.run()
    build.session.commit()
    now = build.clock()

    def write(_: int) -> None:
        with factory() as session:
            CheckpointRepository(session).append(
                run.id, checkpoint_id=uuid.uuid4(), segment_id=None, kind="INTERMEDIATE",
                payload_schema_version=1, payload={}, now=now,
            )  # fmt: skip
            session.commit()

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(write, range(16)))

    with factory() as session:
        ordinals = session.scalars(
            select(ProcessingCheckpoint.ordinal)
            .where(ProcessingCheckpoint.processing_run_id == run.id)
            .order_by(ProcessingCheckpoint.ordinal)
        ).all()
    assert list(ordinals) == list(range(16))  # none repeated, none skipped


def test_one_valid_final_checkpoint_per_run_until_it_is_invalidated(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    run = build.run()
    build.session.commit()
    with factory() as session:
        repository = CheckpointRepository(session)
        first = write_checkpoint(repository, build, run.id, "FINAL")
        session.commit()
        with pytest.raises(IntegrityError):
            write_checkpoint(repository, build, run.id, "FINAL")
        session.rollback()

        assert repository.invalidate(first.id, reason="payload unreadable", now=build.clock())
        replacement = write_checkpoint(repository, build, run.id, "FINAL")
        session.commit()

        final = repository.final_valid(run.id)
        assert final is not None
        assert final.id == replacement.id


def test_latest_valid_skips_invalidated_and_can_move_backward(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    run = build.run()
    build.session.commit()
    with factory() as session:
        repository = CheckpointRepository(session)
        cps = [write_checkpoint(repository, build, run.id) for _ in range(4)]
        repository.invalidate(cps[3].id, reason="bad", now=build.clock())
        session.commit()

        newest = repository.latest_valid(run.id)
        assert newest is not None
        assert newest.id == cps[2].id  # the invalidated newest one is passed over
        older = repository.latest_valid(run.id, before_ordinal=newest.ordinal)
        assert older is not None
        assert older.id == cps[1].id
        assert repository.latest_valid(run.id, before_ordinal=0) is None


def test_latest_valid_is_none_for_a_run_without_checkpoints(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    run = build.run()
    build.session.commit()
    with factory() as session:
        repository = CheckpointRepository(session)
        assert repository.latest_valid(run.id) is None
        assert repository.final_valid(run.id) is None


def test_final_valid_ignores_intermediate_and_invalidated_checkpoints(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    run = build.run()
    build.session.commit()
    with factory() as session:
        repository = CheckpointRepository(session)
        write_checkpoint(repository, build, run.id, "INTERMEDIATE")
        final = write_checkpoint(repository, build, run.id, "FINAL")
        assert repository.final_valid(run.id) is not None
        repository.invalidate(final.id, reason="bad", now=build.clock())

        assert repository.final_valid(run.id) is None


def test_invalidating_records_why_and_when_and_is_never_reversed(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    run = build.run()
    build.session.commit()
    later = build.clock() + timedelta(minutes=1)
    with factory() as session:
        repository = CheckpointRepository(session)
        checkpoint = write_checkpoint(repository, build, run.id)
        assert repository.invalidate(checkpoint.id, reason="schema too new", now=later)
        assert not repository.invalidate(checkpoint.id, reason="again", now=build.clock())
        assert not repository.invalidate(build.new_id(), reason="missing", now=build.clock())
        session.commit()

    with factory() as session:
        row = CheckpointRepository(session).get(checkpoint.id)
        assert row is not None
        assert (row.state, row.invalidated_at, row.invalidated_reason) == (
            "INVALIDATED", later, "schema too new",
        )  # fmt: skip


def test_get_returns_the_row_as_the_database_has_it_now(
    sqlite_engine: Engine, factory: sessionmaker[Session], build: ModelFactory
) -> None:
    run = build.run()
    build.session.commit()
    with factory() as setup:
        segment = start_segment(SegmentRepository(setup), build, run.id)
        checkpoint = write_checkpoint(CheckpointRepository(setup), build, run.id)
        setup.commit()

    with Session(sqlite_engine, expire_on_commit=False) as session:  # keeps what it has loaded
        segments, checkpoints = SegmentRepository(session), CheckpointRepository(session)
        held = (segments.get(segment.id), checkpoints.get(checkpoint.id))  # in the identity map
        assert [row.state for row in held if row is not None] == ["RUNNING", "VALID"]
        session.commit()
        with factory() as other:
            SegmentRepository(other).close(segment.id, "FAILED", reason=None, now=build.clock())
            CheckpointRepository(other).invalidate(checkpoint.id, reason="x", now=build.clock())
            other.commit()

        refreshed_segment = segments.get(segment.id)
        refreshed_checkpoint = checkpoints.get(checkpoint.id)

        assert refreshed_segment is not None
        assert refreshed_checkpoint is not None
        assert (refreshed_segment.state, refreshed_checkpoint.state) == ("FAILED", "INVALIDATED")


def test_list_for_run_orders_by_ordinal_not_by_insertion(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    run = build.run()
    build.session.commit()
    with factory() as session:
        repository = SegmentRepository(session)
        first = start_segment(repository, build, run.id)
        repository.close(first.id, "COMPLETED", reason=None, now=build.clock())
        second = start_segment(repository, build, run.id)
        repository.close(second.id, "COMPLETED", reason=None, now=build.clock())
        third = start_segment(repository, build, run.id)
        # The first row inserted now has the highest ordinal.
        session.execute(
            update(ExecutionSegment).where(ExecutionSegment.id == first.id).values(ordinal=10)
        )
        session.commit()

        listed = repository.list_for_run(run.id)

    assert [s.id for s in listed] == [second.id, third.id, first.id]
