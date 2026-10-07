"""The IdentityReasoner and the assessment it reads (API and Contracts 97 and 98; ML spec 12).

Pure logic, no database: assessments are built from plain retrievals. The decisions are
conservative; the property tests state what no input may ever produce.
"""

import json
import uuid
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from backend.app.recognition.assessment import (
    ASSESSMENT_VERSION,
    INTERPRETATION,
    ObservationQuality,
    RecognitionAssessment,
    RecognitionService,
    assess,
)
from backend.app.recognition.reasoner import (
    DecisionPolicy,
    IdentityReasoner,
    Reason,
    RecognitionOutcome,
)
from backend.app.recognition.retrieval import Pool, Retrieval, RetrievedCandidate

SPACE = uuid.UUID(int=1)
POLICY = DecisionPolicy(
    version="policy-test-1",
    min_detection_score=0.5,
    match_threshold=0.6,
    margin=0.1,
    new_identity_ceiling=0.3,
)
GOOD = ObservationQuality(detection_score=0.9)


def candidate(
    n: int, similarity: float, identity: int | None = None, pool: Pool = Pool.GLOBAL
) -> RetrievedCandidate:
    return RetrievedCandidate(
        pool,
        uuid.UUID(int=100 + n),
        None if identity is None else uuid.UUID(int=identity),
        1.0 - similarity,
    )


def retrieval(
    *candidates: RetrievedCandidate, k: int = 5, dropped: int = 0, converged: bool = True
) -> Retrieval:
    ordered = sorted(candidates, key=lambda c: c.distance)
    return Retrieval(SPACE, k, tuple(ordered), dropped, converged)


def decide(*candidates: RetrievedCandidate, quality: ObservationQuality = GOOD, **kw: Any) -> Any:
    return IdentityReasoner(POLICY).decide(assess(retrieval(*candidates, **kw), quality))


# --- the assessment ----------------------------------------------------------------------------


def test_candidates_of_one_identity_are_one_group_scored_by_its_best_similarity() -> None:
    made = assess(
        retrieval(
            candidate(1, 0.9, identity=7),
            candidate(2, 0.5, identity=8),
            candidate(3, 0.8, identity=7, pool=Pool.RUN_LOCAL),
        ),
        GOOD,
    )
    first, second = made.groups
    assert first.identity_id == uuid.UUID(int=7)
    assert first.best_similarity == pytest.approx(0.9)
    assert [m.representation_id for m in first.members] == [
        uuid.UUID(int=101),
        uuid.UUID(int=103),
    ]  # nearest first
    assert [(m.pool, round(m.similarity, 6)) for m in first.members] == [
        (Pool.GLOBAL, 0.9),
        (Pool.RUN_LOCAL, 0.8),
    ]  # each member keeps its own similarity and pool
    assert second.identity_id == uuid.UUID(int=8)
    assert made.margin == pytest.approx(0.4)


def test_an_identity_with_many_representations_is_not_favoured_by_their_number() -> None:
    crowd = [candidate(n, 0.7, identity=7) for n in range(4)]
    lone = candidate(9, 0.75, identity=8)
    made = assess(retrieval(*crowd, lone), GOOD)
    assert [g.identity_id for g in made.groups] == [uuid.UUID(int=8), uuid.UUID(int=7)]


def test_a_candidate_without_an_identity_is_its_own_group_each_time() -> None:
    made = assess(retrieval(candidate(1, 0.9), candidate(2, 0.8)), GOOD)
    assert [g.identity_id for g in made.groups] == [None, None]
    assert [len(g.members) for g in made.groups] == [1, 1]


def test_groups_with_equal_similarity_are_ordered_by_their_first_representation() -> None:
    made = assess(retrieval(candidate(2, 0.7, identity=8), candidate(1, 0.7, identity=7)), GOOD)
    assert [g.members[0].representation_id for g in made.groups] == [
        uuid.UUID(int=101),
        uuid.UUID(int=102),
    ]


