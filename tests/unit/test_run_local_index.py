"""The run-local index (Persistence 23, CONTEXT open question 21): in memory, ephemeral labels."""

import uuid
from typing import Any

import numpy as np
import pytest

from backend.infrastructure.indexing.run_local_index import RunLocalIndex

NDIM = 4
SPACE = uuid.UUID(int=1)


def unit(*values: float) -> np.ndarray[Any, Any]:
    array = np.array(values, dtype=np.float32)
    return np.asarray(array / np.linalg.norm(array), dtype=np.float32)


def make() -> RunLocalIndex:
    return RunLocalIndex(representation_space_id=SPACE, ndim=NDIM, metric="cos")


def test_an_empty_index_has_no_candidates() -> None:
    index = make()
    assert len(index) == 0
    assert index.search(unit(1, 0, 0, 0), 3) == []


def test_the_nearest_representation_comes_first_with_its_representation_id() -> None:
    index = make()
    near, middle, far = uuid.UUID(int=10), uuid.UUID(int=11), uuid.UUID(int=12)
    index.add(far, unit(0, 0, 1, 0))
    index.add(near, unit(1, 0.01, 0, 0))
    index.add(middle, unit(1, 1, 0, 0))
    found = index.search(unit(1, 0, 0, 0), 3)
    assert [c.representation_id for c in found] == [near, middle, far]
    assert found[0].distance == pytest.approx(0.0, abs=1e-3)
    assert found[2].distance == pytest.approx(1.0, abs=1e-3)  # (orthogonal: 1 - cosine)
    assert [c.representation_id for c in index.search(unit(1, 0, 0, 0), 2)] == [near, middle]


def test_adding_a_representation_twice_keeps_one_entry() -> None:
    index = make()
    one = uuid.UUID(int=10)
    assert index.add(one, unit(1, 0, 0, 0)) is True
    assert index.add(one, unit(0, 1, 0, 0)) is False  # (a vector never changes: the first stays)
    assert len(index) == 1
    (found,) = index.search(unit(1, 0, 0, 0), 5)
    assert found.distance == pytest.approx(0.0, abs=1e-3)


def test_every_entry_is_found_by_its_representation_id_whatever_the_label() -> None:
    index = make()
    ids = [uuid.UUID(int=n) for n in (50, 40, 30)]
    for number, identifier in enumerate(ids):
        index.add(identifier, unit(1, float(number), 0, 0))
    assert {c.representation_id for c in index.search(unit(1, 1, 0, 0), 3)} == set(ids)


@pytest.mark.parametrize(
    "vector",
    [
        np.zeros(3, np.float32),
        np.zeros((2, 2), np.float32),
        np.array([1, np.nan, 0, 0], np.float32),
    ],
    ids=["too short", "not a vector", "not finite"],
)
def test_a_vector_that_is_not_a_finite_vector_of_the_dimension_is_refused(
    vector: np.ndarray[Any, Any],
) -> None:
    index = make()
    with pytest.raises(ValueError, match=r"dimensions|finite"):
        index.add(uuid.UUID(int=1), vector)
    with pytest.raises(ValueError, match=r"dimensions|finite"):
        index.search(vector, 1)
    assert len(index) == 0


def test_k_must_be_at_least_one() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        make().search(unit(1, 0, 0, 0), 0)
