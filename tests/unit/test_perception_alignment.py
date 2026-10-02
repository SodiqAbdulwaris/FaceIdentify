"""TST-039 (part): the ArcFace reference embedder's alignment, preprocessing and vector
normalisation contract, checked on synthetic data (no model, no weights)."""

import math
from typing import Any

import numpy as np
import pytest
from PIL import Image

from backend.ml.contracts.protocol import ContractError, MLErrorCode
from backend.ml.perception.alignment import (
    TEMPLATE,
    EmbedderContract,
    align,
    canonical_vector,
    preprocess,
    similarity_transform,
)

CONTRACT = EmbedderContract()


def picture(width: int, height: int) -> np.ndarray[Any, Any]:
    """A smooth picture with no symmetry, so a wrong turn or flip cannot go unnoticed."""
    x = np.linspace(0, 1, width)[None, :]
    y = np.linspace(0, 1, height)[:, None]
    return np.stack([x * 200 + y * 50, y * 200 + x * 30, (x * y) * 250], axis=-1).astype(np.uint8)


def landmarks_of(points: np.ndarray[Any, Any], width: int, height: int) -> tuple[Any, ...]:
    return tuple((float(x) / width, float(y) / height) for x, y in points)


def apply(matrix: np.ndarray[Any, Any], points: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
    moved: np.ndarray[Any, Any] = points @ matrix[:, :2].T + matrix[:, 2]
    return moved


# --- the similarity transform ------------------------------------------------------------------


def test_the_transform_recovers_a_known_rotation_scale_and_shift() -> None:
    angle, scale, shift = math.radians(25), 1.7, np.array([13.0, -4.0])
    rotation = np.array([[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]])
    source = TEMPLATE
    target = scale * source @ rotation.T + shift
    matrix = similarity_transform(source, target)
    assert matrix[:, :2] == pytest.approx(scale * rotation)
    assert matrix[:, 2] == pytest.approx(shift)


def test_a_mirror_image_is_aligned_by_a_rotation_never_a_reflection() -> None:
    mirrored = TEMPLATE * np.array([-1.0, 1.0])
    matrix = similarity_transform(mirrored, TEMPLATE)
    assert np.linalg.det(matrix[:, :2]) > 0


def test_the_transform_is_the_least_squares_fit_for_noisy_points() -> None:
    noisy = TEMPLATE + np.array([[1, 0], [0, -1], [0.5, 0.5], [-1, 0], [0, 1]], dtype=float)
    matrix = similarity_transform(noisy, TEMPLATE)
    assert np.abs(apply(matrix, noisy) - TEMPLATE).max() < 2.5


def test_points_at_one_place_cannot_be_aligned() -> None:
    with pytest.raises(ContractError) as refused:
        similarity_transform(np.ones((5, 2)), TEMPLATE)
    assert refused.value.code is MLErrorCode.INVALID_INPUT


def test_points_that_only_a_reflection_could_align_cannot_be_aligned() -> None:
    square = np.array([[1.0, 0], [0, 1], [-1, 0], [0, -1]])
    mirrored = np.array([[1.0, 0], [0, -1], [-1, 0], [0, 1]])  # the same corners, y reversed
    # The best proper rotation of one onto the other has scale zero, which is not a transform.
    with pytest.raises(ContractError) as refused:
        similarity_transform(square, mirrored)
    assert refused.value.code is MLErrorCode.INVALID_INPUT


# --- alignment -----------------------------------------------------------------------------------


def test_landmarks_already_on_the_template_leave_the_crop_unchanged() -> None:
    image = picture(112, 112)
    crop = align(image, landmarks_of(TEMPLATE, 112, 112), CONTRACT)
    assert crop.shape == (112, 112, 3)
    assert crop.dtype == np.uint8
    assert np.abs(crop.astype(int) - image.astype(int)).max() <= 1


def test_a_face_twice_as_large_is_brought_back_to_the_template_scale() -> None:
    small = picture(112, 112)
    big = np.asarray(Image.fromarray(small).resize((224, 224), Image.Resampling.BILINEAR))
    crop = align(big, landmarks_of(TEMPLATE * 2, 224, 224), CONTRACT)
    interior = (slice(8, 104), slice(8, 104))
    assert np.abs(crop[interior].astype(int) - small[interior].astype(int)).mean() < 3


def test_a_face_in_a_larger_picture_is_cut_out_where_the_landmarks_are() -> None:
    canvas = picture(400, 300)
    origin = np.array([150.0, 60.0])
    crop = align(canvas, landmarks_of(TEMPLATE + origin, 400, 300), CONTRACT)
    expected = canvas[60:172, 150:262]
    assert np.abs(crop.astype(int) - expected.astype(int)).max() <= 2


def test_the_parts_of_the_crop_beyond_the_image_are_black() -> None:
    image = np.full((112, 112, 3), 200, dtype=np.uint8)
    shifted = TEMPLATE - np.array([40.0, 0.0])  # the face is 40 pixels left of where it belongs
    crop = align(image, landmarks_of(shifted, 112, 112), CONTRACT)
    assert crop[:, :30].max() == 0  # left of the image's edge
    assert crop[:, 60:].min() == 200  # the image itself


def test_a_rotated_face_is_turned_upright() -> None:
    image = picture(300, 300)
    angle = math.radians(30)
    rotation = np.array([[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]])
    centre = np.array([150.0, 150.0])
    points = (TEMPLATE - 56) @ rotation.T + centre
    crop = align(image, landmarks_of(points, 300, 300), CONTRACT)
    turned = np.asarray(
        Image.fromarray(image).rotate(30, resample=Image.Resampling.BILINEAR, center=(150, 150))
    )[94:206, 94:206]
    assert np.abs(crop[20:92, 20:92].astype(int) - turned[20:92, 20:92].astype(int)).mean() < 6


def test_alignment_needs_five_landmarks() -> None:
    with pytest.raises(ContractError) as refused:
        align(picture(112, 112), landmarks_of(TEMPLATE[:4], 112, 112), CONTRACT)
    assert refused.value.code is MLErrorCode.INVALID_INPUT


def test_the_template_is_defined_for_a_112_pixel_crop_and_a_positive_std() -> None:
    with pytest.raises(ValueError, match="112"):
        EmbedderContract(crop_size=128)
    with pytest.raises(ValueError, match="std"):
        EmbedderContract(std=0)


# --- model input and output ----------------------------------------------------------------------


def test_preprocess_normalises_to_unit_range_channels_first() -> None:
    crop = np.zeros((112, 112, 3), dtype=np.uint8)
    crop[..., 0], crop[..., 2] = 255, 128
    tensor = preprocess(crop, CONTRACT)
    assert tensor.shape == (1, 3, 112, 112)
    assert tensor.dtype == np.float32
    assert tensor.flags["C_CONTIGUOUS"]
    assert tensor[0, 0, 5, 5] == pytest.approx(1.0)
    assert tensor[0, 1, 5, 5] == pytest.approx(-1.0)
    assert tensor[0, 2, 5, 5] == pytest.approx(128 / 127.5 - 1)


@pytest.mark.parametrize(
    "crop", [np.zeros((100, 112, 3), np.uint8), np.zeros((112, 112, 3), np.float32)]
)
def test_preprocess_refuses_a_crop_of_the_wrong_kind(crop: np.ndarray[Any, Any]) -> None:
    with pytest.raises(ContractError) as refused:
        preprocess(crop, CONTRACT)
    assert refused.value.code is MLErrorCode.INVALID_INPUT


def test_a_vector_is_stored_little_endian_float32_with_unit_norm() -> None:
    vector = canonical_vector(np.array([[3.0, 4.0, 0.0, 0.0]], dtype=np.float64), 4)
    assert vector.dtype == np.dtype("<f4")
    assert vector.shape == (4,)
    assert vector.tolist() == pytest.approx([0.6, 0.8, 0.0, 0.0])
    assert float(np.linalg.norm(vector)) == pytest.approx(1.0)


@pytest.mark.parametrize(
    "raw",
    [
        np.ones(3),
        np.ones(5),
        np.array([1.0, np.nan, 0, 0]),
        np.array([np.inf, 0, 0, 0]),
        np.zeros(4),
    ],
)
def test_a_vector_that_is_not_one_is_a_model_failure(raw: np.ndarray[Any, Any]) -> None:
    with pytest.raises(ContractError) as refused:
        canonical_vector(raw, 4)
    assert refused.value.code is MLErrorCode.INFERENCE_FAILED
