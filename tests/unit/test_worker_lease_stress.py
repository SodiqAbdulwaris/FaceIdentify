"""The stress benchmark's own arithmetic (benchmarks/worker_lease_stress.py): the nearest-rank
percentile, and per-class outcomes that survive a workload error. Only the background class is
asserted: how many searches start depends on timing, how the one background job ends does not."""

import math
import random
from typing import Any

import pytest

from backend.ml.supervisor.lease import WorkerLease, cancellable
from benchmarks.worker_lease_stress import Simulated, percentile, run_once


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


class Cancelled:
    """A client whose every request is cancelled at its turn."""

    def __init__(self, lease: WorkerLease) -> None:
        self._lease = lease

    def detect(self, _pixels: Any) -> Any:
        with cancellable(lambda: True), self._lease.held():
            raise AssertionError("a cancelled request must not run")


def test_a_workload_that_completes_reports_every_background_request_as_ran() -> None:
    def client_for(lease: WorkerLease) -> Simulated:
        return Simulated(lease, 0.0, 0.0, random.Random(1))

    run = run_once(3, client_for, None, images=3, search_gap_s=0.001, seed=1)

    assert run["errors"] == []
    assert run["background"]["requests"] == 6  # a detection and a representation per image
    assert run["background"]["outcomes"] == {"RAN": 6, "FAILED": 0, "CANCELLED": 0}


def test_a_workload_error_is_reported_with_what_was_measured() -> None:
    run = run_once(3, Cancelled, None, images=3, search_gap_s=0.001, seed=1)

    assert run["errors"] == ["RequestCancelledError"]
    assert run["background"]["outcomes"] == {"RAN": 0, "FAILED": 0, "CANCELLED": 1}
