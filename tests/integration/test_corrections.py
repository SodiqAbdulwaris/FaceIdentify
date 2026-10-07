"""Correcting a recognised face: confirm it, move it, or separate it (M5 step 2; TST-054).

Real SQLite. What is proved: each correction is one `USER_CORRECTION` Evidence row naming what was
decided and what moved; ownership moves (the occurrence and its active representations, with their
index keys untouched and no index operation); the earlier identity stays active and its
representative face is never one that has left it; a refused correction changes nothing.
"""

import uuid
from dataclasses import dataclass

import pytest
from sqlalchemy import select

from backend.app.identities.corrections import (
    confirm_occurrence,
    reassign_occurrence,
)
from backend.app.identities.models import (
    Evidence,
    EvidenceRepresentation,
    Identity,
    IdentityLineage,
)
from backend.app.identities.use_cases import IdentityManagerError, StaleRevisionError
from backend.app.memory.models import (
    IndexOperation,
    Observation,
    Occurrence,
    OccurrenceObservation,
    Representation,
)
from tests.factories.models import ModelFactory


@dataclass
class Face:
    identity: Identity
    occurrence: Occurrence
    representation: Representation


def a_face(build: ModelFactory, identity: Identity | None = None, ann_key: int = 1) -> Face:
    identity = identity or build.identity()
    observation = build.observation()
    representation = build.representation(
        observation, state="ACTIVE", ann_key=ann_key, identity_id=identity.id
    )
    occurrence = build.occurrence(observation, identity_id=identity.id, state="ACTIVE")
    if identity.representative_observation_id is None:
        identity.representative_observation_id = observation.id
    build.session.flush()
    return Face(identity, occurrence, representation)


def corrections(build: ModelFactory) -> list[Evidence]:
    return list(build.session.scalars(select(Evidence).where(Evidence.kind == "USER_CORRECTION")))


def test_confirming_a_face_records_a_statement_and_changes_nothing_else(
    build: ModelFactory,
) -> None:
    face = a_face(build)

    evidence = confirm_occurrence(
        build.session,
        face.occurrence.id,
        expected_identity_id=face.identity.id,
        new_id=build.new_id,
        clock=build.clock,
    )

    assert evidence.kind == "USER_CORRECTION"
    assert evidence.subject_identity_id == face.identity.id
    assert evidence.source_id == face.occurrence.source_id
    assert evidence.payload_json["action"] == "CONFIRM"
    assert evidence.payload_json["occurrence_id"] == str(face.occurrence.id)
    assert evidence.payload_json["representation_ids"] == [str(face.representation.id)]
    assert face.occurrence.identity_id == face.identity.id
    assert face.representation.identity_id == face.identity.id
    link = build.session.get(
        EvidenceRepresentation, (evidence.id, face.representation.id, "SUBJECT")
    )
    assert link is not None


def test_a_face_can_be_moved_to_another_identity_with_its_representations(
    build: ModelFactory,
) -> None:
    mine = a_face(build)
    other = build.identity()
    stays = a_face(build, mine.identity, ann_key=2)
    operations_before = build.session.scalars(select(IndexOperation)).all()

    result = reassign_occurrence(
        build.session,
        mine.occurrence.id,
        other.id,
        expected_identity_id=mine.identity.id,
        new_id=build.new_id,
        clock=build.clock,
    )

    assert result.id == other.id
    assert mine.occurrence.identity_id == other.id
    assert mine.representation.identity_id == other.id
    assert mine.representation.ann_key == 1  # the index is not touched
    assert stays.occurrence.identity_id == mine.identity.id
    assert stays.representation.identity_id == mine.identity.id
    assert mine.identity.state == "ACTIVE"
    assert build.session.scalars(select(IndexOperation)).all() == operations_before
    (evidence,) = corrections(build)
    assert evidence.payload_json["action"] == "REASSIGN"
    assert evidence.payload_json["from_identity_id"] == str(mine.identity.id)
    assert evidence.payload_json["to_identity_id"] == str(other.id)
    assert build.session.scalars(select(IdentityLineage)).all() == []  # only a new identity has one


