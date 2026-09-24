"""Identity merge and split use-case tests (M1 PR 5: TST-015, TST-016).

Merge and split are Identity-level (identity-and-memory-model-v1.md §18/§19.2, decision
2026-09-23): the losing identity in a merge keeps its row (state MERGED, never deleted); a split
creates a genuinely new identity, moving selected representations to it. Both preserve every
representation's `ann_key` untouched — only ownership (`identity_id`) changes, so neither
operation creates an `IndexOperation` (ANN eligibility itself does not change, §23).
"""

import uuid

import pytest
from sqlalchemy import select

from backend.app.identities.models import Evidence, IdentityLineage
from backend.app.identities.use_cases import (
    IdentityManagerError,
    StaleRevisionError,
    merge_identities,
    split_identity,
)
from backend.app.memory.models import IndexOperation, Representation
from backend.app.people.models import IdentityPersonAssociation
from backend.app.people.use_cases import assign_identity_to_person
from tests.factories.models import ModelFactory

# --- merge (TST-015) -----------------------------------------------------------------------------


def test_merge_moves_active_representations_and_keeps_their_ann_keys(build: ModelFactory) -> None:
    survivor = build.identity()
    loser = build.identity()
    space = build.representation_space()
    moved = build.representation(
        representation_space_id=space.id, identity_id=loser.id, state="ACTIVE", ann_key=1
    )
    kept = build.representation(
        representation_space_id=space.id, identity_id=survivor.id, state="ACTIVE", ann_key=2
    )

    result = merge_identities(
        build.session, loser.id, survivor.id, expected_revision=loser.revision,
        new_id=build.new_id, clock=build.clock,
    )  # fmt: skip

    assert result.id == survivor.id
    build.session.expire_all()
    moved_rep = build.session.get(Representation, moved.id)
    kept_rep = build.session.get(Representation, kept.id)
    assert moved_rep is not None
    assert moved_rep.identity_id == survivor.id
    assert moved_rep.ann_key == 1  # untouched: merge changes ownership, not ANN eligibility
    assert kept_rep is not None
    assert kept_rep.identity_id == survivor.id
    assert build.session.scalars(select(IndexOperation)).all() == []  # no ANN change, no op


def test_merge_does_not_move_the_losers_non_active_representations(build: ModelFactory) -> None:
    survivor = build.identity()
    loser = build.identity()
    space = build.representation_space()
    pending = build.representation(
        representation_space_id=space.id, identity_id=loser.id, state="PENDING"
    )

    merge_identities(
        build.session, loser.id, survivor.id, expected_revision=loser.revision,
        new_id=build.new_id, clock=build.clock,
    )  # fmt: skip

    build.session.expire_all()
    still_pending = build.session.get(Representation, pending.id)
    assert still_pending is not None
    assert still_pending.identity_id == loser.id


def test_merge_leaves_the_losing_identitys_row_in_place(build: ModelFactory) -> None:
    """ID-01-equivalent for merge: the losing identity's own identifier and history survive.
    Merge is Identity-level (§18): the row becomes MERGED, it is never deleted."""
    survivor = build.identity()
    loser = build.identity()

    merge_identities(
        build.session, loser.id, survivor.id, expected_revision=loser.revision,
        new_id=build.new_id, clock=build.clock,
    )  # fmt: skip

    build.session.expire_all()
    still_there = build.session.get(type(loser), loser.id)
    assert still_there is not None
    assert still_there.id == loser.id
    assert still_there.state == "MERGED"
    assert still_there.merged_into_identity_id == survivor.id
    assert still_there.revision == 2


def test_merge_records_evidence_and_lineage(build: ModelFactory) -> None:
    survivor = build.identity()
    loser = build.identity()
    space = build.representation_space()
    representation = build.representation(
        representation_space_id=space.id, identity_id=loser.id, state="ACTIVE", ann_key=1
    )

    merge_identities(
        build.session, loser.id, survivor.id, expected_revision=loser.revision,
        new_id=build.new_id, clock=build.clock,
    )  # fmt: skip

    evidence = build.session.scalars(
        select(Evidence).where(Evidence.kind == "IDENTITY_MERGED")
    ).one()
    assert evidence.subject_identity_id == loser.id
    assert evidence.payload_json["merged_into_identity_id"] == str(survivor.id)
    assert evidence.payload_json["moved_representation_ids"] == [str(representation.id)]

    lineage = build.session.scalars(select(IdentityLineage)).one()
    assert (lineage.from_identity_id, lineage.to_identity_id, lineage.kind) == (
        loser.id,
        survivor.id,
        "MERGED_INTO",
    )
    assert lineage.evidence_id == evidence.id


