"""TST-033: the ML worker IPC contract (API and Contracts.md sections 35-50).

Messages are plain dicts. Every message round-trips unchanged, every malformed one is refused with
the spec's error code, and the request/response invariants (exactly one of output and error, zero
faces is a success) hold.
"""

import json
from typing import Any

import pytest

from backend.ml.contracts.control import frame, hello, parse_frame
from backend.ml.contracts.messages import (
    DetectFacesInput,
    DetectFacesOutput,
    Detection,
    ExecutionContext,
    ExecutionProvenance,
    FaceGeometry,
    GenerateRepresentationsInput,
    GenerateRepresentationsOutput,
    MLError,
    MLRequest,
    MLResponse,
    RepresentationResult,
)
from backend.ml.contracts.protocol import (
    PROTOCOL_VERSION,
    ContractError,
    ControlType,
    MLErrorCode,
    MLOperation,
    MLStatus,
)
from backend.ml.contracts.shared_memory import SharedMemoryDescriptor, describe

IMAGE = describe("img-0", "uint8", (480, 640, 3), readonly=True)
EMBEDDING = describe("emb-0", "float32", (512,), readonly=True)
PROVENANCE = ExecutionProvenance("cv-1", "rv-1", "CUDAExecutionProvider", "cuda:0")


def detect_request(**changes: Any) -> MLRequest:
    values: dict[str, Any] = {
        "request_id": "r-1",
        "operation": MLOperation.DETECT_FACES,
        "component": "cv-1",
        "input": DetectFacesInput((IMAGE,)),
        "options": {"max_faces": 10},
        "execution_context": ExecutionContext("job-1", "run-1", "seg-1"),
    }
    return MLRequest(**{**values, **changes})


def represent_request() -> MLRequest:
    face = FaceGeometry(0, 0, (0.1, 0.1, 0.5, 0.6), ((0.2, 0.2), (0.4, 0.2)))
    return MLRequest(
        request_id="r-2",
        operation=MLOperation.GENERATE_REPRESENTATIONS,
        component="cv-2",
        input=GenerateRepresentationsInput((IMAGE,), (face,)),
    )


def success(output: Any, operation: MLOperation) -> MLResponse:
    return MLResponse(
        request_id="r-1",
        status=MLStatus.SUCCESS,
        operation=operation,
        execution=PROVENANCE,
        output=output,
        timings={"inference_ms": 12.5},
    )


def over_the_wire(message: dict[str, Any]) -> dict[str, Any]:
    """What a Connection delivers: the same values, shared with nobody."""
    return json.loads(json.dumps(message))  # type: ignore[no-any-return]


# --- requests ------------------------------------------------------------------------------------


@pytest.mark.parametrize("request_", [detect_request(), represent_request()])
def test_a_request_survives_the_wire_unchanged(request_: MLRequest) -> None:
    assert MLRequest.from_wire(over_the_wire(request_.to_wire())) == request_


def test_options_and_context_are_optional_on_the_wire() -> None:
    wire = detect_request().to_wire()
    del wire["options"], wire["execution_context"]

    parsed = MLRequest.from_wire(wire)

    assert parsed.options == {}
    assert parsed.execution_context == ExecutionContext()


def test_the_worker_exposes_no_application_domain_operation() -> None:
    assert {op.value for op in MLOperation} == {"DETECT_FACES", "GENERATE_REPRESENTATIONS"}
    wire = detect_request().to_wire()
    wire["operation"] = "RECOGNIZE_PERSON"

    with pytest.raises(ContractError, match="unknown operation") as raised:
        MLRequest.from_wire(wire)

    assert raised.value.code is MLErrorCode.INVALID_REQUEST


def test_an_operation_cannot_carry_the_other_operations_input() -> None:
    with pytest.raises(ContractError):
        detect_request(input=GenerateRepresentationsInput((IMAGE,), ()))


