"""Identity, Occurrence and Evidence repositories against real SQLite (M2: TST-022; persistence §7,
§11, §22, §26).

Proved here: nothing is committed on the caller's behalf; `lock` really takes SQLite's write lock
before it reads; an identity changes state only at the revision and from the states the caller
expects, decided by the database (one winner under contention); occurrences keep their observations
in order and page newest first without shifting; evidence is appended whole (links and ranked
candidates) and never rewritten, only marked superseded once.
"""

import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlalchemy import Engine, delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.identities.models import (
    Evidence,
    EvidenceCandidate,
    EvidenceRepresentationRole,
    Identity,
    IdentityLineage,
)
from backend.app.identities.repository import (
    Cursor,
    EvidenceLink,
    EvidenceRepository,
    IdentityRepository,
    OccurrenceRepository,
)
from backend.app.memory.models import Occurrence, OccurrenceObservation
from backend.infrastructure.db.engine import create_session_factory
from tests.factories.models import ModelFactory
from tests.fixtures.concurrency import rendezvous_before_write


@pytest.fixture
def factory(sqlite_engine: Engine) -> sessionmaker[Session]:
    return create_session_factory(sqlite_engine)


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


def new_identity(build: ModelFactory, **kw: object) -> Identity:
    fields: dict[str, object] = dict(
        id=build.new_id(), state="PENDING", created_at=build.clock(), updated_at=build.clock()
    )
    return Identity(**(fields | kw))


# --- identities ---------------------------------------------------------------------------------


