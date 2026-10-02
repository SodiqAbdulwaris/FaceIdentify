"""MLRequest, MLResponse and the typed inputs and outputs of the two initial operations
(API and Contracts.md sections 36-43).

Zero detected faces is a successful result (an empty tuple), never an error. The worker has no
application-domain operation: it detects faces and generates representations, nothing else.

The constructors are the gate: every rule is checked when an object is built, so a message the
backend assembles in process is validated exactly like one read from the wire (`from_wire` only
reads the types and constructs).
"""

from dataclasses import dataclass, field
from typing import Any, cast

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


def _check_box(box: Any) -> None:
    if not isinstance(box, tuple) or len(box) != 4:
        raise invalid("box must have four numbers")
    x0, y0, x1, y1 = (number(v, "box") for v in box)
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        raise invalid("box must be a non-empty box inside the image")


def _check_landmarks(landmarks: Any) -> None:
    if landmarks is None:
        return
    if not isinstance(landmarks, tuple):
        raise invalid("landmarks must be a tuple of points")
    for point in landmarks:
        if not isinstance(point, tuple) or len(point) != 2:
            raise invalid("a landmark is an (x, y) pair")
        if not all(0 <= number(v, "landmarks") <= 1 for v in point):
            raise invalid("landmarks must be points inside the image")


def _read_box(value: Any) -> Box:
    items = tuple(number(v, "box") for v in sequence(value, "box"))
    _check_box(items)
    return items  # type: ignore[return-value]


def _read_landmarks(value: Any) -> tuple[Point, ...] | None:
    if value is None:
        return None
    points = tuple(
        tuple(number(v, "landmarks") for v in sequence(p, "landmarks"))
        for p in sequence(value, "landmarks")
    )
    _check_landmarks(points)
    return points  # type: ignore[return-value]


def _wire_landmarks(landmarks: tuple[Point, ...] | None) -> list[list[float]] | None:
    return None if landmarks is None else [list(p) for p in landmarks]


def _operation(value: Any) -> MLOperation:
    name = string(value, "operation")
    try:
        return MLOperation(name)
    except ValueError:
        raise invalid(f"unknown operation {name!r}") from None


def _check_operation(value: Any) -> MLOperation:
    if not isinstance(value, MLOperation):
        raise invalid("operation must be an MLOperation")
    return value


def _check_version(version: Any) -> None:
    if integer(version, "version") != PROTOCOL_VERSION:
        raise ContractError(
            MLErrorCode.UNSUPPORTED_PROTOCOL_VERSION,
            f"protocol version {version} is not supported (expected {PROTOCOL_VERSION})",
        )


# --- execution context -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    """Correlation ids for diagnostics and provenance only; the worker never interprets them."""

    job_id: str | None = None
    processing_run_id: str | None = None
    execution_segment_id: str | None = None

    def __post_init__(self) -> None:
        for name in self.__slots__:
            optional_string(getattr(self, name), name)

    def to_wire(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__slots__}

    @classmethod
    def from_wire(cls, value: Any) -> "ExecutionContext":
        data = as_mapping(value, "execution_context")
        exact_keys(data, "execution_context", set(), frozenset(cls.__slots__))
        return cls(**{name: data.get(name) for name in cls.__slots__})


# --- inputs ------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FaceGeometry:
    """One detected face, addressed by the image it came from."""

    input_index: int
    face_index: int
    box: Box
    landmarks: tuple[Point, ...] | None = None

    def __post_init__(self) -> None:
        integer(self.input_index, "input_index", minimum=0)
        integer(self.face_index, "face_index", minimum=0)
        _check_box(self.box)
        _check_landmarks(self.landmarks)

    def to_wire(self) -> dict[str, Any]:
        return {
            "input_index": self.input_index,
            "face_index": self.face_index,
            "box": list(self.box),
            "landmarks": _wire_landmarks(self.landmarks),
        }

    @classmethod
    def from_wire(cls, value: Any) -> "FaceGeometry":
        data = as_mapping(value, "face")
        exact_keys(data, "face", {"input_index", "face_index", "box"}, frozenset({"landmarks"}))
        return cls(
            input_index=data["input_index"],
            face_index=data["face_index"],
            box=_read_box(data["box"]),
            landmarks=_read_landmarks(data.get("landmarks")),
        )


def _check_images(images: Any) -> None:
    """Decoded images: RGB, uint8, HWC, contiguous, orientation already applied."""
    if not isinstance(images, tuple) or not images:
        raise invalid("at least one image is required")
    for image in images:
        if not isinstance(image, SharedMemoryDescriptor):
            raise invalid("an image is a shared-memory descriptor")
        if image.dtype != "uint8" or len(image.shape) != 3 or image.shape[2] != 3:
            raise ContractError(MLErrorCode.INVALID_INPUT, "an image must be uint8 HWC, 3 channels")


def _read_images(value: Any) -> tuple[SharedMemoryDescriptor, ...]:
    return tuple(SharedMemoryDescriptor.from_wire(v) for v in sequence(value, "images"))