def test_a_different_protocol_version_is_refused_with_its_own_code() -> None:
    wire = detect_request().to_wire()
    wire["version"] = PROTOCOL_VERSION + 1

    with pytest.raises(ContractError) as raised:
        MLRequest.from_wire(wire)

    assert raised.value.code is MLErrorCode.UNSUPPORTED_PROTOCOL_VERSION


def break_it(path: list[str | int], value: Any) -> dict[str, Any]:
    wire = over_the_wire(represent_request().to_wire())
    target: Any = wire
    for step in path[:-1]:
        target = target[step]
    if value is _DELETE:
        del target[path[-1]]
    else:
        target[path[-1]] = value
    return wire


_DELETE = object()


@pytest.mark.parametrize(
    ("path", "value", "code"),
    [
        (["request_id"], "", MLErrorCode.INVALID_REQUEST),
        (["request_id"], 7, MLErrorCode.INVALID_REQUEST),
        (["component"], _DELETE, MLErrorCode.INVALID_REQUEST),
        (["surprise"], 1, MLErrorCode.INVALID_REQUEST),
        (["version"], True, MLErrorCode.INVALID_REQUEST),
        (["version"], "1", MLErrorCode.INVALID_REQUEST),
        (["input", "faces", 0, "box"], [0.5, 0.1, 0.1, 0.6], MLErrorCode.INVALID_REQUEST),
        (["input", "faces", 0, "box"], [0.1, 0.1, 1.5, 0.6], MLErrorCode.INVALID_REQUEST),
        (["input", "faces", 0, "box"], [0.3, 0.1, 0.3, 0.6], MLErrorCode.INVALID_REQUEST),
        (["input", "faces", 0, "box"], [0.1, 0.4, 0.5, 0.4], MLErrorCode.INVALID_REQUEST),
        (["input", "faces", 0, "box"], [0.1, 0.1, 0.5], MLErrorCode.INVALID_REQUEST),
        (["input", "faces", 0, "box"], [0.1, 0.1, 0.5, float("nan")], MLErrorCode.INVALID_REQUEST),
        (["input", "faces", 0, "box"], [0.1, 0.1, 0.5, True], MLErrorCode.INVALID_REQUEST),
        (["input", "faces", 0, "landmarks"], [[0.1]], MLErrorCode.INVALID_REQUEST),
        (["input", "faces", 0, "landmarks"], [[0.1, 2.0]], MLErrorCode.INVALID_REQUEST),
        (["input", "faces", 0, "input_index"], 1, MLErrorCode.INVALID_REQUEST),
        (["input", "faces", 0, "input_index"], -1, MLErrorCode.INVALID_REQUEST),
        (["input", "faces", 0, "face_index"], "0", MLErrorCode.INVALID_REQUEST),
        (["input", "images"], [], MLErrorCode.INVALID_REQUEST),
        (["input", "images"], "img", MLErrorCode.INVALID_REQUEST),
        (["input", "images", 0, "dtype"], "float32", MLErrorCode.SHARED_MEMORY_INVALID),
        (["input", "images", 0, "shape"], [480, 640], MLErrorCode.SHARED_MEMORY_INVALID),
        (["input"], 5, MLErrorCode.INVALID_REQUEST),
        (["options"], [], MLErrorCode.INVALID_REQUEST),
        (["execution_context", "job_id"], 5, MLErrorCode.INVALID_REQUEST),
        (["execution_context", "extra"], "x", MLErrorCode.INVALID_REQUEST),
    ],
)
def test_a_malformed_request_is_refused_with_the_right_code(
    path: list[str | int], value: Any, code: MLErrorCode
) -> None:
    with pytest.raises(ContractError) as raised:
        MLRequest.from_wire(break_it(path, value))

    assert raised.value.code is code


def test_a_request_must_be_an_object() -> None:
    with pytest.raises(ContractError):
        MLRequest.from_wire(["not", "an", "object"])


def test_a_detection_request_needs_at_least_one_image() -> None:
    wire = detect_request().to_wire()
    wire["input"]["images"] = []

    with pytest.raises(ContractError, match="at least one image"):
        MLRequest.from_wire(wire)