def test_the_assessment_records_what_was_asked_found_and_dropped() -> None:
    made = assess(retrieval(candidate(1, 0.9, identity=7), k=8, dropped=2), GOOD)
    assert (made.requested_k, made.returned, made.dropped) == (8, 1, 2)
    assert made.complete is False
    assert made.version == ASSESSMENT_VERSION
    assert made.interpretation == INTERPRETATION
    assert made.representation_space_id == SPACE
    assert made.quality == GOOD
    assert assess(retrieval(), GOOD).complete is True


def test_there_is_no_margin_with_fewer_than_two_groups() -> None:
    assert assess(retrieval(), GOOD).margin is None
    assert assess(retrieval(candidate(1, 0.9, identity=7)), GOOD).margin is None


# --- the decisions -----------------------------------------------------------------------------


def test_a_clear_match_matches_the_identity_of_the_best_group() -> None:
    decision = decide(candidate(1, 0.9, identity=7), candidate(2, 0.6, identity=8))
    assert decision.outcome is RecognitionOutcome.MATCH_EXISTING
    assert decision.reason is Reason.MATCHED
    assert decision.identity_id == uuid.UUID(int=7)


def test_a_lone_candidate_at_the_threshold_matches_it_needs_no_margin() -> None:
    decision = decide(candidate(1, 0.6, identity=7))
    assert decision.outcome is RecognitionOutcome.MATCH_EXISTING


def test_a_pending_identity_of_this_run_is_matched_like_any_identity() -> None:
    decision = decide(candidate(1, 0.9, identity=7, pool=Pool.RUN_LOCAL))
    assert decision.outcome is RecognitionOutcome.MATCH_EXISTING
    assert decision.identity_id == uuid.UUID(int=7)


def test_the_margin_is_a_least_lead_and_exactly_the_margin_is_enough() -> None:
    enough = decide(candidate(1, 0.8, identity=7), candidate(2, 0.7, identity=8))
    assert enough.outcome is RecognitionOutcome.MATCH_EXISTING
    too_close = decide(candidate(1, 0.8, identity=7), candidate(2, 0.71, identity=8))
    assert too_close.outcome is RecognitionOutcome.ABSTAIN
    assert too_close.reason is Reason.AMBIGUOUS_CANDIDATES
    assert too_close.identity_id is None


def test_a_high_top_score_with_a_small_margin_is_ambiguous_not_a_match() -> None:
    decision = decide(candidate(1, 0.95, identity=7), candidate(2, 0.94, identity=8))
    assert decision.outcome is RecognitionOutcome.ABSTAIN
    assert decision.reason is Reason.AMBIGUOUS_CANDIDATES


def test_a_neighbour_without_an_identity_is_evidence_and_never_a_match() -> None:
    decision = decide(candidate(1, 0.9), candidate(2, 0.4, identity=8))
    assert decision.outcome is RecognitionOutcome.ABSTAIN
    assert decision.reason is Reason.UNRESOLVED_NEIGHBOUR
    assert decision.identity_id is None


def test_nothing_retrieved_is_a_valid_unknown_and_creates_a_new_identity() -> None:
    decision = decide()
    assert decision.outcome is RecognitionOutcome.CREATE_NEW
    assert decision.reason is Reason.NO_CANDIDATE


def test_a_nearest_group_well_below_the_ceiling_is_clearly_not_this_face() -> None:
    decision = decide(candidate(1, 0.29, identity=7))
    assert decision.outcome is RecognitionOutcome.CREATE_NEW
    assert decision.reason is Reason.NOT_SIMILAR


def test_similar_but_not_similar_enough_abstains_it_is_never_a_low_confidence_new_identity() -> (
    None
):
    for similarity in (0.3, 0.45, 0.59):
        decision = decide(candidate(1, similarity, identity=7))
        assert decision.outcome is RecognitionOutcome.ABSTAIN
        assert decision.reason is Reason.UNCERTAIN_SIMILARITY


