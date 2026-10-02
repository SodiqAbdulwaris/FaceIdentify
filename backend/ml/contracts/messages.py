"""MLRequest, MLResponse and the typed inputs and outputs of the two initial operations
(API and Contracts.md sections 36-43).

Zero detected faces is a successful result (an empty tuple), never an error. The worker has no
application-domain operation: it detects faces and generates representations, nothing else.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from backend.ml.contracts.protocol import (
    PROTOCOL_VERSION,
    ContractError,
    MLErrorCode,
    MLOperation,
    MLStatus,
    invalid,
)
from backend.ml.contracts.shared_memory import SharedMemoryDescriptor
from backend.ml.contracts.wire import (
    as_mapping,
    error_code,
    exact_keys,
    integer,
    number,
    optional_string,
    sequence,
    string,
)

Point = tuple[float, float]
Box = tuple[float, float, float, float]  # x0, y0, x1, y1, normalised to the image (0..1)


def _box(value: Any, what: str) -> Box:
    items = [number(v, what) for v in sequence(value, what)]
    if len(items) != 4:
        raise invalid(f"{what} must have four numbers")
    x0, y0, x1, y1 = items
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        raise invalid(f"{what} must be a non-empty box inside the image")
    return (x0, y0, x1, y1)


def _landmarks(value: Any, what: str) -> tuple[Point, ...] | None:
    if value is None:
        return None
    points: list[Point] = []
    for raw in sequence(value, what):
        pair = [number(v, what) for v in sequence(raw, what)]
        if len(pair) != 2 or not all(0 <= v <= 1 for v in pair):
            raise invalid(f"{what} must be points inside the image")
        points.append((pair[0], pair[1]))
    return tuple(points)


# --- execution context -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    """Correlation ids for diagnostics and provenance only; the worker never interprets them."""

    job_id: str | None = None
    processing_run_id: str | None = None
    execution_segment_id: str | None = None

    def to_wire(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "processing_run_id": self.processing_run_id,
            "execution_segment_id": self.execution_segment_id,
        }

    @classmethod
    def from_wire(cls, value: Any) -> "ExecutionContext":
        data = as_mapping(value, "execution_context")
        exact_keys(data, "execution_context", set(), frozenset(cls.__slots__))
        return cls(**{k: optional_string(data.get(k), k) for k in cls.__slots__})


# --- inputs ------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FaceGeometry:
    """One detected face, addressed by the image it came from."""

    input_index: int
    face_index: int
    box: Box
    landmarks: tuple[Point, ...] | None = None

    def to_wire(self) -> dict[str, Any]:
        return {
            "input_index": self.input_index,
            "face_index": self.face_index,
            "box": list(self.box),
            "landmarks": None if self.landmarks is None else [list(p) for p in self.landmarks],
        }

    @classmethod
    def from_wire(cls, value: Any) -> "FaceGeometry":
        data = as_mapping(value, "face")
        exact_keys(data, "face", {"input_index", "face_index", "box"}, frozenset({"landmarks"}))
        return cls(
            input_index=integer(data["input_index"], "input_index", minimum=0),
            face_index=integer(data["face_index"], "face_index", minimum=0),
            box=_box(data["box"], "box"),
            landmarks=_landmarks(data.get("landmarks"), "landmarks"),
        )


@dataclass(frozen=True, slots=True)
class DetectFacesInput:
    """Decoded images: RGB, uint8, HWC, contiguous, orientation already applied."""

    images: tuple[SharedMemoryDescriptor, ...]

    def to_wire(self) -> dict[str, Any]:
        return {"images": [image.to_wire() for image in self.images]}

    @classmethod
    def from_wire(cls, value: Any) -> "DetectFacesInput":
        data = as_mapping(value, "input")
        exact_keys(data, "input", {"images"})
        return cls(images=_images(data["images"]))


@dataclass(frozen=True, slots=True)
class GenerateRepresentationsInput:
    images: tuple[SharedMemoryDescriptor, ...]
    faces: tuple[FaceGeometry, ...]

    def to_wire(self) -> dict[str, Any]:
        return {
            "images": [image.to_wire() for image in self.images],
            "faces": [face.to_wire() for face in self.faces],
        }

    @classmethod
    def from_wire(cls, value: Any) -> "GenerateRepresentationsInput":
        data = as_mapping(value, "input")
        exact_keys(data, "input", {"images", "faces"})
        images = _images(data["images"])
        faces = tuple(FaceGeometry.from_wire(f) for f in sequence(data["faces"], "faces"))
        for face in faces:
            if face.input_index >= len(images):
                raise invalid(f"a face refers to image {face.input_index}, which does not exist")
        return cls(images=images, faces=faces)


def _images(value: Any) -> tuple[SharedMemoryDescriptor, ...]:
    images = tuple(SharedMemoryDescriptor.from_wire(v) for v in sequence(value, "images"))
    if not images:
        raise invalid("at least one image is required")
    for image in images:
        if image.dtype != "uint8" or len(image.shape) != 3 or image.shape[2] != 3:
            raise ContractError(
                MLErrorCode.INVALID_INPUT, "an image must be uint8 HWC with 3 channels"
            )
    return images


# --- outputs -----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Detection:
    input_index: int
    detection_index: int
    box: Box
    score: float
    landmarks: tuple[Point, ...] | None = None

    def to_wire(self) -> dict[str, Any]:
        return {
            "input_index": self.input_index,
            "detection_index": self.detection_index,
            "box": list(self.box),
            "score": self.score,
            "landmarks": None if self.landmarks is None else [list(p) for p in self.landmarks],
        }

    @classmethod
    def from_wire(cls, value: Any) -> "Detection":
        data = as_mapping(value, "detection")
        exact_keys(
            data,
            "detection",
            {"input_index", "detection_index", "box", "score"},
            frozenset({"landmarks"}),
        )
        return cls(
            input_index=integer(data["input_index"], "input_index", minimum=0),
            detection_index=integer(data["detection_index"], "detection_index", minimum=0),
            box=_box(data["box"], "box"),
            score=number(data["score"], "score"),
            landmarks=_landmarks(data.get("landmarks"), "landmarks"),
        )


@dataclass(frozen=True, slots=True)
class DetectFacesOutput:
    detections: tuple[Detection, ...]  # empty is a successful "no face"

    def to_wire(self) -> dict[str, Any]:
        return {"detections": [d.to_wire() for d in self.detections]}

    @classmethod
    def from_wire(cls, value: Any) -> "DetectFacesOutput":
        data = as_mapping(value, "output")
        exact_keys(data, "output", {"detections"})
        return cls(
            tuple(Detection.from_wire(d) for d in sequence(data["detections"], "detections"))
        )


@dataclass(frozen=True, slots=True)
class RepresentationResult:
    """One embedding. The vector itself is in a worker-created segment, released afterwards with
    RELEASE_OUTPUT; no fixed dimension is assumed."""

    input_index: int
    face_index: int
    dimension: int
    dtype: str
    normalization: str
    embedding: SharedMemoryDescriptor

    def __post_init__(self) -> None:
        if self.embedding.shape != (self.dimension,) or self.embedding.dtype != self.dtype:
            raise ContractError(
                MLErrorCode.SHARED_MEMORY_INVALID,
                "the embedding segment does not match its dimension",
            )

    def to_wire(self) -> dict[str, Any]:
        return {
            "input_index": self.input_index,
            "face_index": self.face_index,
            "dimension": self.dimension,
            "dtype": self.dtype,
            "normalization": self.normalization,
            "embedding": self.embedding.to_wire(),
        }

    @classmethod
    def from_wire(cls, value: Any) -> "RepresentationResult":
        data = as_mapping(value, "representation")
        exact_keys(
            data,
            "representation",
            {"input_index", "face_index", "dimension", "dtype", "normalization", "embedding"},
        )
        return cls(
            input_index=integer(data["input_index"], "input_index", minimum=0),
            face_index=integer(data["face_index"], "face_index", minimum=0),
            dimension=integer(data["dimension"], "dimension", minimum=1),
            dtype=string(data["dtype"], "dtype"),
            normalization=string(data["normalization"], "normalization"),
            embedding=SharedMemoryDescriptor.from_wire(data["embedding"]),
        )


@dataclass(frozen=True, slots=True)
class GenerateRepresentationsOutput:
    representations: tuple[RepresentationResult, ...]

    def to_wire(self) -> dict[str, Any]:
        return {"representations": [r.to_wire() for r in self.representations]}

    @classmethod
    def from_wire(cls, value: Any) -> "GenerateRepresentationsOutput":
        data = as_mapping(value, "output")
        exact_keys(data, "output", {"representations"})
        return cls(
            tuple(
                RepresentationResult.from_wire(r)
                for r in sequence(data["representations"], "representations")
            )
        )


_INPUTS: dict[MLOperation, Any] = {
    MLOperation.DETECT_FACES: DetectFacesInput,
    MLOperation.GENERATE_REPRESENTATIONS: GenerateRepresentationsInput,
}
_OUTPUTS: dict[MLOperation, Any] = {
    MLOperation.DETECT_FACES: DetectFacesOutput,
    MLOperation.GENERATE_REPRESENTATIONS: GenerateRepresentationsOutput,
}
MLInput = DetectFacesInput | GenerateRepresentationsInput
MLOutput = DetectFacesOutput | GenerateRepresentationsOutput


def _operation(value: Any) -> MLOperation:
    try:
        return MLOperation(string(value, "operation"))
    except ValueError:
        raise invalid(f"unknown operation {value!r}") from None


def _version(data: Mapping[str, Any]) -> None:
    version = integer(data["version"], "version")
    if version != PROTOCOL_VERSION:
        raise ContractError(
            MLErrorCode.UNSUPPORTED_PROTOCOL_VERSION,
            f"protocol version {version} is not supported (expected {PROTOCOL_VERSION})",
        )


# --- request -----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MLRequest:
    request_id: str
    operation: MLOperation
    component: str  # the component version the caller wants executed
    input: MLInput
    options: dict[str, Any] = field(default_factory=dict)
    execution_context: ExecutionContext = field(default_factory=ExecutionContext)
    version: int = PROTOCOL_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.input, _INPUTS[self.operation]):
            raise invalid(f"{self.operation} does not take a {type(self.input).__name__}")

    def to_wire(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "request_id": self.request_id,
            "operation": self.operation.value,
            "component": self.component,
            "input": self.input.to_wire(),
            "options": dict(self.options),
            "execution_context": self.execution_context.to_wire(),
        }

    @classmethod
    def from_wire(cls, value: Any) -> "MLRequest":
        data = as_mapping(value, "request")
        exact_keys(
            data,
            "request",
            {"version", "request_id", "operation", "component", "input"},
            frozenset({"options", "execution_context"}),
        )
        _version(data)
        operation = _operation(data["operation"])
        return cls(
            request_id=string(data["request_id"], "request_id"),
            operation=operation,
            component=string(data["component"], "component"),
            input=_INPUTS[operation].from_wire(data["input"]),
            options=dict(as_mapping(data.get("options", {}), "options")),
            execution_context=ExecutionContext.from_wire(data.get("execution_context", {})),
        )


# --- response ----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExecutionProvenance:
    """What actually ran. The worker never silently falls back from CUDA to CPU: the backend
    decides fallback, so this is always what the backend asked for or an error says otherwise."""

    component_version_id: str
    runtime_variant_id: str
    provider: str
    device: str

    def to_wire(self) -> dict[str, Any]:
        return {
            "component_version_id": self.component_version_id,
            "runtime_variant_id": self.runtime_variant_id,
            "provider": self.provider,
            "device": self.device,
        }

    @classmethod
    def from_wire(cls, value: Any) -> "ExecutionProvenance":
        data = as_mapping(value, "execution")
        exact_keys(data, "execution", set(cls.__slots__))
        return cls(**{k: string(data[k], k) for k in cls.__slots__})


@dataclass(frozen=True, slots=True)
class MLError:
    code: MLErrorCode
    message: str

    def to_wire(self) -> dict[str, Any]:
        return {"code": self.code.value, "message": self.message}

    @classmethod
    def from_wire(cls, value: Any) -> "MLError":
        data = as_mapping(value, "error")
        exact_keys(data, "error", {"code", "message"})
        return cls(error_code(data["code"], "code"), string(data["message"], "message"))


@dataclass(frozen=True, slots=True)
class MLResponse:
    """Every accepted request ends as SUCCESS (with an output) or ERROR (with an error), exactly
    one of the two. A worker crash produces no response at all; the supervisor handles that."""

    request_id: str
    status: MLStatus
    operation: MLOperation  # not on the wire: see from_wire
    execution: ExecutionProvenance | None = None
    output: MLOutput | None = None
    timings: dict[str, float] = field(default_factory=dict)
    error: MLError | None = None
    version: int = PROTOCOL_VERSION

    def __post_init__(self) -> None:
        if self.status is MLStatus.SUCCESS:
            if self.error is not None or self.output is None or self.execution is None:
                raise invalid("a SUCCESS response has an output and its execution, and no error")
            if not isinstance(self.output, _OUTPUTS[self.operation]):
                raise invalid(f"{self.operation} does not produce a {type(self.output).__name__}")
        elif self.error is None or self.output is not None:
            raise invalid("an ERROR response has an error and no output")

    def to_wire(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "request_id": self.request_id,
            "status": self.status.value,
            "output": None if self.output is None else self.output.to_wire(),
            "execution": None if self.execution is None else self.execution.to_wire(),
            "timings": dict(self.timings),
            "error": None if self.error is None else self.error.to_wire(),
        }

    @classmethod
    def from_wire(cls, value: Any, operation: MLOperation) -> "MLResponse":
        """`operation` is the one of the pending request with the same `request_id`: the wire
        format does not repeat it (the receiver already knows what it asked for)."""
        data = as_mapping(value, "response")
        exact_keys(
            data,
            "response",
            {"version", "request_id", "status"},
            frozenset({"output", "execution", "timings", "error"}),
        )
        _version(data)
        try:
            status = MLStatus(string(data["status"], "status"))
        except ValueError:
            raise invalid(f"unknown status {data['status']!r}") from None
        output = data.get("output")
        execution = data.get("execution")
        error = data.get("error")
        timings = as_mapping(data.get("timings", {}), "timings")
        return cls(
            request_id=string(data["request_id"], "request_id"),
            operation=operation,
            status=status,
            output=None if output is None else _OUTPUTS[operation].from_wire(output),
            execution=None if execution is None else ExecutionProvenance.from_wire(execution),
            timings={string(k, "timing"): number(v, k) for k, v in timings.items()},
            error=None if error is None else MLError.from_wire(error),
        )