def test_merge_carries_over_the_losers_person_when_the_survivor_has_none(
    build: ModelFactory,
) -> None:
    survivor = build.identity()
    loser = build.identity()
    alice = build.person(display_name="Alice")
    assign_identity_to_person(
        build.session, loser.id, alice.id, new_id=build.new_id, clock=build.clock
    )

    merge_identities(
        build.session, loser.id, survivor.id, expected_revision=loser.revision,
        new_id=build.new_id, clock=build.clock,
    )  # fmt: skip

    survivor_active = build.session.scalars(
        select(IdentityPersonAssociation).where(
            IdentityPersonAssociation.identity_id == survivor.id,
            IdentityPersonAssociation.state == "ACTIVE",
        )
    ).one()
    assert survivor_active.person_id == alice.id

    build.session.expire_all()
    loser_associations = build.session.scalars(
        select(IdentityPersonAssociation).where(IdentityPersonAssociation.identity_id == loser.id)
    ).all()
    assert len(loser_associations) == 1
    assert loser_associations[0].state == "SUPERSEDED"
    assert loser_associations[0].person_id == alice.id  # still records who it WAS


def test_merge_when_both_identities_already_point_at_the_same_person(
    build: ModelFactory,
) -> None:
    """Not a special case in the code: the survivor already having an active link (to anyone,
    including the loser's own person) is what skips the carry-over branch. No duplicate
    association or Evidence should appear."""
    survivor = build.identity()
    loser = build.identity()
    alice = build.person(display_name="Alice")
    assign_identity_to_person(
        build.session, survivor.id, alice.id, new_id=build.new_id, clock=build.clock
    )
    assign_identity_to_person(
        build.session, loser.id, alice.id, new_id=build.new_id, clock=build.clock
    )

    merge_identities(
        build.session, loser.id, survivor.id, expected_revision=loser.revision,
        new_id=build.new_id, clock=build.clock,
    )  # fmt: skip

    build.session.expire_all()
    survivor_active = build.session.scalars(
        select(IdentityPersonAssociation).where(
            IdentityPersonAssociation.identity_id == survivor.id,
            IdentityPersonAssociation.state == "ACTIVE",
        )
    ).all()
    assert len(survivor_active) == 1
    assert survivor_active[0].person_id == alice.id
    loser_association = build.session.scalars(
        select(IdentityPersonAssociation).where(IdentityPersonAssociation.identity_id == loser.id)
    ).one()
    assert loser_association.state == "SUPERSEDED"
    survivor_evidence = build.session.scalars(
        select(Evidence).where(
            Evidence.subject_identity_id == survivor.id,
            Evidence.kind == "IDENTITY_ASSIGNED_TO_PERSON",
        )
    ).all()
    # Exactly the initial assignment's own Evidence — merge creates no second, carry-over one,
    # since the survivor's own active link already existed.
    assert len(survivor_evidence) == 1


def test_merge_keeps_the_survivors_own_person_when_it_already_has_one(
    build: ModelFactory,
) -> None:
    survivor = build.identity()
    loser = build.identity()
    bob = build.person(display_name="Bob")
    alice = build.person(display_name="Alice")
    assign_identity_to_person(
        build.session, survivor.id, bob.id, new_id=build.new_id, clock=build.clock
    )
    assign_identity_to_person(
        build.session, loser.id, alice.id, new_id=build.new_id, clock=build.clock
    )

    merge_identities(
        build.session, loser.id, survivor.id, expected_revision=loser.revision,
        new_id=build.new_id, clock=build.clock,
    )  # fmt: skip

    build.session.expire_all()
    survivor_active = build.session.scalars(
        select(IdentityPersonAssociation).where(
            IdentityPersonAssociation.identity_id == survivor.id,
            IdentityPersonAssociation.state == "ACTIVE",
        )
    ).one()
    assert survivor_active.person_id == bob.id  # unchanged; alice does not override it
    loser_association = build.session.scalars(
        select(IdentityPersonAssociation).where(IdentityPersonAssociation.identity_id == loser.id)
    ).one()
    assert loser_association.state == "SUPERSEDED"


