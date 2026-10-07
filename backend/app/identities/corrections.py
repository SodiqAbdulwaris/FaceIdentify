"""User corrections of a recognised face (M5 step 2; API section 7 and 114 to 115).

A face is an Occurrence: the appearance of an Identity in a Source, resting on an observation and
the representation made from it. The user can confirm that the face belongs to the identity it was
given, or say it does not: move it to another existing identity, or separate it into a new unknown
identity. Each is one `USER_CORRECTION` Evidence row naming what was decided and what moved; the
earlier decision is never rewritten.

What moves is ownership only: the occurrence and the ACTIVE representations made from its
observations that currently belong to the same identity. A representation's `ann_key` and the index
are untouched (ownership is not part of the index), so no `IndexOperation` is written. There is no
"cannot link" constraint (owner decision 2026-10-07): a correction does not stop recognition from
choosing the same identity for a similar face again.

`expected_identity_id` is the identity the caller saw the face under: if the face has since moved,
the correction is refused as stale instead of being applied to something the user did not see.

Functions flush but do not commit: the caller owns the transaction (Persistence 26).
"""

import uuid
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.identities.models import (
    Evidence,
    EvidenceKind,
    EvidenceRepresentation,
    EvidenceRepresentationRole,
    Identity,
    IdentityLineage,
    IdentityLineageKind,
    IdentityState,
)
from backend.app.identities.repository import OccurrenceRepository
from backend.app.identities.use_cases import IdentityManagerError, StaleRevisionError
from backend.app.memory.models import (
    Observation,
    ObservationState,
    Occurrence,
    OccurrenceKind,
    OccurrenceObservation,
    OccurrenceState,
    Representation,
    RepresentationState,
)


def _occurrence(
    session: Session, occurrence_id: uuid.UUID, expected_identity_id: uuid.UUID
) -> Occurrence:
    occurrence = session.get(Occurrence, occurrence_id, populate_existing=True)
    if occurrence is None:
        raise IdentityManagerError(f"occurrence {occurrence_id} does not exist")
    if occurrence.state != OccurrenceState.ACTIVE:
        raise IdentityManagerError(f"occurrence {occurrence_id} is {occurrence.state}, not ACTIVE")
    if occurrence.identity_id != expected_identity_id:
        raise StaleRevisionError(
            f"occurrence {occurrence_id} now belongs to another identity than the one shown"
        )
    return occurrence


def _identity(session: Session, identity_id: uuid.UUID, what: str) -> Identity:
    identity = session.get(Identity, identity_id, populate_existing=True)
    if identity is None:
        raise IdentityManagerError(f"identity {identity_id} does not exist")
    if identity.state != IdentityState.ACTIVE:
        raise IdentityManagerError(
            f"identity {identity_id} is {identity.state}, not ACTIVE;"
            f" only an active identity {what}"
        )
    return identity


def _observation_ids(session: Session, occurrence: Occurrence) -> list[uuid.UUID]:
    members = list(
        session.scalars(
            select(OccurrenceObservation.observation_id).where(
                OccurrenceObservation.occurrence_id == occurrence.id
            )
        )
    )
    if occurrence.representative_observation_id is not None:
        members.append(occurrence.representative_observation_id)
    return list(dict.fromkeys(members))  # in order, without repeats


def _representations(session: Session, occurrence: Occurrence) -> list[Representation]:
    """The occurrence's ACTIVE representations that are still owned by its identity."""
    return list(
        session.scalars(
            select(Representation)
            .where(
                Representation.observation_id.in_(_observation_ids(session, occurrence)),
                Representation.state == RepresentationState.ACTIVE,
                Representation.identity_id == occurrence.identity_id,
            )
            .order_by(Representation.id)
        )
    )


def _correction(
    session: Session,
    occurrence: Occurrence,
    subject_identity_id: uuid.UUID,
    representations: list[Representation],
    payload: dict[str, object],
    *,
    new_id: Callable[[], uuid.UUID],
    now: datetime,
) -> Evidence:
    evidence = Evidence(
        id=new_id(),
        kind=EvidenceKind.USER_CORRECTION,
        source_id=occurrence.source_id,
        subject_identity_id=subject_identity_id,
        payload_schema_version=1,
        payload_json={
            "occurrence_id": str(occurrence.id),
            "representation_ids": [str(r.id) for r in representations],
            **payload,
        },
        created_at=now,
    )
    session.add(evidence)
    session.flush()
    for representation in representations:
        session.add(
            EvidenceRepresentation(
                evidence_id=evidence.id,
                representation_id=representation.id,
                role=EvidenceRepresentationRole.SUBJECT,
            )
        )
    session.flush()
    return evidence


