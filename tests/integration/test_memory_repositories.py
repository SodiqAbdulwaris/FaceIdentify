"""Observation and Representation repositories against real SQLite (M2: TST-022; persistence §6,
§22, §26).

Proved here: nothing is committed on the caller's behalf; pages are keyset-paginated so rows added
between two page requests cannot shift or repeat a page; representation reads are projections
without the vector; a key lookup is per space and sees every state; state changes are one guarded
`UPDATE` decided by the database (one winner under contention); erasure is refused as a plain state
change; and ANN keys are allocated one at a time per space, never twice.
"""

import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import fields
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.identities.use_cases import allocate_ann_key
from backend.app.memory import repository
from backend.app.memory.models import Observation, Representation
from backend.app.memory.repository import (
    ObservationRepository,
    RepresentationCursor,
    RepresentationRepository,
    RepresentationSummary,
)
from backend.infrastructure.db.engine import create_session_factory
from tests.factories.models import ModelFactory, float32_vector
from tests.fixtures.concurrency import rendezvous_before_write


@pytest.fixture
def factory(sqlite_engine: Engine) -> sessionmaker[Session]:
    return create_session_factory(sqlite_engine)


def new_observations(build: ModelFactory, count: int) -> tuple[uuid.UUID, list[Observation]]:
    """A committed run and segment, and `count` observations of it not yet added."""
    run = build.run()
    segment = build.segment(run)
    detector = build.component_version()
    build.session.commit()
    return run.id, [
        Observation(
            id=build.new_id(), source_id=run.source_id, processing_run_id=run.id,
            execution_segment_id=segment.id, state="PENDING", sequence_in_run=sequence,
            bbox_x=0.1, bbox_y=0.1, bbox_width=0.2, bbox_height=0.3,
            detector_component_version_id=detector.id, created_at=build.clock(),
        )
        for sequence in range(count)
    ]  # fmt: skip


def new_representation(build: ModelFactory, observation: Observation, **kw: Any) -> Representation:
    fields_: dict[str, Any] = dict(
        id=build.new_id(), observation_id=observation.id,
        processing_run_id=observation.processing_run_id,
        execution_segment_id=observation.execution_segment_id, state="PENDING",
        vector=float32_vector([0.5, 0.5, 0.5, 0.5]), vector_dimension=4, created_at=build.clock(),
    )  # fmt: skip
    return Representation(**(fields_ | kw))


# --- observations -------------------------------------------------------------------------------


