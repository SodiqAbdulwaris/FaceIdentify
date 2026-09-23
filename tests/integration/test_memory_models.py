"""Constraint tests for the memory, identity and people models (M1 PR 2).

Each test starts from a valid row built by the shared `build` factory and breaks one rule.
Cross-row rules (e.g. an ACTIVE representation's identity must itself be ACTIVE) belong to the
use cases in later PRs, not here (PERSISTENCE_IMPLEMENTATION.md §20).
"""

from enum import StrEnum

import pytest
from sqlalchemy import delete, func, select

from backend.app.identities.models import (
    Evidence,
    EvidenceCandidate,
    EvidenceKind,
    EvidenceRepresentation,
    EvidenceRepresentationRole,
    IdentityLineageKind,
    IdentityState,
)
from backend.app.memory.models import (
    AnnKeySequence,
    IndexOperationKind,
    IndexOperationState,
    Observation,
    ObservationState,
    Occurrence,
    OccurrenceKind,
    OccurrenceObservation,
    OccurrenceState,
    Representation,
    RepresentationState,
)
from backend.app.people.models import AssociationState, PersonState
from tests.factories.models import ModelFactory, float32_vector
from tests.fixtures.constraints import check, rejected, unique

# --- observations ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bbox",
    [
        {"bbox_x": -0.1},
        {"bbox_width": 0.0},
        {"bbox_height": -0.2},
        {"bbox_x": 0.9, "bbox_width": 0.2},
        {"bbox_y": 0.8, "bbox_height": 0.3},
    ],
    ids=["negative-x", "zero-width", "negative-height", "past-right-edge", "past-bottom-edge"],
)
def test_observation_bbox_must_be_normalized(build: ModelFactory, bbox: dict[str, float]) -> None:
    rejected(
        build.session, lambda: build.observation(**bbox), check("ck_observations_bbox_normalized")
    )


def test_observation_bbox_may_touch_the_edges(build: ModelFactory) -> None:
    edge = build.observation(bbox_x=0.0, bbox_y=0.0, bbox_width=1.0, bbox_height=1.0)
    assert (edge.bbox_x, edge.bbox_width) == (0.0, 1.0)


def test_observation_frame_and_time_come_together(build: ModelFactory) -> None:
    image = build.observation()
    video = build.observation(frame_index=12, timestamp_ms=480)
    assert (image.frame_index, video.frame_index) == (None, 12)
    rejected(
        build.session,
        lambda: build.observation(frame_index=12),
        check("ck_observations_frame_time_paired"),
    )
    rejected(
        build.session,
        lambda: build.observation(frame_index=-1, timestamp_ms=0),
        check("ck_observations_frame_time_non_negative"),
    )


def test_observation_sequence_is_unique_within_a_run(build: ModelFactory) -> None:
    run = build.run()
    build.observation(run, sequence_in_run=0)
    rejected(
        build.session,
        lambda: build.observation(run, sequence_in_run=0),
        unique("observations.processing_run_id", "observations.sequence_in_run"),
    )


# --- representations ---------------------------------------------------------------------------


def test_active_representation_needs_identity_and_ann_key(build: ModelFactory) -> None:
    active = build.representation(state="ACTIVE", identity_id=build.identity().id, ann_key=1)
    assert active.ann_key == 1
    rejected(
        build.session,
        lambda: build.representation(state="ACTIVE", ann_key=2),
        check("ck_representations_active_eligible"),
    )
    rejected(
        build.session,
        lambda: build.representation(state="ACTIVE", identity_id=build.identity().id),
        check("ck_representations_active_eligible"),
    )


def test_pending_representation_needs_no_identity_or_key(build: ModelFactory) -> None:
    pending = build.representation()
    assert (pending.state, pending.identity_id, pending.ann_key) == ("PENDING", None, None)


def test_erasure_removes_vector_and_key_and_nothing_else_may_lack_a_vector(
    build: ModelFactory,
) -> None:
    erased = build.representation(state="ERASED", vector=None)
    assert erased.vector is None
    rejected(
        build.session,
        lambda: build.representation(state="ERASED"),
        check("ck_representations_erasure"),
    )
    rejected(
        build.session,
        lambda: build.representation(state="ERASED", vector=None, ann_key=5),
        check("ck_representations_erasure"),
    )
    rejected(
        build.session,
        lambda: build.representation(vector=None),
        check("ck_representations_erasure"),
    )


def test_vector_bytes_match_the_declared_dimension(build: ModelFactory) -> None:
    rejected(
        build.session,
        lambda: build.representation(vector=float32_vector([1.0, 0.0, 0.0])),
        check("ck_representations_vector_length"),
    )


