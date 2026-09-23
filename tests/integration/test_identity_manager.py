"""Identity Manager use-case tests (M1 PR 3: TST-011, TST-012, TST-017, TST-018).

Covers the critical invariants from TESTING_STRATEGY.md §5 that these use cases are
responsible for: ID-01 (stable identifiers), ID-02 (authoritative assignment consistency),
ID-06 (domain authority), OBS-02/OBS-03 (source provenance is preserved and never rewritten),
and JOB-independent "a failed operation is not represented as committed" for identity/evidence.
"""

import uuid

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from backend.app.identities.models import (
    Evidence,
    EvidenceKind,
    EvidenceRepresentation,
    EvidenceRepresentationRole,
    Identity,
)
from backend.app.identities.use_cases import (
    IdentityManagerError,
    StaleRevisionError,
    activate_identity,
    allocate_ann_key,
    assign_representation_to_identity,
    create_pending_identity,
)
from backend.app.memory.models import IndexOperation, Representation
from tests.factories.models import ModelFactory

# --- create_pending_identity (TST-011) ---------------------------------------------------------


def test_create_pending_identity_produces_a_valid_row(build: ModelFactory) -> None:
    run = build.run()
    identity = create_pending_identity(
        build.session, new_id=build.new_id, clock=build.clock, created_by_processing_run_id=run.id
    )
    assert isinstance(identity.id, uuid.UUID)
    assert identity.id.version == 4
    assert identity.state == "PENDING"
    assert identity.revision == 1
    assert identity.created_by_processing_run_id == run.id
    assert identity.activated_at is None
    assert identity.created_at == identity.updated_at == build.clock()


def test_created_identity_is_immediately_visible_by_its_id(build: ModelFactory) -> None:
    run = build.run()
    created = create_pending_identity(
        build.session, new_id=build.new_id, clock=build.clock, created_by_processing_run_id=run.id
    )
    fetched = build.session.get(Identity, created.id)
    assert fetched is not None
    assert fetched.id == created.id


# --- activate_identity (TST-011: stable id across lifecycle; ID-01) ----------------------------


def _pending(build: ModelFactory) -> Identity:
    return create_pending_identity(
        build.session,
        new_id=build.new_id,
        clock=build.clock,
        created_by_processing_run_id=build.run().id,
    )


def test_activation_changes_state_but_never_the_identifier(build: ModelFactory) -> None:
    identity = _pending(build)
    original_id = identity.id
    activated = activate_identity(
        build.session, identity.id, expected_revision=1, clock=build.clock
    )
    assert activated.id == original_id  # ID-01: renaming/activation never changes the identifier
    assert activated.state == "ACTIVE"
    assert activated.activated_at == build.clock()
    assert activated.revision == 2


def test_activation_rejects_a_stale_revision(build: ModelFactory) -> None:
    identity = _pending(build)
    activate_identity(build.session, identity.id, expected_revision=1, clock=build.clock)
    with pytest.raises(StaleRevisionError, match="expected 1"):
        activate_identity(build.session, identity.id, expected_revision=1, clock=build.clock)


def test_activation_rejects_an_already_active_identity_even_with_the_current_revision(
    build: ModelFactory,
) -> None:
    identity = _pending(build)
    activated = activate_identity(
        build.session, identity.id, expected_revision=1, clock=build.clock
    )
    with pytest.raises(IdentityManagerError, match="not PENDING"):
        activate_identity(
            build.session, identity.id, expected_revision=activated.revision, clock=build.clock
        )


def test_conflict_diagnosis_reflects_the_database_not_a_stale_cached_copy(
    build: ModelFactory,
) -> None:
    """Regression: `_raise_activation_conflict` must re-read the row itself. The identity map can
    hold a stale copy of it (here, deliberately desynced from the database), and diagnosing the
    conflict from that stale copy instead of the database would misreport it: a stale-but-still-
    matching-`expected_revision` cached object would wrongly reach the "not PENDING" branch
    instead of correctly raising `StaleRevisionError`."""
    identity = _pending(build)
    # Simulate a concurrent writer: change the row in the database without touching this
    # session's in-memory copy of it (synchronize_session=False suppresses the ORM's own sync).
    build.session.execute(
        update(Identity).where(Identity.id == identity.id).values(revision=2),
        execution_options={"synchronize_session": False},
    )
    build.session.flush()

    with pytest.raises(StaleRevisionError, match="expected 1"):
        activate_identity(build.session, identity.id, expected_revision=1, clock=build.clock)

    # The in-memory object must reflect reality (still PENDING, revision 2 — activation did not
    # happen), not a phantom ACTIVE/revision-3 state synthesised from its own stale attributes.
    build.session.expire_all()
    reloaded = build.session.get(Identity, identity.id)
    assert reloaded is not None
    assert (reloaded.state, reloaded.revision) == ("PENDING", 2)


