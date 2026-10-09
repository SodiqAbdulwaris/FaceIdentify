"""Historical and name search over the authoritative library (API and Contracts.md section 12.1;
universal-search-and-retrieval-architecture-v1.md; M5 step 5a; TST-055).

`GET /search?q=` reads only what is authoritative and active: people by name, unnamed identities by
their label, sources by file name, and the appearances (occurrences) of the people and identities
found. A query is not an ingest: nothing is written, and no index is needed (these lookups ask
SQLite; the face index is for face search, step 5b). Results are ranked within their own type by a
plain rule (exact name, then prefix, then contains), never fused into one score (spec section 5);
each response says how it was planned and how much of the library it could see (spec section 7).

Agent design, because the spec leaves it open (section 11): the query is one text, case-insensitive,
matched as a whole; `recycled` is the hard constraint on the image's place (`include`, the default,
marks recycled images; `exclude` hides them; `only` shows just those); a source being or already
deleted never appears. A source's appearances of a recycled image keep `source_recycled: true`.
"""

import re
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import String, case, cast, func, select
from sqlalchemy.orm import Session

from backend.api.dependencies import Library
from backend.api.errors import ApiError
from backend.api.routes.memory import OccurrenceSummary, occurrence_summaries
from backend.app.identities.models import Identity, IdentityState
from backend.app.memory.models import Occurrence, OccurrenceState
from backend.app.people.models import (
    AssociationState,
    IdentityPersonAssociation,
    Person,
    PersonState,
)
from backend.app.processing.models import ProcessingRun, ProcessingRunState
from backend.app.sources.models import Source, SourceState

router = APIRouter(tags=["search"])

Recycled = Literal["include", "exclude", "only"]
Kind = Literal["people", "identities", "sources", "occurrences"]
KINDS: tuple[Kind, ...] = ("people", "identities", "sources", "occurrences")
Match = Literal["EXACT", "PREFIX", "CONTAINS"]
_RANK = {"EXACT": 0, "PREFIX": 1, "CONTAINS": 2}
_HEX = re.compile(r"[0-9a-f]+")


class PersonHit(BaseModel):
    id: str
    display_name: str
    match: Match
    identity_ids: list[str]
    occurrence_count: int
    source_count: int
    # False once nothing visual is left to recognise them by (images deleted, faces forgotten).
    visual_support: bool
    # Their faces were forgotten on purpose and none remain; the name stays (owner, 2026-10-09).
    biometric_memory_forgotten: bool


class IdentityHit(BaseModel):
    id: str
    label: str
    match: Match
    occurrence_count: int
    source_count: int


class SourceHit(BaseModel):
    id: str
    display_name: str
    match: Match
    state: str
    source_recycled: bool
    processed: bool


class Results(BaseModel):
    people: list[PersonHit]
    identities: list[IdentityHit]
    sources: list[SourceHit]
    occurrences: list[OccurrenceSummary]


class Coverage(BaseModel):
    """How much of the library a search could see: unprocessed images have no faces to find."""

    sources: int
    processed: int
    not_processed: int


class Ranking(BaseModel):
    plan: str
    ranker: str
    recycled: Recycled
    types: list[str]


class SearchResponse(BaseModel):
    query: str
    results: Results
    coverage: Coverage
    ranking: Ranking


def _normal(text: str) -> str:
    return " ".join(text.split()).casefold()


def _match(name: str, query: str) -> Match:
    if name == query:
        return "EXACT"
    return "PREFIX" if name.startswith(query) else "CONTAINS"


def _label(identity_id: uuid.UUID) -> str:
    return f"Person {identity_id.hex[:6].upper()}"


def _states(recycled: Recycled) -> tuple[str, ...]:
    return {
        "include": (SourceState.ACTIVE, SourceState.RECYCLED),
        "exclude": (SourceState.ACTIVE,),
        "only": (SourceState.RECYCLED,),
    }[recycled]


