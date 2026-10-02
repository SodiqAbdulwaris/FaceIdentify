"""The ML worker's message loop (API and Contracts.md sections 35, 43 and 47 to 50).

One persistent worker process owns the loaded models and has no database. This loop is the whole of
its protocol: say HELLO, wait for INITIALIZE, answer READY, then serve EXECUTE, RELEASE_OUTPUT and
PING until told to SHUTDOWN or until the parent goes away.

Every request that reaches the worker ends as exactly one response, SUCCESS or ERROR with one of
the spec's codes; a bad request, a handler that fails and a missing handler are all answered, never
dropped, and none of them stops the worker. Answering is total: whatever a handler does, including
failing in a way that cannot be described, ends in a response. Only a worker or process failure
produces no response, and that is the supervisor's concern.

Memory: the worker creates the segments that carry results out and keeps them until RELEASE_OUTPUT
for that request (the creator owns the lifetime). It releases whatever it still owns when it
leaves, however it leaves, and a parent that has gone is noticed as a closed connection (on a read
or on a write, both end the worker quietly). A segment a handler left a view open on cannot be
released; it is left to the operating system when the process ends.

The loop never gives up waiting for INITIALIZE or a frame by itself: the supervisor owns every
timeout (section 50) and ends a worker that does not answer. Every way of leaving says why on
`log`, because from outside a closed pipe is all anyone sees.

The handlers (detector, embedder) are passed in: this module knows nothing of any model.
"""

import sys
import time
import uuid
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Protocol

from backend.infrastructure.resources.shared_memory import SegmentInUseError, SegmentLedger
from backend.ml.contracts.control import frame, hello, parse_frame
from backend.ml.contracts.messages import (
    ExecutionProvenance,
    MLOutput,
    MLRequest,
    MLResponse,
    error_wire,
)
from backend.ml.contracts.protocol import (
    ContractError,
    ControlType,
    MLErrorCode,
    MLOperation,
    MLStatus,
)

MAX_MESSAGE = 500  # characters of a failure's text that go on the wire


