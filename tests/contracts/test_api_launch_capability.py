"""SEC-003 contract tests for the local, per-launch capability boundary."""

import base64
import secrets
from typing import Any, cast

import httpx
import pytest

from backend.api.app import (
    WEBSOCKET_PROTOCOL,
    BackendReadiness,
    LaunchTokenError,
    create_app,
    validate_launch_token,
)


def _token() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")


@pytest.mark.parametrize(
    "candidate", ["", "x" * 42, "x" * 44, "not a token", "x" * 43 + "=", cast(str, None)]
)
def test_the_api_refuses_noncanonical_or_short_launch_capabilities(candidate: str) -> None:
    with pytest.raises(LaunchTokenError):
        validate_launch_token(candidate)


async def _request(app: Any, path: str, headers: dict[str, str]) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.get(path, headers=headers)


async def _websocket_messages(app: Any, protocols: list[str] | None) -> list[dict[str, Any]]:
    messages = iter(({"type": "websocket.connect"}, {"type": "websocket.disconnect"}))
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return next(messages)

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    scope = {
        "type": "websocket",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "scheme": "ws",
        "path": "/api/v1/events",
        "raw_path": b"/api/v1/events",
        "query_string": b"",
        "headers": (
            []
            if protocols is None
            else [(b"sec-websocket-protocol", ", ".join(protocols).encode("ascii"))]
        ),
        "client": ("127.0.0.1", 1),
        "server": ("127.0.0.1", 2),
        "subprotocols": [] if protocols is None else protocols,
    }
    await app(scope, receive, send)
    return sent


async def test_every_http_route_requires_the_current_bearer_capability() -> None:
    token = _token()
    app = create_app(token)

    for headers in ({}, {"Authorization": "Bearer wrong"}, {"Authorization": f"Token {token}"}):
        response = await _request(app, "/health", headers)
        assert response.status_code == 401
        assert response.json() == {"error": {"code": "UNAUTHORIZED", "message": "unauthorized"}}
        assert response.headers["www-authenticate"] == "Bearer"

    assert (await _request(app, "/health", {"Authorization": f"Bearer {token}"})).json() == {
        "status": "ok"
    }


async def test_readiness_is_authenticated_and_uses_the_current_capability_only() -> None:
    first = _token()
    second = _token()
    app = create_app(first, readiness=lambda: BackendReadiness("DEGRADED"))

    assert (
        await _request(app, "/readiness", {"Authorization": f"Bearer {second}"})
    ).status_code == 401
    response = await _request(app, "/readiness", {"Authorization": f"Bearer {first}"})
    assert response.status_code == 200
    assert response.json() == {"state": "DEGRADED"}


async def test_websocket_requires_the_same_capability_without_echoing_it() -> None:
    token = _token()
    app = create_app(token)

    rejected = await _websocket_messages(app, [WEBSOCKET_PROTOCOL])
    assert rejected == [{"type": "websocket.close", "code": 1008, "reason": ""}]
    assert await _websocket_messages(app, None) == [
        {"type": "websocket.close", "code": 1008, "reason": ""}
    ]

    accepted = await _websocket_messages(app, [f"fi.{token}", WEBSOCKET_PROTOCOL])
    assert accepted == [
        {"type": "websocket.accept", "subprotocol": WEBSOCKET_PROTOCOL, "headers": []}
    ]
