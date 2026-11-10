"""Reprocessing: what the activation transaction does besides ordinary acceptance (persistence
12.1, identity model 60.1; approved 2026-11-09).

`plan_supersession` reads SQLite only, before anything changes: which new faces must stay
suppressed because they are a forgotten or erased face again (item 9a), which human decisions of
the previous generation carry over to a corresponding new face, and which need review (item 8).
`supersede_previous` moves the previous generation out of every current view and queues the
removal of its vectors from the index (items 5c and 5f). The caller, `AcceptProcessingRunUseCase`,
does all of it inside its one acceptance transaction.
"""

import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
from sqlalchemy import exists, select, update
from sqlalchemy.orm import Session

from backend.app.identities.models import (
    Evidence,
    EvidenceKind,
    EvidenceRepresentation,
    EvidenceRepresentationRole,
    Identity,
)
from backend.app.identities.repository import EvidenceLink, EvidenceRepository
from backend.app.identities.use_cases import touch_identity
from backend.app.memory.index_operation_repository import IndexOperationRepository, NewOperation
from backend.app.memory.models import (
    IndexOperationKind,
    Observation,
    ObservationState,
    Occurrence,
    OccurrenceState,
    Representation,
    RepresentationState,
)
from backend.app.people.models import AssociationState, IdentityPersonAssociation
from backend.app.processing.correspondence import (
    MIN_COSINE,
    MIN_IOU,
    RULE_VERSION,
    Box,
    Face,
    Pair,
    Unmatched,
    correspond,
    geometric_pairs,
)
from backend.app.processing.models import ProcessingRun

# A face whose representation is the subject of one of these, or whose identity is named, carries a
# human decision (identity model 60.1). A carried-over decision is still the human's, so a second
# reprocessing carries it again.
HUMAN_DECISION_KINDS = (
    EvidenceKind.USER_CORRECTION,
    EvidenceKind.IDENTITY_MERGED,
    EvidenceKind.IDENTITY_SPLIT,
    EvidenceKind.REPROCESS_DECISION_CARRIED_OVER,
)
PAYLOAD_SCHEMA_VERSION = 1
RULE = {"version": RULE_VERSION, "min_iou": MIN_IOU, "min_cosine": MIN_COSINE}
CARRIED_KEYS = {
    "representation_id",
    "previous_representation_id",
    "run_id",
    "previous_run_id",
    "identity_id",
    "iou",
    "cosine",
    "rule",
}
_ERASED_STATES = (RepresentationState.ERASING, RepresentationState.ERASED)


@dataclass(frozen=True, slots=True)
class CarriedDecision:
    previous_representation_id: uuid.UUID
    identity_id: uuid.UUID
    iou: float
    cosine: float


@dataclass(frozen=True, slots=True)
class Review:
    previous_representation_id: uuid.UUID
    identity_id: uuid.UUID
    reason: str
    candidate_ids: tuple[uuid.UUID, ...]


@dataclass(frozen=True, slots=True)
class SupersessionPlan:
    # New representation id -> the decision it takes over from the previous generation.
    carried: dict[uuid.UUID, CarriedDecision] = field(default_factory=dict)
    # New representation ids that are a forgotten or erased face again.
    suppressed: frozenset[uuid.UUID] = frozenset()
    reviews: tuple[Review, ...] = ()


def box_of(observation: Observation) -> Box:
    return Box(
        observation.bbox_x, observation.bbox_y, observation.bbox_width, observation.bbox_height
    )


def _vector(representation: Representation) -> np.ndarray:
    """An `ACTIVE` or `PENDING` representation's vector (only those are compared)."""
    assert representation.vector is not None  # (the schema: only ERASED has none)
    return np.frombuffer(representation.vector, dtype="<f4")


def _faces(session: Session, run_id: uuid.UUID) -> list[tuple[Observation, Representation]]:
    return [
        (observation, representation)
        for representation, observation in session.execute(
            select(Representation, Observation)
            .join(Observation, Observation.id == Representation.observation_id)
            .where(Observation.processing_run_id == run_id)
            .order_by(Observation.sequence_in_run, Representation.id)
        ).tuples()
    ]


