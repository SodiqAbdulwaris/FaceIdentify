"""The ML worker protocol vocabulary (API and Contracts.md sections 35-50).

Messages cross `multiprocessing.Connection` as plain dicts of JSON-compatible values, so the
contract is explicit and testable and does not depend on pickling our classes. Anything
malformed is a `ContractError` carrying one of the spec's error codes.
"""

from enum import StrEnum

PROTOCOL_VERSION = 1


class MLOperation(StrEnum):
    DETECT_FACES = "DETECT_FACES"
    GENERATE_REPRESENTATIONS = "GENERATE_REPRESENTATIONS"


class MLStatus(StrEnum):
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"


class MLErrorCode(StrEnum):
    INVALID_REQUEST = "INVALID_REQUEST"
    UNSUPPORTED_PROTOCOL_VERSION = "UNSUPPORTED_PROTOCOL_VERSION"
    COMPONENT_NOT_AVAILABLE = "COMPONENT_NOT_AVAILABLE"
    COMPONENT_LOAD_FAILED = "COMPONENT_LOAD_FAILED"
    RUNTIME_VARIANT_NOT_AVAILABLE = "RUNTIME_VARIANT_NOT_AVAILABLE"
    RUNTIME_INITIALIZATION_FAILED = "RUNTIME_INITIALIZATION_FAILED"
    INVALID_INPUT = "INVALID_INPUT"
    INFERENCE_FAILED = "INFERENCE_FAILED"
    OUT_OF_MEMORY = "OUT_OF_MEMORY"
    SHARED_MEMORY_UNAVAILABLE = "SHARED_MEMORY_UNAVAILABLE"
    SHARED_MEMORY_INVALID = "SHARED_MEMORY_INVALID"
    INTERNAL_WORKER_ERROR = "INTERNAL_WORKER_ERROR"


class WorkerState(StrEnum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    READY = "READY"
    BUSY = "BUSY"
    STOPPING = "STOPPING"
    UNAVAILABLE = "UNAVAILABLE"
    FAILED = "FAILED"


class ControlType(StrEnum):
    HELLO = "HELLO"
    INITIALIZE = "INITIALIZE"
    READY = "READY"
    EXECUTE = "EXECUTE"
    RESPONSE = "RESPONSE"
    RELEASE_OUTPUT = "RELEASE_OUTPUT"
    PING = "PING"
    PONG = "PONG"
    SHUTDOWN = "SHUTDOWN"
    SHUTDOWN_ACK = "SHUTDOWN_ACK"


class ContractError(ValueError):
    """A message that does not satisfy the contract. `code` is what a worker would answer with."""

    def __init__(self, code: MLErrorCode, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def invalid(message: str) -> ContractError:
    return ContractError(MLErrorCode.INVALID_REQUEST, message)
