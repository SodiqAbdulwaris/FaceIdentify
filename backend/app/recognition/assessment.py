"""RecognitionService: a retrieval turned into a `RecognitionAssessment` (API and Contracts 97).

The service owns retrieval, authoritative revalidation (both in `retrieval.retrieve`), candidate
grouping and the interpretation of similarity. It creates no Identity, no Evidence and no
association: it only describes, for one observation's vector, what the memory looks like around it.
What to do about it is the `IdentityReasoner`'s proposal (`reasoner.py`), and what is committed is
the Identity Manager's.

Grouping: candidates of one identity are one group, scored by its **best** (highest) similarity, so
an identity with many representations is not favoured by their number (no history-count feature
before representation-count bias is measured, ML spec 12.2). A candidate with no identity (an
accepted `ABSTAIN` representation, or a pending one the run left unresolved) is its own group: it
is evidence that something looks like this face, never a target to match (Persistence 6.2).

Interpretation: the similarity is the cosine similarity, used as it is. No calibration profile
exists for the reference models (M3 does not benchmark them), so nothing here claims a calibrated
probability; `interpretation` says so, and a later calibration is a new interpretation value.
"""

import uuid
from dataclasses import dataclass
from typing import Final

from sqlalchemy.orm import Session

from backend.app.recognition.retrieval import Pool, Retrieval, retrieve
from backend.infrastructure.indexing.representation_index import RepresentationIndex, Vector
from backend.infrastructure.indexing.run_local_index import RunLocalIndex

ASSESSMENT_VERSION: Final = "recognition-assessment-v1"
INTERPRETATION: Final = "COSINE_UNCALIBRATED"


@dataclass(frozen=True, slots=True)
class ObservationQuality:
    """What is measured about the observation itself (the detector's score for now)."""

    detection_score: float


@dataclass(frozen=True, slots=True)
class CandidateGroup:
    identity_id: uuid.UUID | None  # None: unresolved evidence, never a match target
    representation_ids: tuple[uuid.UUID, ...]  # nearest first
    pools: tuple[Pool, ...]  # the pools its representations came from
    best_similarity: float


@dataclass(frozen=True, slots=True)
class RecognitionAssessment:
    version: str
    interpretation: str
    representation_space_id: uuid.UUID
    quality: ObservationQuality
    requested_k: int
    returned: int  # revalidated candidates in the shortlist
    dropped: int  # candidates an index returned that SQLite refused
    groups: tuple[CandidateGroup, ...]  # best first

    @property
    def complete(self) -> bool:
        """Whether the shortlist can be trusted to hold the nearest candidates: nothing stale was
        dropped (a dropped candidate may have hidden one beyond the cut)."""
        return self.dropped == 0

    @property
    def margin(self) -> float | None:
        """The best group's similarity minus the next group's; None with fewer than two groups."""
        if len(self.groups) < 2:
            return None
        return self.groups[0].best_similarity - self.groups[1].best_similarity


def assess(retrieval: Retrieval, quality: ObservationQuality) -> RecognitionAssessment:
    """Group a retrieval's candidates and rank the groups."""
    groups: dict[uuid.UUID | tuple[uuid.UUID], list[tuple[float, Pool, uuid.UUID]]] = {}
    for candidate in retrieval.candidates:  # (nearest first)
        key = candidate.identity_id or (candidate.representation_id,)
        groups.setdefault(key, []).append(
            (candidate.similarity, candidate.pool, candidate.representation_id)
        )
    ranked = sorted(
        (
            CandidateGroup(
                identity_id=key if isinstance(key, uuid.UUID) else None,
                representation_ids=tuple(item[2] for item in members),
                pools=tuple(sorted({item[1] for item in members})),
                best_similarity=members[0][0],
            )
            for key, members in groups.items()
        ),
        key=lambda g: (-g.best_similarity, str(g.representation_ids[0])),
    )
    return RecognitionAssessment(
        version=ASSESSMENT_VERSION,
        interpretation=INTERPRETATION,
        representation_space_id=retrieval.representation_space_id,
        quality=quality,
        requested_k=retrieval.requested_k,
        returned=len(retrieval.candidates),
        dropped=retrieval.dropped,
        groups=tuple(ranked),
    )


@dataclass(frozen=True, slots=True)
class RecognitionService:
    k: int  # the shortlist size: the caller's measured choice, no default

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
            ),
            quality,
        )
