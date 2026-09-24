"""Person and Identity-Person association use-case tests (M1 PR 4: TST-013, TST-014).

TST-013 (ID-03): a correction is calling `assign_identity_to_person` again with a different
person; the previous association must become SUPERSEDED, never deleted, and its own Evidence
must be untouched. TST-014: renaming a Person changes only its display/normalized name — it
must never change any identifier, and it must never touch an Identity's own state, evidence or
associations.
"""

import pytest
from sqlalchemy import select

from backend.app.identities.models import Evidence
from backend.app.identities.use_cases import IdentityManagerError, StaleRevisionError
from backend.app.people.models import IdentityPersonAssociation, Person
from backend.app.people.use_cases import (
    assign_identity_to_person,
    remove_identity_from_person,
    rename_person,
)
from tests.factories.models import ModelFactory

# --- assignment and correction (TST-013) --------------------------------------------------------


def test_assignment_creates_an_active_association_with_founding_evidence(
    build: ModelFactory,
) -> None:
    identity = build.identity()
    person = build.person()

    association = assign_identity_to_person(
        build.session, identity.id, person.id, new_id=build.new_id, clock=build.clock
    )

    assert association.state == "ACTIVE"
    assert association.person_id == person.id
    assert association.ended_at is None

    evidence = build.session.get(Evidence, association.evidence_id)
    assert evidence is not None
    assert evidence.kind == "IDENTITY_ASSIGNED_TO_PERSON"
    assert evidence.subject_identity_id == identity.id
    assert evidence.subject_person_id == person.id
    assert evidence.payload_json["previous_person_id"] is None


def test_reassigning_to_a_different_person_corrects_the_link_and_preserves_history(
    build: ModelFactory,
) -> None:
    identity = build.identity()
    alice = build.person(display_name="Alice")
    bob = build.person(display_name="Bob")

    first = assign_identity_to_person(
        build.session, identity.id, alice.id, new_id=build.new_id, clock=build.clock
    )
    first_evidence_id = first.evidence_id
    build.clock.advance(seconds=1)
    second = assign_identity_to_person(
        build.session, identity.id, bob.id, new_id=build.new_id, clock=build.clock
    )

    # The correction: a new active association, to the corrected person.
    assert second.state == "ACTIVE"
    assert second.person_id == bob.id
    assert second.evidence_id != first_evidence_id

    # The earlier decision is preserved, not deleted or overwritten (ID-03 / TST-013).
    build.session.expire_all()
    superseded = build.session.get(IdentityPersonAssociation, first.id)
    assert superseded is not None
    assert superseded.state == "SUPERSEDED"
    assert superseded.person_id == alice.id  # still records who it WAS, not who it became
    assert superseded.ended_at == build.clock()

    original_evidence = build.session.get(Evidence, first_evidence_id)
    assert original_evidence is not None
    assert original_evidence.subject_person_id == alice.id  # untouched, still says Alice

    correction_evidence = build.session.get(Evidence, second.evidence_id)
    assert correction_evidence is not None
    assert correction_evidence.payload_json["previous_person_id"] == str(alice.id)

    # Exactly one ACTIVE association for this identity at a time.
    active_ids = build.session.scalars(
        select(IdentityPersonAssociation.id).where(
            IdentityPersonAssociation.identity_id == identity.id,
            IdentityPersonAssociation.state == "ACTIVE",
        )
    ).all()
    assert active_ids == [second.id]
    assert build.session.get(Person, alice.id) is not None  # Alice herself is untouched


def test_assignment_rejects_reassigning_to_the_same_person(build: ModelFactory) -> None:
    identity = build.identity()
    person = build.person()
    assign_identity_to_person(
        build.session, identity.id, person.id, new_id=build.new_id, clock=build.clock
    )
    with pytest.raises(IdentityManagerError, match="already linked"):
        assign_identity_to_person(
            build.session, identity.id, person.id, new_id=build.new_id, clock=build.clock
        )


@pytest.mark.parametrize("identity_state", ["PENDING", "FORGOTTEN", "DELETED"])
def test_assignment_rejects_a_non_active_identity(build: ModelFactory, identity_state: str) -> None:
    identity = build.identity(state=identity_state)
    person = build.person()
    with pytest.raises(IdentityManagerError, match="not ACTIVE"):
        assign_identity_to_person(
            build.session, identity.id, person.id, new_id=build.new_id, clock=build.clock
        )


