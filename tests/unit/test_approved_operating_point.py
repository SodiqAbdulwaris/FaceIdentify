"""The approved automatic-matching operating point, decided by the real reasoner (owner decision
2026-10-15; evidence in docs/implementations/2026-10-15-enable-automatic-acceptance.md).

The policy is built from `APPROVED_MATCHING` itself, so a change to the approved numbers is tested
here, not a copy of them.
"""

import pytest

from backend.api.real import APPROVED_MATCHING
from backend.app.recognition.assessment import assess
from backend.app.recognition.reasoner import (
    DecisionPolicy,
    IdentityReasoner,
    Reason,
    RecognitionDecision,
    RecognitionOutcome,
)
from backend.app.recognition.retrieval import RetrievedCandidate
from tests.unit.test_recognition_reasoner import GOOD, candidate, retrieval

VERSION, NUMBERS = next(iter(APPROVED_MATCHING.items()))
POLICY = DecisionPolicy(version=VERSION, **NUMBERS)
THRESHOLD, MARGIN = POLICY.match_threshold, POLICY.margin
BEST_STRANGER_RECORDED = 0.402  # the highest stranger top-1 in any recorded gate run (LFW)


def decide(*candidates: RetrievedCandidate) -> RecognitionDecision:
    return IdentityReasoner(POLICY).decide(assess(retrieval(*candidates), GOOD))


def test_the_approved_point_matches_and_never_creates_an_identity_from_a_score() -> None:
    assert POLICY.automatic_matching
    assert POLICY.new_identity_ceiling == -1.0  # an automatic new identity is not approved
    assert THRESHOLD > BEST_STRANGER_RECORDED  # above every stranger recorded so far


def test_a_face_above_the_threshold_with_the_margin_is_matched() -> None:
    decision = decide(
        candidate(1, THRESHOLD + 0.01, identity=7),
        candidate(2, THRESHOLD + 0.01 - MARGIN - 0.01, identity=8),
    )
    assert decision.outcome is RecognitionOutcome.MATCH_EXISTING
    assert decision.reason is Reason.MATCHED
    assert decision.evidence_payload()["policy"]["version"] == VERSION  # the point is on record


def test_a_face_below_the_threshold_abstains() -> None:
    decision = decide(candidate(1, THRESHOLD - 0.01, identity=7), candidate(2, 0.1, identity=8))
    assert decision.outcome is RecognitionOutcome.ABSTAIN
    assert decision.reason is Reason.UNCERTAIN_SIMILARITY


def test_a_face_above_the_threshold_but_within_the_margin_abstains() -> None:
    decision = decide(
        candidate(1, 0.7, identity=7),
        candidate(2, 0.7 - MARGIN + 0.01, identity=8),  # a sibling, say, nearly as close
    )
    assert decision.outcome is RecognitionOutcome.ABSTAIN
    assert decision.reason is Reason.AMBIGUOUS_CANDIDATES


@pytest.mark.parametrize("similarity", [BEST_STRANGER_RECORDED, 0.309, 0.0, -0.2])
def test_a_stranger_is_neither_matched_nor_made_a_new_identity(similarity: float) -> None:
    decision = decide(candidate(1, similarity, identity=7), candidate(2, similarity - 0.2, 8))
    assert decision.outcome is RecognitionOutcome.ABSTAIN  # waits for the owner
