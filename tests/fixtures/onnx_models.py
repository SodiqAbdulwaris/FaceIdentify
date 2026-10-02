"""Tiny generated ONNX models that stand in for SCRFD and ArcFace in tests (never real weights).

The licence of the real weights is unverified (issue 69), so they are not committed; these are
built from scratch with the `onnx` package and are small, deterministic and honest about what they
are. They honour the same tensor contracts as the references (`scrfd-letterbox-v1` outputs,
`arcface-112-similarity-v1` input), so the worker's whole path (letterbox, session, decode, align,
vector) runs for real; only the "intelligence" is fake:

* the detector reports the faces it was built with, at fixed anchors, whatever the picture looks
  like, except that a picture with no light in it (every pixel black) has no face; so a test
  controls both what is found and where, and can show an empty result;
* the embedder is a fixed random projection of a 4 x 4 average of the aligned crop, so the same
  crop always gives the same vector and different crops give different ones.
"""

from dataclasses import dataclass
from typing import Any

import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper

from backend.ml.perception.detection import ANCHORS_PER_CELL, STRIDES

INPUT_SIZE = 640
CROP_SIZE = 112
EMBEDDING_DIMENSION = 16
# Offsets, in strides, from the anchor centre: eyes above, nose in the middle, mouth below.
FACE_OFFSETS = (-1.0, -1.0, 1.0, -1.0, 0.0, 0.0, -1.0, 1.0, 1.0, 1.0)


@dataclass(frozen=True, slots=True)
class PlantedFace:
    level: int  # 0, 1, 2: stride 8, 16, 32
    column: int
    row: int
    score: float = 0.9
    distances: tuple[float, float, float, float] = (2.0, 2.0, 2.0, 2.0)
    anchor: int = 0

    def index(self) -> int:
        cells = INPUT_SIZE // STRIDES[self.level]
        return (self.row * cells + self.column) * ANCHORS_PER_CELL + self.anchor


def _constant(name: str, array: Any) -> onnx.TensorProto:
    return numpy_helper.from_array(array, name)


def _finish(graph: onnx.GraphProto) -> bytes:
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 8
    onnx.checker.check_model(model)
    return bytes(model.SerializeToString())


def detector_model(faces: tuple[PlantedFace, ...] = ()) -> bytes:
    """A detector with nine outputs in the contract's order (all scores, boxes, landmarks)."""
    cells = [(INPUT_SIZE // s) ** 2 * ANCHORS_PER_CELL for s in STRIDES]
    scores = [np.zeros((n, 1), np.float32) for n in cells]
    boxes = [np.zeros((n, 4), np.float32) for n in cells]
    points = [np.zeros((n, 10), np.float32) for n in cells]
    for face in faces:
        scores[face.level][face.index(), 0] = face.score
        boxes[face.level][face.index()] = face.distances
        points[face.level][face.index()] = FACE_OFFSETS
    initializers = [
        _constant("shift", np.float32(0.99)),
        _constant("gain", np.float32(1000.0)),
        _constant("low", np.float32(0.0)),
        _constant("high", np.float32(1.0)),
    ]
    nodes = [
        helper.make_node("ReduceMax", ["input"], ["brightest"], keepdims=0),
        helper.make_node("Add", ["brightest", "shift"], ["lit"]),
        helper.make_node("Relu", ["lit"], ["positive"]),
        helper.make_node("Mul", ["positive", "gain"], ["amplified"]),
        helper.make_node("Clip", ["amplified", "low", "high"], ["gate"]),
    ]
    outputs = []
    for level, stride in enumerate(STRIDES):
        initializers += [
            _constant(f"scores_{stride}", scores[level]),
            _constant(f"boxes_raw_{stride}", boxes[level]),
            _constant(f"points_raw_{stride}", points[level]),
        ]
    for kind, count in (("score", 1), ("bbox", 4), ("kps", 10)):
        for level, stride in enumerate(STRIDES):
            name = f"{kind}_{stride}"
            if kind == "score":
                nodes.append(helper.make_node("Mul", [f"scores_{stride}", "gate"], [name]))
            else:
                raw = f"{'boxes' if kind == 'bbox' else 'points'}_raw_{stride}"
                nodes.append(helper.make_node("Identity", [raw], [name]))
            outputs.append(
                helper.make_tensor_value_info(name, TensorProto.FLOAT, [cells[level], count])
            )
    graph = helper.make_graph(
        nodes,
        "fixture-detector",
        [helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 3, INPUT_SIZE, INPUT_SIZE])],
        outputs,
        initializers,
    )
    return _finish(graph)


def embedder_model(
    dimension: int = EMBEDDING_DIMENSION,
    *,
    seed: int = 1,
    zero: bool = False,
    dynamic: bool = False,
) -> bytes:
    """An embedder: average-pool the crop to 4 x 4, flatten, project to `dimension` values."""
    rng = np.random.default_rng(seed)
    weights = np.zeros((48, dimension), np.float32) if zero else rng.normal(size=(48, dimension))
    pool = CROP_SIZE // 4
    graph = helper.make_graph(
        [
            helper.make_node(
                "AveragePool",
                ["input"],
                ["pooled"],
                kernel_shape=[pool, pool],
                strides=[pool, pool],
            ),
            helper.make_node("Flatten", ["pooled"], ["flat"], axis=1),
            helper.make_node("MatMul", ["flat", "weights"], ["embedding"]),
        ],
        "fixture-embedder",
        [helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 3, CROP_SIZE, CROP_SIZE])],
        [helper.make_tensor_value_info("embedding", TensorProto.FLOAT, [1, dimension])],
        [_constant("weights", weights.astype(np.float32))],
    )
    return _finish(graph)


def two_input_model() -> bytes:
    """A model the worker must refuse: it takes two inputs."""
    graph = helper.make_graph(
        [helper.make_node("Add", ["a", "b"], ["c"])],
        "two-inputs",
        [
            helper.make_tensor_value_info("a", TensorProto.FLOAT, [1]),
            helper.make_tensor_value_info("b", TensorProto.FLOAT, [1]),
        ],
        [helper.make_tensor_value_info("c", TensorProto.FLOAT, [1])],
    )
    return _finish(graph)
