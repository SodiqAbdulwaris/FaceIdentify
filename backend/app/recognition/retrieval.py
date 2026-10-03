"""Candidate retrieval for recognition: one query vector, one representation space, two pools.

Recognition searches the **global** pool (the space's persisted index of `ACTIVE` representations)
and the **run-local** pool (this run's own `PENDING` representations, in memory), Persistence 23.
What comes back is a bounded shortlist, and nothing more: ANN similarity is a retrieval signal,
neither a confirmed identity nor a decision (ML spec 1, 3).

Compatibility is enforced here, not trusted: the query vector, the global index and the run-local
index must all be the one representation space's, or `IncompatibleSpaceError` is raised and
nothing is searched; and every candidate an index returns is revalidated against SQLite, which
drops it unless it is still in that space and eligible (a global candidate: `ACTIVE`, with an
`ACTIVE` identity, `resolve_ann_candidates`; a run-local one: still `PENDING` in this run). A stale
index can name a representation that was erased, merged away or discarded; SQLite refuses it. The
number refused is reported (`dropped`), so a caller can tell a short shortlist from a complete one.

The caller supplies the global index it has opened (`open_or_rebuild`); a missing or unusable one
is the caller's failure to report, never an empty answer here: an empty library has an empty
index, and "no candidates" must not be confused with "could not look".

The run-local pool is rebuilt from SQLite after a crash (`rebuild_run_local_index`): it was only
ever a copy of the run's pending representations.

Distances are the index's (`cos`: 1 minus the cosine similarity); `similarity` is derived from them
for the cosine metric, the only one a space may have today.
"""

import uuid
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.identities.use_cases import resolve_ann_candidates
from backend.app.memory.index_coordinator import decode_vector
from backend.app.memory.models import Representation, RepresentationState
from backend.infrastructure.indexing.representation_index import RepresentationIndex, Vector
from backend.infrastructure.indexing.run_local_index import RunLocalIndex

# Ids per SELECT, well under SQLite's bound-variable limit (see `resolve_ann_candidates`).
_IDS_PER_QUERY = 500


class IncompatibleSpaceError(ValueError):
    """The query, the global index and the run-local index are not all one space's."""


class Pool(StrEnum):
    GLOBAL = "GLOBAL"
    RUN_LOCAL = "RUN_LOCAL"


@dataclass(frozen=True, slots=True)
class RetrievedCandidate:
    pool: Pool
    representation_id: uuid.UUID
    identity_id: uuid.UUID | None  # None for a run-local candidate: it has no identity yet
    distance: float

    @property
    def similarity(self) -> float:
        """The cosine similarity (the metric is `cos`, so the distance is 1 minus it)."""
        return 1.0 - self.distance


@dataclass(frozen=True, slots=True)
class Retrieval:
    representation_space_id: uuid.UUID
    requested_k: int
    candidates: tuple[RetrievedCandidate, ...]  # nearest first, at most `requested_k`, both pools
    dropped: int  # candidates an index returned that SQLite refused (stale: erased, merged, ...)


def retrieve(
    session: Session,
    *,
    representation_space_id: uuid.UUID,
    dimension: int,
    vector: Vector,
    k: int,
    global_index: RepresentationIndex,
    processing_run_id: uuid.UUID,
    run_local: RunLocalIndex | None = None,
) -> Retrieval:
    if global_index.representation_space_id != representation_space_id or (
        global_index.ndim != dimension
    ):
        raise IncompatibleSpaceError("the global index is not this representation space's")
    if run_local is not None and (
        run_local.representation_space_id != representation_space_id or run_local.ndim != dimension
    ):
        raise IncompatibleSpaceError("the run-local index is not this representation space's")
    found: list[RetrievedCandidate] = []
    dropped = 0

    hits = global_index.search(vector, k)
    distance_of = {hit.key: hit.distance for hit in hits}
    for kept in resolve_ann_candidates(session, representation_space_id, list(distance_of)):
        found.append(
            RetrievedCandidate(
                Pool.GLOBAL, kept.representation_id, kept.identity_id, distance_of[kept.ann_key]
            )
        )
    dropped += len(hits) - len(found)

    if run_local is not None:
        near = run_local.search(vector, k)
        distances = {hit.representation_id: hit.distance for hit in near}
        alive = _still_pending(session, processing_run_id, representation_space_id, list(distances))
        found.extend(
            RetrievedCandidate(Pool.RUN_LOCAL, identifier, None, distances[identifier])
            for identifier in alive
        )
        dropped += len(near) - len(alive)

    found.sort(key=lambda c: (c.distance, c.pool, str(c.representation_id)))
    return Retrieval(representation_space_id, k, tuple(found[:k]), dropped)


def _still_pending(
    session: Session,
    processing_run_id: uuid.UUID,
    representation_space_id: uuid.UUID,
    representation_ids: list[uuid.UUID],
) -> list[uuid.UUID]:
    """The ids that are still `PENDING` representations of this run in this space (plain columns,
    no ORM objects: the answer is the database's, not a cached row's)."""
    alive: list[uuid.UUID] = []
    for start in range(0, len(representation_ids), _IDS_PER_QUERY):
        alive.extend(
            session.scalars(
                select(Representation.id).where(
                    Representation.id.in_(representation_ids[start : start + _IDS_PER_QUERY]),
                    Representation.processing_run_id == processing_run_id,
                    Representation.representation_space_id == representation_space_id,
                    Representation.state == RepresentationState.PENDING,
                )
            )
        )
    return alive


def rebuild_run_local_index(
    session: Session,
    *,
    processing_run_id: uuid.UUID,
    representation_space_id: uuid.UUID,
    dimension: int,
    metric: str,
) -> RunLocalIndex:
    """The run's `PENDING` representations in this space, as a fresh run-local index (after a
    crash, or when a run is resumed). A vector that cannot be decoded is an error, not skipped."""
    index = RunLocalIndex(
        representation_space_id=representation_space_id, ndim=dimension, metric=metric
    )
    rows = session.execute(
        select(Representation.id, Representation.vector).where(
            Representation.processing_run_id == processing_run_id,
            Representation.representation_space_id == representation_space_id,
            Representation.state == RepresentationState.PENDING,
        )
    )
    for representation_id, blob in rows:
        index.add(representation_id, decode_vector(blob, dimension))
    return index
