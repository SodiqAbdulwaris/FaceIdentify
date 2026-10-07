"""Notifications for the one event connection, `WS /api/v1/events` (API sections 31 to 34; M4 W4).

REST is authoritative; an event only says *something changed*, so a client refetches. Delivery is
therefore best effort and says so honestly:

* every event has a `sequence` from one counter for the process, assigned when it is published;
* a connection has a bounded queue; when a slow client's queue is full the new event is dropped for
  that client, which sees the gap in `sequence` and refetches (nothing is buffered without limit);
* a new connection is greeted with `system.hello`, carrying the current sequence (it consumes
  none), so the first real event is checked against it;
* nothing is replayed after a reconnect: the client refetches through REST.

`publish` is safe from any thread (the scheduler loop and the route worker threads publish); each
subscriber is fed on its own event loop.
"""

import asyncio
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Final

ENVELOPE_VERSION: Final = 1
DEFAULT_QUEUE_SIZE: Final = 256


class Subscription:
    """One connection's feed: a bounded queue filled from any thread, read on its own loop."""

    def __init__(self, loop: asyncio.AbstractEventLoop, size: int, baseline: int) -> None:
        self._loop = loop
        self.baseline = baseline  # the sequence when it subscribed: it is offered only later ones
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=size)

    def _offer(self, event: dict[str, Any]) -> None:
        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            pass  # dropped for this slow client; its sequence gap tells it to refetch

    def offer_threadsafe(self, event: dict[str, Any]) -> None:
        try:
            self._loop.call_soon_threadsafe(self._offer, event)
        except RuntimeError:
            pass  # the connection's loop is closed: it is gone


class EventHub:
    def __init__(
        self,
        clock: Callable[[], datetime] | None = None,
        new_id: Callable[[], uuid.UUID] = uuid.uuid4,
        queue_size: int = DEFAULT_QUEUE_SIZE,
    ) -> None:
        self._clock = clock if clock is not None else lambda: datetime.now(UTC)
        self._new_id = new_id
        self._queue_size = queue_size
        self._lock = threading.Lock()
        self._sequence = 0
        self._subscribers: set[Subscription] = set()

    @property
    def sequence(self) -> int:
        return self._sequence

    def _envelope(
        self, type_: str, resource_type: str, resource_id: str, data: dict[str, Any], sequence: int
    ) -> dict[str, Any]:
        return {
            "version": ENVELOPE_VERSION,
            "event_id": str(self._new_id()),
            "sequence": sequence,
            "type": type_,
            "occurred_at": self._clock().isoformat(),
            "resource": {"type": resource_type, "id": resource_id},
            "data": data,
        }

    def publish(
        self,
        type_: str,
        resource_type: str,
        resource_id: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Number the event and offer it to every connection. Returns the envelope."""
        with self._lock:
            self._sequence += 1
            event = self._envelope(type_, resource_type, resource_id, data or {}, self._sequence)
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            subscriber.offer_threadsafe(event)
        return event

    def hello(self, baseline: int | None = None) -> dict[str, Any]:
        """The greeting for a new connection: it carries a sequence and consumes none. A connection
        passes its subscription's `baseline`, so an event published between subscribing and
        greeting is never numbered at or before the greeting (default: the current sequence)."""
        sequence = self._sequence if baseline is None else baseline
        return self._envelope("system.hello", "system", "events", {}, sequence)

    def subscribe(self) -> Subscription:
        """Start feeding the calling loop's connection. Pair with `unsubscribe`."""
        with self._lock:
            subscription = Subscription(
                asyncio.get_running_loop(), self._queue_size, self._sequence
            )
            self._subscribers.add(subscription)
        return subscription

    def unsubscribe(self, subscription: Subscription) -> None:
        with self._lock:
            self._subscribers.discard(subscription)

    @property
    def subscribers(self) -> int:
        with self._lock:
            return len(self._subscribers)