def test_activation_rejects_an_unknown_identity(build: ModelFactory) -> None:
    with pytest.raises(IdentityManagerError, match="does not exist"):
        activate_identity(build.session, build.new_id(), expected_revision=1, clock=build.clock)


def test_a_rejected_activation_leaves_the_identity_untouched(build: ModelFactory) -> None:
    identity = _pending(build)
    with pytest.raises(StaleRevisionError):
        activate_identity(build.session, identity.id, expected_revision=99, clock=build.clock)
    build.session.expire_all()
    unchanged = build.session.get(Identity, identity.id)
    assert unchanged is not None
    assert (unchanged.state, unchanged.revision, unchanged.activated_at) == ("PENDING", 1, None)


# --- allocate_ann_key ---------------------------------------------------------------------------


def test_ann_keys_are_sequential_and_per_space(build: ModelFactory) -> None:
    space_a = build.representation_space()
    space_b = build.representation_space()
    assert [allocate_ann_key(build.session, space_a.id) for _ in range(3)] == [1, 2, 3]
    assert allocate_ann_key(build.session, space_b.id) == 1  # a fresh space starts at 1
    assert allocate_ann_key(build.session, space_a.id) == 4  # space_a's sequence kept counting


# --- assign_representation_to_identity (TST-012, TST-018) ---------------------------------------


def _active_identity(build: ModelFactory) -> Identity:
    identity = _pending(build)
    return activate_identity(build.session, identity.id, expected_revision=1, clock=build.clock)


def test_assignment_activates_the_representation_with_evidence_and_an_index_intent(
    build: ModelFactory,
) -> None:
    identity = _active_identity(build)
    representation = build.representation()

    result = assign_representation_to_identity(
        build.session,
        representation.id,
        identity.id,
        new_id=build.new_id,
        clock=build.clock,
        evidence_kind=EvidenceKind.IDENTITY_CREATED,
    )

    assert result.state == "ACTIVE"
    assert result.identity_id == identity.id
    assert result.ann_key == 1
    assert result.activated_at == build.clock()

    evidence = build.session.scalars(select(Evidence)).one()
    assert evidence.kind == "IDENTITY_CREATED"
    assert evidence.subject_identity_id == identity.id
    assert evidence.payload_json["representation_id"] == str(representation.id)

    link = build.session.scalars(select(EvidenceRepresentation)).one()
    assert (link.evidence_id, link.representation_id, link.role) == (
        evidence.id,
        representation.id,
        EvidenceRepresentationRole.SUBJECT.value,
    )

    operation = build.session.scalars(select(IndexOperation)).one()
    assert (operation.representation_id, operation.operation, operation.state) == (
        representation.id,
        "ADD",
        "PENDING",
    )


def test_two_representations_may_be_assigned_to_the_same_identity(build: ModelFactory) -> None:
    """ID-02: many representations may authoritatively point to one identity; that is not a
    conflict. A conflict would be one representation with two different active identities,
    which UNIQUE(observation_id, representation_space_id) plus this use case's PENDING
    precondition make impossible (an already-assigned representation cannot be assigned again).
    """
    identity = _active_identity(build)
    space = build.representation_space()
    first = build.representation(representation_space_id=space.id)
    second = build.representation(representation_space_id=space.id)

    for representation in (first, second):
        assign_representation_to_identity(
            build.session,
            representation.id,
            identity.id,
            new_id=build.new_id,
            clock=build.clock,
            evidence_kind=EvidenceKind.IDENTITY_MATCHED,
        )

    ann_keys = build.session.scalars(
        select(Representation.ann_key).where(Representation.identity_id == identity.id)
    ).all()
    assert sorted(ann_keys, key=lambda key: key or 0) == [1, 2]


