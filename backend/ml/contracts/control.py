"""Control-plane frames (API and Contracts.md sections 47-49).

Every frame is `{"type": ..., **fields}` with the exact fields of its type. The protocol is
intentionally small: handshake, execute, release an output segment, ping, shutdown.
"""

from typing import Any

from backend.ml.contracts.protocol import (
    PROTOCOL_VERSION,
    ContractError,
    ControlType,
    MLErrorCode,
    invalid,
)
from backend.ml.contracts.wire import as_mapping, exact_keys, integer, sequence, string

_FIELDS: dict[ControlType, frozenset[str]] = {
    ControlType.HELLO: frozenset({"protocol_version", "worker_instance_id", "capabilities"}),
    ControlType.INITIALIZE: frozenset({"protocol_version"}),
    ControlType.READY: frozenset(),
    ControlType.EXECUTE: frozenset({"request"}),
    ControlType.RESPONSE: frozenset({"response"}),
    ControlType.RELEASE_OUTPUT: frozenset({"request_id"}),
    ControlType.PING: frozenset({"nonce"}),
    ControlType.PONG: frozenset({"nonce"}),
    ControlType.SHUTDOWN: frozenset(),
    ControlType.SHUTDOWN_ACK: frozenset(),
}


def frame(kind: ControlType, **fields: Any) -> dict[str, Any]:
    """Build a frame; the fields must be exactly those of its type."""
    message = {"type": kind.value, **fields}
    parse_frame(message)
    return message


def hello(worker_instance_id: str, capabilities: list[str]) -> dict[str, Any]:
    return frame(
        ControlType.HELLO,
        protocol_version=PROTOCOL_VERSION,
        worker_instance_id=worker_instance_id,
        capabilities=capabilities,
    )


def parse_frame(value: Any) -> tuple[ControlType, dict[str, Any]]:
    """Validate a frame and return its type and fields. The worker instance id is ephemeral
    diagnostic identity, nothing more. The payload of EXECUTE and RESPONSE is not looked into
    here: it is read with `MLRequest.from_wire` and `MLResponse.from_wire(wire, request)`."""
    data = as_mapping(value, "frame")
    name = string(data.get("type"), "type")
    try:
        kind = ControlType(name)
    except ValueError:
        raise invalid(f"unknown frame type {name!r}") from None
    fields = _FIELDS[kind]
    exact_keys(data, f"{kind} frame", {"type"} | set(fields))
    body = {k: data[k] for k in fields}
    if kind in (ControlType.HELLO, ControlType.INITIALIZE):
        integer(body["protocol_version"], "protocol_version")
        if body["protocol_version"] != PROTOCOL_VERSION:
            raise ContractError(
                MLErrorCode.UNSUPPORTED_PROTOCOL_VERSION,
                f"protocol version {body['protocol_version']} is not supported",
            )
    if kind is ControlType.HELLO:
        string(body["worker_instance_id"], "worker_instance_id")
        for capability in sequence(body["capabilities"], "capabilities"):
            string(capability, "capability")
    elif kind is ControlType.RELEASE_OUTPUT:
        string(body["request_id"], "request_id")
    elif kind in (ControlType.PING, ControlType.PONG):
        string(body["nonce"], "nonce")
    return kind, body
