"""The ML worker's protocol loop, run in a thread over a real pipe (API and Contracts.md 35 to 50).

Every request is answered exactly once, a failing request does not stop the worker, the worker owns
and releases the segments it creates, and it leaves cleanly on SHUTDOWN, on a parent that has gone
and on a stream it cannot follow. (The same loop in a real child process is tested with the
supervisor.)
"""

import threading
from collections.abc import Iterator
from multiprocessing import Pipe
from typing import Any

import pytest

from backend.infrastructure.resources.shared_memory import (
    AttachedSegment,
    OwnedSegment,
    SegmentLedger,
)
from backend.ml.contracts.control import frame, parse_frame
from backend.ml.contracts.messages import (
    DetectFacesInput,
    DetectFacesOutput,
    FaceGeometry,
    GenerateRepresentationsInput,
    GenerateRepresentationsOutput,
    MLRequest,
    MLResponse,
)
from backend.ml.contracts.protocol import (
    PROTOCOL_VERSION,
    ContractError,
    ControlType,
    MLErrorCode,
    MLOperation,
    MLStatus,
)
from backend.ml.contracts.shared_memory import SharedMemoryDescriptor
from backend.ml.worker.loop import Handler, serve
from tests.fixtures.deterministic import SeededUUIDs
from tests.fixtures.ml_handlers import (
    EMBEDDING_DIMENSION,
    build_detector_only,
    build_handlers,
)

WAIT = 15  # seconds a test will wait for the worker before calling it hung


def gone(descriptor: SharedMemoryDescriptor) -> bool:
    try:
        AttachedSegment(descriptor).close()
    except ContractError as error:
        return error.code is MLErrorCode.SHARED_MEMORY_UNAVAILABLE
    return False


class Worker:
    """A worker loop on a thread, and the parent's end of its pipe."""

    def __init__(self, handlers: dict[MLOperation, Handler], new_id: SeededUUIDs) -> None:
        self.pings = 0
        self.parent, child = Pipe()
        self.thread = threading.Thread(
            target=serve,
            args=(child, handlers),
            kwargs={"instance_id": "worker-1", "new_id": new_id},
            daemon=True,
        )
        self.thread.start()

    def receive(self) -> Any:
        assert self.parent.poll(WAIT), "the worker did not answer"
        return self.parent.recv()

    def handshake(self) -> dict[str, Any]:
        _kind, hello = parse_frame(self.receive())
        self.parent.send(frame(ControlType.INITIALIZE, protocol_version=PROTOCOL_VERSION))
        kind, _ = parse_frame(self.receive())
        assert kind is ControlType.READY
        return hello

    def execute(self, wire: Any) -> dict[str, Any]:
        self.parent.send(frame(ControlType.EXECUTE, request=wire))
        kind, body = parse_frame(self.receive())
        assert kind is ControlType.RESPONSE
        response: dict[str, Any] = body["response"]
        return response

    def ask(self, request: MLRequest) -> MLResponse:
        return MLResponse.from_wire(self.execute(request.to_wire()), request)

    def ping(self, nonce: str | None = None) -> None:
        self.pings += 1
        nonce = nonce or f"nonce-{self.pings}"
        self.parent.send(frame(ControlType.PING, nonce=nonce))
        kind, body = parse_frame(self.receive())
        assert kind is ControlType.PONG
        assert body["nonce"] == nonce

    def release(self, request_id: str) -> None:
        self.parent.send(frame(ControlType.RELEASE_OUTPUT, request_id=request_id))
        self.ping()  # the worker has handled the release once it answers the next frame

    def sent_after_hello(self) -> list[Any]:
        """Whatever else the worker has sent (nothing, if it left before becoming ready)."""
        sent: list[Any] = []
        try:
            while self.parent.poll(0.1):
                sent.append(self.parent.recv())
        except (EOFError, OSError):  # the worker's end is closed: nothing more can come
            pass
        return sent

    def left(self) -> bool:
        self.thread.join(WAIT)
        return not self.thread.is_alive()


@pytest.fixture
def worker(new_id: SeededUUIDs) -> Iterator[Worker]:
    started = Worker(build_handlers(), new_id)
    yield started
    started.parent.close()
    started.thread.join(WAIT)


@pytest.fixture
def ready(worker: Worker) -> Worker:
    worker.handshake()
    return worker


