"""The face-correspondence rule of identity model 60.1 (owner decision D3): boundaries, spaces,
missing vectors, ties and mutual uniqueness."""

import uuid

import numpy as np
import pytest

from backend.app.processing.correspondence import (
    MIN_COSINE,
    MIN_IOU,
    Box,
    Face,
    NoCorrespondence,
    Pair,
    Unmatched,
    correspond,
    cosine,
    geometric_pairs,
    iou,
)

SPACE = uuid.UUID(int=1)
OTHER_SPACE = uuid.UUID(int=2)
BOX = Box(0.1, 0.1, 0.4, 0.4)


def ident(n: int) -> uuid.UUID:
    return uuid.UUID(int=1000 + n)


def unit(*values: float) -> np.ndarray:
    vector = np.array(values, dtype=np.float32)
    return (vector / np.linalg.norm(vector)).astype(np.float32)


def with_cosine(value: float) -> np.ndarray:
    """A unit vector at exactly `value` cosine from (1, 0)."""
    return np.array([value, np.sqrt(1.0 - value * value)], dtype=np.float32)


def face(
    n: int, box: Box = BOX, vector: np.ndarray | None = None, space: uuid.UUID = SPACE
) -> Face:
    return Face(ident(n), box, space, unit(1.0, 0.0) if vector is None else vector)


def shifted(dx: float) -> Box:
    return Box(BOX.x + dx, BOX.y, BOX.width, BOX.height)


def test_iou_of_identical_disjoint_and_partial_boxes() -> None:
    assert iou(BOX, BOX) == pytest.approx(1.0)
    assert iou(BOX, Box(0.6, 0.6, 0.2, 0.2)) == 0.0
    assert iou(Box(0, 0, 0.2, 0.2), Box(0.2, 0, 0.2, 0.2)) == 0.0  # touching edges
    # half of a box: overlap 0.5, union 1.5
    assert iou(Box(0, 0, 0.2, 0.2), Box(0.1, 0, 0.2, 0.2)) == pytest.approx(1 / 3)


def test_cosine_is_scale_free_and_zero_for_a_null_vector() -> None:
    assert cosine(unit(1, 0), np.array([3, 0], dtype=np.float32)) == pytest.approx(1.0)
    assert cosine(unit(1, 0), unit(0, 1)) == pytest.approx(0.0)
    assert cosine(unit(1, 0), np.zeros(2, dtype=np.float32)) == 0.0


def test_a_single_close_pair_corresponds_and_reports_its_measures() -> None:
    old, new = face(1), face(2, shifted(0.01), with_cosine(0.95))

    result = correspond([old], [new], space_id=SPACE, decided=[old.id])

    pair = result[old.id]
    assert isinstance(pair, Pair)
    assert pair.current_id == new.id
    assert pair.iou >= MIN_IOU
    assert pair.cosine == pytest.approx(0.95, abs=1e-6)


@pytest.mark.parametrize(
    ("cos", "corresponds"), [(MIN_COSINE + 1e-4, True), (MIN_COSINE - 1e-4, False)]
)
def test_the_cosine_boundary(cos: float, corresponds: bool) -> None:
    old, new = face(1), face(2, vector=with_cosine(cos))

    result = correspond([old], [new], space_id=SPACE, decided=[old.id])

    assert isinstance(result[old.id], Pair) is corresponds


def test_the_iou_boundary() -> None:
    # Two equal boxes of width w shifted by d overlap (w - d) / (w + d); solve for the boundary.
    width = BOX.width
    at_boundary = width * (1 - MIN_IOU) / (1 + MIN_IOU)
    old = face(1)
    inside = face(2, shifted(at_boundary * 0.99))
    outside = face(3, shifted(at_boundary * 1.01))

    assert isinstance(correspond([old], [inside], space_id=SPACE, decided=[old.id])[old.id], Pair)
    missed = correspond([old], [outside], space_id=SPACE, decided=[old.id])[old.id]
    assert missed == Unmatched(old.id, NoCorrespondence.NO_CORRESPONDENCE, ())


def test_a_previous_face_in_another_space_is_never_compared() -> None:
    old, new = face(1, space=OTHER_SPACE), face(2)

    result = correspond([old], [new], space_id=SPACE, decided=[old.id])

    assert result[old.id] == Unmatched(old.id, NoCorrespondence.SPACE_CHANGED, ())


def test_a_previous_face_without_a_vector_is_missing_its_vector() -> None:
    old = Face(ident(1), BOX, SPACE, None)

    result = correspond([old], [face(2)], space_id=SPACE, decided=[old.id])

    assert result[old.id] == Unmatched(old.id, NoCorrespondence.MISSING_VECTOR, ())


def test_two_candidates_for_one_face_are_ambiguous() -> None:
    old, first, second = face(1), face(2, shifted(0.005)), face(3, shifted(-0.005))

    result = correspond([old], [first, second], space_id=SPACE, decided=[old.id])

    assert result[old.id] == Unmatched(old.id, NoCorrespondence.AMBIGUOUS, (first.id, second.id))


def test_a_face_claimed_by_two_previous_faces_is_ambiguous_for_both() -> None:
    """Mutual uniqueness is judged against every previous face, decided or not: the undecided
    face 2 makes the decided face 1 ambiguous."""
    decided, undecided, new = face(1), face(2, shifted(0.005)), face(3)

    result = correspond([decided, undecided], [new], space_id=SPACE, decided=[decided.id])

    assert result == {decided.id: Unmatched(decided.id, NoCorrespondence.AMBIGUOUS, (new.id,))}


def test_disjoint_faces_pair_independently() -> None:
    left, right = Box(0.0, 0.0, 0.3, 0.3), Box(0.6, 0.6, 0.3, 0.3)
    old_left, old_right = face(1, left), face(2, right, unit(0, 1))
    new_left, new_right = face(3, left), face(4, right, unit(0, 1))

    result = correspond(
        [old_left, old_right],
        [new_right, new_left],
        space_id=SPACE,
        decided=[old_left.id, old_right.id],
    )

    assert {key: value.current_id for key, value in result.items() if isinstance(value, Pair)} == {
        old_left.id: new_left.id,
        old_right.id: new_right.id,
    }


def test_geometric_pairs_ignore_vectors_and_spaces_but_require_uniqueness() -> None:
    erased = Face(ident(1), BOX)  # no vector, no space: an erased face
    same_place = face(2, space=OTHER_SPACE, vector=unit(0, 1))
    elsewhere = face(3, Box(0.6, 0.6, 0.3, 0.3))

    assert geometric_pairs([erased], [same_place, elsewhere]) == {same_place.id: erased.id}
    crowded = face(4, shifted(0.005))
    assert geometric_pairs([erased], [same_place, crowded]) == {}


def test_video_faces_correspond_only_within_the_same_frame() -> None:
    box = Box(0.1, 0.1, 0.3, 0.3)
    earlier = Face(uuid.uuid4(), box, time_ms=500)
    same_frame = Face(uuid.uuid4(), box, time_ms=500)
    later = Face(uuid.uuid4(), box, time_ms=1000)

    assert geometric_pairs([earlier], [later]) == {}
    assert geometric_pairs([earlier], [same_frame]) == {same_frame.id: earlier.id}