@dataclass(frozen=True, slots=True)
class DetectFacesInput:
    images: tuple[SharedMemoryDescriptor, ...]

    def __post_init__(self) -> None:
        _check_images(self.images)

    def to_wire(self) -> dict[str, Any]:
        return {"images": [image.to_wire() for image in self.images]}

    @classmethod
    def from_wire(cls, value: Any) -> "DetectFacesInput":
        data = as_mapping(value, "input")
        exact_keys(data, "input", {"images"})
        return cls(images=_read_images(data["images"]))


@dataclass(frozen=True, slots=True)
class GenerateRepresentationsInput:
    images: tuple[SharedMemoryDescriptor, ...]
    faces: tuple[FaceGeometry, ...]

    def __post_init__(self) -> None:
        _check_images(self.images)
        if not isinstance(self.faces, tuple) or not all(
            isinstance(face, FaceGeometry) for face in self.faces
        ):
            raise invalid("faces must be a tuple of FaceGeometry")
        for face in self.faces:
            if face.input_index >= len(self.images):
                raise invalid(f"a face refers to image {face.input_index}, which does not exist")

    def to_wire(self) -> dict[str, Any]:
        return {
            "images": [image.to_wire() for image in self.images],
            "faces": [face.to_wire() for face in self.faces],
        }

    @classmethod
    def from_wire(cls, value: Any) -> "GenerateRepresentationsInput":
        data = as_mapping(value, "input")
        exact_keys(data, "input", {"images", "faces"})
        return cls(
            images=_read_images(data["images"]),
            faces=tuple(FaceGeometry.from_wire(f) for f in sequence(data["faces"], "faces")),
        )


# --- outputs -----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Detection:
    input_index: int
    detection_index: int
    box: Box
    score: float
    landmarks: tuple[Point, ...] | None = None

    def __post_init__(self) -> None:
        integer(self.input_index, "input_index", minimum=0)
        integer(self.detection_index, "detection_index", minimum=0)
        _check_box(self.box)
        number(self.score, "score")
        _check_landmarks(self.landmarks)

    def to_wire(self) -> dict[str, Any]:
        return {
            "input_index": self.input_index,
            "detection_index": self.detection_index,
            "box": list(self.box),
            "score": self.score,
            "landmarks": _wire_landmarks(self.landmarks),
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
            input_index=data["input_index"],
            detection_index=data["detection_index"],
            box=_read_box(data["box"]),
            score=data["score"],
            landmarks=_read_landmarks(data.get("landmarks")),
        )