def test_a_face_can_be_separated_into_a_new_unknown_identity(build: ModelFactory) -> None:
    face = a_face(build)
    a_face(build, face.identity, ann_key=2)

    created = reassign_occurrence(
        build.session,
        face.occurrence.id,
        None,
        expected_identity_id=face.identity.id,
        new_id=build.new_id,
        clock=build.clock,
    )

    assert created.id != face.identity.id
    assert created.state == "ACTIVE"
    assert created.activated_at is not None
    assert face.occurrence.identity_id == created.id
    assert face.representation.identity_id == created.id
    assert created.representative_observation_id == face.occurrence.representative_observation_id
    (evidence,) = corrections(build)
    assert evidence.payload_json["action"] == "SEPARATE"
    (edge,) = build.session.scalars(select(IdentityLineage)).all()
    assert (edge.from_identity_id, edge.to_identity_id, edge.kind) == (
        face.identity.id,
        created.id,
        "SPLIT_FROM",
    )
    assert edge.evidence_id == evidence.id


def test_the_representative_face_of_an_identity_is_never_one_that_has_left_it(
    build: ModelFactory,
) -> None:
    first = a_face(build)
    second = a_face(build, first.identity, ann_key=2)
    assert (
        first.identity.representative_observation_id
        == first.occurrence.representative_observation_id
    )

    reassign_occurrence(
        build.session,
        first.occurrence.id,
        None,
        expected_identity_id=first.identity.id,
        new_id=build.new_id,
        clock=build.clock,
    )

    assert (
        first.identity.representative_observation_id
        == second.occurrence.representative_observation_id
    )


def test_moving_the_last_face_leaves_the_identity_active_with_no_representative(
    build: ModelFactory,
) -> None:
    face = a_face(build)

    reassign_occurrence(
        build.session,
        face.occurrence.id,
        None,
        expected_identity_id=face.identity.id,
        new_id=build.new_id,
        clock=build.clock,
    )

    assert face.identity.state == "ACTIVE"
    assert face.identity.representative_observation_id is None


def test_moving_a_face_that_is_not_the_representative_leaves_the_representative(
    build: ModelFactory,
) -> None:
    first = a_face(build)
    second = a_face(build, first.identity, ann_key=2)
    kept = first.identity.representative_observation_id

    reassign_occurrence(
        build.session, second.occurrence.id, None, expected_identity_id=first.identity.id,
        new_id=build.new_id, clock=build.clock,
    )  # fmt: skip

    assert first.identity.representative_observation_id == kept


def test_the_observations_of_an_occurrence_are_found_through_its_membership_rows(
    build: ModelFactory,
) -> None:
    identity = build.identity()
    observation = build.observation()
    representation = build.representation(
        observation, state="ACTIVE", ann_key=1, identity_id=identity.id
    )
    occurrence = build.occurrence(
        observation, identity_id=identity.id, state="ACTIVE", representative_observation_id=None
    )
    build.add(
        OccurrenceObservation(occurrence_id=occurrence.id, observation_id=observation.id, ordinal=0)
    )
    build.session.flush()

    created = reassign_occurrence(
        build.session, occurrence.id, None, expected_identity_id=identity.id,
        new_id=build.new_id, clock=build.clock,
    )  # fmt: skip

    assert representation.identity_id == created.id
    assert created.representative_observation_id is None  # the occurrence names none


def test_a_target_that_already_has_a_representative_keeps_it(build: ModelFactory) -> None:
    mine = a_face(build)
    other = a_face(build, ann_key=2)
    kept = other.identity.representative_observation_id

    reassign_occurrence(
        build.session,
        mine.occurrence.id,
        other.identity.id,
        expected_identity_id=mine.identity.id,
        new_id=build.new_id,
        clock=build.clock,
    )

    assert other.identity.representative_observation_id == kept


@pytest.mark.parametrize("how", ["confirm", "same", "unknown_target", "inactive_target"])
def test_a_refused_correction_writes_nothing(build: ModelFactory, how: str) -> None:
    face = a_face(build, build.identity(state="PENDING") if how == "confirm" else None)
    inactive = build.identity(state="PENDING")
    evidence_before = len(build.session.scalars(select(Evidence)).all())
    identities_before = len(build.session.scalars(select(Identity)).all())

    def attempt() -> object:
        if how == "same":
            return reassign_occurrence(
                build.session, face.occurrence.id, face.identity.id,
                expected_identity_id=face.identity.id, new_id=build.new_id, clock=build.clock,
            )  # fmt: skip
        target = uuid.uuid4() if how == "unknown_target" else inactive.id
        return reassign_occurrence(
            build.session, face.occurrence.id, target,
            expected_identity_id=face.identity.id, new_id=build.new_id, clock=build.clock,
        )  # fmt: skip

    if how == "confirm":
        with pytest.raises(IdentityManagerError, match="not ACTIVE"):
            confirm_occurrence(
                build.session, face.occurrence.id, expected_identity_id=face.identity.id,
                new_id=build.new_id, clock=build.clock,
            )  # fmt: skip
    else:
        with pytest.raises(IdentityManagerError):
            attempt()

    assert len(build.session.scalars(select(Evidence)).all()) == evidence_before
    assert len(build.session.scalars(select(Identity)).all()) == identities_before
    assert face.occurrence.identity_id == face.identity.id


