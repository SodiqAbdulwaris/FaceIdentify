"""Optimistic concurrency with real, separate sessions and threads (M2: TST-024;
PERSISTENCE_IMPLEMENTATION.md §2: `WHERE id = :id AND revision = :expected_revision`).

The use-case tests already prove that a wrong `expected_revision` is rejected. These prove the
guarantee that matters: when two writers act on what they both believe is the same revision,
exactly one change lands, the loser is rejected without touching anything, and the revision is
bumped once, never twice.
"""

import threading
import uuid
from collections.abc import Callable

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.identities.models import Evidence, Identity, IdentityLineage
from backend.app.identities.use_cases import (
    IdentityManagerError,
    StaleRevisionError,
    activate_identity,
    merge_identities,
)
from backend.app.memory.models import Representation
from backend.app.people.models import Person
from backend.app.people.use_cases import rename_person
from backend.infrastructure.db.engine import create_session_factory
from tests.factories.models import ModelFactory
from tests.fixtures.deterministic import FrozenClock, SeededUUIDs

ROUNDS = 5


def in_transaction(factory: sessionmaker[Session], work: Callable[[Session], object]) -> None:
    """One writer's whole unit of work: its own session, commit on success, rollback on error."""
    with factory() as session:
        try:
            work(session)
            session.commit()
        except BaseException:
            session.rollback()
            raise