def test_adding_observations_flushes_once_but_does_not_commit(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    _, observations = new_observations(build, 3)

    with factory() as session:
        added = ObservationRepository(session).add_batch(observations)
        assert [o.id for o in added] == [o.id for o in observations]
        with factory() as other:  # not visible to another connection until the caller commits
            assert other.get(Observation, observations[0].id) is None
        session.rollback()
    with factory() as session:
        assert session.get(Observation, observations[0].id) is None


def test_a_batch_violating_a_constraint_fails_at_the_add(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    _, observations = new_observations(build, 2)
    observations[1].sequence_in_run = observations[0].sequence_in_run  # unique per run

    with factory() as session, pytest.raises(IntegrityError, match="sequence_in_run"):
        ObservationRepository(session).add_batch(observations)


def test_get_returns_the_row_as_the_database_has_it_now_not_a_cached_copy(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    _, observations = new_observations(build, 1)
    with factory() as session:
        ObservationRepository(session).add_batch(observations)
        session.commit()
    with factory() as session:
        repo = ObservationRepository(session)
        cached = repo.get(observations[0].id)
        assert cached is not None
        assert cached.state == "PENDING"
        # transition() is one UPDATE that leaves the session's copy alone ...
        assert repo.transition(observations[0].id, from_states=["PENDING"], to_state="ACTIVE")
        assert cached.state == "PENDING"
        # ... so get() must go to the database, not answer from the copy it already holds
        again = repo.get(observations[0].id)
        assert again is not None
        assert again.state == "ACTIVE"
        assert repo.get(uuid.UUID(int=99)) is None


def test_a_run_is_paged_in_the_order_it_was_recorded_and_new_rows_do_not_shift_a_page(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    run_id, observations = new_observations(build, 5)
    with factory() as session:
        ObservationRepository(session).add_batch(observations)
        session.commit()

    def page(after: int | None) -> list[int]:  # each page is its own request and transaction
        with factory() as session:
            rows = ObservationRepository(session).page_for_run(
                run_id, limit=2, after_sequence=after
            )
            return [o.sequence_in_run for o in rows]

    assert page(None) == [0, 1]
    with factory() as other:  # a row recorded between two page requests
        late = Observation(
            id=build.new_id(), source_id=observations[0].source_id, processing_run_id=run_id,
            execution_segment_id=observations[0].execution_segment_id, state="PENDING",
            sequence_in_run=5, bbox_x=0.1, bbox_y=0.1, bbox_width=0.2, bbox_height=0.3,
            detector_component_version_id=observations[0].detector_component_version_id,
            created_at=build.clock(),
        )  # fmt: skip
        ObservationRepository(other).add_batch([late])
        other.commit()
    assert page(1) == [2, 3]  # nothing shifted or repeated
    assert page(3) == [4, 5]  # and the late row is seen where it belongs
    assert page(5) == []
    with factory() as session:
        repo = ObservationRepository(session)
        assert repo.page_for_run(uuid.UUID(int=7), limit=2) == []
        with pytest.raises(ValueError, match="at least one"):
            repo.page_for_run(run_id, limit=0)


def test_an_observation_changes_state_only_from_a_state_the_caller_expects(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    run_id, observations = new_observations(build, 1)
    newer_run = build.run()
    build.session.commit()
    with factory() as session:
        ObservationRepository(session).add_batch(observations)
        session.commit()
    observation_id = observations[0].id

    with factory() as session:
        repo = ObservationRepository(session)
        assert repo.transition(observation_id, from_states=["ACTIVE"], to_state="REJECTED") is False
        assert repo.transition(
            observation_id, from_states=["PENDING", "ACTIVE"], to_state="SUPERSEDED",
            superseded_by_run_id=newer_run.id,
        )  # fmt: skip
        session.commit()
    with factory() as session:
        row = session.get(Observation, observation_id)
        assert row is not None
        assert (row.state, row.superseded_by_run_id) == ("SUPERSEDED", newer_run.id)
        assert run_id != newer_run.id


def test_only_one_of_two_concurrent_observation_transitions_wins(
    factory: sessionmaker[Session], sqlite_engine: Engine, build: ModelFactory
) -> None:
    _, observations = new_observations(build, 1)
    with factory() as session:
        ObservationRepository(session).add_batch(observations)
        session.commit()

    def attempt(to_state: str) -> bool:
        with factory() as session:
            done = ObservationRepository(session).transition(
                observations[0].id, from_states=["PENDING"], to_state=to_state
            )
            session.commit()
            return done

    with (
        rendezvous_before_write(sqlite_engine, "UPDATE observations", parties=2),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        outcomes = list(pool.map(attempt, ["ACTIVE", "REJECTED"]))

    assert sorted(outcomes) == [False, True]


# --- representations ----------------------------------------------------------------------------


def committed_representations(
    factory: sessionmaker[Session], build: ModelFactory, count: int, **kw: Any
) -> tuple[uuid.UUID, uuid.UUID, list[Representation]]:
    """(space id, run id, `count` representations of one run, added and committed). Each needs its
    own observation; `kw` may be a callable of the index returning column overrides."""
    run_id, observations = new_observations(build, count)
    space = build.representation_space(dimension=4)
    build.session.commit()
    start = build.clock()
    each = kw.get("each", lambda i: {})
    reps = [
        new_representation(
            build,
            observation,
            representation_space_id=space.id,
            **({"created_at": start + timedelta(seconds=i)} | each(i)),
        )
        for i, observation in enumerate(observations)
    ]
    with factory() as session:
        ObservationRepository(session).add_batch(observations)
        RepresentationRepository(session).add_batch(reps)
        session.commit()
    return space.id, run_id, reps


def test_adding_representations_flushes_but_does_not_commit(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    run_id, observations = new_observations(build, 1)
    space = build.representation_space(dimension=4)
    build.session.commit()
    with factory() as session:
        ObservationRepository(session).add_batch(observations)
        session.commit()
    rep = new_representation(build, observations[0], representation_space_id=space.id)

    with factory() as session:
        RepresentationRepository(session).add_batch([rep])
        with factory() as other:
            assert other.get(Representation, rep.id) is None
        session.rollback()
    assert run_id == observations[0].processing_run_id


def test_a_representation_page_is_a_projection_without_the_vector_in_keyset_order(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    _, run_id, reps = committed_representations(factory, build, 5)
    assert "vector" not in {f.name for f in fields(RepresentationSummary)}

    with factory() as session:
        repo = RepresentationRepository(session)
        page, cursor = repo.page_for_run(run_id, limit=2)
        assert [r.id for r in page] == [r.id for r in reps[:2]]
        assert isinstance(page[0], RepresentationSummary)
        assert cursor == RepresentationCursor(page[-1].created_at, page[-1].id)
        ids = [r.id for r in page]
        while cursor is not None:
            page, cursor = repo.page_for_run(run_id, limit=2, after=cursor)
            ids += [r.id for r in page]
        assert ids == [r.id for r in reps]  # all, once, in order
        last, end = repo.page_for_run(run_id, limit=5)
        assert len(last) == 5
        assert end is None  # exactly full: no next page
        assert repo.page_for_run(uuid.UUID(int=7), limit=2) == ([], None)
        with pytest.raises(ValueError, match="at least one"):
            repo.page_for_run(run_id, limit=0)


def test_a_representation_page_can_be_limited_to_states_and_ties_are_broken_by_id(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    _, run_id, reps = committed_representations(
        factory,
        build,
        4,
        each=lambda i: {
            "state": "SUPERSEDED" if i % 2 else "PENDING",
            "created_at": build.clock(),  # all the same: the id breaks the tie
        },
    )

    with factory() as session:
        repo = RepresentationRepository(session)
        superseded, _ = repo.page_for_run(run_id, limit=10, states=["SUPERSEDED"])
        assert sorted(r.id for r in superseded) == sorted(reps[i].id for i in (1, 3))
        everything, _ = repo.page_for_run(run_id, limit=10)
        ordered = sorted(everything, key=lambda r: (r.created_at, r.id))
        assert [r.id for r in everything] == [r.id for r in ordered]  # same timestamp: id decides


def test_ann_keys_are_looked_up_per_space_in_any_state_and_unknown_keys_are_absent(
    factory: sessionmaker[Session],
    sqlite_engine: Engine,
    build: ModelFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(repository, "_KEYS_PER_QUERY", 2)  # five keys take three statements
    space_id, _, reps = committed_representations(
        factory, build, 5,
        each=lambda i: {"state": "SUPERSEDED", "ann_key": i + 1},
    )  # fmt: skip
    other_space, _, others = committed_representations(
        factory, build, 1, each=lambda i: {"state": "SUPERSEDED", "ann_key": 1}
    )

    bound: list[int] = []

    @event.listens_for(sqlite_engine, "before_cursor_execute")
    def record(conn: Any, cursor: Any, statement: str, parameters: Any, *rest: Any) -> None:
        if statement.lstrip().startswith("SELECT") and "FROM representations" in statement:
            bound.append(len(parameters))

    with factory() as session:
        found = RepresentationRepository(session).by_ann_keys(space_id, [5, 1, 99, 3, 1, 2, 4])
        event.remove(sqlite_engine, "before_cursor_execute", record)
        assert bound == [3, 3, 3]  # 6 distinct keys in chunks of 2, each with the space
        assert sorted(found) == [1, 2, 3, 4, 5]  # 99 is unknown; the repeated 1 counts once
        assert found[1].id == reps[0].id
        assert found[1].state == "SUPERSEDED"  # whatever the state: the caller decides eligibility
        assert RepresentationRepository(session).by_ann_keys(other_space, [1])[1].id == others[0].id
        assert RepresentationRepository(session).by_ann_keys(other_space, [2]) == {}
        assert RepresentationRepository(session).by_ann_keys(space_id, []) == {}


def test_a_representation_changes_state_only_from_a_state_the_caller_expects(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    _, _, (rep,) = committed_representations(factory, build, 1, each=lambda i: {"ann_key": 1})
    identity = build.identity()
    build.session.commit()
    stamp = build.clock()
    with factory() as session:  # the schema requires an identity (and a key) for ACTIVE
        session.execute(
            Representation.__table__.update()  # type: ignore[attr-defined]
            .where(Representation.id == rep.id)
            .values(identity_id=identity.id)
        )
        session.commit()

    with factory() as session:
        repo = RepresentationRepository(session)
        assert repo.transition(
            rep.id, from_states=["ACTIVE"], to_state="SUPERSEDED", now=stamp
        ) is False  # fmt: skip
        assert repo.transition(rep.id, from_states=["PENDING"], to_state="ACTIVE", now=stamp)
        session.commit()
    with factory() as session:
        row = RepresentationRepository(session).get(rep.id)
        assert row is not None
        assert (row.state, row.activated_at) == ("ACTIVE", stamp)
        assert RepresentationRepository(session).transition(
            rep.id, from_states=["ACTIVE"], to_state="SUPERSEDED", now=stamp
        )
        session.commit()
        refreshed = RepresentationRepository(session).get(rep.id)
        assert refreshed is not None
        assert refreshed.state == "SUPERSEDED"
        assert refreshed.activated_at == stamp  # kept, not cleared


def test_becoming_active_without_an_identity_and_key_is_refused_by_the_schema(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    _, _, (rep,) = committed_representations(factory, build, 1)

    with factory() as session, pytest.raises(IntegrityError, match="active_eligible"):
        RepresentationRepository(session).transition(
            rep.id, from_states=["PENDING"], to_state="ACTIVE", now=build.clock()
        )


@pytest.mark.parametrize(
    ("from_states", "to_state"),
    [
        (["ACTIVE"], "ERASING"),
        (["ACTIVE"], "ERASED"),
        (["ERASING"], "SUPERSEDED"),
        (["ERASED"], "ACTIVE"),
        (["ACTIVE", "ERASING"], "SUPERSEDED"),
    ],
)
def test_erasure_is_not_a_plain_state_change(
    factory: sessionmaker[Session], build: ModelFactory, from_states: list[str], to_state: str
) -> None:
    _, _, (rep,) = committed_representations(factory, build, 1)

    with factory() as session, pytest.raises(ValueError, match="RepresentationEraser"):
        RepresentationRepository(session).transition(
            rep.id, from_states=from_states, to_state=to_state, now=build.clock()
        )
    with factory() as session:
        assert session.scalar(select(Representation.state).where(Representation.id == rep.id)) == (
            "PENDING"
        )


def test_only_one_of_two_concurrent_representation_transitions_wins(
    factory: sessionmaker[Session], sqlite_engine: Engine, build: ModelFactory
) -> None:
    _, _, (rep,) = committed_representations(factory, build, 1)
    now = build.clock()

    def attempt(to_state: str) -> bool:
        with factory() as session:
            done = RepresentationRepository(session).transition(
                rep.id, from_states=["PENDING"], to_state=to_state, now=now
            )
            session.commit()
            return done

    with (
        rendezvous_before_write(sqlite_engine, "UPDATE representations", parties=2),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        outcomes = list(pool.map(attempt, ["SUPERSEDED", "DELETED"]))

    assert sorted(outcomes) == [False, True]


# --- ann keys -----------------------------------------------------------------------------------


def test_keys_are_allocated_one_at_a_time_per_space_starting_at_one(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    first, second = build.representation_space(), build.representation_space()
    build.session.commit()

    with factory() as session:
        repo = RepresentationRepository(session)
        assert [repo.allocate_ann_key(first.id) for _ in range(3)] == [1, 2, 3]
        assert repo.allocate_ann_key(second.id) == 1  # its own sequence
        assert repo.allocate_ann_key(first.id) == 4
        assert allocate_ann_key(session, second.id) == 2  # the use-case function is the same one


def test_a_rolled_back_allocation_is_handed_out_again_and_a_committed_one_is_not(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    space = build.representation_space()
    build.session.commit()
    with factory() as session:
        assert RepresentationRepository(session).allocate_ann_key(space.id) == 1
        session.rollback()  # open question 21: harmless, only committed keys are indexed
    with factory() as session:
        assert RepresentationRepository(session).allocate_ann_key(space.id) == 1
        session.commit()
    with factory() as session:
        assert RepresentationRepository(session).allocate_ann_key(space.id) == 2


def test_concurrent_allocations_never_hand_out_the_same_key(
    factory: sessionmaker[Session], sqlite_engine: Engine, build: ModelFactory
) -> None:
    space = build.representation_space()
    build.session.commit()

    def allocate(_: int) -> int:
        with factory() as session:
            key = RepresentationRepository(session).allocate_ann_key(space.id)
            session.commit()
            return key

    with (
        rendezvous_before_write(sqlite_engine, "INSERT OR IGNORE", parties=4),
        ThreadPoolExecutor(max_workers=4) as pool,
    ):
        keys = list(pool.map(allocate, range(4)))

    assert sorted(keys) == [1, 2, 3, 4]