def test_merge_with_neither_identity_named_touches_no_association(build: ModelFactory) -> None:
    survivor = build.identity()
    loser = build.identity()
    merge_identities(
        build.session, loser.id, survivor.id, expected_revision=loser.revision,
        new_id=build.new_id, clock=build.clock,
    )  # fmt: skip
    assert build.session.scalars(select(IdentityPersonAssociation)).all() == []


def test_merge_rejects_merging_an_identity_into_itself(build: ModelFactory) -> None:
    identity = build.identity()
    with pytest.raises(IdentityManagerError, match="itself"):
        merge_identities(
            build.session, identity.id, identity.id, expected_revision=identity.revision,
            new_id=build.new_id, clock=build.clock,
        )  # fmt: skip


@pytest.mark.parametrize("loser_state", ["PENDING", "MERGED", "FORGOTTEN", "DELETED"])
def test_merge_rejects_a_non_active_losing_identity(build: ModelFactory, loser_state: str) -> None:
    survivor = build.identity()
    if loser_state == "MERGED":
        loser = build.identity(state="MERGED", merged_into_identity_id=build.identity().id)
    else:
        loser = build.identity(state=loser_state)
    with pytest.raises(IdentityManagerError, match="not ACTIVE"):
        merge_identities(
            build.session, loser.id, survivor.id, expected_revision=loser.revision,
            new_id=build.new_id, clock=build.clock,
        )  # fmt: skip


@pytest.mark.parametrize("survivor_state", ["PENDING", "FORGOTTEN"])
def test_merge_rejects_a_non_active_survivor(build: ModelFactory, survivor_state: str) -> None:
    survivor = build.identity(state=survivor_state)
    loser = build.identity()
    with pytest.raises(IdentityManagerError, match="not ACTIVE"):
        merge_identities(
            build.session, loser.id, survivor.id, expected_revision=loser.revision,
            new_id=build.new_id, clock=build.clock,
        )  # fmt: skip


def test_merge_rejects_a_stale_revision(build: ModelFactory) -> None:
    survivor = build.identity()
    loser = build.identity()
    with pytest.raises(StaleRevisionError):
        merge_identities(
            build.session, loser.id, survivor.id, expected_revision=99,
            new_id=build.new_id, clock=build.clock,
        )  # fmt: skip


def test_a_stale_revision_merge_still_flushes_its_reconciliation_before_raising(
    build: ModelFactory,
) -> None:
    """Unlike the other rejection paths (`test_a_rejected_merge_leaves_no_partial_state`), a
    stale-revision merge is caught last: the revision check on the loser's own row is the final
    step (matching §114's ordering), so the representation move and the Evidence/Lineage rows are
    already flushed to this session by the time `StaleRevisionError` is raised. This is documented,
    known behaviour (see the implementation entry) — a caller must roll back its transaction on
    any `IdentityManagerError`, which discards this flushed-but-uncommitted work; this test only
    pins down that the flush happens, so a future refactor can't silently change the ordering."""
    survivor = build.identity()
    loser = build.identity()
    space = build.representation_space()
    representation = build.representation(
        representation_space_id=space.id, identity_id=loser.id, state="ACTIVE", ann_key=1
    )

    with pytest.raises(StaleRevisionError):
        merge_identities(
            build.session, loser.id, survivor.id, expected_revision=99,
            new_id=build.new_id, clock=build.clock,
        )  # fmt: skip

    build.session.expire_all()
    moved = build.session.get(Representation, representation.id)
    assert moved is not None
    assert moved.identity_id == survivor.id  # already flushed, pending the caller's rollback
    assert build.session.scalars(select(Evidence)).all() != []


@pytest.mark.parametrize(
    "break_it", ["unknown_survivor", "unknown_loser", "self_merge", "inactive_loser"]
)
def test_a_rejected_merge_leaves_no_partial_state(build: ModelFactory, break_it: str) -> None:
    survivor = build.identity()
    loser = build.identity()
    space = build.representation_space()
    representation = build.representation(
        representation_space_id=space.id, identity_id=loser.id, state="ACTIVE", ann_key=1
    )

    calls = {
        "unknown_survivor": lambda: merge_identities(
            build.session, loser.id, build.new_id(), expected_revision=loser.revision,
            new_id=build.new_id, clock=build.clock,
        ),
        "unknown_loser": lambda: merge_identities(
            build.session, build.new_id(), survivor.id, expected_revision=1,
            new_id=build.new_id, clock=build.clock,
        ),
        "self_merge": lambda: merge_identities(
            build.session, loser.id, loser.id, expected_revision=loser.revision,
            new_id=build.new_id, clock=build.clock,
        ),
        "inactive_loser": lambda: merge_identities(
            build.session, build.identity(state="PENDING").id, survivor.id, expected_revision=1,
            new_id=build.new_id, clock=build.clock,
        ),
    }  # fmt: skip

    with pytest.raises(IdentityManagerError):
        calls[break_it]()

    build.session.expire_all()
    unchanged = build.session.get(Representation, representation.id)
    assert unchanged is not None
    assert unchanged.identity_id == loser.id  # never moved
    assert build.session.scalars(select(Evidence)).all() == []
    assert build.session.scalars(select(IdentityLineage)).all() == []


