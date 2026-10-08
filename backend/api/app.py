"""Loopback-sidecar API bootstrap and per-launch local-process authentication (SEC-003).

The Tauri host owns token generation and supplies the secret only while starting the sidecar.
This module accepts an already-created token, keeps it in memory, and never includes it in a
response, a URL, or an application log.  Binding to loopback is enforced by the sidecar launcher,
not by an ASGI application object.
"""

import asyncio
import base64
import binascii
import hmac
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from typing import Any, Final

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.websockets import WebSocketDisconnected

from backend.api.errors import error_response, install_error_handlers
from backend.api.events import EventHub, Subscription

_TOKEN_BYTES: Final = 32
_AUTH_SCHEME: Final = "Bearer"
_WEBSOCKET_TOKEN_PREFIX: Final = "fi."
WEBSOCKET_PROTOCOL: Final = "faceidentify.v1"


class LaunchTokenError(ValueError):
    """The trusted host did not supply one canonical 256-bit launch capability."""


@dataclass(frozen=True)
class BackendReadiness:
    """The startup projection `/readiness` exposes: the lifecycle state and, once known, the state
    of each capability (Architecture section 22)."""

    state: str
    capabilities: Mapping[str, str] = field(default_factory=dict)
    # Why startup failed: an exception class name only, never a path or the launch capability.
    failure: str | None = None
    # Packages the library's own vectors need that are not installed here ("key version"); empty
    # when none. A different package never stands in for them (issue 80).
    missing_dependencies: tuple[str, ...] = ()


def operation_id(route: APIRoute) -> str:
    return route.name


def validate_launch_token(token: str) -> str:
    """Accept only an unpadded, URL-safe encoding of exactly 256 random bits.

    The comparison later uses the canonical text representation. Rejecting alternate padding or
    encodings avoids treating multiple strings as the same launch capability.
    """
    if not isinstance(token, str):
        raise LaunchTokenError("the launch token must be text")
    try:
        encoded = token.encode("ascii")
        decoded = base64.urlsafe_b64decode(encoded + b"=" * (-len(encoded) % 4))
    except (UnicodeEncodeError, binascii.Error) as error:
        raise LaunchTokenError("the launch token is not URL-safe base64") from error
    if len(decoded) != _TOKEN_BYTES:
        raise LaunchTokenError("the launch token is not 256 bits")
    if base64.urlsafe_b64encode(decoded).rstrip(b"=") != encoded:
        raise LaunchTokenError("the launch token is not canonical")
    return token


def create_app(
    launch_token: str,
    *,
    readiness: Callable[[], BackendReadiness] | None = None,
    lifespan: Callable[[FastAPI], AbstractAsyncContextManager[None]] | None = None,
    events: EventHub | None = None,
) -> FastAPI:
    """Build an in-memory-only authenticated sidecar application.

    The caller must bind its server to loopback. Every HTTP request, including health/readiness,
    requires this launch's Bearer capability. WebSocket clients offer the same capability as a
    protocol value and, after validation, receive only the stable application protocol.
    """
    expected = validate_launch_token(launch_token)
    read = readiness if readiness is not None else lambda: BackendReadiness("READY")
    app = FastAPI(
        title="FaceIdentify local API",
        version="1.0",
        lifespan=lifespan,
        generate_unique_id_function=operation_id,  # the function name: a readable generated client
    )
    install_error_handlers(app)

    @app.middleware("http")
    async def require_launch_capability(
        request: Request, call_next: Callable[[Request], Awaitable[object]]
    ) -> object:
        if not _http_authorized(request.headers.get("authorization"), expected):
            return _unauthorized()
        return await call_next(request)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readiness")
    async def readiness_status() -> dict[str, Any]:
        current = read()
        body: dict[str, Any] = {"state": current.state}
        if current.capabilities:
            body["capabilities"] = dict(current.capabilities)
        if current.failure is not None:
            body["failure"] = current.failure
        if current.missing_dependencies:
            body["missing_dependencies"] = list(current.missing_dependencies)
        return body

    @app.websocket("/api/v1/events")
    async def event_stream(websocket: WebSocket) -> None:
        if not _websocket_authorized(websocket.headers.get("sec-websocket-protocol"), expected):
            await websocket.close(code=1008)
            return
        await websocket.accept(subprotocol=WEBSOCKET_PROTOCOL)
        if events is None:
            await _until_disconnected(websocket)
            return
        subscription = events.subscribe()  # before the greeting: nothing published after it is lost
        tasks: list[asyncio.Task[None]] = []
        try:
            await websocket.send_json(events.hello(subscription.baseline))
            tasks = [
                asyncio.create_task(_forward(websocket, subscription)),
                asyncio.create_task(_until_disconnected(websocket)),
            ]
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        except (WebSocketDisconnect, WebSocketDisconnected, RuntimeError):
            pass  # the client went away while the greeting was being sent
        finally:
            events.unsubscribe(subscription)
            for task in tasks:
                task.cancel()
            # Whichever ended first may have ended with the disconnect: that is not an error.
            await asyncio.gather(*tasks, return_exceptions=True)

    return app


async def _until_disconnected(websocket: WebSocket) -> None:
    """Read and ignore what the client sends (it never commands over this connection)."""
    try:
        while True:
            await websocket.receive()
    except (WebSocketDisconnect, WebSocketDisconnected):
        return


async def _forward(websocket: WebSocket, subscription: Subscription) -> None:
    """Send each published event to this client, in the order it was offered."""
    while True:
        await websocket.send_json(await subscription.queue.get())


def _http_authorized(value: str | None, expected: str) -> bool:
    if value is None:
        return False
    scheme, separator, candidate = value.partition(" ")
    return (
        separator == " "
        and scheme == _AUTH_SCHEME
        and _constant_time_capability_matches(candidate, expected)
    )


def _websocket_authorized(value: str | None, expected: str) -> bool:
    if value is None:
        return False
    offered = {part.strip() for part in value.split(",")}
    return WEBSOCKET_PROTOCOL in offered and any(
        _constant_time_capability_matches(protocol.removeprefix(_WEBSOCKET_TOKEN_PREFIX), expected)
        for protocol in offered
        if protocol.startswith(_WEBSOCKET_TOKEN_PREFIX)
    )


def _constant_time_capability_matches(candidate: str, expected: str) -> bool:
    """Reject hostile header text before calling the byte-oriented constant-time primitive."""
    try:
        return hmac.compare_digest(candidate.encode("ascii"), expected.encode("ascii"))
    except UnicodeEncodeError:
        return False


def _unauthorized() -> JSONResponse:
    return error_response(
        401, "UNAUTHORIZED", "unauthorized", headers={"WWW-Authenticate": _AUTH_SCHEME}
    )
