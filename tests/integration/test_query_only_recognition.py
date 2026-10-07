"""Query-only recognition guard tests (M1 PR 6: TST-019).

`resolve_recognition_candidates` is the domain-level piece of face query search (`API and
Contracts.md` §12.2: "ANN candidate retrieval -> authoritative SQLite revalidation"). A query
must never become ingest (IMPLEMENTATION_ARCHITECTURE.md §32 rule 7; TESTING_STRATEGY.md
SEARCH-01): it reads only, resolving a stale ANN candidate through any merge chain to its current
ACTIVE identity, and creates nothing regardless of what candidates it is given.
"""

import uuid

from sqlalchemy import select

from backend.app.identities.models import Evidence, Identity, IdentityLineage
from backend.app.identities.use_cases import merge_identities, resolve_recognition_candidates
from backend.app.memory.models import IndexOperation, Representation
from backend.app.people.models import IdentityPersonAssociation
from tests.factories.models import ModelFactory


def test_resolves_active_candidates_unchanged(build: ModelFactory) -> None:
    a = build.identity()
    b = build.identity()
    result = resolve_recognition_candidates(build.session, [a.id, b.id])
    assert [identity.id for identity in result] == [a.id, b.id]


def test_preserves_input_order(build: ModelFactory) -> None:
    a = build.identity()
    b = build.identity()
    c = build.identity()
    result = resolve_recognition_candidates(build.session, [c.id, a.id, b.id])
    assert [identity.id for identity in result] == [c.id, a.id, b.id]


def test_drops_an_unknown_candidate(build: ModelFactory) -> None:
    a = build.identity()
    result = resolve_recognition_candidates(build.session, [a.id, uuid.uuid4()])
    assert [identity.id for identity in result] == [a.id]


def test_drops_a_pending_candidate(build: ModelFactory) -> None:
    pending = build.identity(state="PENDING")
    result = resolve_recognition_candidates(build.session, [pending.id])
    assert result == []


def test_drops_a_forgotten_candidate(build: ModelFactory) -> None:
    forgotten = build.identity(state="FORGOTTEN")
    result = resolve_recognition_candidates(build.session, [forgotten.id])
    assert result == []


def test_drops_a_deleted_candidate(build: ModelFactory) -> None:
    deleted = build.identity(state="DELETED")
    result = resolve_recognition_candidates(build.session, [deleted.id])
    assert result == []


def test_resolves_a_merged_candidate_to_its_survivor(build: ModelFactory) -> None:
    survivor = build.identity()
    loser = build.identity()
    merge_identities(
        build.session, loser.id, survivor.id, expected_revision=loser.revision,
        new_id=build.new_id, clock=build.clock,
    )  # fmt: skip

    result = resolve_recognition_candidates(build.session, [loser.id])
    assert [identity.id for identity in result] == [survivor.id]


def test_resolves_a_chained_merge_to_the_final_survivor(build: ModelFactory) -> None:
    a = build.identity()
    b = build.identity()
    c = build.identity()
    merge_identities(
        build.session, b.id, a.id, expected_revision=b.revision,
        new_id=build.new_id, clock=build.clock,
    )  # fmt: skip
    merge_identities(
        build.session, c.id, b.id, expected_revision=c.revision,
        new_id=build.new_id, clock=build.clock,
    )  # fmt: skip

    result = resolve_recognition_candidates(build.session, [c.id])
    assert [identity.id for identity in result] == [a.id]


def test_drops_a_candidate_merged_into_something_no_longer_active(build: ModelFactory) -> None:
    """A merge chain can end at an identity that has itself since been forgotten; that is not
    the same as the chain being broken, and should still be dropped, not resurrected."""
    survivor = build.identity()
    loser = build.identity()
    merge_identities(
        build.session, loser.id, survivor.id, expected_revision=loser.revision,
        new_id=build.new_id, clock=build.clock,
    )  # fmt: skip
    survivor.state = "FORGOTTEN"
    build.session.flush()

    result = resolve_recognition_candidates(build.session, [loser.id])
    assert result == []


def test_deduplicates_candidates_that_resolve_to_the_same_survivor(build: ModelFactory) -> None:
    survivor = build.identity()
    loser_one = build.identity()
    loser_two = build.identity()
    merge_identities(
        build.session, loser_one.id, survivor.id, expected_revision=loser_one.revision,
        new_id=build.new_id, clock=build.clock,
    )  # fmt: skip
    merge_identities(
        build.session, loser_two.id, survivor.id, expected_revision=loser_two.revision,
        new_id=build.new_id, clock=build.clock,
    )  # fmt: skip

    result = resolve_recognition_candidates(
        build.session, [loser_one.id, survivor.id, loser_two.id]
    )
    # First-seen order: loser_one resolves to survivor first, so that's where it appears.
    assert [identity.id for identity in result] == [survivor.id]


def test_an_empty_candidate_list_resolves_to_nothing(build: ModelFactory) -> None:
    assert resolve_recognition_candidates(build.session, []) == []


def test_a_query_creates_no_persistent_state(build: ModelFactory) -> None:
    """The core guard (SEARCH-01 / IMPLEMENTATION_ARCHITECTURE.md §32 rule 7): regardless of
    what candidates are supplied — known, unknown, merged, forgotten, deleted, duplicated — a
    query never creates an Identity, Evidence, IdentityLineage, Representation or IndexOperation
    row, and never touches an existing row's state."""
    survivor = build.identity()
    loser = build.identity()
    merge_identities(
        build.session, loser.id, survivor.id, expected_revision=loser.revision,
        new_id=build.new_id, clock=build.clock,
    )  # fmt: skip
    before_identity_count = len(build.session.scalars(select(Identity)).all())
    before_evidence_count = len(build.session.scalars(select(Evidence)).all())
    before_lineage_count = len(build.session.scalars(select(IdentityLineage)).all())

    resolve_recognition_candidates(
        build.session,
        [survivor.id, loser.id, uuid.uuid4(), build.identity(state="FORGOTTEN").id],
    )

    assert len(build.session.new) == 0  # nothing pending insertion
    assert len(build.session.dirty) == 0  # nothing pending an update
    assert len(build.session.scalars(select(Identity)).all()) == before_identity_count + 1
    assert len(build.session.scalars(select(Evidence)).all()) == before_evidence_count
    assert len(build.session.scalars(select(IdentityLineage)).all()) == before_lineage_count
    assert build.session.scalars(select(Representation)).all() == []
    assert build.session.scalars(select(IndexOperation)).all() == []
    assert build.session.scalars(select(IdentityPersonAssociation)).all() == []


def test_repeating_the_same_query_does_not_grow_memory(build: ModelFactory) -> None:
    """API and Contracts.md §12.2: 'Repeating the same face search must not grow memory.'"""
    a = build.identity()
    resolve_recognition_candidates(build.session, [a.id])
    resolve_recognition_candidates(build.session, [a.id])
    resolve_recognition_candidates(build.session, [a.id])
    assert len(build.session.scalars(select(Identity)).all()) == 1
