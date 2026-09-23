"""Deterministic clocks, identifiers and randomness for tests.

Production code should accept these as injected callables (`clock: Callable[[], datetime]`,
`new_id: Callable[[], UUID]`) rather than calling `datetime.now()` / `uuid.uuid4()` directly.
"""

import random
import uuid
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

DEFAULT_SEED = 20260923
EPOCH = datetime(2026, 1, 1, tzinfo=UTC)


class FrozenClock:
    """UTC clock that only moves when told to. Call it like `datetime.now`."""

    def __init__(self, start: datetime = EPOCH) -> None:
        if start.tzinfo is None:
            raise ValueError("FrozenClock requires a timezone-aware start (all timestamps are UTC)")
        self._now = start

    def __call__(self) -> datetime:
        return self._now

    def advance(self, **delta: float) -> datetime:
        step = timedelta(**delta)
        if step < timedelta(0):
            raise ValueError("clock cannot move backwards")
        self._now += step
        return self._now


class SeededUUIDs:
    """Reproducible version-4 UUIDs, matching the uuid4() identifiers used in production."""

    def __init__(self, seed: int = DEFAULT_SEED) -> None:
        self._rng = random.Random(seed)

    def __call__(self) -> uuid.UUID:
        return uuid.UUID(int=self._rng.getrandbits(128), version=4)


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock()


@pytest.fixture
def new_id() -> SeededUUIDs:
    return SeededUUIDs()


@pytest.fixture
def rng() -> random.Random:
    return random.Random(DEFAULT_SEED)


@pytest.fixture
def np_rng() -> np.random.Generator:
    return np.random.default_rng(DEFAULT_SEED)
