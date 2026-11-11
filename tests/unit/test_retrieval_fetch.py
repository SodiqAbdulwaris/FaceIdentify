"""How far a pool is asked when candidates are excluded (D8, 2026-11-11: a video's thousands of
faces are excluded from each other's candidates; asking every pool for `k + len(exclude)` made
recognising them quadratic)."""

from collections.abc import Callable

from backend.app.recognition.retrieval import _enough


def pool(
    size: int, excluded: set[int], asked: list[int]
) -> Callable[[int], tuple[int, int, list[int]]]:
    """A pool of candidates 0..size-1 by distance; `excluded` are left out of what it gives."""

    def ask(fetch: int) -> tuple[int, int, list[int]]:
        asked.append(fetch)
        returned = list(range(min(fetch, size)))
        return len(returned), 0, [c for c in returned if c not in excluded]

    return ask


def test_k_is_enough_when_the_excluded_are_not_among_the_nearest() -> None:
    asked: list[int] = []
    _dropped, found = _enough(pool(10_000, set(range(5000, 10_000)), asked), 8, 8 + 5000)

    assert asked == [8]  # not 5,008: the excluded are far away
    assert found == list(range(8))


def test_the_ask_grows_until_k_usable_are_found_and_matches_one_full_ask() -> None:
    asked: list[int] = []
    excluded = set(range(0, 20))  # the nearest twenty are excluded

    _dropped, found = _enough(pool(100, excluded, asked), 5, 5 + len(excluded))

    assert asked == [5, 10, 20, 25]  # doubling, capped at k + every excluded one
    assert found == list(range(20, 25))  # the same five as one ask for 25 would give


def test_a_pool_with_too_few_stops_asking() -> None:
    asked: list[int] = []

    _dropped, found = _enough(pool(3, {0}, asked), 5, 6)

    assert asked == [5]  # the pool had fewer than asked: asking again would give nothing new
    assert found == [1, 2]