def test_an_unresolved_neighbour_in_the_grey_band_prevents_a_new_identity() -> None:
    decision = decide(candidate(1, 0.45), candidate(2, 0.1, identity=8))
    assert decision.outcome is RecognitionOutcome.ABSTAIN
    assert decision.reason is Reason.UNCERTAIN_SIMILARITY


def test_a_face_below_the_quality_gate_decides_nothing_whatever_the_candidates() -> None:
    poor = ObservationQuality(detection_score=0.49)
    for candidates in ((), (candidate(1, 0.99, identity=7),), (candidate(1, 0.0, identity=7),)):
        decision = decide(*candidates, quality=poor)
        assert decision.outcome is RecognitionOutcome.ABSTAIN
        assert decision.reason is Reason.LOW_QUALITY
    assert decide(quality=ObservationQuality(detection_score=0.5)).outcome is (
        RecognitionOutcome.CREATE_NEW
    )


def test_a_shortlist_that_lost_candidates_is_not_trusted_to_match_or_create() -> None:
    for candidates in ((), (candidate(1, 0.99, identity=7),), (candidate(1, 0.0, identity=7),)):
        decision = decide(*candidates, dropped=1)
        assert decision.outcome is RecognitionOutcome.ABSTAIN
        assert decision.reason is Reason.RETRIEVAL_INCOMPLETE


def test_the_quality_gate_is_decided_before_the_retrieval_check() -> None:
    decision = decide(dropped=3, quality=ObservationQuality(detection_score=0.1))
    assert decision.reason is Reason.LOW_QUALITY


# --- the policy --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "override",
    [
        {"version": ""},
        {"new_identity_ceiling": 0.7},  # above the match threshold
        {"new_identity_ceiling": -1.1},
        {"match_threshold": 2.1, "new_identity_ceiling": 0.3},
        {"margin": 0.0},  # (a match needs a lead)
        {"margin": -0.01},
        {"margin": 2.01},
        {"min_detection_score": -0.1},
        {"min_detection_score": 1.1},
        {"match_threshold": float("nan")},
    ],
)
def test_a_policy_that_is_not_coherent_is_refused(override: dict[str, Any]) -> None:
    fields: dict[str, Any] = dict(
        version="v", min_detection_score=0.5, match_threshold=0.6, margin=0.1,
        new_identity_ceiling=0.3,
    )  # fmt: skip
    with pytest.raises(ValueError):  # noqa: PT011
        DecisionPolicy(**(fields | override))


def test_a_policy_at_its_limits_is_accepted() -> None:
    DecisionPolicy("v", 0.0, 1.0, 0.001, -1.0)
    DecisionPolicy("v", 1.0, -1.0, 2.0, -1.0)
    DecisionPolicy("v", 0.5, 0.5, 0.1, 0.5)  # (no grey band: the two thresholds may meet)


# --- the evidence ------------------------------------------------------------------------------