def test_an_image_must_be_three_channel_uint8() -> None:
    gray = describe("g", "uint8", (480, 640, 1), readonly=True)
    wire = detect_request(input=DetectFacesInput((gray,))).to_wire()

    with pytest.raises(ContractError) as raised:
        MLRequest.from_wire(wire)

    assert raised.value.code is MLErrorCode.INVALID_INPUT


# --- responses -----------------------------------------------------------------------------------


def test_zero_detected_faces_is_a_successful_response() -> None:
    response = success(DetectFacesOutput(()), MLOperation.DETECT_FACES)

    parsed = MLResponse.from_wire(over_the_wire(response.to_wire()), MLOperation.DETECT_FACES)

    assert parsed == response
    assert parsed.status is MLStatus.SUCCESS
    assert parsed.output == DetectFacesOutput(())


def test_detections_and_representations_survive_the_wire() -> None:
    detections = DetectFacesOutput(
        (
            Detection(0, 0, (0.1, 0.1, 0.5, 0.6), 0.98, ((0.2, 0.2),)),
            Detection(0, 1, (0.6, 0.1, 0.9, 0.5), 0.7),
        )
    )
    representations = GenerateRepresentationsOutput(
        (RepresentationResult(0, 0, 512, "float32", "l2", EMBEDDING),)
    )

    for output, operation in (
        (detections, MLOperation.DETECT_FACES),
        (representations, MLOperation.GENERATE_REPRESENTATIONS),
    ):
        response = success(output, operation)
        assert MLResponse.from_wire(over_the_wire(response.to_wire()), operation) == response


def test_the_embedding_dimension_is_not_assumed_to_be_512() -> None:
    small = describe("emb-1", "float32", (128,), readonly=True)

    result = RepresentationResult(0, 0, 128, "float32", "l2", small)

    assert result.dimension == 128


def test_an_embedding_segment_must_match_the_stated_dimension_and_dtype() -> None:
    with pytest.raises(ContractError) as raised:
        RepresentationResult(0, 0, 256, "float32", "l2", EMBEDDING)
    assert raised.value.code is MLErrorCode.SHARED_MEMORY_INVALID
    with pytest.raises(ContractError):
        RepresentationResult(0, 0, 512, "float64", "l2", EMBEDDING)


def test_an_error_response_carries_an_error_code_and_no_output() -> None:
    response = MLResponse(
        request_id="r-1",
        status=MLStatus.ERROR,
        operation=MLOperation.DETECT_FACES,
        error=MLError(MLErrorCode.OUT_OF_MEMORY, "no room for the model"),
    )

    parsed = MLResponse.from_wire(over_the_wire(response.to_wire()), MLOperation.DETECT_FACES)

    assert parsed == response
    assert parsed.output is None
    assert parsed.error is not None
    assert parsed.error.code is MLErrorCode.OUT_OF_MEMORY


def test_a_response_is_exactly_one_of_output_and_error() -> None:
    output = DetectFacesOutput(())
    error = MLError(MLErrorCode.INFERENCE_FAILED, "boom")
    cases: list[dict[str, Any]] = [
        {"status": MLStatus.SUCCESS},  # no output
        {"status": MLStatus.SUCCESS, "output": output},  # no execution
        {"status": MLStatus.SUCCESS, "output": output, "execution": PROVENANCE, "error": error},
        {"status": MLStatus.ERROR},  # no error
        {"status": MLStatus.ERROR, "error": error, "output": output},
    ]
    for case in cases:
        with pytest.raises(ContractError):
            MLResponse(request_id="r", operation=MLOperation.DETECT_FACES, **case)


def test_an_output_must_belong_to_the_operation() -> None:
    with pytest.raises(ContractError):
        success(GenerateRepresentationsOutput(()), MLOperation.DETECT_FACES)


def test_a_response_is_checked_against_the_operation_that_was_asked_for() -> None:
    wire = success(DetectFacesOutput(()), MLOperation.DETECT_FACES).to_wire()
    wire["output"] = {"representations": []}

    with pytest.raises(ContractError):
        MLResponse.from_wire(wire, MLOperation.DETECT_FACES)