def test_chained_pairwise_merges_reach_one_survivor(build: ModelFactory) -> None:
    """A three-or-more-way merge is composed from pairwise calls (see merge_identities'
    docstring): merging B into A, then C into A, must leave both B and C pointing at A."""
    a = build.identity()
    b = build.identity()
    c = build.identity()

    merge_identities(
        build.session, b.id, a.id, expected_revision=b.revision,
        new_id=build.new_id, clock=build.clock,
    )  # fmt: skip
    merge_identities(
        build.session, c.id, a.id, expected_revision=c.revision,
        new_id=build.new_id, clock=build.clock,
    )  # fmt: skip

    build.session.expire_all()
    b_after = build.session.get(type(a), b.id)
    c_after = build.session.get(type(a), c.id)
    assert b_after is not None
    assert b_after.merged_into_identity_id == a.id
    assert c_after is not None
    assert c_after.merged_into_identity_id == a.id
    assert len(build.session.scalars(select(IdentityLineage)).all()) == 2


# --- split (TST-016) -----------------------------------------------------------------------------


def test_split_creates_an_active_identity_and_moves_only_the_selected_representations(
    build: ModelFactory,
) -> None:
    source = build.identity()
    space = build.representation_space()
    keep_a = build.representation(
        representation_space_id=space.id, identity_id=source.id, state="ACTIVE", ann_key=1
    )
    keep_b = build.representation(
        representation_space_id=space.id, identity_id=source.id, state="ACTIVE", ann_key=2
    )
    move_c = build.representation(
        representation_space_id=space.id, identity_id=source.id, state="ACTIVE", ann_key=3
    )

    new_identity = split_identity(
        build.session, source.id, [move_c.id], new_id=build.new_id, clock=build.clock
    )

    assert new_identity.state == "ACTIVE"
    assert new_identity.activated_at is not None
    assert new_identity.id != source.id
    build.session.expire_all()
    moved = build.session.get(Representation, move_c.id)
    stayed_a = build.session.get(Representation, keep_a.id)
    stayed_b = build.session.get(Representation, keep_b.id)
    assert moved is not None
    assert moved.identity_id == new_identity.id
    assert moved.ann_key == 3  # untouched
    assert stayed_a is not None
    assert stayed_a.identity_id == source.id
    assert stayed_b is not None
    assert stayed_b.identity_id == source.id
    assert build.session.scalars(select(IndexOperation)).all() == []


def test_split_source_remains_active_and_unchanged(build: ModelFactory) -> None:
    """The source identity is not retired by a split: it keeps its own id, state and revision
    (identity-and-memory-model-v1.md §19.2 shows the source keeping some of its evidence)."""
    source = build.identity()
    space = build.representation_space()
    kept = build.representation(
        representation_space_id=space.id, identity_id=source.id, state="ACTIVE", ann_key=1
    )
    moved = build.representation(
        representation_space_id=space.id, identity_id=source.id, state="ACTIVE", ann_key=2
    )
    snapshot = (source.id, source.state, source.revision, source.updated_at)

    split_identity(build.session, source.id, [moved.id], new_id=build.new_id, clock=build.clock)

    build.session.expire_all()
    unchanged_source = build.session.get(type(source), source.id)
    assert unchanged_source is not None
    assert (
        unchanged_source.id,
        unchanged_source.state,
        unchanged_source.revision,
        unchanged_source.updated_at,
    ) == snapshot
    still_kept = build.session.get(Representation, kept.id)
    assert still_kept is not None
    assert still_kept.identity_id == source.id


