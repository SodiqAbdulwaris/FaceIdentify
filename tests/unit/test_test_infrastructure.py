"""M0 smoke tests: deterministic utilities, async execution and per-test isolation."""

import asyncio
import os
import random
from datetime import UTC, datetime, timedelta

import httpx
import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from tests.fixtures.deterministic import DEFAULT_SEED, FrozenClock, SeededUUIDs


def test_frozen_clock_only_moves_when_advanced(clock: FrozenClock) -> None:
    start = clock()
    assert clock() == start
    assert start.tzinfo is UTC
    assert clock.advance(minutes=5) - start == timedelta(minutes=5)


def test_frozen_clock_rejects_naive_start_and_backwards_moves() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        FrozenClock(datetime(2026, 1, 1))
    with pytest.raises(ValueError, match="backwards"):
        FrozenClock().advance(seconds=-1)


def test_seeded_uuids_are_reproducible_unique_and_version_4() -> None:
    assert SeededUUIDs(7)() == SeededUUIDs(7)()

    generator = SeededUUIDs(7)
    ids = [generator() for _ in range(1000)]
    assert len(set(ids)) == len(ids)
    assert {i.version for i in ids} == {4}
    assert ids[0] != SeededUUIDs(8)()


def test_seeded_random_sources_reproduce(rng: random.Random, np_rng: np.random.Generator) -> None:
    assert rng.random() == random.Random(DEFAULT_SEED).random()
    np.testing.assert_array_equal(np_rng.random(4), np.random.default_rng(DEFAULT_SEED).random(4))


@given(st.lists(st.integers(min_value=0, max_value=10_000), max_size=20))
def test_hypothesis_runs_and_clock_is_monotonic(steps: list[int]) -> None:
    clock = FrozenClock()
    previous = clock()
    for seconds in steps:
        current = clock.advance(seconds=seconds)
        assert current >= previous
        previous = current


async def test_async_tests_run_on_an_event_loop() -> None:
    order: list[str] = []

    async def worker(name: str, delay: float) -> None:
        await asyncio.sleep(delay)
        order.append(name)

    await asyncio.gather(worker("slow", 0.02), worker("fast", 0.0))
    assert order == ["fast", "slow"]


async def test_httpx_async_client_works_in_test_loop() -> None:
    # Future FastAPI contract tests will use httpx.ASGITransport(app=...) in the same way.
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"path": request.url.path})
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/health")
    assert response.json() == {"path": "/api/v1/health"}


@pytest.mark.parametrize("run", ["first", "second"])
def test_temporary_configuration_does_not_leak(run: str, monkeypatch: pytest.MonkeyPatch) -> None:
    # Both cases assert a clean start, so whichever runs second catches a leak from the other.
    assert "FACEIDENTIFY_TEST_LEAK_PROBE" not in os.environ
    monkeypatch.setenv("FACEIDENTIFY_TEST_LEAK_PROBE", run)
    assert os.environ["FACEIDENTIFY_TEST_LEAK_PROBE"] == run