def test_a_face_that_moved_since_it_was_shown_is_a_stale_correction(build: ModelFactory) -> None:
    face = a_face(build)
    shown_as = face.identity.id
    reassign_occurrence(
        build.session, face.occurrence.id, None, expected_identity_id=shown_as,
        new_id=build.new_id, clock=build.clock,
    )  # fmt: skip

    with pytest.raises(StaleRevisionError):
        confirm_occurrence(
            build.session, face.occurrence.id, expected_identity_id=shown_as,
            new_id=build.new_id, clock=build.clock,
        )  # fmt: skip
    with pytest.raises(StaleRevisionError):
        reassign_occurrence(
            build.session, face.occurrence.id, None, expected_identity_id=shown_as,
            new_id=build.new_id, clock=build.clock,
        )  # fmt: skip


def test_an_unknown_or_inactive_occurrence_is_refused(build: ModelFactory) -> None:
    identity = build.identity()
    with pytest.raises(IdentityManagerError, match="does not exist"):
        confirm_occurrence(
            build.session, uuid.uuid4(), expected_identity_id=identity.id,
            new_id=build.new_id, clock=build.clock,
        )  # fmt: skip
    pending = build.occurrence(identity_id=identity.id)  # PENDING: a run's private output
    with pytest.raises(IdentityManagerError, match="not ACTIVE"):
        confirm_occurrence(
            build.session, pending.id, expected_identity_id=identity.id,
            new_id=build.new_id, clock=build.clock,
        )  # fmt: skip


def test_only_the_representations_the_identity_owns_move_with_the_face(
    build: ModelFactory,
) -> None:
    face = a_face(build)
    other_space = build.representation_space()
    unowned = build.representation(
        build.session.get(Observation, face.representation.observation_id),
        representation_space_id=other_space.id,
        state="ACTIVE",
        ann_key=1,
        identity_id=None,
    )

    created = reassign_occurrence(
        build.session, face.occurrence.id, None, expected_identity_id=face.identity.id,
        new_id=build.new_id, clock=build.clock,
    )  # fmt: skip

    assert face.representation.identity_id == created.id
    assert unowned.identity_id is None


def test_a_retired_representation_does_not_move_with_the_face(build: ModelFactory) -> None:
    face = a_face(build)
    retired = build.representation(
        build.session.get(Observation, face.representation.observation_id),
        representation_space_id=build.representation_space().id,
        state="SUPERSEDED",
        identity_id=face.identity.id,
    )

    created = reassign_occurrence(
        build.session, face.occurrence.id, None, expected_identity_id=face.identity.id,
        new_id=build.new_id, clock=build.clock,
    )  # fmt: skip

    assert face.representation.identity_id == created.id
    assert retired.identity_id == face.identity.id


def test_a_shared_observation_cannot_remain_the_representative_after_its_representation_leaves(
    build: ModelFactory,
) -> None:
    first = a_face(build)
    shared = build.occurrence(  # another occurrence resting on the same observation
        build.session.get(Observation, first.representation.observation_id),
        identity_id=first.identity.id,
        state="ACTIVE",
    )
    build.clock.advance(seconds=1)  # (the shared occurrence is older: it would win a tie)
    own = a_face(build, first.identity, ann_key=2)
    assert shared.representative_observation_id == first.occurrence.representative_observation_id

    reassign_occurrence(
        build.session, first.occurrence.id, None, expected_identity_id=first.identity.id,
        new_id=build.new_id, clock=build.clock,
    )  # fmt: skip

    assert first.representation.identity_id != first.identity.id  # it left with the face
    assert (
        first.identity.representative_observation_id == own.occurrence.representative_observation_id
    )