def human_decided(session: Session, representation: Representation) -> bool:
    """An `ACTIVE` representation with an identity that a person corrected, merged or split, whose
    decision was carried over, or whose identity is named (identity model 60.1). (That the identity
    is still `ACTIVE` is checked where the decision is applied.)"""
    if representation.identity_id is None:  # an accepted abstention: nobody decided anything
        return False
    decided = select(
        exists().where(
            EvidenceRepresentation.representation_id == representation.id,
            EvidenceRepresentation.evidence_id == Evidence.id,
            Evidence.kind.in_(HUMAN_DECISION_KINDS),
        )
    )
    named = select(
        exists().where(
            IdentityPersonAssociation.identity_id == representation.identity_id,
            IdentityPersonAssociation.state == AssociationState.ACTIVE,
        )
    )
    return bool(session.scalar(decided)) or bool(session.scalar(named))


def erased_faces(session: Session, previous_run_id: uuid.UUID) -> list[Face]:
    """The previous generation's faces whose vector is being or was erased (a forgotten identity or
    an erased representation), by observation id and box only."""
    seen: dict[uuid.UUID, Face] = {}
    for observation, representation in _faces(session, previous_run_id):
        if representation.state in _ERASED_STATES:
            seen.setdefault(observation.id, Face(observation.id, box_of(observation)))
    return list(seen.values())


def plan_supersession(
    session: Session,
    run: ProcessingRun,
    *,
    space_id: uuid.UUID,
    representation_ids: Sequence[uuid.UUID],
) -> SupersessionPlan:
    """What activation must do for the faces of `run`, a reprocess run, given the previous
    generation as SQLite holds it now. `representation_ids` are the run's own (its FINAL)."""
    assert run.supersedes_run_id is not None
    new_faces = [
        (observation, representation)
        for observation, representation in _faces(session, run.id)
        if representation.id in set(representation_ids)
    ]
    current = [
        Face(
            representation.id,
            box_of(observation),
            representation.representation_space_id,
            _vector(representation),
        )
        for observation, representation in new_faces
    ]
    suppressed = frozenset(geometric_pairs(erased_faces(session, run.supersedes_run_id), current))
    kept = [face for face in current if face.id not in suppressed]

    previous: dict[uuid.UUID, Face] = {}  # one face per previous observation
    identities: dict[uuid.UUID, uuid.UUID] = {}
    for observation, representation in _faces(session, run.supersedes_run_id):
        if (
            observation.state != ObservationState.ACTIVE
            or representation.state != RepresentationState.ACTIVE
        ):
            continue
        face = Face(
            representation.id,
            box_of(observation),
            representation.representation_space_id,
            _vector(representation),
        )
        previous.setdefault(observation.id, face)  # (an image run has one space)
        if human_decided(session, representation):
            assert representation.identity_id is not None
            identities[representation.id] = representation.identity_id
    decided = [face.id for face in previous.values() if face.id in identities]

    carried: dict[uuid.UUID, CarriedDecision] = {}
    reviews: list[Review] = []
    outcome = correspond(list(previous.values()), kept, space_id=space_id, decided=decided)
    for previous_id in decided:
        match = outcome[previous_id]
        if isinstance(match, Pair):
            carried[match.current_id] = CarriedDecision(
                previous_id, identities[previous_id], match.iou, match.cosine
            )
        else:
            assert isinstance(match, Unmatched)
            reviews.append(
                Review(previous_id, identities[previous_id], match.reason, match.candidate_ids)
            )
    return SupersessionPlan(carried, suppressed, tuple(reviews))


