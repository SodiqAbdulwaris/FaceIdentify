"""RecognitionService: a retrieval turned into a `RecognitionAssessment` (API and Contracts 97).

The service owns retrieval, authoritative revalidation (both in `retrieval.retrieve`), candidate
grouping and the interpretation of similarity. It creates no Identity, no Evidence and no
association: it only describes, for one observation's vector, what the memory looks like around it.
What to do about it is the `IdentityReasoner`'s proposal (`reasoner.py`), and what is committed is
the Identity Manager's.

Preconditions the caller owns, because this module cannot know them:

* **The query's own representation, and the other faces of its image, must be excluded**
  (`exclude`). The representation being recognised exists, `PENDING`, before it is recognised, and
  an identity-less pending neighbour at similarity 1.0 would make every face abstain.
* **The index must have caught up.** `Retrieval.converged` says whether an `ADD` or `REMOVE` is
  still waiting or failed; an index that is behind returns fewer candidates and drops none, which
  looks exactly like a person never seen, so an assessment of an unconverged index is not complete.

Grouping: candidates of one identity are one group, scored by its **best** (highest) similarity, so
an identity with many representations is not favoured by their number (no history-count feature
before representation-count bias is measured, ML spec 12.2); every member keeps its own similarity
and pool, so the evidence says which representation was how near. A candidate with no identity (an
accepted `ABSTAIN` representation, or a pending one that has no identity yet) is its own group: it
is evidence that something looks like this face, never a target to match (Persistence 6.2).

Not modelled yet: *correction constraints* (a prior rejection or manual override that similarity
alone must not overwhelm, ML spec 12.2). No correction history exists in M3's first slice, so the
assessment has no field for it and a previously rejected identity is matchable on similarity alone;
a later assessment version adds it.

Interpretation: the similarity is the cosine similarity, used as it is. No calibration profile
exists for the reference models (M3 does not benchmark them), so nothing here claims a calibrated
probability; `interpretation` says so, and a later calibration is a new interpretation value.
"""

import uuid
from collections.abc import Collection
from dataclasses import dataclass
from typing import Final

from sqlalchemy.orm import Session

from backend.app.recognition.retrieval import Pool, Retrieval, retrieve
from backend.infrastructure.indexing.representation_index import RepresentationIndex, Vector
from backend.infrastructure.indexing.run_local_index import RunLocalIndex

ASSESSMENT_VERSION: Final = "recognition-assessment-v2"
INTERPRETATION: Final = "COSINE_UNCALIBRATED"


@dataclass(frozen=True, slots=True)
class ObservationQuality:
    """What is measured about the observation itself (the detector's score for now)."""

    detection_score: float


@dataclass(frozen=True, slots=True)
class GroupMember:
    representation_id: uuid.UUID
    pool: Pool
    similarity: float


@dataclass(frozen=True, slots=True)
class CandidateGroup:
    identity_id: uuid.UUID | None  # None: unresolved evidence, never a match target
    members: tuple[GroupMember, ...]  # nearest first

    @property
    def best_similarity(self) -> float:
        return max(member.similarity for member in self.members)


@dataclass(frozen=True, slots=True)
class RecognitionAssessment:
    version: str
    interpretation: str
    representation_space_id: uuid.UUID
    quality: ObservationQuality
    requested_k: int
    returned: int  # revalidated candidates in the shortlist
    dropped: int  # candidates an index returned that SQLite refused
    converged: bool  # the index had caught up with SQLite
    groups: tuple[CandidateGroup, ...]  # best first

    @property
    def complete(self) -> bool:
        """Whether the shortlist can be trusted to hold the nearest candidates: nothing stale was
        dropped (a dropped candidate may have hidden one beyond the cut) and the index had caught
        up (one that is behind returns fewer candidates and drops none)."""
        return self.dropped == 0 and self.converged

    @property
    def margin(self) -> float | None:
        """The best group's similarity minus the next group's; None with fewer than two groups."""
        if len(self.groups) < 2:
            return None
        return self.groups[0].best_similarity - self.groups[1].best_similarity


def assess(retrieval: Retrieval, quality: ObservationQuality) -> RecognitionAssessment:
    """Group a retrieval's candidates and rank the groups."""
    members: dict[uuid.UUID | tuple[uuid.UUID], list[GroupMember]] = {}
    for candidate in retrieval.candidates:
        key = candidate.identity_id or (candidate.representation_id,)
        members.setdefault(key, []).append(
            GroupMember(candidate.representation_id, candidate.pool, candidate.similarity)
        )
    ranked = sorted(
        (
            CandidateGroup(
                identity_id=key if isinstance(key, uuid.UUID) else None,
                members=tuple(
                    sorted(group, key=lambda m: (-m.similarity, m.pool, str(m.representation_id)))
                ),
            )
            for key, group in members.items()
        ),
        key=lambda g: (-g.best_similarity, str(g.members[0].representation_id)),
    )
    return RecognitionAssessment(
        version=ASSESSMENT_VERSION,
        interpretation=INTERPRETATION,
        representation_space_id=retrieval.representation_space_id,
        quality=quality,
        requested_k=retrieval.requested_k,
        returned=len(retrieval.candidates),
        dropped=retrieval.dropped,
        converged=retrieval.converged,
        groups=tuple(ranked),
    )


@dataclass(frozen=True, slots=True)
class RecognitionService:
    # The shortlist size: the caller's measured choice, no default. At least 2: with one candidate
    # there is never a second group, so the separation a match needs could never be measured.
    k: int

    def __post_init__(self) -> None:
        if self.k < 2:
            raise ValueError("the shortlist needs at least two candidates to measure a margin")

    def assess(
        self,
        session: Session,
        *,
        representation_space_id: uuid.UUID,
        dimension: int,
        vector: Vector,
        quality: ObservationQuality,
        global_index: RepresentationIndex,
        processing_run_id: uuid.UUID,
        run_local: RunLocalIndex | None = None,
        exclude: Collection[uuid.UUID] = (),
    ) -> RecognitionAssessment:
        return assess(
            retrieve(
                session,
                representation_space_id=representation_space_id,
                dimension=dimension,
                vector=vector,
                k=self.k,
                global_index=global_index,
                processing_run_id=processing_run_id,
                run_local=run_local,
                exclude=exclude,
            ),
            quality,
        )
