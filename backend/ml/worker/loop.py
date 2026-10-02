"""The ML worker's message loop (API and Contracts.md sections 35, 43 and 47 to 50).

One persistent worker process owns the loaded models and has no database. This loop is the whole of
its protocol: say HELLO, wait for INITIALIZE, answer READY, then serve EXECUTE, RELEASE_OUTPUT and
PING until told to SHUTDOWN or until the parent goes away.

Every request that reaches the worker ends as exactly one response, SUCCESS or ERROR with one of
the spec's codes; a bad request, a handler that fails and a missing handler are all answered, never
dropped, and none of them stops the worker. Only a worker or process failure produces no response,
and that is the supervisor's concern.

Memory: the worker creates the segments that carry results out and keeps them until RELEASE_OUTPUT
for that request (the creator owns the lifetime). It releases whatever it still owns when it
leaves, however it leaves, and a parent that has gone is noticed as a closed connection.

The handlers (detector, embedder) are passed in: this module knows nothing of any model.
"""

import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from multiprocessing.connection import Connection
from typing import Any

from backend.infrastructure.resources.shared_memory import SegmentLedger
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


class WorkerError(Exception):
    """A failure a handler wants reported with a specific code."""

    def __init__(self, code: MLErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
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


class ProtocolViolation(Exception):
    """The peer sent something the protocol does not allow at this point: the worker leaves."""


def _handshake(connection: Connection, capabilities: list[str], instance_id: str) -> None:
    connection.send(hello(instance_id, capabilities))
    kind, _body = parse_frame(connection.recv())
    if kind is not ControlType.INITIALIZE:
        raise ProtocolViolation(f"expected INITIALIZE, got {kind}")
    connection.send(frame(ControlType.READY))


def _error_code_for(error: BaseException) -> tuple[MLErrorCode, str]:
    """The spec's code for a failure inside a handler, and a message that is never empty."""
    if isinstance(error, WorkerError | ContractError):
        return error.code, error.message or error.code.value
    if isinstance(error, MemoryError):
        return MLErrorCode.OUT_OF_MEMORY, "out of memory"
    return MLErrorCode.INFERENCE_FAILED, f"{type(error).__name__}: {error}"


def serve(
    connection: Connection,
    handlers: Mapping[MLOperation, Handler],
    *,
    instance_id: str,
    new_id: Callable[[], uuid.UUID],
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """Run the protocol on `connection` until shutdown, parent loss or a protocol violation.
    Everything this worker still owns is released on the way out."""
    try:
        _handshake(connection, sorted(op.value for op in handlers), instance_id)
    except (EOFError, OSError, ContractError, ProtocolViolation):
        return
    ledger = SegmentLedger(new_id=new_id)
    outputs: dict[str, list[str]] = {}  # request id -> the segments made for its result
    try:
        while True:
            try:
                message = connection.recv()
            except (EOFError, OSError):
                return  # the parent is gone
            try:
                kind, body = parse_frame(message)
            except ContractError:
                return  # a stream we cannot follow is one we must not guess at
            if kind is ControlType.SHUTDOWN:
                connection.send(frame(ControlType.SHUTDOWN_ACK))
                return
            if kind is ControlType.PING:
                connection.send(frame(ControlType.PONG, nonce=body["nonce"]))
            elif kind is ControlType.RELEASE_OUTPUT:
                for name in outputs.pop(body["request_id"], []):
                    ledger.release(name)
            elif kind is ControlType.EXECUTE:
                connection.send(
                    frame(
                        ControlType.RESPONSE,
                        response=_execute(body["request"], handlers, ledger, outputs, clock),
                    )
                )
            else:
                return  # HELLO, READY, RESPONSE...: not something a parent sends now
    finally:
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
    started = clock()
    try:
        result = handler(request, HandlerContext(ledger))
        response = MLResponse(
            request_id=request.request_id,
            status=MLStatus.SUCCESS,
            operation=request.operation,
            execution=result.execution,
            output=result.output,
            timings={"handler_seconds": clock() - started},
        )
    except Exception as error:
        # A failed request leaves nothing behind: whatever it created is released at once.
        for name in set(ledger.names) - before:
            ledger.release(name)
        code, message = _error_code_for(error)
        return error_wire(request.request_id, code, message)
    outputs.setdefault(request.request_id, []).extend(sorted(set(ledger.names) - before))
    return response.to_wire()


def _request_id(payload: Any) -> str:
    """The id to answer a request under, even one that does not parse."""
    if isinstance(payload, dict):
        candidate = payload.get("request_id")
        if isinstance(candidate, str) and candidate:
            return candidate
    return "unknown"