def _counts(
    session: Session, identity_ids: list[uuid.UUID], states: tuple[str, ...]
) -> dict[uuid.UUID, tuple[int, int]]:
    """(appearances, images) per identity, over the images this search may see."""
    return {
        identity_id: (appearances, images)
        for identity_id, appearances, images in session.execute(
            select(
                Occurrence.identity_id,
                func.count(Occurrence.id),
                func.count(func.distinct(Occurrence.source_id)),
            )
            .join(Source, Source.id == Occurrence.source_id)
            .where(
                Occurrence.identity_id.in_(identity_ids),
                Occurrence.state == OccurrenceState.ACTIVE,
                Source.state.in_(states),
            )
            .group_by(Occurrence.identity_id)
        )
    }


def _people(
    session: Session, query: str, states: tuple[str, ...], limit: int
) -> tuple[list[PersonHit], list[uuid.UUID]]:
    rank = case(
        (Person.normalized_name == query, 0),
        (Person.normalized_name.startswith(query, autoescape=True), 1),
        else_=2,
    )
    people = list(
        session.scalars(
            select(Person)
            .where(
                Person.state == PersonState.ACTIVE,
                Person.normalized_name.contains(query, autoescape=True),
            )
            .order_by(rank, Person.normalized_name, Person.id)
            .limit(limit)
        )
    )
    linked: dict[uuid.UUID, list[uuid.UUID]] = {person.id: [] for person in people}
    for person_id, identity_id in session.execute(
        select(IdentityPersonAssociation.person_id, IdentityPersonAssociation.identity_id)
        .join(Identity, Identity.id == IdentityPersonAssociation.identity_id)
        .where(
            IdentityPersonAssociation.person_id.in_(list(linked)),
            IdentityPersonAssociation.state == AssociationState.ACTIVE,
            Identity.state == IdentityState.ACTIVE,
        )
    ):
        linked[person_id].append(identity_id)
    everyone = [identity for ids in linked.values() for identity in ids]
    forgotten = set(
        session.scalars(
            select(IdentityPersonAssociation.person_id)
            .join(Identity, Identity.id == IdentityPersonAssociation.identity_id)
            .where(
                IdentityPersonAssociation.person_id.in_(list(linked)),
                Identity.state == IdentityState.FORGOTTEN,
            )
        )
    )
    counts = _counts(session, everyone, states)
    hits = []
    for person in people:
        totals = [counts.get(identity, (0, 0)) for identity in linked[person.id]]
        appearances = sum(a for a, _ in totals)
        hits.append(
            PersonHit(
                id=str(person.id),
                display_name=person.display_name,
                match=_match(person.normalized_name or "", query),
                identity_ids=[str(identity) for identity in linked[person.id]],
                occurrence_count=appearances,
                # (images, not appearances: one image may show two of the person's identities)
                source_count=_distinct_sources(session, linked[person.id], states),
                visual_support=appearances > 0,
                biometric_memory_forgotten=person.id in forgotten and not linked[person.id],
            )
        )
    return hits, everyone


def _distinct_sources(
    session: Session, identity_ids: list[uuid.UUID], states: tuple[str, ...]
) -> int:
    if not identity_ids:
        return 0
    return (
        session.scalar(
            select(func.count(func.distinct(Occurrence.source_id)))
            .join(Source, Source.id == Occurrence.source_id)
            .where(
                Occurrence.identity_id.in_(identity_ids),
                Occurrence.state == OccurrenceState.ACTIVE,
                Source.state.in_(states),
            )
        )
        or 0
    )


def _identities(
    session: Session, query: str, states: tuple[str, ...], limit: int
) -> tuple[list[IdentityHit], list[uuid.UUID]]:
    """Unnamed identities by their label (`Person A1B2C3`) or the start of their id."""
    typed = query.removeprefix("person").strip().replace("-", "")
    if not _HEX.fullmatch(typed):
        return [], []
    named = select(IdentityPersonAssociation.identity_id).where(
        IdentityPersonAssociation.state == AssociationState.ACTIVE
    )
    found = list(
        session.scalars(
            select(Identity.id)
            .where(
                Identity.state == IdentityState.ACTIVE,
                Identity.id.not_in(named),
                func.lower(cast(Identity.id, String)).startswith(typed),
            )
            .order_by(Identity.id)
            .limit(limit)
        )
    )
    counts = _counts(session, found, states)
    hits = [
        IdentityHit(
            id=str(identity),
            label=_label(identity),
            match="EXACT" if identity.hex[:6] == typed else "PREFIX",
            occurrence_count=counts.get(identity, (0, 0))[0],
            source_count=counts.get(identity, (0, 0))[1],
        )
        for identity in found
    ]
    return hits, found