def test_the_evidence_payload_keeps_candidates_scores_versions_and_thresholds() -> None:
    decision = decide(
        candidate(1, 0.9, identity=7), candidate(2, 0.5, identity=8, pool=Pool.RUN_LOCAL), k=8
    )
    payload = decision.evidence_payload()
    assert json.loads(json.dumps(payload)) == payload  # (plain JSON values)
    assert payload["schema_version"] == 1
    assert payload["outcome"] == "MATCH_EXISTING"
    assert payload["reason"] == "MATCHED"
    assert payload["identity_id"] == str(uuid.UUID(int=7))
    assert payload["assessment_version"] == ASSESSMENT_VERSION
    assert payload["interpretation"] == INTERPRETATION
    assert payload["representation_space_id"] == str(SPACE)
    assert payload["quality"] == {"detection_score": 0.9}
    assert payload["retrieval"] == {
        "requested_k": 8,
        "returned": 2,
        "dropped": 0,
        "converged": True,
    }
    assert payload["margin"] == pytest.approx(0.4)
    assert payload["policy"] == {
        "version": "policy-test-1",
        "min_detection_score": 0.5,
        "match_threshold": 0.6,
        "margin": 0.1,
        "new_identity_ceiling": 0.3,
    }
    first, second = payload["candidates"]
    assert first["rank"] == 1 and second["rank"] == 2  # noqa: PT018
    assert first["identity_id"] == str(uuid.UUID(int=7))
    assert first["similarity"] == pytest.approx(0.9)
    (member,) = first["members"]
    assert member["representation_id"] == str(uuid.UUID(int=101))
    assert member["pool"] == "GLOBAL"
    assert member["similarity"] == pytest.approx(0.9)
    assert second["members"][0]["pool"] == "RUN_LOCAL"


def test_the_payload_of_an_abstention_names_no_identity_and_keeps_the_unresolved_candidate() -> (
    None
):
    payload = decide(candidate(1, 0.9)).evidence_payload()
    assert payload["outcome"] == "ABSTAIN"
    assert payload["identity_id"] is None
    assert payload["candidates"][0]["identity_id"] is None
    assert payload["margin"] is None


# --- what no input may produce -----------------------------------------------------------------

similarities = st.floats(min_value=-1.0, max_value=1.0, allow_nan=False)
shortlists = st.lists(
    st.tuples(similarities, st.one_of(st.none(), st.integers(1, 4)), st.sampled_from(Pool)),
    max_size=8,
)


def build(entries: list[tuple[float, int | None, Pool]], dropped: int) -> RecognitionAssessment:
    made = [candidate(n, s, i, p) for n, (s, i, p) in enumerate(entries)]
    return assess(retrieval(*made, dropped=dropped), GOOD)


@given(shortlists, st.integers(0, 2), st.floats(0.0, 1.0), st.booleans())
def test_no_input_produces_a_match_or_a_new_identity_the_rules_forbid(
    entries: list[tuple[float, int | None, Pool]], dropped: int, score: float, converged: bool
) -> None:
    assessment = assess(
        retrieval(
            *[candidate(n, s, i, p) for n, (s, i, p) in enumerate(entries)],
            dropped=dropped,
            converged=converged,
        ),
        ObservationQuality(score),
    )
    decision = IdentityReasoner(POLICY).decide(assessment)
    top = assessment.groups[0] if assessment.groups else None
    if decision.outcome is RecognitionOutcome.MATCH_EXISTING:
        assert top is not None
        assert top.identity_id is not None
        assert decision.identity_id == top.identity_id
        assert top.best_similarity >= POLICY.match_threshold
        assert assessment.margin is None or assessment.margin >= POLICY.margin
    else:
        assert decision.identity_id is None
    if decision.outcome is not RecognitionOutcome.ABSTAIN:
        assert assessment.complete
        assert score >= POLICY.min_detection_score
    if decision.outcome is RecognitionOutcome.CREATE_NEW:
        assert top is None or top.best_similarity < POLICY.new_identity_ceiling
    if decision.reason is Reason.MATCHED:
        assert decision.outcome is RecognitionOutcome.MATCH_EXISTING


@given(shortlists)
def test_assessing_is_deterministic_and_ranks_groups_best_first(
    entries: list[tuple[float, int | None, Pool]],
) -> None:
    first, second = build(entries, 0), build(entries, 0)
    assert first == second
    scores = [g.best_similarity for g in first.groups]
    assert scores == sorted(scores, reverse=True)
    members = [m.representation_id for g in first.groups for m in g.members]
    assert len(members) == len(set(members)) == len(entries)


# --- the boundaries, with similarities that are exact in binary ---------------------------------

EXACT = DecisionPolicy("exact", 0.5, 0.5, 0.125, 0.25)