def race(*jobs: Callable[[], None]) -> list[BaseException | None]:
    """Start every job at the same instant; return each job's exception, or None if it succeeded."""
    barrier = threading.Barrier(len(jobs))
    outcomes: list[BaseException | None] = [None] * len(jobs)

    def run(index: int, job: Callable[[], None]) -> None:
        barrier.wait()
        try:
            job()
        except BaseException as error:  # reported to the caller, not swallowed
            outcomes[index] = error

    threads = [threading.Thread(target=run, args=(i, job)) for i, job in enumerate(jobs)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not any(thread.is_alive() for thread in threads), "a writer never finished"
    return outcomes


# --- two sessions, one stale ------------------------------------------------------------------


def test_a_stale_rename_is_rejected_and_the_first_rename_wins(
    sqlite_engine: Engine, db_session: Session, build: ModelFactory
) -> None:
    person = build.person(display_name="Alice")
    db_session.commit()
    factory = create_session_factory(sqlite_engine)

    in_transaction(
        factory,
        lambda s: rename_person(s, person.id, "Alice B", expected_revision=1, clock=build.clock),
    )
    with pytest.raises(StaleRevisionError):  # the second user still holds revision 1
        in_transaction(
            factory,
            lambda s: rename_person(s, person.id, "Alicia", expected_revision=1, clock=build.clock),
        )

    with factory() as check:
        row = check.get(Person, person.id)
        assert row is not None
        assert (row.display_name, row.revision) == ("Alice B", 2)


def test_a_stale_activation_is_rejected(
    sqlite_engine: Engine, db_session: Session, build: ModelFactory
) -> None:
    identity = build.identity(state="PENDING")
    db_session.commit()
    factory = create_session_factory(sqlite_engine)

    in_transaction(
        factory,
        lambda s: activate_identity(s, identity.id, expected_revision=1, clock=build.clock),
    )
    with pytest.raises(StaleRevisionError):
        in_transaction(
            factory,
            lambda s: activate_identity(s, identity.id, expected_revision=1, clock=build.clock),
        )

    with factory() as check:
        row = check.get(Identity, identity.id)
        assert row is not None
        assert (row.state, row.revision) == ("ACTIVE", 2)


def test_a_merge_from_a_stale_revision_is_rejected_and_moves_nothing(
    sqlite_engine: Engine, db_session: Session, build: ModelFactory
) -> None:
    survivor = build.identity()
    other_survivor = build.identity()
    loser = build.identity()
    space = build.representation_space()
    representation = build.representation(
        representation_space_id=space.id, identity_id=loser.id, state="ACTIVE", ann_key=1
    )
    db_session.commit()
    factory = create_session_factory(sqlite_engine)

    in_transaction(
        factory,
        lambda s: merge_identities(
            s, loser.id, survivor.id, expected_revision=1, new_id=build.new_id, clock=build.clock
        ),
    )
    with pytest.raises(IdentityManagerError):  # the loser is no longer ACTIVE
        in_transaction(
            factory,
            lambda s: merge_identities(
                s, loser.id, other_survivor.id,
                expected_revision=1, new_id=build.new_id, clock=build.clock,
            ),
        )  # fmt: skip

    with factory() as check:
        moved = check.get(Representation, representation.id)
        assert moved is not None
        assert moved.identity_id == survivor.id  # the first merge's outcome, untouched
        assert check.scalar(select(func.count()).select_from(IdentityLineage)) == 1


# --- simultaneous writers ---------------------------------------------------------------------


@pytest.mark.parametrize("round_number", range(ROUNDS))
def test_simultaneous_renames_from_one_revision_land_exactly_once(
    round_number: int, sqlite_engine: Engine, db_session: Session, build: ModelFactory
) -> None:
    person = build.person(display_name="Original")
    db_session.commit()
    factory = create_session_factory(sqlite_engine)
    names = [f"Writer {i}" for i in range(6)]

    outcomes = race(
        *[
            (
                lambda name=name: in_transaction(
                    factory,
                    lambda s: rename_person(
                        s, person.id, name, expected_revision=1, clock=build.clock
                    ),
                )
            )
            for name in names
        ]
    )

    winners = [i for i, outcome in enumerate(outcomes) if outcome is None]
    assert len(winners) == 1
    assert all(isinstance(o, StaleRevisionError) for o in outcomes if o is not None), outcomes
    with factory() as check:
        row = check.get(Person, person.id)
        assert row is not None
        assert row.revision == 2  # bumped once, not once per writer
        assert row.display_name == names[winners[0]]


@pytest.mark.parametrize("round_number", range(ROUNDS))
def test_simultaneous_activations_land_exactly_once(
    round_number: int, sqlite_engine: Engine, db_session: Session, build: ModelFactory
) -> None:
    identity = build.identity(state="PENDING")
    db_session.commit()
    factory = create_session_factory(sqlite_engine)

    outcomes = race(
        *[
            lambda: in_transaction(
                factory,
                lambda s: activate_identity(s, identity.id, expected_revision=1, clock=build.clock),
            )
            for _ in range(4)
        ]
    )

    assert sum(outcome is None for outcome in outcomes) == 1
    assert all(isinstance(o, StaleRevisionError) for o in outcomes if o is not None), outcomes
    with factory() as check:
        row = check.get(Identity, identity.id)
        assert row is not None
        assert (row.state, row.revision) == ("ACTIVE", 2)


@pytest.mark.parametrize("round_number", range(ROUNDS))
def test_simultaneous_merges_of_one_identity_apply_exactly_one(
    round_number: int, sqlite_engine: Engine, db_session: Session, build: ModelFactory
) -> None:
    """Two users merge the same identity into different survivors at the same instant. Merge reads
    before it writes, so the loser can be refused either by the domain (`IdentityManagerError`) or,
    if it had already read when the winner committed, by SQLite itself (`OperationalError`, see
    `test_sqlite_wal_behaviour.py`). Either way exactly one merge must land, completely."""
    first = build.identity()
    second = build.identity()
    loser = build.identity()
    space = build.representation_space()
    representation_ids = [
        build.representation(
            representation_space_id=space.id, identity_id=loser.id, state="ACTIVE", ann_key=n
        ).id
        for n in (1, 2)
    ]
    db_session.commit()
    factory = create_session_factory(sqlite_engine)

    def merge_into(survivor_id: uuid.UUID) -> Callable[[], None]:
        return lambda: in_transaction(
            factory,
            lambda s: merge_identities(
                s, loser.id, survivor_id,
                expected_revision=1, new_id=build.new_id, clock=build.clock,
            ),
        )  # fmt: skip

    outcomes = race(merge_into(first.id), merge_into(second.id))

    assert sum(outcome is None for outcome in outcomes) == 1, outcomes
    assert all(
        isinstance(o, IdentityManagerError | OperationalError) for o in outcomes if o is not None
    ), outcomes
    with factory() as check:
        merged = check.get(Identity, loser.id)
        assert merged is not None
        assert merged.state == "MERGED"
        assert merged.revision == 2
        assert merged.merged_into_identity_id in {first.id, second.id}
        lineage = check.scalars(select(IdentityLineage)).one()
        assert lineage.to_identity_id == merged.merged_into_identity_id
        for representation_id in representation_ids:
            moved = check.get(Representation, representation_id)
            assert moved is not None
            assert moved.identity_id == merged.merged_into_identity_id  # all of it, one place
        merges = check.scalars(select(Evidence).where(Evidence.kind == "IDENTITY_MERGED")).all()
        assert len(merges) == 1


def test_the_clock_and_id_sources_are_safe_to_share_between_writers() -> None:
    """The races above share one `SeededUUIDs` and one `FrozenClock` across threads; ids must
    stay unique or a lost-update test could pass for the wrong reason."""
    new_id = SeededUUIDs()
    clock = FrozenClock()
    drawn: list[uuid.UUID] = []

    def draw() -> None:
        for _ in range(500):
            drawn.append(new_id())
            clock()

    race(*[draw for _ in range(6)])
    assert len(set(drawn)) == len(drawn) == 3000
