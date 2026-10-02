"""The SCRFD reference detector's pre- and postprocessing, as a versioned contract
(ML_COMPONENTS_AND_EVALUATION.md sections 4.1 and 8.1; M3 decision "reference models").

Everything here is model-independent NumPy and Pillow: no ONNX Runtime, no weights. A different
detector gets its own contract and its own version; changing anything below changes `VERSION`.

The contract (`scrfd-letterbox-v1`):

* input: the decoded RGB image is scaled by one factor so that its longer side is `input_size`
  (bilinear), pasted at the top-left of a zero-filled `input_size` square, normalised as
  `(pixel - mean) / std`, channels first, `float32`, one image per tensor;
* outputs: nine tensors, three per stride (8, 16, 32): scores `(cells * 2, 1)`, box distances
  `(cells * 2, 4)` and five landmark offsets `(cells * 2, 10)`, in that order (all scores, then all
  boxes, then all landmarks); a leading batch axis of one is accepted. Two anchors per grid cell,
  centred on `(column * stride, row * stride)`, distances and offsets in units of the stride;
* postprocessing: keep scores of at least `score_threshold`, greedy non-maximum suppression at
  `nms_iou`, divide by the scale to get original pixels, then normalise to the image.

Detections the contract cannot use are rejected here, before alignment (section 4.1): a box is
clipped to the image (a face cut off by the border is still a face) and dropped if nothing is left;
a detection with a landmark outside the image is dropped, because alignment from a guessed point
would be a silent error. The numbers are the reference model's published defaults and are
provisional like every threshold (section 18.1).
"""

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from backend.ml.contracts.messages import Box, Point
from backend.ml.contracts.protocol import ContractError, MLErrorCode

VERSION = "scrfd-letterbox-v1"
STRIDES = (8, 16, 32)
ANCHORS_PER_CELL = 2
LANDMARKS = 5

Floats = NDArray[np.float32]


@dataclass(frozen=True, slots=True)
class DetectorContract:
    input_size: int = 640
    mean: float = 127.5
    std: float = 128.0
    score_threshold: float = 0.5
    nms_iou: float = 0.4

    def __post_init__(self) -> None:
        if self.input_size <= 0 or self.input_size % max(STRIDES) != 0:
            raise ValueError(f"input_size must be a positive multiple of {max(STRIDES)}")
        if self.std <= 0:
            raise ValueError("std must be positive")
        if not (0 <= self.score_threshold <= 1 and 0 < self.nms_iou <= 1):
            raise ValueError("the thresholds are fractions")


@dataclass(frozen=True, slots=True)
class Letterboxed:
    tensor: Floats  # (1, 3, size, size)
    scale: float  # input pixels per original pixel


@dataclass(frozen=True, slots=True)
class FoundFace:
    box: Box  # normalised to the image
    score: float
    landmarks: tuple[Point, ...]  # five points, normalised to the image


def _bad_output(message: str) -> ContractError:
    return ContractError(MLErrorCode.INFERENCE_FAILED, f"the detector's output: {message}")


def letterbox(image: NDArray[np.uint8], contract: DetectorContract) -> Letterboxed:
    """The detector's input tensor for one canonical image (RGB, uint8, HWC)."""
    if image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:
        raise ContractError(MLErrorCode.INVALID_INPUT, "an image must be uint8 HWC, 3 channels")
    height, width = image.shape[:2]
    if height < 1 or width < 1:
        raise ContractError(MLErrorCode.INVALID_INPUT, "an image has no pixels")
    size = contract.input_size
    scale = size / max(height, width)
    new_width = max(1, round(width * scale))
    new_height = max(1, round(height * scale))
    resized = Image.fromarray(image).resize((new_width, new_height), Image.Resampling.BILINEAR)
    canvas = np.zeros((size, size, 3), dtype=np.float32)
    canvas[:new_height, :new_width] = np.asarray(resized, dtype=np.float32)
    canvas = (canvas - contract.mean) / contract.std  # (padding is zero pixels, normalised too)
    tensor = np.ascontiguousarray(canvas.transpose(2, 0, 1)[None])
    return Letterboxed(tensor=tensor, scale=scale)


def _anchor_centres(size: int, stride: int) -> Floats:
    cells = size // stride
    columns, rows = np.meshgrid(np.arange(cells), np.arange(cells))
    centres = np.stack([columns, rows], axis=-1).reshape(-1, 2).astype(np.float32) * stride
    return np.repeat(centres, ANCHORS_PER_CELL, axis=0)