def test_assignment_rejects_a_representation_that_is_not_pending(build: ModelFactory) -> None:
    identity = _active_identity(build)
    representation = build.representation()
    assign_representation_to_identity(
        build.session,
        representation.id,
        identity.id,
        new_id=build.new_id,
        clock=build.clock,
        evidence_kind=EvidenceKind.IDENTITY_CREATED,
    )
    with pytest.raises(IdentityManagerError, match="not PENDING"):
        assign_representation_to_identity(
            build.session,
            representation.id,
            identity.id,
            new_id=build.new_id,
            clock=build.clock,
            evidence_kind=EvidenceKind.IDENTITY_MATCHED,
        )


@pytest.mark.parametrize("identity_state", ["PENDING", "MERGED", "FORGOTTEN", "DELETED"])
def test_assignment_rejects_a_non_active_identity(build: ModelFactory, identity_state: str) -> None:
    if identity_state == "MERGED":
        identity = build.identity(state="MERGED", merged_into_identity_id=build.identity().id)
    else:
        identity = build.identity(state=identity_state)
    representation = build.representation()

    with pytest.raises(IdentityManagerError, match="not ACTIVE"):
        assign_representation_to_identity(
            build.session,
            representation.id,
            identity.id,
            new_id=build.new_id,
            clock=build.clock,
            evidence_kind=EvidenceKind.IDENTITY_CREATED,
        )


def test_an_identity_can_only_be_created_once(build: ModelFactory) -> None:
    identity = _active_identity(build)
    space = build.representation_space()
    first = build.representation(representation_space_id=space.id)
    second = build.representation(representation_space_id=space.id)

    assign_representation_to_identity(
        build.session, first.id, identity.id, new_id=build.new_id, clock=build.clock,
        evidence_kind=EvidenceKind.IDENTITY_CREATED,
    )  # fmt: skip
    with pytest.raises(IdentityManagerError, match="already has IDENTITY_CREATED"):
        assign_representation_to_identity(
            build.session, second.id, identity.id, new_id=build.new_id, clock=build.clock,
            evidence_kind=EvidenceKind.IDENTITY_CREATED,
        )  # fmt: skip

    # The rejection left the second representation untouched and consumed no ann_key for it.
    build.session.expire_all()
    unchanged = build.session.get(Representation, second.id)
    assert unchanged is not None
    assert unchanged.state == "PENDING"
    assert allocate_ann_key(build.session, space.id) == 2  # only the first assignment used key 1


def test_assignment_rejects_an_evidence_kind_outside_the_two_it_authors(
    build: ModelFactory,
) -> None:
    identity = _active_identity(build)
    representation = build.representation()
    with pytest.raises(IdentityManagerError, match="IDENTITY_CREATED or IDENTITY_MATCHED"):
        assign_representation_to_identity(
            build.session,
            representation.id,
            identity.id,
            new_id=build.new_id,
            clock=build.clock,
            evidence_kind=EvidenceKind.USER_CORRECTION,
        )


@pytest.mark.parametrize(
    "break_it",
    ["bad_evidence_kind", "unknown_representation", "unknown_identity", "inactive_identity"],
)
def test_a_rejected_assignment_leaves_no_partial_state(build: ModelFactory, break_it: str) -> None:
    """TST-018 / JOB-05-equivalent: a failed use case must not leak an ann_key, an Evidence row,
    or an IndexOperation. Ordering matters here: allocation happens only after every
    precondition passes (see use_cases.py), and this test guards that ordering."""
    space = build.representation_space()
    representation = build.representation(representation_space_id=space.id)
    identity = _active_identity(build)

    calls = {
        "bad_evidence_kind": lambda: assign_representation_to_identity(
            build.session, representation.id, identity.id, new_id=build.new_id, clock=build.clock,
            evidence_kind=EvidenceKind.USER_CORRECTION,
        ),
        "unknown_representation": lambda: assign_representation_to_identity(
            build.session, build.new_id(), identity.id, new_id=build.new_id, clock=build.clock,
            evidence_kind=EvidenceKind.IDENTITY_CREATED,
        ),
        "unknown_identity": lambda: assign_representation_to_identity(
            build.session, representation.id, build.new_id(),
            new_id=build.new_id, clock=build.clock,
            evidence_kind=EvidenceKind.IDENTITY_CREATED,
        ),
        "inactive_identity": lambda: assign_representation_to_identity(
            build.session, representation.id, _pending(build).id, new_id=build.new_id,
            clock=build.clock, evidence_kind=EvidenceKind.IDENTITY_CREATED,
        ),
    }  # fmt: skip

    with pytest.raises(IdentityManagerError):
        calls[break_it]()

    build.session.expire_all()
    unchanged = build.session.get(Representation, representation.id)
    assert unchanged is not None
    assert (unchanged.state, unchanged.identity_id, unchanged.ann_key) == ("PENDING", None, None)
    assert build.session.scalars(select(Evidence)).all() == []
    assert build.session.scalars(select(IndexOperation)).all() == []
    # No ann_key was consumed either: the next real allocation still starts at 1.
    assert allocate_ann_key(build.session, space.id) == 1