def supersede_previous(
    session: Session, run: ProcessingRun, *, now: datetime, new_id: Callable[[], uuid.UUID]
) -> None:
    """Move the previous generation's `ACTIVE` observations, representations and occurrences to
    `SUPERSEDED` at `now`, and queue a `REMOVE` for every representation that held a key. The
    identities that owned them only have their revision bumped: a view taken before is stale."""
    previous = run.supersedes_run_id
    assert previous is not None
    no_sync = {"synchronize_session": False}
    session.execute(
        update(Observation)
        .where(
            Observation.processing_run_id == previous,
            Observation.state == ObservationState.ACTIVE,
        )
        .values(state=ObservationState.SUPERSEDED, superseded_at=now, superseded_by_run_id=run.id),
        execution_options=no_sync,
    )
    moved = session.execute(
        update(Representation)
        .where(
            Representation.processing_run_id == previous,
            Representation.state == RepresentationState.ACTIVE,
        )
        .values(state=RepresentationState.SUPERSEDED, superseded_at=now)
        .returning(
            Representation.id,
            Representation.representation_space_id,
            Representation.ann_key,
            Representation.identity_id,
        )
        .execution_options(**no_sync)
    ).all()
    session.execute(
        update(Occurrence)
        .where(
            Occurrence.processing_run_id == previous,
            Occurrence.state == OccurrenceState.ACTIVE,
        )
        .values(state=OccurrenceState.SUPERSEDED, superseded_at=now),
        execution_options=no_sync,
    )
    IndexOperationRepository(session).append_batch(
        [
            NewOperation(representation_id, space_id, IndexOperationKind.REMOVE)
            for representation_id, space_id, ann_key, _identity in moved
            if ann_key is not None
        ],
        now=now,
        new_id=new_id,
    )
    for identity_id in sorted({identity for *_rest, identity in moved if identity is not None}):
        identity = session.get(Identity, identity_id)
        assert identity is not None  # the representation's foreign key guarantees it
        touch_identity(session, identity, now)


def carried_payload(
    run: ProcessingRun, representation_id: uuid.UUID, carried: CarriedDecision
) -> dict[str, object]:
    return {
        "representation_id": str(representation_id),
        "previous_representation_id": str(carried.previous_representation_id),
        "run_id": str(run.id),
        "previous_run_id": str(run.supersedes_run_id),
        "identity_id": str(carried.identity_id),
        "iou": carried.iou,
        "cosine": carried.cosine,
        "rule": RULE,
    }


def record_reviews(
    session: Session,
    run: ProcessingRun,
    reviews: Sequence[Review],
    *,
    now: datetime,
    new_id: Callable[[], uuid.UUID],
) -> None:
    """One append-only `REPROCESS_REVIEW_REQUIRED` row per human decision that found no
    trustworthy counterpart: ids only, never a vector or an image (persistence 10)."""
    repository = EvidenceRepository(session)
    for review in reviews:
        repository.append(
            Evidence(
                id=new_id(),
                kind=EvidenceKind.REPROCESS_REVIEW_REQUIRED,
                processing_run_id=run.id,
                source_id=run.source_id,
                subject_identity_id=review.identity_id,
                payload_schema_version=PAYLOAD_SCHEMA_VERSION,
                payload_json={
                    "previous_representation_id": str(review.previous_representation_id),
                    "identity_id": str(review.identity_id),
                    "reason": review.reason,
                    "candidate_representation_ids": [str(c) for c in review.candidate_ids],
                    "run_id": str(run.id),
                    "previous_run_id": str(run.supersedes_run_id),
                    "rule": RULE,
                },
                created_at=now,
            ),
            representations=(
                EvidenceLink(review.previous_representation_id, EvidenceRepresentationRole.SUBJECT),
                *(
                    EvidenceLink(candidate, EvidenceRepresentationRole.CANDIDATE)
                    for candidate in review.candidate_ids
                ),
            ),
        )


def carried_evidence(session: Session, run_id: uuid.UUID) -> Mapping[str, list[Evidence]]:
    """The run's `REPROCESS_DECISION_CARRIED_OVER` rows, grouped by the new representation each
    names (as its payload records it, unparsed), so a duplicate is visible to the caller."""
    found: dict[str, list[Evidence]] = {}
    for row in session.scalars(
        select(Evidence).where(
            Evidence.processing_run_id == run_id,
            Evidence.kind == EvidenceKind.REPROCESS_DECISION_CARRIED_OVER,
        )
    ):
        payload = row.payload_json
        named = payload.get("representation_id") if isinstance(payload, dict) else None
        found.setdefault(str(named), []).append(row)
    return found
