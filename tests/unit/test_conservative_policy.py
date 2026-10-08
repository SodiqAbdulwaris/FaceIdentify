"""The conservative operating-point rule of the evaluation script (owner decision 2026-10-07)."""

import argparse
from typing import Any

import numpy as np
import pytest

from evaluation.measure_operating_point import (
    bounded,
    choose_conservative,
    conservative_verdict,
    decision_policy,
    fraction,
    tail_floor,
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


def photo(person: str, *vector: float) -> Any:
    return (person, f"{person}-{vector}", np.array(vector, dtype=np.float32))


def test_the_floor_is_the_owners_figure_unless_the_selection_half_has_a_higher_tail() -> None:
    low = [photo("a", 1.0, 0.0), photo("b", 0.0, 1.0)]  # one different-person pair, cosine 0
    assert tail_floor(low, 0.326) == 0.326

    high = [photo("a", 1.0, 0.0), photo("b", 0.6, 0.8)]  # cosine 0.6
    assert tail_floor(high, 0.326) == 0.6

    assert tail_floor([], 0.326) == 0.326  # nothing to read, the owner's figure stands


def test_the_floor_reads_only_the_photographs_it_is_given() -> None:
    selection = [photo("a", 1.0, 0.0), photo("b", 0.0, 1.0)]
    final_only = [
        photo("c", 1.0, 0.0),
        photo("d", 0.99, 0.141),
    ]  # a very high different-person pair

    assert tail_floor(selection, 0.326) == tail_floor(selection[:], 0.326) == 0.326
    assert tail_floor(selection + final_only, 0.326) > 0.326  # (so it would matter if it were read)


def final_with(accepted: int, correct: int, recall: float | None) -> dict[str, Any]:
    return {"match": {"accepted": accepted, "correct": correct, "recall": recall}}


@pytest.mark.parametrize(
    ("final", "expected", "reason"),
    [
        ("nothing", "auto-accept-disabled", "no point met"),
        (final_with(40, 35, 0.6), "auto-accept-disabled", "5 false accepts"),
        (final_with(10, 10, 0.1), "auto-accept-disabled", "below the useful minimum"),
        (final_with(10, 10, 0.49), "auto-accept-disabled", "below the useful minimum"),
        (final_with(10, 10, 0.5), "provisional-conservative", "no false accept"),
        (final_with(40, 40, 0.6), "provisional-conservative", "no false accept"),
    ],
)
def test_the_final_half_decides_whether_the_point_stands(
    final: Any, expected: str, reason: str
) -> None:
    if final == "nothing":
        final = {"match": "nothing accepted automatically"}

    verdict, why = conservative_verdict(final, 0.5)

    assert verdict == expected
    assert reason in why


def test_a_disabled_policy_accepts_nothing_and_never_creates_an_identity() -> None:
    policy = decision_policy("auto-accept-disabled", {"threshold": 0.4, "margin": 0.02})

    assert policy["match_threshold"] == 2.0  # above any cosine: nothing is ever matched
    assert policy["new_identity_ceiling"] == -1.0
    assert policy["version"] == "buffalo-l-abstain-only-v1"


def test_an_enabled_policy_carries_the_measured_point() -> None:
    policy = decision_policy("provisional-conservative", {"threshold": 0.3544, "margin": 0.02})

    assert (policy["match_threshold"], policy["margin"]) == (0.3544, 0.02)
    assert policy["new_identity_ceiling"] == -1.0  # below the threshold a face abstains
    assert policy["version"] == "buffalo-l-conservative-provisional-v1"


def test_the_recall_target_is_configurable_and_never_relaxes_safety() -> None:
    final = final_with(10, 10, 0.4)

    assert conservative_verdict(final, 0.5)[0] == "auto-accept-disabled"
    assert conservative_verdict(final, 0.3)[0] == "provisional-conservative"

    # A missed target disables automatic acceptance. It never turns a false accept into a pass and
    # changes no threshold: the disabled policy is the same whatever the target was.
    unsafe = final_with(10, 9, 0.99)
    assert conservative_verdict(unsafe, 0.0)[0] == "auto-accept-disabled"
    assert decision_policy("auto-accept-disabled", None) == decision_policy(
        "auto-accept-disabled", {"threshold": 0.4, "margin": 0.02}
    )


def test_evaluation_cosines_never_leave_the_range_of_a_cosine() -> None:
    unit = np.array([0.6, 0.8], dtype=np.float32)
    nearly = np.float32(1.0000001)  # what float32 dot products of unit vectors can produce

    assert float(bounded(np.array([nearly, -nearly])[0])) == 1.0
    assert float(bounded(np.array([nearly, -nearly])[1])) == -1.0
    assert float(bounded(unit @ unit)) <= 1.0
    assert bounded(np.array([0.25, -0.5])).tolist() == [0.25, -0.5]  # inside the range: unchanged


@pytest.mark.parametrize("text", ["nan", "inf", "-inf", "-0.1", "1.01", "abc"])
def test_a_recall_target_must_be_a_finite_share(text: str) -> None:
    with pytest.raises((argparse.ArgumentTypeError, ValueError)):
        fraction(text)


def test_a_valid_recall_target_is_accepted() -> None:
    assert fraction("0.5") == 0.5
    assert fraction("0") == 0.0
    assert fraction("1") == 1.0
    assert fraction("-0.5", -1.0, 1.0) == -0.5