def decide_exact(*candidates: RetrievedCandidate) -> Any:
    return IdentityReasoner(EXACT).decide(assess(retrieval(*candidates), GOOD))


def test_a_similarity_exactly_at_the_match_threshold_is_considered_for_a_match() -> None:
    assert decide_exact(candidate(1, 0.5, identity=7)).outcome is RecognitionOutcome.MATCH_EXISTING


def test_a_lead_exactly_the_margin_is_enough_and_a_hair_less_is_not() -> None:
    enough = decide_exact(candidate(1, 0.875, identity=7), candidate(2, 0.75, identity=8))
    assert enough.outcome is RecognitionOutcome.MATCH_EXISTING
    short = decide_exact(candidate(1, 0.875, identity=7), candidate(2, 0.76, identity=8))
    assert short.reason is Reason.AMBIGUOUS_CANDIDATES


OFF = DecisionPolicy(
    version="off",
    min_detection_score=0.5,
    match_threshold=2.0,
    margin=2.0,
    new_identity_ceiling=-1.0,
)


@pytest.mark.parametrize(
    "candidates",
    [
        (candidate(1, 1.0, identity=7),),  # an exact copy, nothing to compare it with
        (candidate(1, 1.0, identity=7), candidate(2, -1.0, identity=8)),  # the widest possible lead
    ],
)
def test_a_policy_with_matching_off_never_matches_and_never_creates_from_a_weak_score(
    candidates: Any,
) -> None:
    decision = IdentityReasoner(OFF).decide(assess(retrieval(*candidates), GOOD))

    assert decision.outcome is RecognitionOutcome.ABSTAIN
    assert decision.reason is Reason.UNCERTAIN_SIMILARITY


def test_a_policy_with_matching_off_still_starts_an_identity_when_there_is_nobody_to_compare() -> (
    None
):
    decision = IdentityReasoner(OFF).decide(assess(retrieval(), GOOD))

    assert decision.outcome is RecognitionOutcome.CREATE_NEW
    assert decision.reason is Reason.NO_CANDIDATE


def test_a_similarity_exactly_at_the_ceiling_is_not_clearly_new() -> None:
    at = decide_exact(candidate(1, 0.25, identity=7))
    assert at.outcome is RecognitionOutcome.ABSTAIN
    assert at.reason is Reason.UNCERTAIN_SIMILARITY
    below = decide_exact(candidate(1, 0.24, identity=7))
    assert below.outcome is RecognitionOutcome.CREATE_NEW


def test_the_evidence_keeps_how_many_candidates_were_dropped() -> None:
    payload = decide(candidate(1, 0.9, identity=7), dropped=2).evidence_payload()
    assert payload["retrieval"]["dropped"] == 2
    assert payload["reason"] == "RETRIEVAL_INCOMPLETE"


def test_an_index_that_had_not_caught_up_is_not_trusted_to_create_or_match() -> None:
    for candidates in ((), (candidate(1, 0.99, identity=7),), (candidate(1, 0.0, identity=7),)):
        decision = decide(*candidates, converged=False)
        assert decision.outcome is RecognitionOutcome.ABSTAIN
        assert decision.reason is Reason.RETRIEVAL_INCOMPLETE
        assert decision.assessment.converged is False
        assert decision.evidence_payload()["retrieval"]["converged"] is False


def test_the_shortlist_must_be_able_to_show_a_margin() -> None:
    for k in (-1, 0, 1):
        with pytest.raises(ValueError, match="two candidates"):
            RecognitionService(k=k)
    assert RecognitionService(k=2).k == 2


def test_a_candidate_distance_that_is_not_a_number_is_refused() -> None:
    for distance in (float("nan"), float("inf")):
        with pytest.raises(ValueError, match="finite"):
            RetrievedCandidate(Pool.GLOBAL, uuid.UUID(int=1), None, distance)
