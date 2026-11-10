"""The stress benchmark's percentile is the nearest-rank one (benchmarks/worker_lease_stress.py)."""

import math

import pytest

from benchmarks.worker_lease_stress import percentile


@pytest.mark.parametrize(
    ("values", "p", "expected"),
    [
        ([1.0, 2.0, 3.0, 4.0], 50, 2.0),  # at least half the values at or below it
        ([4.0, 1.0, 3.0, 2.0], 50, 2.0),  # (order does not matter)
        ([float(n) for n in range(1, 21)], 95, 19.0),  # the 19th of 20
        ([float(n) for n in range(1, 21)], 100, 20.0),
        ([7.0], 50, 7.0),
        ([1.0, 2.0, 3.0], 0, 1.0),  # never below the first rank
    ],
)
def test_the_percentile_is_the_nearest_rank(values: list[float], p: float, expected: float) -> None:
    assert percentile(values, p) == expected


def test_no_values_have_no_percentile() -> None:
    assert math.isnan(percentile([], 95))