class WorkerError(Exception):
    """A failure a handler wants reported with a specific code."""

    def __init__(self, code: MLErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = MLErrorCode(code)  # (a code that is not one is refused where it is raised)
        self.message = message


@dataclass(frozen=True, slots=True)
class HandlerResult:
    output: MLOutput
    execution: ExecutionProvenance


@dataclass(frozen=True, slots=True)
class HandlerContext:
    """What a handler may use besides the request: the ledger it creates result segments in."""

    ledger: SegmentLedger


Handler = Callable[[MLRequest, HandlerContext], HandlerResult]


class Channel(Protocol):
    """The two things the loop needs of a connection (a `multiprocessing` Connection is one; its
    class differs between Windows and POSIX)."""

    def send(self, obj: Any, /) -> None: ...

    def recv(self) -> Any: ...


class ProtocolViolation(Exception):
    """The peer sent something the protocol does not allow at this point: the worker leaves."""


def _log_to_stderr(line: str) -> None:
    print(f"ml-worker: {line}", file=sys.stderr, flush=True)


def _handshake(connection: Channel, capabilities: list[str], instance_id: str) -> None:
    connection.send(hello(instance_id, capabilities))
    kind, _body = parse_frame(connection.recv())
    if kind is not ControlType.INITIALIZE:
        raise ProtocolViolation(f"expected INITIALIZE, got {kind}")
    connection.send(frame(ControlType.READY))


def _error_code_for(error: BaseException) -> tuple[MLErrorCode, str]:
    """The spec's code for a failure inside a handler, and a message that is never empty and
    never long."""
    if isinstance(error, WorkerError | ContractError):
        code, message = error.code, error.message or error.code.value
    elif isinstance(error, MemoryError):
        code, message = MLErrorCode.OUT_OF_MEMORY, "out of memory"
    else:
        code, message = MLErrorCode.INFERENCE_FAILED, f"{type(error).__name__}: {error}"
    return code, message[:MAX_MESSAGE]


def serve(
    connection: Channel,
    handlers: Mapping[MLOperation, Handler],
    *,
    instance_id: str,
    new_id: Callable[[], uuid.UUID],
    clock: Callable[[], float] = time.monotonic,
    log: Callable[[str], None] = _log_to_stderr,
) -> None:
    """Run the protocol on `connection` until shutdown, parent loss or a protocol violation.
    Everything this worker still owns is released on the way out."""
    try:
        _handshake(connection, sorted(op.value for op in handlers), instance_id)
    except (EOFError, OSError) as error:
        log(f"leaving: the parent went away during the handshake ({type(error).__name__})")
        return
    except (ContractError, ProtocolViolation) as error:
        log(f"leaving: the handshake was refused ({error})")
        return
    ledger = SegmentLedger(new_id=new_id)
    outputs: dict[str, list[str]] = {}  # request id -> the segments made for its result
    try:
        while True:
            message = connection.recv()
            try:
                kind, body = parse_frame(message)
            except ContractError as error:
                log(f"leaving: a frame it cannot follow ({error})")
                return
            if kind is ControlType.SHUTDOWN:
                connection.send(frame(ControlType.SHUTDOWN_ACK))
                return
            if kind is ControlType.PING:
                connection.send(frame(ControlType.PONG, nonce=body["nonce"]))
            elif kind is ControlType.RELEASE_OUTPUT:
                for name in outputs.pop(body["request_id"], []):
                    ledger.release(name)
            elif kind is ControlType.EXECUTE:
                response = _execute(body["request"], handlers, ledger, outputs, clock)
                connection.send(frame(ControlType.RESPONSE, response=response))
            else:
                log(f"leaving: a {kind} frame, which a parent does not send")
                return
    except (EOFError, OSError) as error:  # reading or writing: the parent is gone
        log(f"leaving: the connection to the parent failed ({type(error).__name__})")
    finally:
        with suppress(SegmentInUseError):  # (a leaked view: the process ending frees it)
            ledger.release_all()


def _execute(
    payload: Any,
    handlers: Mapping[MLOperation, Handler],
    ledger: SegmentLedger,
    outputs: dict[str, list[str]],
    clock: Callable[[], float],
) -> dict[str, Any]:
    """Answer one request. Never raises."""
    request_id = _request_id(payload)
    try:
        request = MLRequest.from_wire(payload)
    except ContractError as error:
        return error_wire(request_id, error.code, error.message)
    handler = handlers.get(request.operation)
    if handler is None:
        return error_wire(
            request_id, MLErrorCode.COMPONENT_NOT_AVAILABLE, f"no handler for {request.operation}"
        )
    before = set(ledger.names)
    try:
        started = clock()
        result = handler(request, HandlerContext(ledger))
        response = MLResponse(
            request_id=request.request_id,
            status=MLStatus.SUCCESS,
            operation=request.operation,
            execution=result.execution,
            output=result.output,
            timings={"handler_seconds": clock() - started},
        )
        try:
            response.check_answers(request)
        except ContractError as error:
            raise WorkerError(
                MLErrorCode.INTERNAL_WORKER_ERROR,
                f"the result does not answer the request: {error.message}",
            ) from error
        answer = response.to_wire()
    except Exception as error:
        # A failed request leaves nothing behind: whatever it created is released at once, and
        # never what other requests made.
        for name in sorted(set(ledger.names) - before):
            with suppress(SegmentInUseError):
                ledger.release(name)
        return _failure_wire(request.request_id, error)
    made = sorted(set(ledger.names) - before)
    if made:
        outputs.setdefault(request.request_id, []).extend(made)
    return answer


def _failure_wire(request_id: str, error: Exception) -> dict[str, Any]:
    try:
        code, message = _error_code_for(error)
        return error_wire(request_id, code, message)
    except Exception:  # a failure that cannot even be described is still answered
        return error_wire(
            request_id, MLErrorCode.INTERNAL_WORKER_ERROR, "the failure could not be described"
        )


def _request_id(payload: Any) -> str:
    """The id to answer a request under, even one that does not parse."""
    if isinstance(payload, dict):
        candidate = payload.get("request_id")
        if isinstance(candidate, str) and candidate:
            return candidate
    return "unknown"
