"""TST-038 (part): the SCRFD reference detector's preprocessing and postprocessing contract,
checked on synthetic tensors (no model, no weights)."""

from typing import Any

import numpy as np
import pytest

from backend.ml.contracts.protocol import ContractError, MLErrorCode
from backend.ml.perception.detection import (
    ANCHORS_PER_CELL,
    STRIDES,
    DetectorContract,
    decode,
    letterbox,
    non_maximum_suppression,
)

CONTRACT = DetectorContract()
SIZE = CONTRACT.input_size
# A landmark layout that is easy to read: offsets, in strides, from the anchor centre.
OFFSETS = np.array([-1.0, -1.0, 1.0, -1.0, 0.0, 0.0, -1.0, 1.0, 1.0, 1.0], dtype=np.float32)


def blank_outputs() -> list[np.ndarray[Any, Any]]:
    """Nine output tensors in which nothing is a face."""
    cells = [(SIZE // s) ** 2 * ANCHORS_PER_CELL for s in STRIDES]
    return (
        [np.zeros((n, 1), np.float32) for n in cells]
        + [np.zeros((n, 4), np.float32) for n in cells]
        + [np.zeros((n, 10), np.float32) for n in cells]
    )


def plant(
    outputs: list[np.ndarray[Any, Any]],
    level: int,
    column: int,
    row: int,
    *,
    score: float = 0.9,
    distances: tuple[float, float, float, float] = (2, 2, 2, 2),
    anchor: int = 0,
) -> tuple[float, float]:
    """Make one anchor a face; returns its centre in input pixels."""
    stride = STRIDES[level]
    index = (row * (SIZE // stride) + column) * ANCHORS_PER_CELL + anchor
    outputs[level][index, 0] = score
    outputs[level + 3][index] = distances
    outputs[level + 6][index] = OFFSETS
    return column * stride, row * stride


# --- the input tensor --------------------------------------------------------------------------


def test_letterbox_scales_the_longer_side_and_pads_at_the_bottom_right() -> None:
    image = np.full((100, 200, 3), 255, dtype=np.uint8)
    boxed = letterbox(image, CONTRACT)
    assert boxed.tensor.shape == (1, 3, SIZE, SIZE)
    assert boxed.tensor.dtype == np.float32
    assert boxed.tensor.flags["C_CONTIGUOUS"]
    assert boxed.scale == SIZE / 200
    white = (255 - CONTRACT.mean) / CONTRACT.std
    padding = (0 - CONTRACT.mean) / CONTRACT.std
    assert boxed.tensor[0, 0, 0, 0] == pytest.approx(white)
    assert boxed.tensor[0, 2, 319, 639] == pytest.approx(white)  # the last scaled row and column
    assert boxed.tensor[0, 1, 320, 0] == pytest.approx(padding)  # below the picture
    assert boxed.tensor[0, 1, 0, SIZE - 1] == pytest.approx(white)


def test_letterbox_keeps_channels_in_rgb_order() -> None:
    image = np.zeros((64, 64, 3), dtype=np.uint8)
    image[..., 0] = 255  # pure red
    tensor = letterbox(image, CONTRACT).tensor
    assert tensor[0, 0, 10, 10] > 0 > tensor[0, 1, 10, 10]
    assert tensor[0, 1, 10, 10] == tensor[0, 2, 10, 10]


def test_letterbox_shrinks_a_larger_image_and_leaves_a_tiny_one_at_least_one_pixel() -> None:
    assert letterbox(np.zeros((1280, 1280, 3), np.uint8), CONTRACT).scale == 0.5
    assert letterbox(np.zeros((5, 640, 3), np.uint8), CONTRACT).tensor.shape == (1, 3, SIZE, SIZE)


@pytest.mark.parametrize("shape", [(1, 5000, 3), (5000, 1, 3), (4, 5000, 3)])
def test_an_image_too_thin_to_keep_its_shape_is_refused_not_distorted(shape: Any) -> None:
    with pytest.raises(ContractError, match="thin") as refused:
        letterbox(np.zeros(shape, np.uint8), CONTRACT)
    assert refused.value.code is MLErrorCode.INVALID_INPUT


@pytest.mark.parametrize(
    "image",
    [
        np.zeros((10, 10), np.uint8),
        np.zeros((10, 10, 4), np.uint8),
        np.zeros((10, 10, 3), np.float32),
        np.zeros((0, 10, 3), np.uint8),
        np.zeros((0, 0, 3), np.uint8),
    ],
)
def test_letterbox_refuses_what_is_not_a_canonical_image(image: np.ndarray[Any, Any]) -> None:
    with pytest.raises(ContractError) as refused:
        letterbox(image, CONTRACT)
    assert refused.value.code is MLErrorCode.INVALID_INPUT


@pytest.mark.parametrize(
    "options",
    [
        {"input_size": 0},
        {"input_size": 100},
        {"std": 0},
        {"score_threshold": 1.5},
        {"score_threshold": 0},
        {"nms_iou": 0},
    ],
)
def test_the_contract_refuses_nonsense(options: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="input_size|std|fractions"):
        DetectorContract(**options)


# --- non-maximum suppression ---------------------------------------------------------------------


def test_nms_keeps_the_best_of_overlapping_boxes_and_all_distinct_ones() -> None:
    boxes = np.array(
        [[0, 0, 10, 10], [1, 1, 11, 11], [50, 50, 60, 60], [0, 0, 10, 10]], dtype=np.float32
    )
    scores = np.array([0.6, 0.9, 0.7, 0.6], dtype=np.float32)
    assert non_maximum_suppression(boxes, scores, 0.4) == [1, 2]


def test_nms_overlap_exactly_at_the_threshold_is_kept_and_a_tie_keeps_the_earlier_box() -> None:
    boxes = np.array([[0, 0, 10, 10], [5, 0, 15, 10]], dtype=np.float32)  # overlap 50 / 150
    scores = np.array([0.8, 0.8], dtype=np.float32)
    assert non_maximum_suppression(boxes, scores, 1 / 3) == [0, 1]
    assert non_maximum_suppression(boxes, scores, 0.3) == [0]


def test_nms_of_nothing_and_of_an_empty_box() -> None:
    nothing = np.zeros((0, 4), np.float32)
    assert non_maximum_suppression(nothing, np.zeros(0, np.float32), 0.4) == []
    flat = np.array([[3, 3, 3, 3], [3, 3, 3, 3]], dtype=np.float32)  # zero area: never overlaps
    assert non_maximum_suppression(flat, np.array([0.9, 0.8], np.float32), 0.4) == [0, 1]


# --- decoding ------------------------------------------------------------------------------------


def test_nothing_above_the_threshold_is_no_face() -> None:
    assert decode(blank_outputs(), CONTRACT, 1.0, (640, 640)) == []


def test_one_planted_face_decodes_to_normalised_geometry() -> None:
    outputs = blank_outputs()
    cx, cy = plant(outputs, level=0, column=40, row=30, score=0.93)  # centre (320, 240), stride 8
    (face,) = decode(outputs, CONTRACT, 1.0, (640, 640))
    assert face.score == pytest.approx(0.93)
    assert face.box == pytest.approx(
        ((cx - 16) / 640, (cy - 16) / 640, (cx + 16) / 640, (cy + 16) / 640)
    )
    expected = [(cx + dx * 8, cy + dy * 8) for dx, dy in OFFSETS.reshape(5, 2)]
    assert np.array(face.landmarks).reshape(-1) == pytest.approx(
        [v / 640 for point in expected for v in point]
    )


def test_decode_undoes_the_letterbox_scale_and_normalises_to_the_original_image() -> None:
    outputs = blank_outputs()
    plant(outputs, level=1, column=20, row=10)  # stride 16: centre (320, 160) in the 640 input
    # The original was 1280 x 960 (width x height), shrunk by 0.5.
    (face,) = decode(outputs, CONTRACT, 0.5, (960, 1280))
    assert face.box == pytest.approx(
        ((320 - 32) * 2 / 1280, (160 - 32) * 2 / 960, 704 / 1280, 384 / 960)
    )
    assert face.landmarks[2] == pytest.approx((640 / 1280, 320 / 960))  # the nose: the centre


def test_the_three_strides_are_read_with_their_own_grids() -> None:
    outputs = blank_outputs()
    plant(outputs, level=2, column=5, row=7, anchor=1)  # stride 32: centre (160, 224)
    (face,) = decode(outputs, CONTRACT, 1.0, (640, 640))
    assert face.box == pytest.approx(((160 - 64) / 640, (224 - 64) / 640, 224 / 640, 288 / 640))


def test_a_leading_batch_axis_of_one_is_accepted() -> None:
    outputs = blank_outputs()
    plant(outputs, level=0, column=40, row=30)
    batched = [o[None] for o in outputs]
    assert decode(batched, CONTRACT, 1.0, (640, 640)) == decode(outputs, CONTRACT, 1.0, (640, 640))


def test_duplicates_of_one_face_are_merged_best_first() -> None:
    outputs = blank_outputs()
    plant(outputs, level=0, column=40, row=30, score=0.7)
    plant(outputs, level=0, column=40, row=30, score=0.95, anchor=1)
    plant(outputs, level=0, column=60, row=60, score=0.8)
    faces = decode(outputs, CONTRACT, 1.0, (640, 640))
    assert [round(f.score, 2) for f in faces] == [0.95, 0.8]


def test_a_box_over_the_border_is_clipped_and_one_wholly_outside_is_dropped() -> None:
    outputs = blank_outputs()
    plant(outputs, level=0, column=3, row=40, distances=(2, 2, 2, 2), score=0.9)  # x from 8 to 40
    plant(outputs, level=0, column=0, row=10, distances=(2, 2, 2, 2), score=0.8)  # x from -16 to 16
    # Landmarks of the first face fall inside; the second one's do not (x = -8 for two of them).
    faces = decode(outputs, CONTRACT, 1.0, (640, 640))
    assert [round(f.score, 1) for f in faces] == [0.9]
    outputs = blank_outputs()
    index = (40 * 80 + 0) * ANCHORS_PER_CELL
    outputs[0][index, 0] = 0.9
    outputs[3][index] = (2, 2, 2, 2)  # a box over the left border: x from -16 to 16
    outputs[6][index] = (0.1, 0, 0.1, 0, 0.1, 0, 0.1, 0, 0.1, 0)  # landmarks all inside
    (face,) = decode(outputs, CONTRACT, 1.0, (640, 640))
    assert face.box[0] == 0.0
    assert face.box[2] == pytest.approx(16 / 640)


def test_a_box_with_nothing_left_inside_the_image_is_dropped() -> None:
    outputs = blank_outputs()
    index = (10 * 80 + 79) * ANCHORS_PER_CELL  # the last column: centre x = 632
    outputs[0][index, 0] = 0.9
    outputs[3][index] = (-3, 1, 5, 1)  # x from 632 + 24 = 656 to 632 + 40: wholly outside
    assert decode(outputs, CONTRACT, 1.0, (640, 640)) == []


def test_a_face_with_a_landmark_outside_the_image_is_rejected_not_clamped() -> None:
    outputs = blank_outputs()
    plant(outputs, level=0, column=0, row=40)  # landmarks at x = -8
    assert decode(outputs, CONTRACT, 1.0, (640, 640)) == []
    outputs = blank_outputs()
    plant(outputs, level=0, column=40, row=70)
    outputs[6][(70 * 80 + 40) * ANCHORS_PER_CELL, 9] = 12  # a landmark far below the image
    assert decode(outputs, CONTRACT, 1.0, (640, 640)) == []


def test_the_right_and_bottom_edges_are_inside() -> None:
    outputs = blank_outputs()
    index = (79 * 80 + 79) * ANCHORS_PER_CELL  # centre (632, 632); the landmark offset is +1 stride
    outputs[0][index, 0] = 0.9
    outputs[3][index] = (2, 2, 2, 2)
    outputs[6][index] = (0, 0, 0, 0, 0, 0, 0, 0, 1, 1)  # the last point lands exactly on (640, 640)
    (face,) = decode(outputs, CONTRACT, 1.0, (640, 640))
    assert face.landmarks[4] == (1.0, 1.0)
    assert face.box[2] == 1.0


@pytest.mark.parametrize("bad", ["count", "shape", "nan", "inf"])
def test_malformed_model_output_is_an_inference_failure(bad: str) -> None:
    outputs = blank_outputs()
    if bad == "count":
        outputs = outputs[:-1]
    elif bad == "shape":
        outputs[4] = outputs[4][:-1]
    else:
        outputs[7][3, 1] = np.nan if bad == "nan" else np.inf
    with pytest.raises(ContractError) as refused:
        decode(outputs, CONTRACT, 1.0, (640, 640))
    assert refused.value.code is MLErrorCode.INFERENCE_FAILED


def test_a_score_exactly_at_the_threshold_counts_and_one_below_does_not() -> None:
    outputs = blank_outputs()
    plant(outputs, level=0, column=40, row=30, score=CONTRACT.score_threshold)
    plant(outputs, level=0, column=60, row=60, score=CONTRACT.score_threshold - 0.01)
    assert len(decode(outputs, CONTRACT, 1.0, (640, 640))) == 1


def test_a_box_that_only_touches_the_border_has_nothing_inside() -> None:
    outputs = blank_outputs()
    index = (10 * 80 + 79) * ANCHORS_PER_CELL  # centre x = 632
    outputs[0][index, 0] = 0.9
    outputs[3][index] = (-3, 1, 5, 1)  # x from 656 to 672
    outputs[6][index] = (0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    assert decode(outputs, CONTRACT, 1.0, (640, 656)) == []  # an image 656 wide: x0 == its width


def face_at(column: int, row: int, distances: tuple[float, float, float, float]) -> list[Any]:
    """One face on the stride-8 grid whose five landmarks all sit on the anchor centre."""
    outputs = blank_outputs()
    index = (row * 80 + column) * ANCHORS_PER_CELL
    outputs[0][index, 0] = 0.9
    outputs[3][index] = distances
    return outputs


def test_a_box_over_each_border_is_clipped_to_it_and_a_landmark_on_the_edge_is_inside() -> None:
    (top,) = decode(face_at(40, 0, (2, 2, 2, 2)), CONTRACT, 1.0, (640, 640))
    assert top.box[1] == 0.0
    assert top.landmarks[0][1] == 0.0
    (left,) = decode(face_at(0, 40, (2, 2, 2, 2)), CONTRACT, 1.0, (640, 640))
    assert left.box[0] == 0.0
    assert left.landmarks[0][0] == 0.0
    (bottom,) = decode(face_at(40, 79, (2, 2, 2, 2)), CONTRACT, 1.0, (640, 640))
    assert bottom.box[3] == 1.0


def test_a_box_that_only_touches_the_bottom_border_has_nothing_inside() -> None:
    assert decode(face_at(40, 79, (1, -3, 1, 5)), CONTRACT, 1.0, (656, 640)) == []


@pytest.mark.parametrize(
    ("scale", "size"),
    [
        (0.0, (640, 640)),
        (-1.0, (640, 640)),
        (float("nan"), (640, 640)),
        (1.0, (0, 640)),
        (1.0, (640, 0)),
    ],
)
def test_a_scale_or_image_size_that_cannot_be_right_is_refused(
    scale: float, size: tuple[int, int]
) -> None:
    with pytest.raises(ContractError) as refused:
        decode(blank_outputs(), CONTRACT, scale, size)
    assert refused.value.code is MLErrorCode.INVALID_INPUT


def test_an_unusable_detection_does_not_suppress_a_usable_neighbour() -> None:
    outputs = blank_outputs()
    plant(outputs, level=0, column=40, row=30, score=0.7)  # fine
    # A better-scoring, overlapping detection one anchor over whose landmark is outside.
    index = (30 * 80 + 41) * ANCHORS_PER_CELL
    outputs[0][index, 0] = 0.95
    outputs[3][index] = (2, 2, 2, 2)
    outputs[6][index] = (0, 0, 0, 0, 0, 0, 0, 0, 0, -200)
    faces = decode(outputs, CONTRACT, 1.0, (640, 640))
    assert [round(f.score, 1) for f in faces] == [0.7]
