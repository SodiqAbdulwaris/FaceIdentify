"""Identities and occurrences, read-only (API sections 8, 9 and 11; M4 W3.5).

What a person sees is what has been made authoritative. An observation, occurrence or identity that
is still `PENDING` (a run's private output) is never listed or returned, whatever its ids; only
`ACTIVE` ones are. A representative observation that is not `ACTIVE` is simply absent. Bounding
boxes are the normalized coordinates the pipeline stored. No face crops exist yet, so `face_crop`
is always `null` (the field is in the contract so it does not change when they do).
"""

import uuid
from collections.abc import Sequence
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from backend.api.dependencies import Library
from backend.api.errors import ApiError
from backend.api.pagination import (
    Page,
    PageQuery,
    created_cursor,
    created_key,
    older_than,
    paginate,
)
from backend.api.routes.sources import MediaReference, source_not_found
from backend.app.identities.models import Identity, IdentityState
from backend.app.memory.models import Observation, ObservationState, Occurrence, OccurrenceState
from backend.app.people.models import AssociationState, IdentityPersonAssociation, Person
from backend.app.sources.models import Source, SourceState

router = APIRouter(tags=["memory"])


class BoundingBox(BaseModel):
    x: float
    y: float
    width: float
    height: float


class ObservationBrief(BaseModel):
    id: str
    source_id: str
    bounding_box: BoundingBox
    face_crop: MediaReference | None


class PersonReference(BaseModel):
    id: str
    display_name: str
    revision: int


class OccurrenceSummary(BaseModel):
    id: str
    source_id: str
    source_display_name: str
    identity_id: str
    kind: str
    representative_observation: ObservationBrief | None
    person: PersonReference | None
    # The Source is in the Recycle Bin: its faces stay in memory, counts and search, marked.
    source_recycled: bool
    created_at: datetime


class IdentitySummary(BaseModel):
    id: str
    state: str
    revision: int
    person: PersonReference | None
    representative_observation: ObservationBrief | None
    occurrence_count: int
    source_count: int
    created_at: datetime
    activated_at: datetime | None


def identity_not_found(identity_id: uuid.UUID) -> ApiError:
    return ApiError(
        404, "IDENTITY_NOT_FOUND", "The requested identity could not be found.",
        details={"identity_id": str(identity_id)},
    )  # fmt: skip


def _representatives(session: Session, ids: list[uuid.UUID | None]) -> dict[uuid.UUID, Observation]:
    wanted = [i for i in ids if i is not None]
    return {o.id: o for o in session.scalars(select(Observation).where(Observation.id.in_(wanted)))}


def _brief(
    observations: dict[uuid.UUID, Observation], observation_id: uuid.UUID | None
) -> ObservationBrief | None:
    observation = None if observation_id is None else observations.get(observation_id)
    if observation is None or observation.state != ObservationState.ACTIVE:
        return None
    return ObservationBrief(
        id=str(observation.id),
        source_id=str(observation.source_id),
        bounding_box=BoundingBox(
            x=observation.bbox_x,
            y=observation.bbox_y,
            width=observation.bbox_width,
            height=observation.bbox_height,
        ),
        face_crop=None,
    )


# --- occurrences ----------------------------------------------------------------------------


def occurrence_summaries(
    session: Session, rows: Sequence[tuple[Occurrence, Source]]
) -> list[OccurrenceSummary]:
    observations = _representatives(session, [occ.representative_observation_id for occ, _ in rows])
    people = person_references(session, [occ.identity_id for occ, _ in rows])
    return [
        OccurrenceSummary(
            id=str(occ.id),
            source_id=str(occ.source_id),
            source_display_name=source.display_name,
            identity_id=str(occ.identity_id),
            kind=occ.kind,
            representative_observation=_brief(observations, occ.representative_observation_id),
            person=people.get(occ.identity_id),
            source_recycled=source.state == SourceState.RECYCLED,
            created_at=occ.created_at,
        )
        for occ, source in rows
    ]


def _occurrence_page(
    session: Session, query: Select[tuple[Occurrence, Source]], page: PageQuery, context: str
) -> Page[OccurrenceSummary]:
    after = created_cursor(page.cursor, context)
    query = query.where(Occurrence.state == OccurrenceState.ACTIVE)
    if after is not None:
        query = query.where(older_than(Occurrence.created_at, Occurrence.id, after))
    rows = (
        session.execute(
            query.order_by(Occurrence.created_at.desc(), Occurrence.id.desc())
            .limit(page.limit + 1)
            .execution_options(populate_existing=True)
        )
        .tuples()
        .all()
    )
    summaries = {s.id: s for s in occurrence_summaries(session, rows)}
    return paginate(
        rows,
        page.limit,
        context=context,
        key=lambda row: created_key(row[0].created_at, row[0].id),
        item=lambda row: summaries[str(row[0].id)],
    )


