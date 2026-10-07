"""A WebSocket client that drives an ASGI app directly (no network, no deprecated TestClient).

The app runs in a task; what the "client" sends is fed through a queue and what the server sends
is read from another, so a test can wait for exactly the next event.
"""

import asyncio
import json
from types import TracebackType
from typing import Any, Self

from backend.api.app import WEBSOCKET_PROTOCOL


class WsClient:
    def __init__(self, app: Any, secret: str, path: str = "/api/v1/events") -> None:
        self._app = app
        self._path = path
        self._protocols = [f"fi.{secret}", WEBSOCKET_PROTOCOL]
        self._incoming: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._outgoing: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self.accepted: dict[str, Any] | None = None

    async def __aenter__(self) -> Self:
        scope = {
            "type": "websocket",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "1.1",
            "scheme": "ws",
            "path": self._path,
            "raw_path": self._path.encode(),
            "query_string": b"",
            "headers": [(b"sec-websocket-protocol", ", ".join(self._protocols).encode())],
            "client": ("127.0.0.1", 1),
            "server": ("127.0.0.1", 2),
            "subprotocols": self._protocols,
        }
        await self._incoming.put({"type": "websocket.connect"})
        self._task = asyncio.create_task(self._app(scope, self._incoming.get, self._outgoing.put))
        self.accepted = await self._message()
        assert self.accepted["type"] == "websocket.accept", self.accepted  # else: refused
        return self

    async def _message(self, seconds: float = 10) -> dict[str, Any]:
        async with asyncio.timeout(seconds):
            return await self._outgoing.get()

    async def next_event(self, seconds: float = 10) -> dict[str, Any]:
        """The next event the server sent, decoded."""
        message = await self._message(seconds)
        assert message["type"] == "websocket.send", message
        event: dict[str, Any] = json.loads(message["text"])
        return event

    async def next_event_of(self, type_: str, seconds: float = 30) -> dict[str, Any]:
        """The next event of one type (others, such as a state change on the way, are skipped)."""
        async with asyncio.timeout(seconds):
            while True:
                event = await self.next_event(seconds)
                if event["type"] == type_:
                    return event

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self._incoming.put({"type": "websocket.disconnect", "code": 1000})
        assert self._task is not None
        async with asyncio.timeout(10):
            await self._task