def _sources(session: Session, query: str, states: tuple[str, ...], limit: int) -> list[SourceHit]:
    # File names are matched in Python so they get the query's own normalisation (case folding,
    # collapsed spaces); SQLite's lower() is ASCII-only. ponytail: reads every visible name; push
    # into SQL (a stored normalised name) if libraries grow to hundreds of thousands of images.
    rows = session.execute(
        select(Source, ProcessingRun.state)
        .outerjoin(ProcessingRun, ProcessingRun.id == Source.current_processing_run_id)
        .where(Source.state.in_(states))
    ).tuples()
    hits = [
        SourceHit(
            id=str(source.id),
            display_name=source.display_name,
            match=_match(_normal(source.display_name), query),
            state=source.state,
            source_recycled=source.state == SourceState.RECYCLED,
            processed=run_state == ProcessingRunState.COMPLETED,
        )
        for source, run_state in rows
        if query in _normal(source.display_name)
    ]
    hits.sort(key=lambda h: (_RANK[h.match], h.display_name.casefold(), h.id))
    return hits[:limit]


def _appearances(
    session: Session, identity_ids: list[uuid.UUID], states: tuple[str, ...], limit: int
) -> list[OccurrenceSummary]:
    if not identity_ids:
        return []
    rows = (
        session.execute(
            select(Occurrence, Source)
            .join(Source, Source.id == Occurrence.source_id)
            .where(
                Occurrence.identity_id.in_(identity_ids),
                Occurrence.state == OccurrenceState.ACTIVE,
                Source.state.in_(states),
            )
            .order_by(Occurrence.created_at.desc(), Occurrence.id.desc())
            .limit(limit)
            .execution_options(populate_existing=True)
        )
        .tuples()
        .all()
    )
    return occurrence_summaries(session, rows)


def _coverage(session: Session, states: tuple[str, ...]) -> Coverage:
    total = session.scalar(select(func.count()).select_from(Source).where(Source.state.in_(states)))
    processed = session.scalar(
        select(func.count())
        .select_from(Source)
        .join(ProcessingRun, ProcessingRun.id == Source.current_processing_run_id)
        .where(Source.state.in_(states), ProcessingRun.state == ProcessingRunState.COMPLETED)
    )
    return Coverage(
        sources=total or 0, processed=processed or 0, not_processed=(total or 0) - (processed or 0)
    )


@router.get("/search")
def search(
    library: Library,
    q: Annotated[str, Query(min_length=1, max_length=200)],
    recycled: Recycled = "exclude",
    types: Annotated[
        str, Query(description="Comma-separated: people,identities,sources,occurrences")
    ] = ",".join(KINDS),
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> SearchResponse:
    query = _normal(q)
    wanted = [kind.strip() for kind in types.split(",") if kind.strip()]
    if not query or not wanted or any(kind not in KINDS for kind in wanted):
        raise ApiError(
            422, "INVALID_SEARCH", "Give a word to look for and, optionally, which kinds.",
            details={"types": list(KINDS)},
        )  # fmt: skip
    states = _states(recycled)

    def read(session: Session) -> SearchResponse:
        # Appearances come from the people and identities found, so those are looked up whenever
        # any of the three is asked for; only the asked-for groups are returned.
        people, person_identities = _people(session, query, states, limit)
        identities, unnamed = _identities(session, query, states, limit)
        sources = _sources(session, query, states, limit) if "sources" in wanted else []
        appearances = (
            _appearances(session, [*person_identities, *unnamed], states, limit)
            if "occurrences" in wanted
            else []
        )
        return SearchResponse(
            query=query,
            results=Results(
                people=people if "people" in wanted else [],
                identities=identities if "identities" in wanted else [],
                sources=sources,
                occurrences=appearances,
            ),
            coverage=_coverage(session, states),
            ranking=Ranking(plan="NAME_LOOKUP", ranker="rule-v1", recycled=recycled, types=wanted),
        )

    return library.unit_of_work.read(read)