def _rows(tensor: Floats, expected: int, width: int, what: str) -> Floats:
    array = np.asarray(tensor, dtype=np.float32)
    if array.ndim == 3 and array.shape[0] == 1:
        array = array[0]
    if array.shape != (expected, width):
        raise _bad_output(f"{what} has shape {array.shape}, expected {(expected, width)}")
    if not np.isfinite(array).all():
        raise _bad_output(f"{what} holds a value that is not finite")
    return array


def non_maximum_suppression(boxes: Floats, scores: Floats, iou: float) -> list[int]:
    """Indices to keep, best score first; a box is dropped when its overlap with a better kept
    one exceeds `iou`. Ties in score keep the earlier box, so the result is deterministic."""
    order = np.argsort(-scores, kind="stable")
    kept: list[int] = []
    areas = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    while order.size:
        best = int(order[0])
        kept.append(best)
        rest = order[1:]
        x0 = np.maximum(boxes[best, 0], boxes[rest, 0])
        y0 = np.maximum(boxes[best, 1], boxes[rest, 1])
        x1 = np.minimum(boxes[best, 2], boxes[rest, 2])
        y1 = np.minimum(boxes[best, 3], boxes[rest, 3])
        inter = np.maximum(0.0, x1 - x0) * np.maximum(0.0, y1 - y0)
        union = areas[best] + areas[rest] - inter
        overlap = np.divide(inter, union, out=np.zeros_like(inter), where=union > 0)
        order = rest[overlap <= iou]
    return kept


def decode(
    outputs: list[Floats],
    contract: DetectorContract,
    letterboxed_scale: float,
    image_size: tuple[int, int],
) -> list[FoundFace]:
    """The faces in the model's nine output tensors, best first. `image_size` is the original
    image's (height, width), which the normalised result refers to."""
    if len(outputs) != 3 * len(STRIDES):
        raise _bad_output(f"{len(outputs)} tensors, expected {3 * len(STRIDES)}")
    height, width = image_size
    boxes: list[Floats] = []
    scores: list[Floats] = []
    points: list[Floats] = []
    for level, stride in enumerate(STRIDES):
        centres = _anchor_centres(contract.input_size, stride)
        count = len(centres)
        score = _rows(outputs[level], count, 1, f"scores at stride {stride}")[:, 0]
        distance = _rows(outputs[level + 3], count, 4, f"boxes at stride {stride}") * stride
        offset = _rows(outputs[level + 6], count, 2 * LANDMARKS, f"landmarks at stride {stride}")
        keep = score >= contract.score_threshold
        centres, score, distance, offset = centres[keep], score[keep], distance[keep], offset[keep]
        boxes.append(
            np.stack(
                [
                    centres[:, 0] - distance[:, 0],
                    centres[:, 1] - distance[:, 1],
                    centres[:, 0] + distance[:, 2],
                    centres[:, 1] + distance[:, 3],
                ],
                axis=1,
            )
        )
        scores.append(score)
        points.append(centres[:, None, :] + offset.reshape(-1, LANDMARKS, 2) * stride)
    all_boxes = np.concatenate(boxes) / letterboxed_scale
    all_scores = np.concatenate(scores)
    all_points = np.concatenate(points) / letterboxed_scale
    found: list[FoundFace] = []
    for index in non_maximum_suppression(all_boxes, all_scores, contract.nms_iou):
        face = _normalised(
            all_boxes[index], all_points[index], float(all_scores[index]), width, height
        )
        if face is not None:
            found.append(face)
    return found


def _normalised(
    box: Floats, landmarks: Floats, score: float, width: int, height: int
) -> FoundFace | None:
    x0, y0 = max(0.0, float(box[0])), max(0.0, float(box[1]))
    x1, y1 = min(float(width), float(box[2])), min(float(height), float(box[3]))
    if not (x0 < x1 and y0 < y1):
        return None
    inside = (
        (landmarks[:, 0] >= 0)
        & (landmarks[:, 0] <= width)
        & (landmarks[:, 1] >= 0)
        & (landmarks[:, 1] <= height)
    )
    if not inside.all():
        return None
    return FoundFace(
        box=(x0 / width, y0 / height, x1 / width, y1 / height),
        score=score,
        landmarks=tuple((float(x) / width, float(y) / height) for x, y in landmarks),
    )