def confirm_occurrence(
    session: Session,
    occurrence_id: uuid.UUID,
    *,
    expected_identity_id: uuid.UUID,
    new_id: Callable[[], uuid.UUID],
    clock: Callable[[], datetime],
) -> Evidence:
    """Record that a person says this face belongs to the identity it was given.

    It changes nothing else: confirmation is a statement of truth, kept as Evidence, and does not
    (yet) change how recognition treats the face.
    """
    occurrence = _occurrence(session, occurrence_id, expected_identity_id)
    _identity(session, occurrence.identity_id, "can have a face confirmed")
    return _correction(
        session,
        occurrence,
        occurrence.identity_id,
        _representations(session, occurrence),
        {"action": "CONFIRM"},
        new_id=new_id,
        now=clock(),
    )


def reassign_occurrence(
    session: Session,
    occurrence_id: uuid.UUID,
    to_identity_id: uuid.UUID | None,
    *,
    expected_identity_id: uuid.UUID,
    new_id: Callable[[], uuid.UUID],
    clock: Callable[[], datetime],
) -> Identity:
    """Move a face to another identity, or (`to_identity_id` is None) into a new unknown one.

    Returns the identity the face now belongs to. The first identity keeps everything else and
    stays ACTIVE even if this was its last face. A new identity is created directly ACTIVE, linked
    to the first by a `SPLIT_FROM` lineage edge that cites the correction.
    """
    occurrence = _occurrence(session, occurrence_id, expected_identity_id)
    source = _identity(session, expected_identity_id, "can have a face moved away")
    if to_identity_id == expected_identity_id:
        raise IdentityManagerError("the face already belongs to that identity")
    target = (
        None if to_identity_id is None else _identity(session, to_identity_id, "can receive a face")
    )
    moved = _representations(session, occurrence)
    now = clock()
    created = target is None
    if target is None:
        target = Identity(
            id=new_id(),
            state=IdentityState.ACTIVE,
            created_by_processing_run_id=None,
            created_at=now,
            activated_at=now,
            updated_at=now,
        )
        session.add(target)
        session.flush()

    evidence = _correction(
        session,
        occurrence,
        target.id,
        moved,
        {
            "action": "SEPARATE" if created else "REASSIGN",
            "from_identity_id": str(source.id),
            "to_identity_id": str(target.id),
        },
        new_id=new_id,
        now=now,
    )
    observation_ids = _observation_ids(session, occurrence)
    for representation in moved:
        representation.identity_id = target.id
    occurrence.identity_id = target.id
    if created:
        session.add(
            IdentityLineage(
                id=new_id(),
                from_identity_id=source.id,
                to_identity_id=target.id,
                kind=IdentityLineageKind.SPLIT_FROM,
                evidence_id=evidence.id,
                created_at=now,
            )
        )
    session.flush()  # (so the identity's remaining faces are read as they now are)
    _refresh_representative(session, source, observation_ids, now)
    if target.representative_observation_id is None:
        target.representative_observation_id = occurrence.representative_observation_id
        target.updated_at = now
    session.flush()
    return target


def abstentions_of(session: Session, representation_id: uuid.UUID) -> list[uuid.UUID]:
    """The `RECOGNITION_ABSTAINED` Evidence recorded about a representation (it is cited as the
    SUBJECT of exactly one when recognition accepted an ABSTAIN for it)."""
    return list(
        session.scalars(
            select(Evidence.id)
            .join(EvidenceRepresentation, EvidenceRepresentation.evidence_id == Evidence.id)
            .where(
                Evidence.kind == EvidenceKind.RECOGNITION_ABSTAINED,
                EvidenceRepresentation.representation_id == representation_id,
                EvidenceRepresentation.role == EvidenceRepresentationRole.SUBJECT,
            )
            .order_by(Evidence.created_at, Evidence.id)
        )
    )