# --- source provenance (TST-017 / OBS-02, OBS-03) -----------------------------------------------


def test_assigning_an_identity_never_touches_observation_provenance(
    build: ModelFactory, db_session: Session
) -> None:
    run = build.run()
    observation = build.observation(run)
    before = (
        observation.source_id,
        observation.processing_run_id,
        observation.execution_segment_id,
        observation.sequence_in_run,
        observation.created_at,
    )

    identity = _active_identity(build)
    representation = build.representation(observation)
    assign_representation_to_identity(
        build.session,
        representation.id,
        identity.id,
        new_id=build.new_id,
        clock=build.clock,
        evidence_kind=EvidenceKind.IDENTITY_CREATED,
    )

    build.session.expire_all()
    after = build.session.get(type(observation), observation.id)
    assert after is not None
    assert (
        after.source_id,
        after.processing_run_id,
        after.execution_segment_id,
        after.sequence_in_run,
        after.created_at,
    ) == before


def test_each_observation_keeps_its_own_run_and_source(build: ModelFactory) -> None:
    """OBS-02: provenance is per-observation, not inferred from whatever ran most recently."""
    first_run = build.run()
    second_run = build.run()
    first = build.observation(first_run)
    second = build.observation(second_run)

    assert first.source_id == first_run.source_id
    assert second.source_id == second_run.source_id
    assert first.source_id != second.source_id
    assert first.processing_run_id != second.processing_run_id


# --- historical evidence (TST-018) ---------------------------------------------------------------


def test_evidence_is_append_only_across_later_operations(build: ModelFactory) -> None:
    identity = _active_identity(build)
    space = build.representation_space()
    first_representation = build.representation(representation_space_id=space.id)
    assign_representation_to_identity(
        build.session,
        first_representation.id,
        identity.id,
        new_id=build.new_id,
        clock=build.clock,
        evidence_kind=EvidenceKind.IDENTITY_CREATED,
    )
    first_evidence = build.session.scalars(select(Evidence)).one()
    snapshot = (
        first_evidence.id,
        first_evidence.kind,
        first_evidence.payload_json,
        first_evidence.created_at,
    )

    build.clock.advance(seconds=5)
    second_representation = build.representation(representation_space_id=space.id)
    assign_representation_to_identity(
        build.session,
        second_representation.id,
        identity.id,
        new_id=build.new_id,
        clock=build.clock,
        evidence_kind=EvidenceKind.IDENTITY_MATCHED,
    )

    build.session.expire_all()
    unchanged_first = build.session.get(Evidence, first_evidence.id)
    assert unchanged_first is not None
    assert (
        unchanged_first.id,
        unchanged_first.kind,
        unchanged_first.payload_json,
        unchanged_first.created_at,
    ) == snapshot
    assert len(build.session.scalars(select(Evidence)).all()) == 2


def test_evidence_kind_records_whether_the_identity_was_new_or_matched(build: ModelFactory) -> None:
    identity = _active_identity(build)
    space = build.representation_space()
    created_rep = build.representation(representation_space_id=space.id)
    matched_rep = build.representation(representation_space_id=space.id)

    assign_representation_to_identity(
        build.session, created_rep.id, identity.id, new_id=build.new_id, clock=build.clock,
        evidence_kind=EvidenceKind.IDENTITY_CREATED,
    )  # fmt: skip
    assign_representation_to_identity(
        build.session, matched_rep.id, identity.id, new_id=build.new_id, clock=build.clock,
        evidence_kind=EvidenceKind.IDENTITY_MATCHED,
    )  # fmt: skip

    rows = build.session.execute(
        select(EvidenceRepresentation.representation_id, Evidence.kind).join(
            Evidence, Evidence.id == EvidenceRepresentation.evidence_id
        )
    ).all()
    kinds_by_representation: dict[uuid.UUID, str] = {row[0]: row[1] for row in rows}
    assert kinds_by_representation[created_rep.id] == "IDENTITY_CREATED"
    assert kinds_by_representation[matched_rep.id] == "IDENTITY_MATCHED"