@pytest.fixture
def images(new_id: SeededUUIDs) -> Iterator[tuple[OwnedSegment, OwnedSegment]]:
    blank = OwnedSegment("uint8", (4, 4, 3), new_id=new_id)
    blank.write(0)
    lit = OwnedSegment("uint8", (4, 4, 3), new_id=new_id)
    lit.write(200)
    yield blank, lit
    blank.release()
    lit.release()


def detect_request(*segments: OwnedSegment, **options: Any) -> MLRequest:
    return MLRequest(
        request_id="r-1",
        operation=MLOperation.DETECT_FACES,
        component="cv-fake",
        input=DetectFacesInput(tuple(s.descriptor for s in segments)),
        options=options,
    )


def represent_request(segment: OwnedSegment, request_id: str = "r-2", **options: Any) -> MLRequest:
    return MLRequest(
        request_id=request_id,
        operation=MLOperation.GENERATE_REPRESENTATIONS,
        component="cv-fake",
        input=GenerateRepresentationsInput(
            (segment.descriptor,),
            (FaceGeometry(0, 0, (0.1, 0.1, 0.5, 0.6)), FaceGeometry(0, 1, (0.5, 0.1, 0.9, 0.6))),
        ),
        options=options,
    )


# --- the handshake -------------------------------------------------------------------------------


def test_the_worker_introduces_itself_and_becomes_ready_when_initialized(worker: Worker) -> None:
    hello = worker.handshake()

    assert hello["protocol_version"] == PROTOCOL_VERSION
    assert hello["worker_instance_id"] == "worker-1"
    assert hello["capabilities"] == ["DETECT_FACES", "GENERATE_REPRESENTATIONS"]
    worker.ping()  # and it serves


def test_a_worker_with_one_handler_says_so_in_its_capabilities(new_id: SeededUUIDs) -> None:
    detector_only = Worker(build_detector_only(), new_id)

    assert detector_only.handshake()["capabilities"] == ["DETECT_FACES"]
    detector_only.parent.close()


@pytest.mark.parametrize(
    "first",
    [
        frame(ControlType.PING, nonce="n"),  # not INITIALIZE
        {"type": "NOPE"},  # not a frame
        {"type": "INITIALIZE", "protocol_version": PROTOCOL_VERSION + 1},  # another protocol
    ],
)
def test_a_worker_that_is_not_initialized_properly_leaves(worker: Worker, first: Any) -> None:
    worker.receive()  # its HELLO
    worker.parent.send(first)

    assert worker.left()
    assert worker.sent_after_hello() == []  # and it never said READY


def test_a_worker_whose_parent_vanishes_before_initializing_leaves(worker: Worker) -> None:
    worker.receive()
    worker.parent.close()

    assert worker.left()


# --- requests ------------------------------------------------------------------------------------


def test_a_blank_image_has_no_face_and_that_is_a_success(
    ready: Worker, images: tuple[OwnedSegment, OwnedSegment]
) -> None:
    blank, _ = images

    response = ready.ask(detect_request(blank))

    assert response.status is MLStatus.SUCCESS
    assert response.output == DetectFacesOutput(())
    assert response.execution is not None
    assert response.execution.provider == "FakeProvider"
    assert response.timings["handler_seconds"] >= 0


def test_a_face_is_detected_in_the_image_that_has_one(
    ready: Worker, images: tuple[OwnedSegment, OwnedSegment]
) -> None:
    blank, lit = images

    response = ready.ask(detect_request(blank, lit))

    assert isinstance(response.output, DetectFacesOutput)
    assert [d.input_index for d in response.output.detections] == [1]


def test_representations_come_back_in_segments_the_worker_keeps_until_released(
    ready: Worker, images: tuple[OwnedSegment, OwnedSegment]
) -> None:
    _, lit = images

    response = ready.ask(represent_request(lit))

    assert isinstance(response.output, GenerateRepresentationsOutput)
    results = response.output.representations
    assert [r.face_index for r in results] == [0, 1]
    assert all(r.dimension == EMBEDDING_DIMENSION for r in results)
    with AttachedSegment(results[1].embedding) as attached:
        assert attached.copy().tolist() == [200.0, 1.0, 0.0, 1.0]
    ready.release("r-2")  # RELEASE_OUTPUT
    assert all(gone(r.embedding) for r in results)


def test_releasing_an_output_twice_or_one_that_never_existed_does_nothing(
    ready: Worker, images: tuple[OwnedSegment, OwnedSegment]
) -> None:
    _, lit = images
    response = ready.ask(represent_request(lit))
    assert isinstance(response.output, GenerateRepresentationsOutput)

    ready.release("r-2")
    ready.release("r-2")
    ready.release("never-asked")

    ready.ping()


