"""The conservative operating-point rule of the evaluation script (owner decision 2026-10-07)."""

from typing import Any

import pytest

from evaluation.measure_operating_point import (
    choose_conservative,
    conservative_verdict,
    decision_policy,
)


def query(score: float, runner_up: float, *, right: bool = True, known: bool = True) -> Any:
    # (person, best person, best score, runner-up, known)
    return ("a", "a" if right else "b", score, runner_up, known)


def test_only_scores_above_the_floor_can_be_the_threshold() -> None:
    queries = [query(0.30, 0.0), query(0.40, 0.0), query(0.50, 0.0)]

    point = choose_conservative(queries, floor=0.35, minimum_accepted=1)

    assert point is not None
    assert point["threshold"] == 0.40  # 0.30 is below the floor: never chosen, however clean


def test_a_false_accept_on_the_selection_half_rules_a_threshold_out() -> None:
    queries = [query(0.60, 0.0), query(0.50, 0.0, right=False), query(0.40, 0.0)]

    point = choose_conservative(queries, floor=0.35, minimum_accepted=1)

    assert point is not None
    assert point["threshold"] == 0.60  # 0.50 and 0.40 would also accept the wrong face


def test_a_margin_is_always_required() -> None:
    point = choose_conservative([query(0.60, 0.59), query(0.70, 0.0)], 0.35, 1)

    assert point is not None
    assert point["margin"] > 0
    assert point["accepted"] == 1  # the near-tie is not accepted


def test_nothing_is_chosen_without_enough_accepted_queries() -> None:
    assert choose_conservative([query(0.60, 0.0)], floor=0.35, minimum_accepted=2) is None


def final_with(accepted: int, correct: int, recall: float | None) -> dict[str, Any]:
    return {"match": {"accepted": accepted, "correct": correct, "recall": recall}}


@pytest.mark.parametrize(
    ("final", "expected", "reason"),
    [
        ("nothing", "auto-accept-disabled", "no point met"),
        (final_with(40, 35, 0.6), "auto-accept-disabled", "5 false accepts"),
        (final_with(10, 10, 0.1), "auto-accept-disabled", "below the useful minimum"),
        (final_with(40, 40, 0.6), "provisional-conservative", "no false accept"),
    ],
)
def test_the_final_half_decides_whether_the_point_stands(
    final: Any, expected: str, reason: str
) -> None:
    if final == "nothing":
        final = {"match": "nothing accepted automatically"}

    verdict, why = conservative_verdict(final)

    assert verdict == expected
    assert reason in why


def test_a_disabled_policy_accepts_nothing_and_never_creates_an_identity() -> None:
    policy = decision_policy("auto-accept-disabled", {"threshold": 0.4, "margin": 0.02})

    assert policy["match_threshold"] == 1.0
    assert policy["margin"] == 2.0  # no pair of scores is two apart from the runner-up and above 1
    assert policy["new_identity_ceiling"] == -1.0
    assert policy["version"] == "buffalo-l-abstain-only-v1"


def test_an_enabled_policy_carries_the_measured_point() -> None:
    policy = decision_policy("provisional-conservative", {"threshold": 0.3544, "margin": 0.02})

    assert (policy["match_threshold"], policy["margin"]) == (0.3544, 0.02)
    assert policy["new_identity_ceiling"] == -1.0  # below the threshold a face abstains
    assert policy["version"] == "buffalo-l-conservative-provisional-v1"
