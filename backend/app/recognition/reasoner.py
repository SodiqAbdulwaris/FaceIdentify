"""IdentityReasoner: an assessment and a policy become a proposal (API and Contracts 98).

Three outcomes (Roadmap phase 6, decision 2026-10-02): `MATCH_EXISTING`, `CREATE_NEW` and
`ABSTAIN`. An abstention is a deliberate "no identity decided", with a reason; it is never a
`CREATE_NEW` with low confidence, and an ambiguous shortlist is an abstention *reason*, not an
outcome. The proposal commits nothing: the Identity Manager revalidates it before any write.

The rules are transparent and conservative (ML spec 12.2, Identity Decision Engine Plan 6):

1. A face below the quality gate decides nothing (`LOW_QUALITY`): it must neither match nor create.
2. A shortlist that lost candidates to revalidation is not trusted to hold the nearest ones
   (`RETRIEVAL_INCOMPLETE`): no automatic match or new identity on a possibly missing neighbour.
3. Nothing retrieved is a valid unknown: `CREATE_NEW` (`NO_CANDIDATE`).
4. The best group at or above `match_threshold` needs the margin to the next group, or the
   shortlist is `AMBIGUOUS_CANDIDATES`; a group without an identity can never be matched
   (`UNRESOLVED_NEIGHBOUR`); otherwise `MATCH_EXISTING` that group's identity.
5. Below `new_identity_ceiling` the nearest group is clearly not this face: `CREATE_NEW`.
6. Between the two (similar, not similar enough) is `UNCERTAIN_SIMILARITY`: an abstention.

The thresholds are configuration, not constants: policy thresholds "must be supported by recorded
evaluation evidence" (Identity Decision Engine Plan 3), and the reference models are not
benchmarked in M3 (TST-044 is after it). So `DecisionPolicy` has no defaults and ships none: a run
supplies the values it was configured with (the processing snapshot), and the decision records them.
"""

import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from backend.app.recognition.assessment import RecognitionAssessment

EVIDENCE_SCHEMA_VERSION = 1


class RecognitionOutcome(StrEnum):
    MATCH_EXISTING = "MATCH_EXISTING"
    CREATE_NEW = "CREATE_NEW"
    ABSTAIN = "ABSTAIN"


class Reason(StrEnum):
    MATCHED = "MATCHED"
    NO_CANDIDATE = "NO_CANDIDATE"
    NOT_SIMILAR = "NOT_SIMILAR"
    LOW_QUALITY = "LOW_QUALITY"
    RETRIEVAL_INCOMPLETE = "RETRIEVAL_INCOMPLETE"
    AMBIGUOUS_CANDIDATES = "AMBIGUOUS_CANDIDATES"
    UNRESOLVED_NEIGHBOUR = "UNRESOLVED_NEIGHBOUR"
    UNCERTAIN_SIMILARITY = "UNCERTAIN_SIMILARITY"


@dataclass(frozen=True, slots=True)
class DecisionPolicy:
    version: str
    min_detection_score: float  # the quality gate
    match_threshold: float  # the best group's similarity at or above which a match is considered
    margin: float  # the least lead over the next group a match needs
    new_identity_ceiling: float  # below this similarity the nearest group is clearly not this face

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("a policy has a version")
        if not -1.0 <= self.new_identity_ceiling <= self.match_threshold <= 1.0:
            raise ValueError(
                "the thresholds must satisfy -1 <= new_identity_ceiling <= match_threshold <= 1"
            )
        if not 0.0 <= self.margin <= 2.0:
            raise ValueError("the margin is a difference of cosine similarities, 0 to 2")
        if not 0.0 <= self.min_detection_score <= 1.0:
            raise ValueError("the quality gate is a detection score, 0 to 1")


@dataclass(frozen=True, slots=True)
class RecognitionDecision:
    outcome: RecognitionOutcome
    reason: Reason
    identity_id: uuid.UUID | None  # only for MATCH_EXISTING
    assessment: RecognitionAssessment
    policy: DecisionPolicy

    def evidence_payload(self) -> dict[str, Any]:
        """The candidate evidence the decision is kept with (top candidates, scores, the engine's
        version, the thresholds), as the JSON payload of an Evidence row."""
        assessment, policy = self.assessment, self.policy
        return {
            "schema_version": EVIDENCE_SCHEMA_VERSION,
            "outcome": self.outcome.value,
            "reason": self.reason.value,
            "identity_id": None if self.identity_id is None else str(self.identity_id),
            "assessment_version": assessment.version,
            "interpretation": assessment.interpretation,
            "representation_space_id": str(assessment.representation_space_id),
            "quality": {"detection_score": assessment.quality.detection_score},
            "retrieval": {
                "requested_k": assessment.requested_k,
                "returned": assessment.returned,
                "dropped": assessment.dropped,
            },
            "candidates": [
                {
                    "rank": rank,
                    "identity_id": None if group.identity_id is None else str(group.identity_id),
                    "representation_ids": [str(r) for r in group.representation_ids],
                    "pools": [pool.value for pool in group.pools],
                    "similarity": group.best_similarity,
                }
                for rank, group in enumerate(assessment.groups, start=1)
            ],
            "margin": assessment.margin,
            "policy": {
                "version": policy.version,
                "min_detection_score": policy.min_detection_score,
                "match_threshold": policy.match_threshold,
                "margin": policy.margin,
                "new_identity_ceiling": policy.new_identity_ceiling,
            },
        }


@dataclass(frozen=True, slots=True)
class IdentityReasoner:
    policy: DecisionPolicy

    def decide(self, assessment: RecognitionAssessment) -> RecognitionDecision:
        policy = self.policy

        def abstain(reason: Reason) -> RecognitionDecision:
            return RecognitionDecision(RecognitionOutcome.ABSTAIN, reason, None, assessment, policy)

        def create(reason: Reason) -> RecognitionDecision:
            return RecognitionDecision(
                RecognitionOutcome.CREATE_NEW, reason, None, assessment, policy
            )

        if assessment.quality.detection_score < policy.min_detection_score:
            return abstain(Reason.LOW_QUALITY)
        if not assessment.complete:
            return abstain(Reason.RETRIEVAL_INCOMPLETE)
        if not assessment.groups:
            return create(Reason.NO_CANDIDATE)
        top = assessment.groups[0]
        if top.best_similarity >= policy.match_threshold:
            margin = assessment.margin
            if margin is not None and margin < policy.margin:
                return abstain(Reason.AMBIGUOUS_CANDIDATES)
            if top.identity_id is None:
                return abstain(Reason.UNRESOLVED_NEIGHBOUR)
            return RecognitionDecision(
                RecognitionOutcome.MATCH_EXISTING,
                Reason.MATCHED,
                top.identity_id,
                assessment,
                policy,
            )
        if top.best_similarity < policy.new_identity_ceiling:
            return create(Reason.NOT_SIMILAR)
        return abstain(Reason.UNCERTAIN_SIMILARITY)