def test_ann_keys_are_positive_and_unique(build: ModelFactory) -> None:
    rejected(
        build.session,
        lambda: build.representation(ann_key=0),
        check("ck_representations_ann_key_positive"),
    )
    build.representation(ann_key=7)
    rejected(
        build.session, lambda: build.representation(ann_key=7), unique("representations.ann_key")
    )


def test_one_representation_per_observation_per_space(build: ModelFactory) -> None:
    first = build.representation()
    observation = build.session.get(Observation, first.observation_id)
    assert observation is not None
    rejected(
        build.session,
        lambda: build.representation(
            observation, representation_space_id=first.representation_space_id
        ),
        unique("representations.observation_id", "representations.representation_space_id"),
    )


def test_deleting_an_observation_deletes_its_representations(build: ModelFactory) -> None:
    representation = build.representation()
    build.session.execute(
        delete(Observation).where(Observation.id == representation.observation_id)
    )
    assert build.session.scalar(select(func.count()).select_from(Representation)) == 0


def test_ann_key_sequence_starts_positive(build: ModelFactory) -> None:
    space = build.representation_space()
    rejected(
        build.session,
        lambda: build.add(AnnKeySequence(representation_space_id=space.id, next_ann_key=0)),
        check("ck_ann_key_sequences_next_ann_key_positive"),
    )


# --- occurrences -------------------------------------------------------------------------------


def test_image_occurrence_has_no_frame_or_time_range(build: ModelFactory) -> None:
    rejected(
        build.session,
        lambda: build.occurrence(start_frame=0, end_frame=5),
        check("ck_occurrences_image_has_no_range"),
    )


def test_track_occurrence_ranges_are_ordered(build: ModelFactory) -> None:
    track = build.occurrence(kind="TRACK", start_frame=3, end_frame=3)
    assert track.start_frame == track.end_frame
    rejected(
        build.session,
        lambda: build.occurrence(kind="TRACK", start_frame=5, end_frame=4),
        check("ck_occurrences_frame_range_ordered"),
    )
    rejected(
        build.session,
        lambda: build.occurrence(kind="SEGMENT", start_timestamp_ms=900, end_timestamp_ms=100),
        check("ck_occurrences_time_range_ordered"),
    )


def test_occurrence_membership_is_owned_and_ordered(build: ModelFactory) -> None:
    occurrence = build.occurrence()
    first, second = build.observation(), build.observation()
    build.add(
        OccurrenceObservation(occurrence_id=occurrence.id, observation_id=first.id, ordinal=0)
    )
    rejected(
        build.session,
        lambda: build.add(
            OccurrenceObservation(occurrence_id=occurrence.id, observation_id=second.id, ordinal=0)
        ),
        unique("occurrence_observations.occurrence_id", "occurrence_observations.ordinal"),
    )


# --- index operations --------------------------------------------------------------------------


def test_only_one_pending_operation_per_representation_and_kind(build: ModelFactory) -> None:
    representation = build.representation()
    build.index_operation(representation)
    build.index_operation(representation, operation="REMOVE")  # the opposite kind may coexist
    rejected(
        build.session,
        lambda: build.index_operation(representation),
        unique("index_operations.representation_id", "index_operations.operation"),
    )


def test_settled_operations_do_not_block_new_pending_ones(build: ModelFactory) -> None:
    representation = build.representation()
    build.index_operation(representation, state="APPLIED", applied_at=build.clock())
    build.index_operation(representation, state="FAILED", failure_code="INDEX_IO")
    assert build.index_operation(representation).state == "PENDING"


def test_applied_operation_records_when(build: ModelFactory) -> None:
    rejected(
        build.session,
        lambda: build.index_operation(build.representation(), state="APPLIED"),
        check("ck_index_operations_applied_has_time"),
    )


# --- identities, lineage, evidence ---------------------------------------------------------------


def test_merged_identity_must_name_its_target(build: ModelFactory) -> None:
    target = build.identity()
    merged = build.identity(state="MERGED", merged_into_identity_id=target.id)
    assert merged.merged_into_identity_id == target.id
    rejected(
        build.session, lambda: build.identity(state="MERGED"), check("ck_identities_merged_target")
    )


def test_a_later_state_may_keep_the_merge_pointer(build: ModelFactory) -> None:
    # Unspecified by §7, so deliberately not constrained (PR #5 review).
    forgotten = build.identity(state="FORGOTTEN", merged_into_identity_id=build.identity().id)
    assert forgotten.merged_into_identity_id is not None