def test_an_output_is_kept_for_one_request_not_released_with_another(
    ready: Worker, images: tuple[OwnedSegment, OwnedSegment]
) -> None:
    _, lit = images
    first = ready.ask(represent_request(lit, "first"))
    second = ready.ask(represent_request(lit, "second"))
    assert isinstance(first.output, GenerateRepresentationsOutput)
    assert isinstance(second.output, GenerateRepresentationsOutput)

    ready.release("first")

    assert all(gone(r.embedding) for r in first.output.representations)
    assert not any(gone(r.embedding) for r in second.output.representations)
    ready.release("second")


def test_a_request_that_fails_does_not_release_the_outputs_of_other_requests(
    ready: Worker, images: tuple[OwnedSegment, OwnedSegment]
) -> None:
    _, lit = images
    kept = ready.ask(represent_request(lit, "kept"))
    assert isinstance(kept.output, GenerateRepresentationsOutput)

    failed = ready.ask(represent_request(lit, "fails", mode="raise-after-output"))

    assert failed.status is MLStatus.ERROR
    assert not any(gone(r.embedding) for r in kept.output.representations)  # still there
    ready.release("kept")
    assert all(gone(r.embedding) for r in kept.output.representations)


@pytest.mark.parametrize("how", ["shutdown", "parent-gone", "garbage"])
def test_the_worker_always_releases_everything_it_owns_when_it_leaves(
    new_id: SeededUUIDs,
    images: tuple[OwnedSegment, OwnedSegment],
    monkeypatch: pytest.MonkeyPatch,
    how: str,
) -> None:
    released: list[str] = []
    real = SegmentLedger.release_all

    def spy(self: SegmentLedger) -> list[str]:
        released.extend(self.names)
        return real(self)

    monkeypatch.setattr(SegmentLedger, "release_all", spy)
    worker = Worker(build_handlers(), new_id)
    worker.handshake()
    _, lit = images
    response = worker.ask(represent_request(lit))
    assert isinstance(response.output, GenerateRepresentationsOutput)
    names = sorted(r.embedding.name for r in response.output.representations)

    if how == "shutdown":
        worker.parent.send(frame(ControlType.SHUTDOWN))
    elif how == "parent-gone":
        worker.parent.close()
    else:
        worker.parent.send("garbage")

    assert worker.left()
    assert sorted(released) == names  # the explicit release, not the garbage collector


def test_the_same_request_id_used_twice_releases_both_outputs_together(
    ready: Worker, images: tuple[OwnedSegment, OwnedSegment]
) -> None:
    _, lit = images
    first = ready.ask(represent_request(lit, "again"))
    second = ready.ask(represent_request(lit, "again"))
    assert isinstance(first.output, GenerateRepresentationsOutput)
    assert isinstance(second.output, GenerateRepresentationsOutput)

    ready.release("again")

    assert all(gone(r.embedding) for r in first.output.representations)
    assert all(gone(r.embedding) for r in second.output.representations)


@pytest.mark.parametrize(
    ("mode", "code", "message"),
    [
        ("raise", MLErrorCode.INFERENCE_FAILED, "RuntimeError: the fake model failed"),
        ("raise-silently", MLErrorCode.INFERENCE_FAILED, "RuntimeError: "),
        ("memory", MLErrorCode.OUT_OF_MEMORY, "out of memory"),
        (
            "coded",
            MLErrorCode.RUNTIME_INITIALIZATION_FAILED,
            "the provider would not start",
        ),
        ("coded-blank", MLErrorCode.INTERNAL_WORKER_ERROR, "INTERNAL_WORKER_ERROR"),
    ],
)
def test_a_handler_that_fails_is_answered_with_its_code_and_the_worker_carries_on(
    ready: Worker,
    images: tuple[OwnedSegment, OwnedSegment],
    mode: str,
    code: MLErrorCode,
    message: str,
) -> None:
    blank, _ = images

    response = ready.ask(detect_request(blank, mode=mode))

    assert response.status is MLStatus.ERROR
    assert response.output is None
    assert response.error is not None
    assert response.error.code is code
    assert response.error.message == message
    ready.ping()
    assert ready.ask(detect_request(blank)).status is MLStatus.SUCCESS  # and still works