def broken_response(**changes: Any) -> dict[str, Any]:
    wire = over_the_wire(success(DetectFacesOutput(()), MLOperation.DETECT_FACES).to_wire())
    wire.update(changes)
    return wire


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "MAYBE"},
        {"status": 3},
        {"version": 99},
        {"request_id": ""},
        {"timings": {"inference_ms": "slow"}},
        {"timings": {"inference_ms": float("inf")}},
        {"timings": []},
        {"execution": {"component_version_id": "cv-1"}},
        {"execution": {**PROVENANCE.to_wire(), "device": ""}},
        {"error": {"code": "NOT_A_CODE", "message": "x"}},
        {"error": {"code": "INFERENCE_FAILED"}},
        {"unexpected": 1},
    ],
)
def test_a_malformed_response_is_refused(changes: dict[str, Any]) -> None:
    with pytest.raises(ContractError):
        MLResponse.from_wire(broken_response(**changes), MLOperation.DETECT_FACES)


def test_every_spec_error_code_exists() -> None:
    assert {code.value for code in MLErrorCode} == {
        "INVALID_REQUEST",
        "UNSUPPORTED_PROTOCOL_VERSION",
        "COMPONENT_NOT_AVAILABLE",
        "COMPONENT_LOAD_FAILED",
        "RUNTIME_VARIANT_NOT_AVAILABLE",
        "RUNTIME_INITIALIZATION_FAILED",
        "INVALID_INPUT",
        "INFERENCE_FAILED",
        "OUT_OF_MEMORY",
        "SHARED_MEMORY_UNAVAILABLE",
        "SHARED_MEMORY_INVALID",
        "INTERNAL_WORKER_ERROR",
    }


# --- shared-memory descriptors -------------------------------------------------------------------


def test_a_descriptor_survives_the_wire() -> None:
    assert SharedMemoryDescriptor.from_wire(over_the_wire(IMAGE.to_wire())) == IMAGE


def test_a_real_segment_may_be_larger_than_its_array() -> None:
    padded = describe("img", "uint8", (4, 4, 3), readonly=False, size_bytes=4096)

    assert padded.size_bytes == 4096


@pytest.mark.parametrize(
    "changes",
    [
        {"name": ""},
        {"dtype": "complex128"},
        {"layout": "F"},
        {"shape": []},
        {"shape": [0, 4, 3], "strides": [12, 3, 1]},
        {"shape": [-1, 4, 3]},
        {"strides": [1, 1, 1]},  # not the contiguous strides of the shape
        {"strides": [12, 3]},
        {"size_bytes": 10},  # the shape does not fit
        {"size_bytes": 0},
        {"readonly": "yes"},
        {"extra": 1},
    ],
)
def test_a_corrupt_descriptor_is_refused_before_anything_is_read(changes: dict[str, Any]) -> None:
    wire = over_the_wire(describe("img", "uint8", (4, 4, 3), readonly=True).to_wire())
    wire.update(changes)

    with pytest.raises(ContractError) as raised:
        SharedMemoryDescriptor.from_wire(wire)

    assert raised.value.code is MLErrorCode.SHARED_MEMORY_INVALID


def test_a_descriptor_is_checked_even_when_built_in_process() -> None:
    SharedMemoryDescriptor("x", 100, "uint8", (10, 10), (10, 1), "C", True)  # fits exactly

    with pytest.raises(ContractError) as raised:
        SharedMemoryDescriptor("x", 99, "uint8", (10, 10), (10, 1), "C", True)

    assert raised.value.code is MLErrorCode.SHARED_MEMORY_INVALID
    with pytest.raises(ContractError, match="at least 1"):
        SharedMemoryDescriptor("x", 100, "uint8", (0, 10), (10, 1), "C", True)
    with pytest.raises(ContractError, match="at least 1"):
        SharedMemoryDescriptor("x", 100, "uint8", (), (), "C", True)
    with pytest.raises(ContractError, match="needs a name"):
        SharedMemoryDescriptor("", 100, "uint8", (10, 10), (10, 1), "C", True)