@pytest.mark.parametrize("person_state", ["RECYCLED", "DELETED"])
def test_assignment_rejects_a_non_active_person(build: ModelFactory, person_state: str) -> None:
    identity = build.identity()
    person = build.person(state=person_state)
    with pytest.raises(IdentityManagerError, match="not ACTIVE"):
        assign_identity_to_person(
            build.session, identity.id, person.id, new_id=build.new_id, clock=build.clock
        )


@pytest.mark.parametrize(
    "break_it", ["unknown_identity", "unknown_person", "inactive_identity", "inactive_person"]
)
def test_a_rejected_assignment_leaves_no_partial_state(build: ModelFactory, break_it: str) -> None:
    identity = build.identity()
    person = build.person()

    calls = {
        "unknown_identity": lambda: assign_identity_to_person(
            build.session, build.new_id(), person.id, new_id=build.new_id, clock=build.clock
        ),
        "unknown_person": lambda: assign_identity_to_person(
            build.session, identity.id, build.new_id(), new_id=build.new_id, clock=build.clock
        ),
        "inactive_identity": lambda: assign_identity_to_person(
            build.session, build.identity(state="PENDING").id, person.id,
            new_id=build.new_id, clock=build.clock,
        ),
        "inactive_person": lambda: assign_identity_to_person(
            build.session, identity.id, build.person(state="DELETED").id,
            new_id=build.new_id, clock=build.clock,
        ),
    }  # fmt: skip

    with pytest.raises(IdentityManagerError):
        calls[break_it]()

    assert build.session.scalars(select(Evidence)).all() == []
    assert build.session.scalars(select(IdentityPersonAssociation)).all() == []


def test_a_person_may_have_many_active_identities(build: ModelFactory) -> None:
    person = build.person()
    first_identity = build.identity()
    second_identity = build.identity()

    assign_identity_to_person(
        build.session, first_identity.id, person.id, new_id=build.new_id, clock=build.clock
    )
    assign_identity_to_person(
        build.session, second_identity.id, person.id, new_id=build.new_id, clock=build.clock
    )

    active_identities = build.session.scalars(
        select(IdentityPersonAssociation.identity_id).where(
            IdentityPersonAssociation.person_id == person.id,
            IdentityPersonAssociation.state == "ACTIVE",
        )
    ).all()
    assert sorted(active_identities, key=str) == sorted(
        [first_identity.id, second_identity.id], key=str
    )


# --- removal (TST-013) ---------------------------------------------------------------------------


def test_removal_ends_the_association_and_records_evidence(build: ModelFactory) -> None:
    identity = build.identity()
    person = build.person()
    association = assign_identity_to_person(
        build.session, identity.id, person.id, new_id=build.new_id, clock=build.clock
    )
    build.clock.advance(seconds=1)

    removed = remove_identity_from_person(
        build.session, identity.id, new_id=build.new_id, clock=build.clock
    )

    assert removed.id == association.id
    assert removed.state == "REMOVED"
    assert removed.ended_at == build.clock()
    assert removed.person_id == person.id  # still records who it was linked to

    evidence = build.session.scalars(
        select(Evidence).where(Evidence.kind == "IDENTITY_REMOVED_FROM_PERSON")
    ).one()
    assert evidence.subject_identity_id == identity.id
    assert evidence.subject_person_id == person.id


def test_removal_rejects_when_no_active_association_exists(build: ModelFactory) -> None:
    identity = build.identity()
    with pytest.raises(IdentityManagerError, match="no active person association"):
        remove_identity_from_person(
            build.session, identity.id, new_id=build.new_id, clock=build.clock
        )


def test_removal_does_not_require_an_active_identity(build: ModelFactory) -> None:
    """Unlike assignment, removal only ends an existing row, so it is not gated on identity
    state — see the docstring in people/use_cases.py for why that asymmetry is deliberate.

    The association is built directly (not via assign_identity_to_person, which itself requires
    an ACTIVE identity) to simulate an identity that changed state after being linked."""
    identity = build.identity(state="FORGOTTEN")
    person = build.person()
    build.association(identity_id=identity.id, person_id=person.id)

    removed = remove_identity_from_person(
        build.session, identity.id, new_id=build.new_id, clock=build.clock
    )
    assert removed.state == "REMOVED"