def resolve_representation(
    session: Session,
    representation_id: uuid.UUID,
    to_identity_id: uuid.UUID | None,
    *,
    new_id: Callable[[], uuid.UUID],
    clock: Callable[[], datetime],
) -> Occurrence:
    """Say who a face is that recognition declined to place (issue 79): an existing identity, or
    (`to_identity_id` is None) a new unknown one. Returns the occurrence this creates.

    An accepted ABSTAIN leaves an identity-less ACTIVE representation, no identity and no
    occurrence, and `RECOGNITION_ABSTAINED` Evidence. Resolving it gives the representation its
    identity and the face its occurrence, and adds one `USER_CORRECTION` Evidence row citing the
    abstention; the abstention itself is never rewritten. The representation is already in the index
    under its `ann_key`, so nothing in the index changes.
    """
    representation = session.get(Representation, representation_id, populate_existing=True)
    if representation is None:
        raise IdentityManagerError(f"representation {representation_id} does not exist")
    if representation.state != RepresentationState.ACTIVE or representation.identity_id is not None:
        raise IdentityManagerError(
            f"representation {representation_id} is not an unresolved face"
            f" (state {representation.state}, identity {representation.identity_id})"
        )
    observation = session.get(Observation, representation.observation_id)
    assert observation is not None  # (a foreign key)
    if observation.state != ObservationState.ACTIVE:
        raise IdentityManagerError(f"the observation of {representation_id} is {observation.state}")
    if session.scalar(
        select(Occurrence.id)
        .outerjoin(OccurrenceObservation, OccurrenceObservation.occurrence_id == Occurrence.id)
        .where(
            Occurrence.state == OccurrenceState.ACTIVE,
            (Occurrence.representative_observation_id == observation.id)
            | (OccurrenceObservation.observation_id == observation.id),
        )
        .limit(1)
    ):
        raise IdentityManagerError(
            f"the face of representation {representation_id} has an occurrence"
        )
    abstentions = abstentions_of(session, representation.id)
    if len(abstentions) != 1:
        raise IdentityManagerError(
            f"representation {representation_id} has {len(abstentions)} recorded abstentions,"
            " not one: it is not a face recognition declined to place"
        )
    now = clock()
    target = (
        None if to_identity_id is None else _identity(session, to_identity_id, "can receive a face")
    )
    created = target is None
    if target is None:
        target = Identity(
            id=new_id(),
            state=IdentityState.ACTIVE,
            created_by_processing_run_id=None,
            created_at=now,
            activated_at=now,
            updated_at=now,
        )
        session.add(target)
        session.flush()
    occurrence = Occurrence(
        id=new_id(),
        source_id=observation.source_id,
        identity_id=target.id,
        processing_run_id=representation.processing_run_id,
        representative_observation_id=observation.id,
        kind=OccurrenceKind.IMAGE,
        state=OccurrenceState.ACTIVE,
        created_at=now,
        activated_at=now,
    )
    evidence = Evidence(
        id=new_id(),
        kind=EvidenceKind.USER_CORRECTION,
        source_id=observation.source_id,
        subject_identity_id=target.id,
        payload_schema_version=1,
        payload_json={
            "action": "RESOLVE_NEW" if created else "RESOLVE",
            "occurrence_id": str(occurrence.id),
            "representation_ids": [str(representation.id)],
            "to_identity_id": str(target.id),
            "resolves_evidence_id": str(abstentions[0]),
        },
        created_at=now,
    )
    session.add(evidence)
    session.flush()
    session.add(
        EvidenceRepresentation(
            evidence_id=evidence.id,
            representation_id=representation.id,
            role=EvidenceRepresentationRole.SUBJECT,
        )
    )
    OccurrenceRepository(session).add(occurrence, (observation.id,))
    representation.identity_id = target.id
    if target.representative_observation_id is None:
        target.representative_observation_id = observation.id
        target.updated_at = now
    session.flush()
    return occurrence


def _refresh_representative(
    session: Session, identity: Identity, moved_observations: list[uuid.UUID], now: datetime
) -> None:
    """An identity's representative face must not be one that has just left it."""
    if identity.representative_observation_id not in moved_observations:
        return
    # Only a face whose representation the identity still owns can stand for it (an observation
    # can belong to two occurrences, and moving one moves the representation both rest on).
    identity.representative_observation_id = session.scalar(
        select(Occurrence.representative_observation_id)
        .join(
            Representation,
            Representation.observation_id == Occurrence.representative_observation_id,
        )
        .where(
            Occurrence.identity_id == identity.id,
            Occurrence.state == OccurrenceState.ACTIVE,
            Representation.identity_id == identity.id,
            Representation.state == RepresentationState.ACTIVE,
        )
        .order_by(Occurrence.created_at, Occurrence.id)
        .limit(1)
    )
    identity.updated_at = now