def test_a_descriptor_must_be_an_object() -> None:
    with pytest.raises(ContractError) as raised:
        SharedMemoryDescriptor.from_wire("seg")

    assert raised.value.code is MLErrorCode.SHARED_MEMORY_INVALID


# --- control frames ------------------------------------------------------------------------------


def test_the_handshake_frames_are_well_formed() -> None:
    kind, body = parse_frame(hello("worker-7", ["DETECT_FACES", "GENERATE_REPRESENTATIONS"]))

    assert kind is ControlType.HELLO
    assert body["worker_instance_id"] == "worker-7"
    assert parse_frame(frame(ControlType.INITIALIZE, protocol_version=PROTOCOL_VERSION))[0] is (
        ControlType.INITIALIZE
    )
    assert parse_frame(frame(ControlType.READY))[0] is ControlType.READY


def test_the_whole_protocol_is_ten_frame_types() -> None:
    assert [c.value for c in ControlType] == [
        "HELLO",
        "INITIALIZE",
        "READY",
        "EXECUTE",
        "RESPONSE",
        "RELEASE_OUTPUT",
        "PING",
        "PONG",
        "SHUTDOWN",
        "SHUTDOWN_ACK",
    ]


def test_execute_response_release_ping_and_shutdown_frames_round_trip() -> None:
    wire = detect_request().to_wire()
    frames = [
        frame(ControlType.EXECUTE, request=wire),
        frame(
            ControlType.RESPONSE,
            response=success(DetectFacesOutput(()), MLOperation.DETECT_FACES).to_wire(),
        ),
        frame(ControlType.RELEASE_OUTPUT, request_id="r-1"),
        frame(ControlType.PING, nonce="n-1"),
        frame(ControlType.PONG, nonce="n-1"),
        frame(ControlType.SHUTDOWN),
        frame(ControlType.SHUTDOWN_ACK),
    ]

    kinds = [parse_frame(over_the_wire(f))[0] for f in frames]

    assert kinds == [
        ControlType.EXECUTE,
        ControlType.RESPONSE,
        ControlType.RELEASE_OUTPUT,
        ControlType.PING,
        ControlType.PONG,
        ControlType.SHUTDOWN,
        ControlType.SHUTDOWN_ACK,
    ]
    assert MLRequest.from_wire(parse_frame(frames[0])[1]["request"]) == detect_request()


@pytest.mark.parametrize(
    "message",
    [
        "HELLO",
        {},
        {"type": "NOPE"},
        {"type": 5},
        {"type": "READY", "extra": 1},
        {"type": "PING"},
        {"type": "PING", "nonce": ""},
        {"type": "RELEASE_OUTPUT", "request_id": 4},
        {
            "type": "HELLO",
            "protocol_version": PROTOCOL_VERSION,
            "worker_instance_id": "",
            "capabilities": [],
        },
        {
            "type": "HELLO",
            "protocol_version": PROTOCOL_VERSION,
            "worker_instance_id": "w",
            "capabilities": ["", "x"],
        },
        {
            "type": "HELLO",
            "protocol_version": PROTOCOL_VERSION,
            "worker_instance_id": "w",
            "capabilities": "x",
        },
        {"type": "INITIALIZE", "protocol_version": "1"},
    ],
)
def test_a_malformed_frame_is_refused(message: Any) -> None:
    with pytest.raises(ContractError):
        parse_frame(message)


def test_a_handshake_at_another_protocol_version_is_refused_with_its_own_code() -> None:
    for kind, extra in (
        (ControlType.INITIALIZE, {}),
        (ControlType.HELLO, {"worker_instance_id": "w", "capabilities": []}),
    ):
        with pytest.raises(ContractError) as raised:
            parse_frame({"type": kind.value, "protocol_version": PROTOCOL_VERSION + 1, **extra})

        assert raised.value.code is MLErrorCode.UNSUPPORTED_PROTOCOL_VERSION