def _occurrences() -> Select[tuple[Occurrence, Source]]:
    return select(Occurrence, Source).join(Source, Source.id == Occurrence.source_id)


@router.get("/sources/{source_id}/occurrences")
def source_occurrences(
    source_id: uuid.UUID, library: Library, page: PageQuery
) -> Page[OccurrenceSummary]:
    def read(session: Session) -> Page[OccurrenceSummary]:
        if session.get(Source, source_id) is None:
            raise source_not_found(source_id)
        return _occurrence_page(
            session,
            _occurrences().where(Occurrence.source_id == source_id),
            page,
            f"occurrences:source:{source_id}",
        )

    return library.unit_of_work.read(read)


@router.get("/identities/{identity_id}/occurrences")
def identity_occurrences(
    identity_id: uuid.UUID, library: Library, page: PageQuery
) -> Page[OccurrenceSummary]:
    def read(session: Session) -> Page[OccurrenceSummary]:
        _active_identity(session, identity_id)
        return _occurrence_page(
            session,
            _occurrences().where(Occurrence.identity_id == identity_id),
            page,
            f"occurrences:identity:{identity_id}",
        )

    return library.unit_of_work.read(read)


# --- identities -----------------------------------------------------------------------------


def _active_identity(session: Session, identity_id: uuid.UUID) -> Identity:
    identity = session.get(Identity, identity_id, populate_existing=True)
    if identity is None or identity.state != IdentityState.ACTIVE:
        raise identity_not_found(identity_id)
    return identity


def person_references(
    session: Session, identity_ids: list[uuid.UUID]
) -> dict[uuid.UUID, PersonReference]:
    """Who each identity is named as, for those that are named."""
    return {
        identity_id: PersonReference(
            id=str(person.id), display_name=person.display_name, revision=person.revision
        )
        for identity_id, person in session.execute(
            select(IdentityPersonAssociation.identity_id, Person)
            .join(Person, Person.id == IdentityPersonAssociation.person_id)
            .where(
                IdentityPersonAssociation.identity_id.in_(identity_ids),
                IdentityPersonAssociation.state == AssociationState.ACTIVE,
            )
            .execution_options(populate_existing=True)
        ).tuples()
    }


def identity_summaries(session: Session, identities: list[Identity]) -> list[IdentitySummary]:
    ids = [identity.id for identity in identities]
    counts = {
        identity_id: (occurrences, sources)
        for identity_id, occurrences, sources in session.execute(
            select(
                Occurrence.identity_id,
                func.count(Occurrence.id),
                func.count(func.distinct(Occurrence.source_id)),
            )
            .where(Occurrence.identity_id.in_(ids), Occurrence.state == OccurrenceState.ACTIVE)
            .group_by(Occurrence.identity_id)
        )
    }
    observations = _representatives(session, [i.representative_observation_id for i in identities])
    people = person_references(session, ids)
    return [
        IdentitySummary(
            id=str(identity.id),
            state=identity.state,
            revision=identity.revision,
            person=people.get(identity.id),
            representative_observation=_brief(observations, identity.representative_observation_id),
            occurrence_count=counts.get(identity.id, (0, 0))[0],
            source_count=counts.get(identity.id, (0, 0))[1],
            created_at=identity.created_at,
            activated_at=identity.activated_at,
        )
        for identity in identities
    ]


@router.get("/identities")
def list_identities(library: Library, page: PageQuery) -> Page[IdentitySummary]:
    context = "identities"
    after = created_cursor(page.cursor, context)

    def read(session: Session) -> Page[IdentitySummary]:
        query = select(Identity).where(Identity.state == IdentityState.ACTIVE)
        if after is not None:
            query = query.where(older_than(Identity.created_at, Identity.id, after))
        identities = list(
            session.scalars(
                query.order_by(Identity.created_at.desc(), Identity.id.desc())
                .limit(page.limit + 1)
                .execution_options(populate_existing=True)
            )
        )
        summaries = {s.id: s for s in identity_summaries(session, identities)}
        return paginate(
            identities,
            page.limit,
            context=context,
            key=lambda identity: created_key(identity.created_at, identity.id),
            item=lambda identity: summaries[str(identity.id)],
        )

    return library.unit_of_work.read(read)


@router.get("/identities/{identity_id}")
def get_identity(identity_id: uuid.UUID, library: Library) -> IdentitySummary:
    def read(session: Session) -> IdentitySummary:
        return identity_summaries(session, [_active_identity(session, identity_id)])[0]

    return library.unit_of_work.read(read)
