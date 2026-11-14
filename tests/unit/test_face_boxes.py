"""The box rule (issue 181): the boundaries of the match between a selected and a detected face."""

import pytest

from evaluation.face_boxes import BadBox, checked, iou, match_face


def test_overlap_at_the_threshold_matches_and_just_under_it_does_not() -> None:
    selected = [0.0, 0.0, 0.5, 0.5]
    half = [0.0, 0.0, 0.5, 0.25]  # inside the selection: intersection 0.125, union 0.25
    assert iou(selected, half) == 0.5
    assert match_face(selected, [half]) == 0
    assert match_face(selected, [[0.0, 0.0, 0.5, 0.24]]) is None


def test_two_faces_both_close_to_the_selection_are_ambiguous_not_the_first() -> None:
    selected = [0.0, 0.0, 0.4, 0.4]
    twins = [[0.0, 0.0, 0.4, 0.4], [0.01, 0.0, 0.41, 0.4]]

    assert match_face(selected, twins) is None
    assert match_face(selected, twins[::-1]) is None
    assert match_face(selected, [twins[0], [0.6, 0.6, 0.9, 0.9]]) == 0
    assert match_face(selected, [[0.6, 0.6, 0.9, 0.9], twins[0]]) == 1  # the answer follows order


def test_a_selection_spanning_two_faces_matches_neither() -> None:
    wide = [0.0, 0.0, 0.9, 0.4]
    faces = [[0.0, 0.0, 0.4, 0.4], [0.5, 0.0, 0.9, 0.4]]  # each has under half of the selection

    assert match_face(wide, faces) is None


def test_no_faces_and_disjoint_boxes_have_no_overlap() -> None:
    assert match_face([0.1, 0.1, 0.2, 0.2], []) is None
    assert iou([0.0, 0.0, 0.1, 0.1], [0.5, 0.5, 0.6, 0.6]) == 0.0


@pytest.mark.parametrize("box", [[0, 0, 1, 1], (0.1, 0.2, 0.3, 0.4), [0.0, 0, 0.5, 0.5]])
def test_a_box_inside_the_picture_is_accepted_as_floats(box: object) -> None:
    assert checked(box) == [float(v) for v in box]  # type: ignore[attr-defined]


@pytest.mark.parametrize("box", ["0123", [True, False, 1, 1], [0, 0, 1], None, [0, 0, 1, 1.0001]])
def test_anything_else_is_refused(box: object) -> None:
    with pytest.raises(BadBox):
        checked(box)