def test_split_records_evidence_and_lineage(build: ModelFactory) -> None:
    source = build.identity()
    space = build.representation_space()
    moved = build.representation(
        representation_space_id=space.id, identity_id=source.id, state="ACTIVE", ann_key=1
    )

    new_identity = split_identity(
        build.session, source.id, [moved.id], new_id=build.new_id, clock=build.clock
    )

    evidence = build.session.scalars(
        select(Evidence).where(Evidence.kind == "IDENTITY_SPLIT")
    ).one()
    assert evidence.subject_identity_id == new_identity.id
    assert evidence.payload_json["split_from_identity_id"] == str(source.id)
    assert evidence.payload_json["moved_representation_ids"] == [str(moved.id)]

    lineage = build.session.scalars(select(IdentityLineage)).one()
    assert (lineage.from_identity_id, lineage.to_identity_id, lineage.kind) == (
        source.id,
        new_identity.id,
        "SPLIT_FROM",
    )
    assert lineage.evidence_id == evidence.id


def test_split_may_move_every_representation_away(build: ModelFactory) -> None:
    """Not restricted: nothing requires the source to retain at least one representation."""
    source = build.identity()
    space = build.representation_space()
    only = build.representation(
        representation_space_id=space.id, identity_id=source.id, state="ACTIVE", ann_key=1
    )
    new_identity = split_identity(
        build.session, source.id, [only.id], new_id=build.new_id, clock=build.clock
    )
    build.session.expire_all()
    moved = build.session.get(Representation, only.id)
    assert moved is not None
    assert moved.identity_id == new_identity.id


def test_split_rejects_an_empty_selection(build: ModelFactory) -> None:
    source = build.identity()
    with pytest.raises(IdentityManagerError, match="at least one"):
        split_identity(build.session, source.id, [], new_id=build.new_id, clock=build.clock)


def test_split_rejects_an_unknown_representation(build: ModelFactory) -> None:
    source = build.identity()
    with pytest.raises(IdentityManagerError, match="does not exist"):
        split_identity(
            build.session, source.id, [uuid.uuid4()], new_id=build.new_id, clock=build.clock
        )


def test_split_rejects_a_representation_belonging_to_a_different_identity(
    build: ModelFactory,
) -> None:
    source = build.identity()
    other = build.identity()
    foreign = build.representation(identity_id=other.id, state="ACTIVE", ann_key=1)
    with pytest.raises(IdentityManagerError, match="does not belong"):
        split_identity(
            build.session, source.id, [foreign.id], new_id=build.new_id, clock=build.clock
        )


def test_split_rejects_a_pending_representation(build: ModelFactory) -> None:
    source = build.identity()
    pending = build.representation(identity_id=None, state="PENDING")
    with pytest.raises(IdentityManagerError, match="does not belong"):
        split_identity(
            build.session, source.id, [pending.id], new_id=build.new_id, clock=build.clock
        )


def test_split_rejects_an_unknown_source_identity(build: ModelFactory) -> None:
    with pytest.raises(IdentityManagerError, match="does not exist"):
        split_identity(
            build.session, uuid.uuid4(), [uuid.uuid4()], new_id=build.new_id, clock=build.clock
        )


def test_split_rejects_a_pending_representation_belonging_to_the_source(
    build: ModelFactory,
) -> None:
    source = build.identity()
    space = build.representation_space()
    pending = build.representation(
        representation_space_id=space.id, identity_id=source.id, state="PENDING"
    )
    with pytest.raises(IdentityManagerError, match="not ACTIVE"):
        split_identity(
            build.session, source.id, [pending.id], new_id=build.new_id, clock=build.clock
        )


def test_split_rejects_a_non_active_source_identity(build: ModelFactory) -> None:
    source = build.identity(state="PENDING")
    with pytest.raises(IdentityManagerError, match="not ACTIVE"):
        split_identity(
            build.session, source.id, [uuid.uuid4()], new_id=build.new_id, clock=build.clock
        )


def test_a_rejected_split_creates_no_identity_and_moves_nothing(build: ModelFactory) -> None:
    source = build.identity()
    space = build.representation_space()
    valid = build.representation(
        representation_space_id=space.id, identity_id=source.id, state="ACTIVE", ann_key=1
    )
    other = build.identity()
    foreign = build.representation(identity_id=other.id, state="ACTIVE", ann_key=2)

    with pytest.raises(IdentityManagerError, match="does not belong"):
        split_identity(
            build.session, source.id, [valid.id, foreign.id], new_id=build.new_id, clock=build.clock
        )

    build.session.expire_all()
    unchanged_valid = build.session.get(Representation, valid.id)
    assert unchanged_valid is not None
    assert unchanged_valid.identity_id == source.id
    assert build.session.scalars(select(Evidence)).all() == []
    assert build.session.scalars(select(IdentityLineage)).all() == []