def test_identity_cannot_merge_into_itself(build: ModelFactory) -> None:
    identity_id = build.new_id()
    rejected(
        build.session,
        lambda: build.identity(id=identity_id, state="MERGED", merged_into_identity_id=identity_id),
        check("ck_identities_not_merged_into_self"),
    )


def test_lineage_edges_are_distinct_and_not_duplicated(build: ModelFactory) -> None:
    a, b = build.identity().id, build.identity().id
    build.lineage(a, b, "MERGED_INTO")
    build.lineage(b, a, "SPLIT_FROM")
    rejected(
        build.session,
        lambda: build.lineage(a, a, "MERGED_INTO"),
        check("ck_identity_lineage_distinct_endpoints"),
    )
    rejected(
        build.session,
        lambda: build.lineage(a, b, "MERGED_INTO"),
        unique(
            "identity_lineage.from_identity_id",
            "identity_lineage.to_identity_id",
            "identity_lineage.kind",
        ),
    )


# --- people and associations ----------------------------------------------------------------------


def test_person_display_name_must_not_be_blank(build: ModelFactory) -> None:
    rejected(
        build.session,
        lambda: build.person(display_name=" "),
        check("ck_people_display_name_not_empty"),
    )


def test_people_may_share_a_name(build: ModelFactory) -> None:
    assert build.person().display_name == build.person().display_name


def test_identity_has_at_most_one_active_person(build: ModelFactory) -> None:
    identity = build.identity()
    build.association(identity_id=identity.id)
    rejected(
        build.session,
        lambda: build.association(identity_id=identity.id),
        unique("identity_person_associations.identity_id"),
    )


def test_person_may_have_many_active_identities(build: ModelFactory) -> None:
    person = build.person()
    build.association(person_id=person.id)
    assert build.association(person_id=person.id).state == "ACTIVE"


def test_ended_associations_keep_history_and_allow_a_new_active_one(build: ModelFactory) -> None:
    identity = build.identity()
    build.association(identity_id=identity.id, state="REMOVED", ended_at=build.clock())
    build.association(identity_id=identity.id, state="SUPERSEDED", ended_at=build.clock())
    assert build.association(identity_id=identity.id).state == "ACTIVE"


def test_association_end_time_matches_its_state(build: ModelFactory) -> None:
    rejected(
        build.session,
        lambda: build.association(state="REMOVED"),
        check("ck_identity_person_associations_ended_when_inactive"),
    )
    rejected(
        build.session,
        lambda: build.association(ended_at=build.clock()),
        check("ck_identity_person_associations_ended_when_inactive"),
    )


# --- value sets --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("row", "column", "table"),
    [
        ("observation", "state", "observations"),
        ("representation", "state", "representations"),
        ("occurrence", "kind", "occurrences"),
        ("occurrence", "state", "occurrences"),
        ("identity", "state", "identities"),
        ("evidence", "kind", "evidence"),
        ("person", "state", "people"),
        ("association", "state", "identity_person_associations"),
    ],
)
def test_spec_defined_value_sets_reject_unknown_literals(
    build: ModelFactory, row: str, column: str, table: str
) -> None:
    make = getattr(build, row)
    extra = {"ended_at": build.clock()} if row == "association" else {}
    rejected(
        build.session,
        lambda: make(**{column: "NOT_A_VALUE"}, **extra),
        check(f"ck_{table}_{column}"),
    )


# The complete value sets PERSISTENCE_IMPLEMENTATION.md defines (§5-§11, §17).
SPEC_VALUE_SETS: dict[type[StrEnum], set[str]] = {
    ObservationState: {"PENDING", "ACTIVE", "SUPERSEDED", "REJECTED", "DELETED"},
    RepresentationState: {"PENDING", "ACTIVE", "SUPERSEDED", "ERASED", "DELETED"},
    IdentityState: {"PENDING", "ACTIVE", "MERGED", "SPLIT", "FORGOTTEN", "DELETED"},
    IdentityLineageKind: {"MERGED_INTO", "SPLIT_FROM"},
    PersonState: {"ACTIVE", "RECYCLED", "DELETED"},
    AssociationState: {"ACTIVE", "REMOVED", "SUPERSEDED"},
    EvidenceKind: {
        "IDENTITY_CREATED", "IDENTITY_MATCHED", "IDENTITY_ASSIGNED_TO_PERSON",
        "IDENTITY_REMOVED_FROM_PERSON", "IDENTITY_MERGED", "IDENTITY_SPLIT",
        "IDENTITY_FORGOTTEN", "USER_CORRECTION",
    },
    EvidenceRepresentationRole: {"SUBJECT", "SELECTED_CANDIDATE", "CANDIDATE", "SUPPORTING"},
    OccurrenceKind: {"IMAGE", "TRACK", "SEGMENT"},
    OccurrenceState: {"PENDING", "ACTIVE", "SUPERSEDED", "DELETED"},
    IndexOperationKind: {"ADD", "REMOVE"},
    IndexOperationState: {"PENDING", "APPLIED", "FAILED"},
}  # fmt: skip