@dataclass(frozen=True, slots=True)
class DetectFacesOutput:
    detections: tuple[Detection, ...]  # empty is a successful "no face"

    def __post_init__(self) -> None:
        if not isinstance(self.detections, tuple) or not all(
            isinstance(d, Detection) for d in self.detections
        ):
            raise invalid("detections must be a tuple of Detection")

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
    RELEASE_OUTPUT; no fixed dimension is assumed. A `float32` embedding is little-endian
    (Persistence section 23); nothing here can express another byte order, and a reader
    attaching the segment must check that the real segment is at least `size_bytes` long."""

    input_index: int
    face_index: int
    dimension: int
    dtype: str
    normalization: str
    embedding: SharedMemoryDescriptor

    def __post_init__(self) -> None:
        integer(self.input_index, "input_index", minimum=0)
        integer(self.face_index, "face_index", minimum=0)
        integer(self.dimension, "dimension", minimum=1)
        string(self.dtype, "dtype")
        string(self.normalization, "normalization")
        if not isinstance(self.embedding, SharedMemoryDescriptor):
            raise invalid("an embedding is a shared-memory descriptor")
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
            input_index=data["input_index"],
            face_index=data["face_index"],
            dimension=data["dimension"],
            dtype=data["dtype"],
            normalization=data["normalization"],
            embedding=SharedMemoryDescriptor.from_wire(data["embedding"]),
        )


@dataclass(frozen=True, slots=True)
class GenerateRepresentationsOutput:
    representations: tuple[RepresentationResult, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.representations, tuple) or not all(
            isinstance(r, RepresentationResult) for r in self.representations
        ):
            raise invalid("representations must be a tuple of RepresentationResult")

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
        _check_version(self.version)
        string(self.request_id, "request_id")
        string(self.component, "component")
        operation = _check_operation(self.operation)
        if not isinstance(self.input, _INPUTS[operation]):
            raise invalid(f"{operation} does not take a {type(self.input).__name__}")
        if not isinstance(self.options, dict):
            raise invalid("options must be an object")
        if not isinstance(self.execution_context, ExecutionContext):
            raise invalid("execution_context must be an ExecutionContext")

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
        _check_version(data["version"])
        operation = _operation(data["operation"])
        return cls(
            request_id=data["request_id"],
            operation=operation,
            component=data["component"],
            input=_INPUTS[operation].from_wire(data["input"]),
            options=dict(as_mapping(data.get("options", {}), "options")),
            execution_context=ExecutionContext.from_wire(data.get("execution_context", {})),
            version=data["version"],
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

    def __post_init__(self) -> None:
        for name in self.__slots__:
            string(getattr(self, name), name)

    def to_wire(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__slots__}

    @classmethod
    def from_wire(cls, value: Any) -> "ExecutionProvenance":
        data = as_mapping(value, "execution")
        exact_keys(data, "execution", set(cls.__slots__))
        return cls(**{name: data[name] for name in cls.__slots__})


@dataclass(frozen=True, slots=True)
class MLError:
    code: MLErrorCode
    message: str

    def __post_init__(self) -> None:
        if not isinstance(self.code, MLErrorCode):
            raise invalid("code must be an MLErrorCode")
        string(self.message, "message")

    def to_wire(self) -> dict[str, Any]:
        return {"code": self.code.value, "message": self.message}

    @classmethod
    def from_wire(cls, value: Any) -> "MLError":
        data = as_mapping(value, "error")
        exact_keys(data, "error", {"code", "message"})
        return cls(error_code(data["code"], "code"), data["message"])


@dataclass(frozen=True, slots=True)
class MLResponse:
    """Every accepted request ends as SUCCESS (with an output) or ERROR (with an error), exactly
    one of the two. A worker crash produces no response at all; the supervisor handles that."""

    request_id: str
    status: MLStatus
    operation: MLOperation  # not on the wire: the request it answers says what it was
    execution: ExecutionProvenance | None = None
    output: MLOutput | None = None
    timings: dict[str, float] = field(default_factory=dict)
    error: MLError | None = None
    version: int = PROTOCOL_VERSION

    def __post_init__(self) -> None:
        _check_version(self.version)
        string(self.request_id, "request_id")
        operation = _check_operation(self.operation)
        if not isinstance(self.status, MLStatus):
            raise invalid("status must be an MLStatus")
        if not isinstance(self.timings, dict):
            raise invalid("timings must be an object")
        for name, seconds in self.timings.items():
            string(name, "timing name")
            number(seconds, name)
        if self.execution is not None and not isinstance(self.execution, ExecutionProvenance):
            raise invalid("execution must be an ExecutionProvenance")
        if self.error is not None and not isinstance(self.error, MLError):
            raise invalid("error must be an MLError")
        if self.status is MLStatus.SUCCESS:
            if self.error is not None or self.output is None or self.execution is None:
                raise invalid("a SUCCESS response has an output and its execution, and no error")
            if not isinstance(self.output, _OUTPUTS[operation]):
                raise invalid(f"{operation} does not produce a {type(self.output).__name__}")
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
    def from_wire(cls, value: Any, request: MLRequest) -> "MLResponse":
        """Read the answer to `request`. The wire format does not repeat the operation, so it
        comes from the request, which must also be the one named by `request_id`; a successful
        output may only refer to images and faces that request contained."""
        data = as_mapping(value, "response")
        exact_keys(
            data,
            "response",
            {"version", "request_id", "status"},
            frozenset({"output", "execution", "timings", "error"}),
        )
        _check_version(data["version"])
        status_name = string(data["status"], "status")
        try:
            status = MLStatus(status_name)
        except ValueError:
            raise invalid(f"unknown status {status_name!r}") from None
        output = data.get("output")
        execution = data.get("execution")
        error = data.get("error")
        response = cls(
            request_id=data["request_id"],
            operation=request.operation,
            status=status,
            output=None if output is None else _OUTPUTS[request.operation].from_wire(output),
            execution=None if execution is None else ExecutionProvenance.from_wire(execution),
            timings=dict(as_mapping(data.get("timings", {}), "timings")),
            error=None if error is None else MLError.from_wire(error),
            version=data["version"],
        )
        response.check_answers(request)
        return response

    def check_answers(self, request: MLRequest) -> None:
        """This response answers `request`, and a successful output refers only to what the
        request contained: every index is an image it sent, and every representation is for a
        face it asked about."""
        if self.request_id != request.request_id or self.operation is not request.operation:
            raise invalid("the response answers a different request")
        if self.output is None:
            return
        if isinstance(self.output, DetectFacesOutput):
            images = len(request.input.images)
            for detection in self.output.detections:
                if detection.input_index >= images:
                    raise invalid(f"a detection refers to image {detection.input_index}")
        else:  # (the operation is the request's, so its input carries the faces)
            asked = {
                (f.input_index, f.face_index)
                for f in cast(GenerateRepresentationsInput, request.input).faces
            }
            for result in self.output.representations:
                if (result.input_index, result.face_index) not in asked:
                    raise invalid("a representation is for a face that was not requested")


def error_wire(request_id: str, code: MLErrorCode, message: str) -> dict[str, Any]:
    """An ERROR response as it goes on the wire, for a request that may not even have parsed (so
    that its operation is unknown): the answer must still carry the request's id."""
    return {
        "version": PROTOCOL_VERSION,
        "request_id": string(request_id, "request_id"),
        "status": MLStatus.ERROR.value,
        "output": None,
        "execution": None,
        "timings": {},
        "error": MLError(code, message).to_wire(),
    }