def test_adding_an_identity_flushes_but_does_not_commit(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    identity = new_identity(build)

    with factory() as session:
        IdentityRepository(session).add(identity)
        with factory() as other:  # not visible to another connection until the caller commits
            assert other.get(Identity, identity.id) is None
        session.rollback()


def test_get_returns_the_row_as_the_database_has_it_now_not_a_cached_copy(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    identity = build.identity(state="PENDING", activated_at=None)
    build.session.commit()
    now = build.clock()

    with factory() as session:
        repo = IdentityRepository(session)
        cached = repo.get(identity.id)
        assert cached is not None
        assert repo.transition(
            identity.id, expected_revision=1, from_states=["PENDING"], to_state="ACTIVE", now=now
        )
        assert cached.state == "PENDING"  # the one UPDATE leaves the held copy alone
        again = repo.get(identity.id)
        assert again is not None
        assert (again.state, again.revision, again.activated_at) == ("ACTIVE", 2, now)
        assert repo.get(uuid.UUID(int=9)) is None


def test_lock_takes_the_write_lock_and_returns_the_identity_fresh(
    sqlite_engine: Engine, factory: sessionmaker[Session], build: ModelFactory
) -> None:
    identity = build.identity()
    build.session.commit()
    path = sqlite_engine.url.database
    assert path is not None
    assert not writers_are_refused(path)

    with factory() as session:
        locked = IdentityRepository(session).lock(identity.id)

        assert locked is not None
        assert (locked.id, locked.revision) == (identity.id, 1)
        assert writers_are_refused(path)  # held until the caller ends the transaction
        session.rollback()

    assert not writers_are_refused(path)


def test_lock_changes_nothing_and_a_missing_identity_is_none(
    sqlite_engine: Engine, factory: sessionmaker[Session], build: ModelFactory
) -> None:
    identity = build.identity()
    build.session.commit()
    path = sqlite_engine.url.database
    assert path is not None

    with factory() as session:
        repo = IdentityRepository(session)
        assert repo.lock(identity.id) is not None
        session.commit()
    with factory() as session:
        row = IdentityRepository(session).get(identity.id)
        assert row is not None
        assert (row.revision, row.updated_at) == (1, identity.updated_at)
        assert IdentityRepository(session).lock(uuid.UUID(int=9)) is None
        assert writers_are_refused(path)  # still takes the lock
        session.rollback()


def test_a_transition_needs_the_expected_revision_and_state(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    identity = build.identity(state="ACTIVE")
    build.session.commit()
    now = build.clock() + timedelta(minutes=1)

    with factory() as session:
        repo = IdentityRepository(session)

        def forget(revision: int, state: str) -> bool:
            return repo.transition(
                identity.id, expected_revision=revision, from_states=[state],
                to_state="FORGOTTEN", now=now,
            )  # fmt: skip

        assert forget(2, "ACTIVE") is False  # a stale revision
        assert forget(1, "PENDING") is False  # not in the expected state
        assert forget(1, "ACTIVE")
        session.commit()
    with factory() as session:
        row = IdentityRepository(session).get(identity.id)
        assert row is not None
        assert (row.state, row.revision, row.forgotten_at, row.updated_at) == (
            "FORGOTTEN", 2, now, now
        )  # fmt: skip


def test_a_merged_identity_names_its_target_and_the_schema_insists(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    losing, surviving = build.identity(), build.identity()
    build.session.commit()
    now = build.clock()

    with factory() as session:
        repo = IdentityRepository(session)
        with pytest.raises(IntegrityError, match="merged_target"):
            repo.transition(
                losing.id, expected_revision=1, from_states=["ACTIVE"], to_state="MERGED", now=now
            )
        session.rollback()
    with factory() as session:
        repo = IdentityRepository(session)
        assert repo.transition(
            losing.id, expected_revision=1, from_states=["ACTIVE"], to_state="MERGED", now=now,
            merged_into_identity_id=surviving.id,
        )  # fmt: skip
        session.commit()
    with factory() as session:
        row = IdentityRepository(session).get(losing.id)
        assert row is not None
        assert (row.state, row.merged_into_identity_id) == ("MERGED", surviving.id)


def test_a_single_string_is_not_a_collection_of_states(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    identity = build.identity()
    occurrence = build.occurrence()
    build.session.commit()

    with factory() as session, pytest.raises(TypeError, match="not a single string"):
        IdentityRepository(session).transition(
            identity.id, expected_revision=1, from_states="ACTIVE", to_state="FORGOTTEN",
            now=build.clock(),
        )  # fmt: skip
    with factory() as session, pytest.raises(TypeError, match="not a single string"):
        OccurrenceRepository(session).transition(
            occurrence.id, from_states="PENDING", to_state="ACTIVE", now=build.clock()
        )


def test_only_one_of_two_concurrent_identity_transitions_wins(
    factory: sessionmaker[Session], sqlite_engine: Engine, build: ModelFactory
) -> None:
    identity = build.identity()
    build.session.commit()
    now = build.clock()

    def attempt(to_state: str) -> bool:
        with factory() as session:
            done = IdentityRepository(session).transition(
                identity.id, expected_revision=1, from_states=["ACTIVE"], to_state=to_state, now=now
            )
            session.commit()
            return done

    with (
        rendezvous_before_write(sqlite_engine, "UPDATE identities", parties=2),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        outcomes = list(pool.map(attempt, ["FORGOTTEN", "DELETED"]))

    assert sorted(outcomes) == [False, True]
    with factory() as session:
        assert session.scalar(select(Identity.revision).where(Identity.id == identity.id)) == 2


def test_a_lineage_edge_is_recorded_and_flushed_without_a_commit(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    losing, surviving = build.identity(), build.identity()
    evidence = build.evidence(kind="IDENTITY_MERGED")
    build.session.commit()
    edge = IdentityLineage(
        id=build.new_id(), from_identity_id=losing.id, to_identity_id=surviving.id,
        kind="MERGED_INTO", evidence_id=evidence.id, created_at=build.clock(),
    )  # fmt: skip

    with factory() as session:
        IdentityRepository(session).add_lineage(edge)
        with factory() as other:
            assert other.get(IdentityLineage, edge.id) is None
        duplicate = IdentityLineage(
            id=build.new_id(), from_identity_id=losing.id, to_identity_id=surviving.id,
            kind="MERGED_INTO", evidence_id=evidence.id, created_at=build.clock(),
        )  # fmt: skip
        with pytest.raises(IntegrityError, match="UNIQUE"):
            IdentityRepository(session).add_lineage(duplicate)
        session.rollback()


# --- occurrences --------------------------------------------------------------------------------


def test_an_occurrence_keeps_its_observations_in_the_order_given(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    run = build.run()
    observations = [build.observation(run) for _ in range(3)]
    identity = build.identity()
    build.session.commit()
    occurrence = Occurrence(
        id=build.new_id(), source_id=run.source_id, identity_id=identity.id,
        processing_run_id=run.id, representative_observation_id=observations[0].id, kind="TRACK",
        state="PENDING", created_at=build.clock(),
    )  # fmt: skip
    order = [observations[2].id, observations[0].id, observations[1].id]

    with factory() as session:
        repo = OccurrenceRepository(session)
        repo.add(occurrence, order)
        assert repo.observation_ids(occurrence.id) == order
        with factory() as other:  # not committed
            assert other.get(Occurrence, occurrence.id) is None
        session.commit()
    with factory() as session:
        assert OccurrenceRepository(session).observation_ids(occurrence.id) == order
        assert OccurrenceRepository(session).observation_ids(uuid.UUID(int=9)) == []


def test_an_observation_listed_twice_is_the_databases_integrity_error(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    run = build.run()
    observation = build.observation(run)
    identity = build.identity()
    build.session.commit()
    occurrence = Occurrence(
        id=build.new_id(), source_id=run.source_id, identity_id=identity.id,
        processing_run_id=run.id, kind="TRACK", state="PENDING", created_at=build.clock(),
    )  # fmt: skip

    with factory() as session, pytest.raises(IntegrityError):
        OccurrenceRepository(session).add(occurrence, [observation.id, observation.id])


def committed_occurrences(
    build: ModelFactory, count: int, *, same_time: bool = False
) -> tuple[uuid.UUID, uuid.UUID, list[Occurrence]]:
    """(source id, identity id, `count` occurrences of both, a second apart or all at once)."""
    run = build.run()
    identity = build.identity()
    start = build.clock()
    occurrences = [
        build.occurrence(
            build.observation(run), identity_id=identity.id, state="ACTIVE",
            created_at=start if same_time else start + timedelta(seconds=i),
        )
        for i in range(count)
    ]  # fmt: skip
    build.session.commit()
    return run.source_id, identity.id, occurrences


def test_occurrences_are_paged_newest_first_by_source_and_by_identity(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    source_id, identity_id, occurrences = committed_occurrences(build, 5)
    newest_first = [o.id for o in reversed(occurrences)]

    for owner in ("source", "identity"):
        seen: list[uuid.UUID] = []
        cursor: Cursor | None = None
        while True:
            with factory() as session:
                repo = OccurrenceRepository(session)
                if owner == "source":
                    page, cursor = repo.page_for_source(
                        source_id, state="ACTIVE", limit=2, after=cursor
                    )
                else:
                    page, cursor = repo.page_for_identity(
                        identity_id, state="ACTIVE", limit=2, after=cursor
                    )
            seen += [o.id for o in page]
            if cursor is None:
                break
        assert seen == newest_first, owner

    with factory() as session:
        repo = OccurrenceRepository(session)
        assert repo.page_for_source(source_id, state="PENDING", limit=2) == ([], None)
        full, end = repo.page_for_source(source_id, state="ACTIVE", limit=5)
        assert len(full) == 5
        assert end is None  # exactly full: no next page
        with pytest.raises(ValueError, match="at least one"):
            repo.page_for_identity(identity_id, state="ACTIVE", limit=0)


def test_paging_does_not_skip_or_repeat_when_rows_change_between_page_requests(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    source_id, _, occurrences = committed_occurrences(build, 5, same_time=True)
    expected = sorted((o.id for o in occurrences), reverse=True)  # same time: the id decides

    with factory() as session:
        first, cursor = OccurrenceRepository(session).page_for_source(
            source_id, state="ACTIVE", limit=2
        )
    assert [o.id for o in first] == expected[:2]
    with factory() as session:  # a row already paged past disappears between the requests
        session.execute(
            delete(OccurrenceObservation).where(OccurrenceObservation.occurrence_id == first[0].id)
        )
        session.execute(delete(Occurrence).where(Occurrence.id == first[0].id))
        session.commit()
    seen = [o.id for o in first]
    while cursor is not None:
        with factory() as session:
            page, cursor = OccurrenceRepository(session).page_for_source(
                source_id, state="ACTIVE", limit=2, after=cursor
            )
        seen += [o.id for o in page]
    assert seen == expected  # none skipped (an offset would skip one) and none repeated


def test_an_occurrence_changes_state_only_from_a_state_the_caller_expects(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    occurrence = build.occurrence()
    build.session.commit()
    stamp = build.clock()

    with factory() as session:
        repo = OccurrenceRepository(session)
        assert repo.transition(
            occurrence.id, from_states=["ACTIVE"], to_state="SUPERSEDED", now=stamp
        ) is False  # fmt: skip
        assert repo.transition(occurrence.id, from_states=["PENDING"], to_state="ACTIVE", now=stamp)
        session.commit()
    with factory() as session:
        row = OccurrenceRepository(session).get(occurrence.id)
        assert row is not None
        assert (row.state, row.activated_at) == ("ACTIVE", stamp)
        assert OccurrenceRepository(session).transition(
            occurrence.id, from_states=["ACTIVE"], to_state="SUPERSEDED", now=stamp
        )
        session.commit()
        kept = OccurrenceRepository(session).get(occurrence.id)
        assert kept is not None
        assert (kept.state, kept.activated_at) == ("SUPERSEDED", stamp)


# --- evidence -----------------------------------------------------------------------------------


def new_evidence(
    build: ModelFactory, identity_id: uuid.UUID | None = None, **kw: object
) -> Evidence:
    fields: dict[str, object] = dict(
        id=build.new_id(), kind="IDENTITY_MATCHED", subject_identity_id=identity_id,
        payload_schema_version=1, payload_json={"why": "similar"}, created_at=build.clock(),
    )  # fmt: skip
    return Evidence(**(fields | kw))


def test_evidence_is_appended_with_its_links_and_candidates_in_rank_order(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    identity = build.identity()
    reps = [build.representation() for _ in range(3)]
    build.session.commit()
    evidence = new_evidence(build, identity.id)
    candidates = [
        EvidenceCandidate(
            rank=rank, representation_id=reps[rank].id, identity_id=identity.id,
            raw_similarity=0.9 - rank / 10, calibrated_confidence=None, decision="CONSIDERED",
            details_json={},
        )
        for rank in (2, 0, 1)
    ]  # fmt: skip
    links = [
        EvidenceLink(reps[1].id, EvidenceRepresentationRole.SUPPORTING),
        EvidenceLink(reps[0].id, EvidenceRepresentationRole.SUBJECT),
    ]

    with factory() as session:
        repo = EvidenceRepository(session)
        repo.append(evidence, representations=links, candidates=candidates)
        assert [c.rank for c in repo.candidates(evidence.id)] == [0, 1, 2]
        assert {(link.representation_id, link.role) for link in repo.links(evidence.id)} == {
            (reps[1].id, "SUPPORTING"),
            (reps[0].id, "SUBJECT"),
        }
        with factory() as other:  # not committed
            assert other.get(Evidence, evidence.id) is None
        session.commit()
    with factory() as session:
        stored = EvidenceRepository(session).get(evidence.id)
        assert stored is not None
        assert stored.payload_json == {"why": "similar"}
        assert EvidenceRepository(session).get(uuid.UUID(int=9)) is None
        assert EvidenceRepository(session).candidates(uuid.UUID(int=9)) == []


def test_evidence_without_links_or_candidates_can_be_appended(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    build.session.commit()
    evidence = new_evidence(build)

    with factory() as session:
        EvidenceRepository(session).append(evidence)
        session.commit()
    with factory() as session:
        assert EvidenceRepository(session).links(evidence.id) == []
        assert EvidenceRepository(session).candidates(evidence.id) == []


def test_evidence_about_an_identity_is_paged_newest_first_without_shifting(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    identity = build.identity()
    other_identity = build.identity()
    start = build.clock()
    rows = [
        build.evidence(subject_identity_id=identity.id, created_at=start + timedelta(seconds=i))
        for i in range(5)
    ]
    build.evidence(subject_identity_id=other_identity.id)
    build.session.commit()
    expected = [e.id for e in reversed(rows)]

    with factory() as session:
        first, cursor = EvidenceRepository(session).page_for_identity(identity.id, limit=2)
    assert [e.id for e in first] == expected[:2]
    with factory() as session:  # a newer row arrives between the two page requests
        late = new_evidence(build, identity.id, created_at=start + timedelta(minutes=1))
        EvidenceRepository(session).append(late)
        session.commit()
    seen = [e.id for e in first]
    while cursor is not None:
        with factory() as session:
            page, cursor = EvidenceRepository(session).page_for_identity(
                identity.id, limit=2, after=cursor
            )
        seen += [e.id for e in page]
    assert seen == expected  # nothing shifted or repeated; the newer row is on an earlier page
    with factory() as session:
        repo = EvidenceRepository(session)
        newest, _ = repo.page_for_identity(identity.id, limit=1)
        assert newest[0].id == late.id
        assert repo.page_for_identity(uuid.UUID(int=9), limit=2) == ([], None)
        with pytest.raises(ValueError, match="at least one"):
            repo.page_for_identity(identity.id, limit=0)


def test_evidence_with_the_same_timestamp_is_paged_by_id(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    identity = build.identity()
    rows = [build.evidence(subject_identity_id=identity.id) for _ in range(4)]  # one timestamp
    build.session.commit()
    expected = sorted((e.id for e in rows), reverse=True)

    seen: list[uuid.UUID] = []
    cursor: Cursor | None = None
    while True:
        with factory() as session:
            page, cursor = EvidenceRepository(session).page_for_identity(
                identity.id, limit=3, after=cursor
            )
        seen += [e.id for e in page]
        if cursor is None:
            break

    assert seen == expected


def test_evidence_is_marked_superseded_once_and_its_payload_is_never_rewritten(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    evidence = build.evidence(payload_json={"why": "similar"})
    build.session.commit()
    first, second = build.clock(), build.clock() + timedelta(hours=1)

    with factory() as session:
        repo = EvidenceRepository(session)
        assert repo.mark_superseded(evidence.id, now=first)
        assert repo.mark_superseded(evidence.id, now=second) is False  # already marked
        assert repo.mark_superseded(uuid.UUID(int=9), now=first) is False
        session.commit()
    with factory() as session:
        row = EvidenceRepository(session).get(evidence.id)
        assert row is not None
        assert (row.superseded_at, row.payload_json) == (first, {"why": "similar"})