@pytest.mark.parametrize("enum", SPEC_VALUE_SETS, ids=lambda e: e.__name__)
def test_enums_match_the_spec_value_sets(enum: type[StrEnum]) -> None:
    assert {member.value for member in enum} == SPEC_VALUE_SETS[enum]


# --- remaining constraints (PR #5 review) ------------------------------------------------------


def test_remaining_integrity_checks(build: ModelFactory) -> None:
    """Checks not covered above, each broken once from an otherwise valid row."""
    s = build.session
    rejected(
        s,
        lambda: build.observation(sequence_in_run=-1),
        check("ck_observations_sequence_non_negative"),
    )
    rejected(s, lambda: build.identity(revision=0), check("ck_identities_revision_positive"))
    rejected(s, lambda: build.person(revision=0), check("ck_people_revision_positive"))
    rejected(
        s,
        lambda: build.association(revision=0),
        check("ck_identity_person_associations_revision_positive"),
    )
    rejected(
        s,
        lambda: build.index_operation(attempt_count=-1),
        check("ck_index_operations_attempt_count_non_negative"),
    )
    rejected(
        s, lambda: build.index_operation(operation="UPSERT"), check("ck_index_operations_operation")
    )
    rejected(s, lambda: build.index_operation(state="RUNNING"), check("ck_index_operations_state"))
    a, b = build.identity().id, build.identity().id
    rejected(s, lambda: build.lineage(a, b, "COPIED_FROM"), check("ck_identity_lineage_kind"))
    rejected(
        s,
        lambda: build.occurrence(start_timestamp_ms=0, end_timestamp_ms=10),
        check("ck_occurrences_image_has_no_range"),
    )  # fmt: skip


def test_evidence_links_and_candidates(build: ModelFactory) -> None:
    evidence = build.evidence(kind="IDENTITY_MATCHED")
    representation = build.representation()
    build.add(
        EvidenceRepresentation(
            evidence_id=evidence.id, representation_id=representation.id, role="SUBJECT"
        )
    )
    rejected(
        build.session,
        lambda: build.add(
            EvidenceRepresentation(
                evidence_id=evidence.id, representation_id=representation.id, role="WITNESS"
            )
        ),
        check("ck_evidence_representations_role"),
    )
    candidate = dict(evidence_id=evidence.id, raw_similarity=0.9, decision="MATCH", details_json={})
    build.add(EvidenceCandidate(rank=0, **candidate))
    rejected(
        build.session,
        lambda: build.add(EvidenceCandidate(rank=-1, **candidate)),
        check("ck_evidence_candidates_rank_non_negative"),
    )
    # Deleting evidence removes its owned link and candidate rows (CASCADE, §20).
    build.session.execute(delete(Evidence).where(Evidence.id == evidence.id))
    assert build.session.scalar(select(func.count()).select_from(EvidenceRepresentation)) == 0
    assert build.session.scalar(select(func.count()).select_from(EvidenceCandidate)) == 0


def test_occurrence_membership_primary_key_and_cascade(build: ModelFactory) -> None:
    occurrence, observation = build.occurrence(), build.observation()
    member = dict(occurrence_id=occurrence.id, observation_id=observation.id)
    build.add(OccurrenceObservation(ordinal=0, **member))
    rejected(
        build.session,
        lambda: build.add(OccurrenceObservation(ordinal=1, **member)),
        unique("occurrence_observations.occurrence_id", "occurrence_observations.observation_id"),
    )
    rejected(
        build.session,
        lambda: build.add(
            OccurrenceObservation(
                occurrence_id=occurrence.id, observation_id=build.observation().id, ordinal=-1
            )
        ),
        check("ck_occurrence_observations_ordinal_non_negative"),
    )
    build.session.execute(delete(Occurrence).where(Occurrence.id == occurrence.id))
    assert build.session.scalar(select(func.count()).select_from(OccurrenceObservation)) == 0
    assert build.session.get(Observation, observation.id) is not None  # history survives
