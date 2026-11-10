"""Which face of a new generation is the same face as one of the previous generation (identity
model 60.1; owner decision D3, 2026-10-21; approved text 2026-11-09).

Pure: it reads nothing and writes nothing, so the activation transaction computes it from SQLite
rows and the rule can be tested on its own.

A previous face and a current face *correspond* only when all of these hold: both representations
are in the run's `RepresentationSpace` (vectors of different spaces are never compared), both
vectors exist, the normalized boxes overlap with IoU >= `MIN_IOU`, the vectors have cosine >=
`MIN_COSINE`, and the pairing is mutual and unique: each face is the other's only candidate. The
numbers are the owner's and are constants of the rule, versioned with it (`RULE_VERSION`).

`geometric_pairs` is the box-only half of the same rule, for faces whose vector is erased: a
reprocessed image must not bring back a face that was forgotten (persistence 12.1 item 9a).
"""

import math
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum

import numpy as np
import numpy.typing as npt

RULE_VERSION = "reprocess-correspondence-v1"
MIN_IOU = 0.7
MIN_COSINE = 0.9


class NoCorrespondence(StrEnum):
    """Why a human-decided previous face was not carried over (persistence 10)."""

    NO_CORRESPONDENCE = "NO_CORRESPONDENCE"
    AMBIGUOUS = "AMBIGUOUS"
    SPACE_CHANGED = "SPACE_CHANGED"
    MISSING_VECTOR = "MISSING_VECTOR"


@dataclass(frozen=True, slots=True)
class Box:
    """A normalized bounding box: origin and size in `[0, 1]`, as observations store it."""

    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True, slots=True)
class Face:
    """One face of a generation: its representation (or observation) id, box, space and vector."""

    id: uuid.UUID
    box: Box
    space_id: uuid.UUID | None = None
    vector: npt.NDArray[np.float32] | None = None
    # A video face's presentation time (M6 step 7): it corresponds only to a face of the same
    # sampled frame. None for an image.
    time_ms: int | None = None


def overlap(old: Face, new: Face) -> float:
    """Box IoU of two faces of the same frame; 0 for faces of different frames."""
    return iou(old.box, new.box) if old.time_ms == new.time_ms else 0.0


@dataclass(frozen=True, slots=True)
class Pair:
    previous_id: uuid.UUID
    current_id: uuid.UUID
    iou: float
    cosine: float


@dataclass(frozen=True, slots=True)
class Unmatched:
    previous_id: uuid.UUID
    reason: NoCorrespondence
    candidate_ids: tuple[uuid.UUID, ...]  # the current faces that made it ambiguous, if any


def iou(a: Box, b: Box) -> float:
    """Intersection over union of two boxes (0 when they do not overlap)."""
    width = min(a.x + a.width, b.x + b.width) - max(a.x, b.x)
    height = min(a.y + a.height, b.y + b.height) - max(a.y, b.y)
    if width <= 0 or height <= 0:
        return 0.0
    overlap = width * height
    return overlap / (a.width * a.height + b.width * b.height - overlap)


def cosine(a: npt.NDArray[np.float32], b: npt.NDArray[np.float32]) -> float:
    """Cosine similarity of two vectors, computed in float64; 0 when either has no length."""
    left, right = a.astype(np.float64), b.astype(np.float64)
    norms = float(np.linalg.norm(left)) * float(np.linalg.norm(right))
    if norms == 0.0 or not math.isfinite(norms):
        return 0.0
    return float(np.dot(left, right)) / norms


def _candidates(
    previous: Sequence[Face],
    current: Sequence[Face],
    related: Callable[[Face, Face], bool],
) -> tuple[dict[uuid.UUID, list[uuid.UUID]], dict[uuid.UUID, list[uuid.UUID]]]:
    forward: dict[uuid.UUID, list[uuid.UUID]] = {face.id: [] for face in previous}
    backward: dict[uuid.UUID, list[uuid.UUID]] = {face.id: [] for face in current}
    for old in previous:
        for new in current:
            if related(old, new):
                forward[old.id].append(new.id)
                backward[new.id].append(old.id)
    return forward, backward


def correspond(
    previous: Sequence[Face],
    current: Sequence[Face],
    *,
    space_id: uuid.UUID,
    decided: Sequence[uuid.UUID],
) -> dict[uuid.UUID, Pair | Unmatched]:
    """For each previous face named in `decided` (the human-decided ones), its trustworthy
    counterpart among `current` or why it has none. Uniqueness is judged against *every* face of
    both generations, so an undecided face can make a decided one ambiguous."""
    by_id = {face.id: face for face in [*previous, *current]}

    def comparable(face: Face) -> bool:
        return face.space_id == space_id and face.vector is not None

    def related(old: Face, new: Face) -> bool:
        if not (comparable(old) and comparable(new)) or overlap(old, new) < MIN_IOU:
            return False
        assert old.vector is not None  # (comparable)
        assert new.vector is not None
        return cosine(old.vector, new.vector) >= MIN_COSINE

    forward, backward = _candidates(previous, current, related)
    result: dict[uuid.UUID, Pair | Unmatched] = {}
    for face_id in decided:
        face = by_id[face_id]
        found = forward[face_id]
        if face.space_id != space_id:
            result[face_id] = Unmatched(face_id, NoCorrespondence.SPACE_CHANGED, ())
        elif face.vector is None:
            result[face_id] = Unmatched(face_id, NoCorrespondence.MISSING_VECTOR, ())
        elif not found:
            result[face_id] = Unmatched(face_id, NoCorrespondence.NO_CORRESPONDENCE, ())
        elif len(found) > 1 or len(backward[found[0]]) > 1:
            result[face_id] = Unmatched(face_id, NoCorrespondence.AMBIGUOUS, tuple(found))
        else:
            new = by_id[found[0]]
            assert face.vector is not None  # (related)
            assert new.vector is not None
            result[face_id] = Pair(
                face_id, new.id, overlap(face, new), cosine(face.vector, new.vector)
            )
    return result


def geometric_pairs(
    previous: Sequence[Face], current: Sequence[Face]
) -> dict[uuid.UUID, uuid.UUID]:
    """Each current face whose box corresponds (IoU >= `MIN_IOU`, mutual and unique) to one of
    `previous`, mapped to it: vectors and spaces play no part."""
    forward, backward = _candidates(
        previous, current, lambda old, new: overlap(old, new) >= MIN_IOU
    )
    return {
        found[0]: old_id
        for old_id, found in forward.items()
        if len(found) == 1 and len(backward[found[0]]) == 1
    }