def test_a_request_that_fails_after_making_an_output_leaves_no_segment_behind(
    ready: Worker, images: tuple[OwnedSegment, OwnedSegment], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, lit = images
    made: list[SharedMemoryDescriptor] = []
    real = OwnedSegment.write

    def remember(self: OwnedSegment, values: Any) -> None:
        made.append(self.descriptor)
        real(self, values)

    monkeypatch.setattr(OwnedSegment, "write", remember)

    response = ready.ask(represent_request(lit, mode="raise-after-output"))

    assert response.status is MLStatus.ERROR
    assert len(made) == 1
    assert gone(made[0])


def test_a_missing_input_segment_is_reported_as_such(ready: Worker, new_id: SeededUUIDs) -> None:
    vanished = OwnedSegment("uint8", (4, 4, 3), new_id=new_id)
    request = detect_request(vanished)
    vanished.release()

    response = ready.ask(request)

    assert response.error is not None
    assert response.error.code is MLErrorCode.SHARED_MEMORY_UNAVAILABLE


def test_an_operation_without_a_handler_is_not_available(
    new_id: SeededUUIDs, images: tuple[OwnedSegment, OwnedSegment]
) -> None:
    _, lit = images
    detector_only = Worker(build_detector_only(), new_id)
    detector_only.handshake()

    response = detector_only.ask(represent_request(lit))

    assert response.error is not None
    assert response.error.code is MLErrorCode.COMPONENT_NOT_AVAILABLE
    detector_only.parent.close()


# --- requests that cannot be read ----------------------------------------------------------------


def broken(request: MLRequest, **changes: Any) -> dict[str, Any]:
    wire = request.to_wire()
    wire.update(changes)
    return wire


def test_a_request_that_cannot_be_read_is_answered_under_its_own_id_with_the_right_code(
    ready: Worker, images: tuple[OwnedSegment, OwnedSegment]
) -> None:
    blank, _ = images
    good = detect_request(blank)

    cases = [
        (broken(good, operation="RECOGNIZE_PERSON"), MLErrorCode.INVALID_REQUEST),
        (broken(good, version=PROTOCOL_VERSION + 1), MLErrorCode.UNSUPPORTED_PROTOCOL_VERSION),
        (broken(good, surprise=1), MLErrorCode.INVALID_REQUEST),
    ]
    for wire, code in cases:
        answer = ready.execute(wire)

        assert answer["request_id"] == "r-1"
        assert answer["status"] == "ERROR"
        assert answer["output"] is None
        assert answer["error"]["code"] == code.value
    ready.ping()


def test_a_request_with_no_usable_id_is_answered_as_unknown(ready: Worker) -> None:
    for payload in ("not even an object", {"request_id": ""}, {"request_id": 5}, {}):
        answer = ready.execute(payload)

        assert answer["request_id"] == "unknown"
        assert answer["error"]["code"] == "INVALID_REQUEST"
    ready.ping()


# --- leaving -------------------------------------------------------------------------------------


def test_shutdown_is_acknowledged_and_releases_what_the_worker_still_owns(
    ready: Worker, images: tuple[OwnedSegment, OwnedSegment]
) -> None:
    _, lit = images
    response = ready.ask(represent_request(lit))
    assert isinstance(response.output, GenerateRepresentationsOutput)
    outputs = [r.embedding for r in response.output.representations]

    ready.parent.send(frame(ControlType.SHUTDOWN))

    kind, _ = parse_frame(ready.receive())
    assert kind is ControlType.SHUTDOWN_ACK
    assert ready.left()
    assert all(gone(d) for d in outputs)


def test_a_vanished_parent_ends_the_worker_and_frees_its_outputs(
    ready: Worker, images: tuple[OwnedSegment, OwnedSegment]
) -> None:
    _, lit = images
    response = ready.ask(represent_request(lit))
    assert isinstance(response.output, GenerateRepresentationsOutput)
    outputs = [r.embedding for r in response.output.representations]

    ready.parent.close()

    assert ready.left()
    assert all(gone(d) for d in outputs)


@pytest.mark.parametrize(
    "message",
    [
        frame(ControlType.READY),  # something a worker sends, not receives
        frame(ControlType.PONG, nonce="n"),
        {"type": "NOPE"},
        "garbage",
    ],
)
def test_a_stream_the_worker_cannot_follow_ends_it_and_frees_its_outputs(
    ready: Worker, images: tuple[OwnedSegment, OwnedSegment], message: Any
) -> None:
    _, lit = images
    response = ready.ask(represent_request(lit))
    assert isinstance(response.output, GenerateRepresentationsOutput)
    outputs = [r.embedding for r in response.output.representations]

    ready.parent.send(message)

    assert ready.left()
    assert all(gone(d) for d in outputs)
