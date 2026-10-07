"""Correcting a recognised face: confirm it, move it, or separate it; resolving an unplaced one.

The API spec says human corrections must leave correction history and gives no route for them, so
these two commands are the agent's design (flagged in the implementation entry): they name the
occurrence (the face in a source), carry the identity the user saw it under so a stale view is
refused, and return the occurrence as it now is. Each is one use case with one Evidence row.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.dependencies import Library, get_backend
from backend.api.errors import ApiError
from backend.api.routes.memory import (
    BoundingBox,
    OccurrenceSummary,
    PersonReference,
    identity_not_found,
    occurrence_summaries,
    person_references,
)
from backend.api.startup import Backend
from backend.app.identities.corrections import (
    confirm_occurrence,
    reassign_occurrence,
    resolve_representation,
)
from backend.app.identities.models import (
    Evidence,
    EvidenceCandidate,
    EvidenceKind,
    EvidenceRepresentation,
    Identity,
    IdentityState,
)
from backend.app.identities.use_cases import IdentityManagerError, StaleRevisionError
from backend.app.memory.models import (
    Observation,
    ObservationState,
    Occurrence,
    OccurrenceState,
    Representation,
    RepresentationState,
)
from backend.app.sources.models import Source

router = APIRouter(tags=["corrections"])


class Confirm(BaseModel):
    expected_identity_id: uuid.UUID


class Reassign(BaseModel):
    expected_identity_id: uuid.UUID
    identity_id: uuid.UUID | None  # None: separate the face into a new unknown identity


def _not_found(occurrence_id: uuid.UUID) -> ApiError:
    return ApiError(
        404, "OCCURRENCE_NOT_FOUND", "The requested face could not be found.",
        details={"occurrence_id": str(occurrence_id)},
    )  # fmt: skip


def _moved(error: StaleRevisionError) -> ApiError:
    return ApiError(
        409, "OCCURRENCE_MOVED", "This face now belongs to someone else. Reload and try again.",
        details={"reason": str(error)},
    )  # fmt: skip


def _summary(session: Session, occurrence_id: uuid.UUID) -> OccurrenceSummary:
    row = session.execute(
        select(Occurrence, Source)
        .join(Source, Source.id == Occurrence.source_id)
        .where(Occurrence.id == occurrence_id, Occurrence.state == OccurrenceState.ACTIVE)
        .execution_options(populate_existing=True)
    ).tuples().one_or_none()  # fmt: skip
    if row is None:
        raise _not_found(occurrence_id)
    return occurrence_summaries(session, [row])[0]


@router.get("/occurrences/{occurrence_id}")
def get_occurrence(occurrence_id: uuid.UUID, library: Library) -> OccurrenceSummary:
    return library.unit_of_work.read(lambda session: _summary(session, occurrence_id))


@router.post("/occurrences/{occurrence_id}/confirm")
def confirm(
    occurrence_id: uuid.UUID,
    body: Confirm,
    library: Library,
    backend: Annotated[Backend, Depends(get_backend)],
) -> OccurrenceSummary:
    settings = backend.settings

    def write(session: Session) -> OccurrenceSummary:
        _summary(session, occurrence_id)  # 404 if it is not an active face
        try:
            confirm_occurrence(
                session, occurrence_id, expected_identity_id=body.expected_identity_id,
                new_id=settings.new_id, clock=settings.clock,
            )  # fmt: skip
        except StaleRevisionError as error:
            raise _moved(error) from None
        except IdentityManagerError as error:
            raise ApiError(
                409, "FACE_NOT_CORRECTABLE", "This face cannot be confirmed now.",
                details={"reason": str(error)},
            ) from None  # fmt: skip
        return _summary(session, occurrence_id)

    result = library.unit_of_work.write(write)
    backend.announce("occurrence.updated", "occurrence", str(occurrence_id))
    return result


@router.post("/occurrences/{occurrence_id}/reassign")
def reassign(
    occurrence_id: uuid.UUID,
    body: Reassign,
    library: Library,
    backend: Annotated[Backend, Depends(get_backend)],
) -> OccurrenceSummary:
    settings = backend.settings

    def write(session: Session) -> OccurrenceSummary:
        current = _summary(session, occurrence_id)  # 404 if it is not an active face
        if current.identity_id != str(body.expected_identity_id):
            raise _moved(StaleRevisionError("the face is under another identity"))
        if body.identity_id is not None:
            target = session.get(Identity, body.identity_id)
            if target is None or target.state != IdentityState.ACTIVE:
                raise identity_not_found(body.identity_id)
        try:
            reassign_occurrence(
                session, occurrence_id, body.identity_id,
                expected_identity_id=body.expected_identity_id,
                new_id=settings.new_id, clock=settings.clock,
            )  # fmt: skip
        except IdentityManagerError as error:  # (staleness was checked above, in this transaction)
            raise ApiError(
                409, "FACE_NOT_CORRECTABLE", "This face cannot be moved there.",
                details={"reason": str(error)},
            ) from None  # fmt: skip
        return _summary(session, occurrence_id)

    result = library.unit_of_work.write(write)
    backend.announce("occurrence.updated", "occurrence", str(occurrence_id))
    return result


# --- faces recognition declined to place (issue 79) -------------------------------------------

LIKELY_PEOPLE = 3


class Likely(BaseModel):
    identity_id: str
    person: PersonReference | None
    similarity: float


class UnresolvedFace(BaseModel):
    representation_id: str
    observation_id: str
    bounding_box: BoundingBox
    likely: list[Likely]  # who it resembled most, best first (a hint, not a decision)


class UnresolvedFaces(BaseModel):
    items: list[UnresolvedFace]


class Resolve(BaseModel):
    identity_id: uuid.UUID | None  # None: a new unknown identity


def _likely(session: Session, representation_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[Likely]]:
    """For each face, the identities its abstention compared it with, best similarity first."""
    rows = session.execute(
        select(
            EvidenceRepresentation.representation_id,
            EvidenceCandidate.identity_id,
            EvidenceCandidate.raw_similarity,
        )
        .join(Evidence, Evidence.id == EvidenceRepresentation.evidence_id)
        .join(EvidenceCandidate, EvidenceCandidate.evidence_id == Evidence.id)
        .where(
            Evidence.kind == EvidenceKind.RECOGNITION_ABSTAINED,
            EvidenceRepresentation.representation_id.in_(representation_ids),
            EvidenceCandidate.identity_id.is_not(None),
        )
        .order_by(EvidenceCandidate.raw_similarity.desc(), EvidenceCandidate.rank)
    ).tuples()
    best: dict[uuid.UUID, dict[uuid.UUID, float]] = {}
    for representation_id, identity_id, similarity in rows:
        assert identity_id is not None  # (filtered above)
        best.setdefault(representation_id, {}).setdefault(identity_id, similarity)
    identities = {i for per in best.values() for i in per}
    active = set(
        session.scalars(
            select(Identity.id).where(
                Identity.id.in_(identities), Identity.state == IdentityState.ACTIVE
            )
        )
    )
    people = person_references(session, list(active))
    return {
        representation_id: [
            Likely(identity_id=str(i), person=people.get(i), similarity=score)
            for i, score in per.items()
            if i in active
        ][:LIKELY_PEOPLE]
        for representation_id, per in best.items()
    }


@router.get("/sources/{source_id}/unresolved-faces")
def unresolved_faces(source_id: uuid.UUID, library: Library) -> UnresolvedFaces:
    def read(session: Session) -> UnresolvedFaces:
        if session.get(Source, source_id) is None:
            raise ApiError(
                404, "SOURCE_NOT_FOUND", "The requested source could not be found.",
                details={"source_id": str(source_id)},
            )  # fmt: skip
        rows = session.execute(
            select(Representation, Observation)
            .join(Observation, Observation.id == Representation.observation_id)
            .where(
                Observation.source_id == source_id,
                Observation.state == ObservationState.ACTIVE,
                Representation.state == RepresentationState.ACTIVE,
                Representation.identity_id.is_(None),
            )
            .order_by(Observation.id)
            .execution_options(populate_existing=True)
        ).tuples().all()  # fmt: skip
        likely = _likely(session, [r.id for r, _ in rows])
        return UnresolvedFaces(
            items=[
                UnresolvedFace(
                    representation_id=str(r.id),
                    observation_id=str(o.id),
                    bounding_box=BoundingBox(
                        x=o.bbox_x, y=o.bbox_y, width=o.bbox_width, height=o.bbox_height
                    ),
                    likely=likely.get(r.id, []),
                )
                for r, o in rows
            ]
        )

    return library.unit_of_work.read(read)


@router.post("/representations/{representation_id}/resolve")
def resolve(
    representation_id: uuid.UUID,
    body: Resolve,
    library: Library,
    backend: Annotated[Backend, Depends(get_backend)],
) -> OccurrenceSummary:
    settings = backend.settings

    def write(session: Session) -> OccurrenceSummary:
        if session.get(Representation, representation_id) is None:
            raise ApiError(
                404, "FACE_NOT_FOUND", "The requested face could not be found.",
                details={"representation_id": str(representation_id)},
            )  # fmt: skip
        if body.identity_id is not None:
            target = session.get(Identity, body.identity_id)
            if target is None or target.state != IdentityState.ACTIVE:
                raise identity_not_found(body.identity_id)
        try:
            occurrence = resolve_representation(
                session, representation_id, body.identity_id,
                new_id=settings.new_id, clock=settings.clock,
            )  # fmt: skip
        except IdentityManagerError as error:
            raise ApiError(
                409, "FACE_NOT_RESOLVABLE", "This face cannot be resolved now.",
                details={"reason": str(error)},
            ) from None  # fmt: skip
        return _summary(session, occurrence.id)

    result = library.unit_of_work.write(write)
    backend.announce("occurrence.updated", "occurrence", result.id)
    return result
