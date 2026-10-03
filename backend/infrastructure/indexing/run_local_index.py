"""The run-local index: the pending representations of one processing run in one space, in memory.

Recognition searches the global index plus this one (Persistence 23): a face seen earlier in the
same run is evidence for a later face of the same run, although neither is part of the library
until the run is accepted. Everything about it is private and discardable:

* it lives in memory and is never written to disk, so a crash loses it and it is rebuilt from the
  run's `PENDING` representations in SQLite (`backend.app.recognition.retrieval`);
* it is never authoritative: what it returns is only candidates, which SQLite revalidates;
* its labels are a plain per-index counter mapped to the representation id, never an `ann_key`
  (decision 2026-10-02, CONTEXT open question 21): an `ann_key` is allocated at ANN-eligibility
  inside a transaction that might roll back, and a pending representation is not eligible.

One index serves one representation space, like the persisted ones: a vector of another dimension
is refused, and a caller never mixes spaces by construction.
"""

import uuid
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from usearch.index import Index

Vector = NDArray[np.float32]


@dataclass(frozen=True, slots=True)
class LocalCandidate:
    representation_id: uuid.UUID
    distance: float


class RunLocalIndex:
    def __init__(self, *, representation_space_id: uuid.UUID, ndim: int, metric: str) -> None:
        self.representation_space_id = representation_space_id
        self.ndim = ndim
        self._index = Index(ndim=ndim, metric=metric, dtype="f32")
        self._labels: list[uuid.UUID] = []  # label = position
        self._known: set[uuid.UUID] = set()

    def __len__(self) -> int:
        return len(self._labels)

    def add(self, representation_id: uuid.UUID, vector: Vector) -> bool:
        """Make a representation searchable. False if it already was (a vector never changes)."""
        array = self._checked(vector)
        if representation_id in self._known:
            return False
        self._index.add(len(self._labels), array)
        self._labels.append(representation_id)
        self._known.add(representation_id)
        return True

    def search(self, vector: Vector, k: int) -> list[LocalCandidate]:
        """The up-to-`k` nearest pending representations, nearest first."""
        if k < 1:
            raise ValueError("k must be at least 1")
        matches = self._index.search(self._checked(vector), k)
        return [
            LocalCandidate(self._labels[int(label)], float(distance))
            for label, distance in zip(matches.keys, matches.distances, strict=True)
        ]

    def _checked(self, vector: Vector) -> Vector:
        array = np.asarray(vector, dtype=np.float32)
        if array.shape != (self.ndim,):
            raise ValueError(
                f"expected a vector of {self.ndim} dimensions, got shape {array.shape}"
            )
        if not np.isfinite(array).all():
            raise ValueError("a vector must be finite (no NaN or infinity)")
        return array
