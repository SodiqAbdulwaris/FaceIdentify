"""The ArcFace reference embedder's alignment, preprocessing and output normalisation, as a
versioned contract (ML_COMPONENTS_AND_EVALUATION.md sections 6.1, 8.1 and 9.1).

Model-independent NumPy and Pillow, no ONNX Runtime and no weights. Changing the template, the
crop size, the pixel normalisation or the vector normalisation is a compatibility change, not an
implementation detail (section 8.1): `VERSION` names the defaults below, a contract built with
other numbers needs its own version from whoever makes it, and a representation space records it.

The contract (`arcface-112-similarity-v1`):

* alignment (Pillow's bilinear resampling, which differs numerically from a four-tap
  `INTER_LINEAR`): the five landmarks (left eye, right eye, nose, left mouth corner, right
  mouth corner, as seen in the image) are mapped onto `TEMPLATE` by the least-squares
  similarity transform (rotation, uniform scale, translation; never a reflection) and the
  image is resampled bilinearly into a `crop_size` square; pixels outside it are black;
* model input: RGB, `(pixel - mean) / std`, channels first, `float32`, one face per tensor;
* output: a finite vector of the model's dimension, divided by its L2 norm so that every stored
  vector has norm one (a zero or non-finite vector is refused, never stored as is).
"""

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from backend.ml.contracts.messages import Point
from backend.ml.contracts.protocol import ContractError, MLErrorCode

VERSION = "arcface-112-similarity-v1"
NORMALIZATION = "L2_NORMALIZED"  # the value a representation's `normalization` carries
TEMPLATE: NDArray[np.float64] = np.array(
    [
        [38.2946, 51.6963],
        [73.5318, 51.5014],
        [56.0252, 71.7366],
        [41.5493, 92.3655],
        [70.7299, 92.2041],
    ]
)  # the reference landmark positions in a 112 x 112 crop

Floats = NDArray[np.float32]


@dataclass(frozen=True, slots=True)
class EmbedderContract:
    crop_size: int = 112
    mean: float = 127.5
    std: float = 127.5

    def __post_init__(self) -> None:
        if self.crop_size != 112:
            raise ValueError("the template is defined for a 112 pixel crop")
        if self.std <= 0:
            raise ValueError("std must be positive")


def _invalid(message: str) -> ContractError:
    return ContractError(MLErrorCode.INVALID_INPUT, message)


def similarity_transform(
    source: NDArray[np.float64], target: NDArray[np.float64]
) -> NDArray[np.float64]:
    """The 2 x 3 matrix M with `target ~ M @ [x, y, 1]` over the points, least squares among the
    similarity transforms (Umeyama, 1991). Needs points that are not all the same."""
    mean_source, mean_target = source.mean(axis=0), target.mean(axis=0)
    centred_source, centred_target = source - mean_source, target - mean_target
    variance = float((centred_source**2).sum() / len(source))
    if not np.isfinite(variance) or variance < 1e-12:
        raise _invalid("the landmarks are all at one point")
    u, singular, vt = np.linalg.svd(centred_target.T @ centred_source / len(source))
    signs = np.ones(2)
    if np.linalg.det(u) * np.linalg.det(vt) < 0:  # a reflection: flip the weakest direction
        signs[1] = -1.0
    rotation = u @ np.diag(signs) @ vt
    scale = float((singular * signs).sum() / variance)
    if scale <= 0:
        raise _invalid("the landmarks cannot be aligned")
    shift = mean_target - scale * rotation @ mean_source
    return np.hstack([scale * rotation, shift[:, None]])


def align(
    image: NDArray[np.uint8], landmarks: tuple[Point, ...], contract: EmbedderContract
) -> NDArray[np.uint8]:
    """The aligned crop (crop_size x crop_size x 3, uint8) of one face. `landmarks` are the
    five points normalised to the image, in the order of `TEMPLATE`."""
    if image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:
        raise _invalid("an image must be uint8 HWC, 3 channels")
    if len(landmarks) != len(TEMPLATE):
        raise _invalid(f"alignment needs {len(TEMPLATE)} landmarks, got {len(landmarks)}")
    height, width = image.shape[:2]
    points = np.array([(x * width, y * height) for x, y in landmarks], dtype=np.float64)
    forward = similarity_transform(points, TEMPLATE)
    inverse = np.linalg.inv(np.vstack([forward, [0.0, 0.0, 1.0]]))[:2]  # crop -> image
    crop = Image.fromarray(image).transform(
        (contract.crop_size, contract.crop_size),
        Image.Transform.AFFINE,
        tuple(inverse.reshape(-1)),
        resample=Image.Resampling.BILINEAR,
        fillcolor=(0, 0, 0),
    )
    return np.asarray(crop, dtype=np.uint8)


def preprocess(crop: NDArray[np.uint8], contract: EmbedderContract) -> Floats:
    """The model's input tensor for one aligned crop: (1, 3, crop_size, crop_size)."""
    size = contract.crop_size
    if crop.shape != (size, size, 3) or crop.dtype != np.uint8:
        raise _invalid(f"a crop must be uint8 {size} x {size} x 3")
    tensor = (crop.astype(np.float32) - contract.mean) / contract.std
    return np.ascontiguousarray(tensor.transpose(2, 0, 1)[None])


def canonical_vector(raw: NDArray[np.floating], dimension: int) -> Floats:
    """The vector to store for a model's raw output: little-endian `float32`, length `dimension`,
    L2 norm one. A vector of another length, one with a value that is not finite, and one with no
    length at all are failures of the model, not vectors."""
    vector = np.asarray(raw, dtype=np.float64).reshape(-1)
    if vector.shape != (dimension,):
        raise ContractError(
            MLErrorCode.INFERENCE_FAILED,
            f"the embedder returned {vector.size} values, not {dimension}",
        )
    if not np.isfinite(vector).all():
        raise ContractError(
            MLErrorCode.INFERENCE_FAILED, "the embedder returned a non-finite value"
        )
    norm = float(np.linalg.norm(vector))
    if norm < 1e-12:
        raise ContractError(MLErrorCode.INFERENCE_FAILED, "the embedder returned a zero vector")
    return (vector / norm).astype("<f4")