# --- rename (TST-014) ----------------------------------------------------------------------------


def test_rename_changes_the_display_and_normalized_name(build: ModelFactory) -> None:
    person = build.person(display_name="Alice")
    renamed = rename_person(
        build.session, person.id, "Alicia Smith", expected_revision=1, clock=build.clock
    )
    assert renamed.display_name == "Alicia Smith"
    assert renamed.normalized_name == "alicia smith"
    assert renamed.revision == 2
    assert renamed.updated_at == build.clock()


def test_rename_never_changes_the_person_identifier(build: ModelFactory) -> None:
    person = build.person()
    original_id = person.id
    renamed = rename_person(
        build.session, person.id, "New Name", expected_revision=1, clock=build.clock
    )
    assert renamed.id == original_id


def test_rename_rejects_a_stale_revision(build: ModelFactory) -> None:
    person = build.person()
    rename_person(build.session, person.id, "First", expected_revision=1, clock=build.clock)
    with pytest.raises(StaleRevisionError, match="expected 1"):
        rename_person(build.session, person.id, "Second", expected_revision=1, clock=build.clock)


def test_rename_rejects_an_unknown_person(build: ModelFactory) -> None:
    with pytest.raises(IdentityManagerError, match="does not exist"):
        rename_person(build.session, build.new_id(), "Name", expected_revision=1, clock=build.clock)


def test_a_rejected_rename_leaves_the_person_untouched(build: ModelFactory) -> None:
    person = build.person(display_name="Alice")
    with pytest.raises(StaleRevisionError):
        rename_person(build.session, person.id, "Wrong", expected_revision=99, clock=build.clock)
    build.session.expire_all()
    unchanged = build.session.get(Person, person.id)
    assert unchanged is not None
    assert (unchanged.display_name, unchanged.revision) == ("Alice", 1)


def test_renaming_a_person_does_not_touch_the_linked_identity_or_its_evidence(
    build: ModelFactory,
) -> None:
    """TST-014: renaming is scoped to the Person row. The Identity it is linked to, and the
    Evidence/association history that names this Person by id, must be completely unaffected."""
    identity = build.identity()
    person = build.person(display_name="Alice")
    association = assign_identity_to_person(
        build.session, identity.id, person.id, new_id=build.new_id, clock=build.clock
    )
    identity_snapshot = (identity.id, identity.state, identity.revision, identity.updated_at)

    rename_person(build.session, person.id, "Alicia", expected_revision=1, clock=build.clock)

    build.session.expire_all()
    unchanged_identity = build.session.get(type(identity), identity.id)
    assert unchanged_identity is not None
    assert (
        unchanged_identity.id,
        unchanged_identity.state,
        unchanged_identity.revision,
        unchanged_identity.updated_at,
    ) == identity_snapshot

    unchanged_association = build.session.get(IdentityPersonAssociation, association.id)
    assert unchanged_association is not None
    assert unchanged_association.person_id == person.id  # the FK, unaffected by the name change

    evidence = build.session.get(Evidence, association.evidence_id)
    assert evidence is not None
    assert evidence.subject_person_id == person.id


def test_multiple_renames_do_not_rewrite_evidence_recorded_under_an_earlier_name(
    build: ModelFactory,
) -> None:
    identity = build.identity()
    person = build.person(display_name="Alice")
    assign_identity_to_person(
        build.session, identity.id, person.id, new_id=build.new_id, clock=build.clock
    )
    evidence_id = build.session.scalars(select(Evidence.id)).one()

    rename_person(build.session, person.id, "Alicia", expected_revision=1, clock=build.clock)
    rename_person(build.session, person.id, "Ali", expected_revision=2, clock=build.clock)

    build.session.expire_all()
    evidence = build.session.get(Evidence, evidence_id)
    assert evidence is not None
    assert evidence.kind == "IDENTITY_ASSIGNED_TO_PERSON"  # unaffected by either rename
    final_person = build.session.get(Person, person.id)
    assert final_person is not None
    assert final_person.display_name == "Ali"
