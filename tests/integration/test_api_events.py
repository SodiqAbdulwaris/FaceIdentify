"""The event connection: envelope, ordering, honest loss, and what the API announces (M4 W4;
TST-049 server side). REST stays authoritative; events say that something changed."""

import asyncio
import base64
import secrets
import threading
import uuid
from collections.abc import MutableMapping
from datetime import datetime, timedelta
from typing import Any

import anyio.to_thread
import pytest
from sqlalchemy import update

from backend.api.app import create_app
from backend.api.events import EventHub
from backend.app.jobs.models import Job
from backend.app.processing.models import ProcessingRun
from tests.fixtures.api import Api, imported
from tests.fixtures.deterministic import EPOCH, FrozenClock, SeededUUIDs
from tests.fixtures.ws import WsClient
from tests.integration.test_api_processing_routes import finished, process

# --- the hub --------------------------------------------------------------------------------


async def test_an_event_is_numbered_and_wrapped_in_the_documented_envelope() -> None:
    clock, new_id = FrozenClock(), SeededUUIDs()
    hub = EventHub(clock, new_id)

    first = hub.publish("source.created", "source", "s-1")
    second = hub.publish("processing_run.updated", "processing_run", "r-1", {"state": "RUNNING"})

    assert first == {
        "version": 1,
        "event_id": first["event_id"],
        "sequence": 1,
        "type": "source.created",
        "occurred_at": EPOCH.isoformat(),
        "resource": {"type": "source", "id": "s-1"},
        "data": {},
    }
    uuid.UUID(first["event_id"])
    assert second["sequence"] == 2
    assert second["event_id"] != first["event_id"]
    assert second["data"] == {"state": "RUNNING"}
    assert hub.sequence == 2


async def test_a_subscriber_receives_events_in_order_and_only_while_subscribed() -> None:
    hub = EventHub()
    early = hub.publish("a.b", "a", "1")  # nobody is listening: not an error, not kept
    subscription = hub.subscribe()
    assert hub.subscribers == 1

    hub.publish("a.b", "a", "2")
    hub.publish("a.b", "a", "3")
    got = [await asyncio.wait_for(subscription.queue.get(), 5) for _ in range(2)]
    hub.unsubscribe(subscription)
    hub.publish("a.b", "a", "4")
    await asyncio.sleep(0.05)

    assert [e["sequence"] for e in got] == [early["sequence"] + 1, early["sequence"] + 2]
    assert subscription.queue.empty()
    assert hub.subscribers == 0


async def test_events_published_from_other_threads_reach_the_subscriber() -> None:
    hub = EventHub()
    subscription = hub.subscribe()

    await anyio.to_thread.run_sync(lambda: [hub.publish("t.x", "t", str(i)) for i in range(5)])

    got = [await asyncio.wait_for(subscription.queue.get(), 5) for _ in range(5)]
    assert sorted(e["sequence"] for e in got) == [1, 2, 3, 4, 5]  # every one numbered once


async def test_a_slow_subscriber_loses_events_and_sees_the_gap_in_the_sequence() -> None:
    hub = EventHub(queue_size=2)
    subscription = hub.subscribe()

    for i in range(5):
        hub.publish("a.b", "a", str(i))
    await asyncio.sleep(0.05)

    kept = [subscription.queue.get_nowait()["sequence"] for _ in range(2)]
    assert kept == [1, 2]  # the first two fit; the rest were dropped for this client
    assert subscription.queue.empty()
    assert hub.sequence == 5  # so the next event (6) exposes the gap


async def test_the_greeting_carries_the_current_sequence_and_consumes_none() -> None:
    hub = EventHub()
    hub.publish("a.b", "a", "1")

    hello = hub.hello()

    assert (hello["type"], hello["sequence"]) == ("system.hello", 1)
    assert hub.hello()["sequence"] == 1
    assert hub.publish("a.b", "a", "2")["sequence"] == 2


async def test_an_event_published_before_the_greeting_is_numbered_after_it() -> None:
    hub = EventHub()
    hub.publish("a.b", "a", "1")
    subscription = hub.subscribe()  # baseline: 1
    hub.publish("a.b", "a", "2")  # between subscribing and greeting

    hello = hub.hello(subscription.baseline)

    assert hello["sequence"] == 1
    assert (await asyncio.wait_for(subscription.queue.get(), 5))["sequence"] == 2
    assert hub.hello()["sequence"] == 2  # without a baseline: the current sequence


async def test_a_subscriber_whose_loop_is_closed_is_ignored() -> None:
    hub = EventHub()
    done = threading.Event()

    def subscribe_on_a_loop_that_then_closes() -> None:
        loop = asyncio.new_event_loop()

        async def subscribe() -> None:
            hub.subscribe()

        loop.run_until_complete(subscribe())
        loop.close()
        done.set()

    await anyio.to_thread.run_sync(subscribe_on_a_loop_that_then_closes)
    assert done.is_set()

    assert hub.publish("a.b", "a", "1")["sequence"] == 1  # no error from the dead subscriber


# --- the connection -------------------------------------------------------------------------


def a_secret() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")


async def test_a_connection_is_greeted_then_receives_what_is_published() -> None:
    secret, hub = a_secret(), EventHub()
    app = create_app(secret, events=hub)
    hub.publish("a.b", "a", "before")  # before the connection: never delivered

    async with WsClient(app, secret) as client:
        hello = await client.next_event()
        hub.publish("source.created", "source", "s-1")
        event = await client.next_event()

    assert hello["type"] == "system.hello"
    assert hello["sequence"] == 1  # the first real event will be 2
    assert (event["type"], event["sequence"], event["resource"]["id"]) == (
        "source.created",
        2,
        "s-1",
    )
    assert hub.subscribers == 0  # leaving the connection unsubscribes it


async def test_an_event_racing_the_greeting_is_numbered_after_it_on_the_wire() -> None:
    secret, hub = a_secret(), EventHub()
    app = create_app(secret, events=hub)
    subscribe = hub.subscribe

    def subscribe_then_race() -> Any:
        subscription = subscribe()
        hub.publish("a.b", "a", "raced")  # lands between subscribing and the greeting
        return subscription

    hub.subscribe = subscribe_then_race  # type: ignore[method-assign]

    async with WsClient(app, secret) as client:
        hello = await client.next_event()
        raced = await client.next_event()

    assert raced["sequence"] == hello["sequence"] + 1  # the client sees no duplicate or gap


@pytest.mark.parametrize("vanishes_at", ["greeting", "event"])
async def test_a_client_that_vanishes_mid_send_is_forgotten_quietly(vanishes_at: str) -> None:
    secret, hub = a_secret(), EventHub()
    app = create_app(secret, events=hub)
    sends: list[str] = []
    released = asyncio.Event()
    incoming: list[MutableMapping[str, Any]] = [{"type": "websocket.connect"}]

    async def receive() -> MutableMapping[str, Any]:
        if incoming:
            return incoming.pop(0)
        await released.wait()  # the client says nothing more
        return {"type": "websocket.disconnect", "code": 1006}

    async def send(message: MutableMapping[str, Any]) -> None:
        sends.append(message["type"])
        if message["type"] == "websocket.send" and (vanishes_at == "greeting" or len(sends) > 2):
            raise OSError("the client is gone")  # a broken pipe, as the server would see it
        if len(sends) == 2:
            hub.publish("a.b", "a", "1")  # the first event goes to a client that has just left

    scope = {
        "type": "websocket",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "path": "/api/v1/events",
        "raw_path": b"/api/v1/events",
        "query_string": b"",
        "headers": [(b"sec-websocket-protocol", f"fi.{secret}, faceidentify.v1".encode())],
        "subprotocols": [],
    }

    await asyncio.wait_for(app(scope, receive, send), 10)  # returns: nothing hangs or raises

    assert hub.subscribers == 0
    released.set()


async def test_the_connection_still_requires_the_launch_capability() -> None:
    secret, hub = a_secret(), EventHub()
    app = create_app(secret, events=hub)

    with pytest.raises(AssertionError):  # the server closes instead of accepting
        async with WsClient(app, a_secret()):
            pass

    assert hub.subscribers == 0


# --- what the API announces -----------------------------------------------------------------


async def test_importing_and_processing_a_source_is_announced_in_order(processing_api: Api) -> None:
    api = processing_api
    async with WsClient(api.app, api.secret) as client:
        hello = await client.next_event()
        source = await imported(api, path=str(api.image()))
        created = await client.next_event_of("source.created")
        run = await process(api, source)
        started = await client.next_event_of("processing_run.created")
        await finished(api, run["id"])
        done = await client.next_event_of("processing_run.updated")
        while done["data"]["state"] != "COMPLETED":
            done = await client.next_event_of("processing_run.updated")

    assert created["resource"] == {"type": "source", "id": source["id"]}
    assert started["resource"] == {"type": "processing_run", "id": run["id"]}
    assert started["data"]["source_id"] == source["id"]
    assert done["resource"]["id"] == run["id"]
    assert done["sequence"] > started["sequence"] > created["sequence"] > hello["sequence"]


async def test_a_run_is_announced_running_while_its_work_is_in_progress(
    processing_api: Api,
) -> None:
    api = processing_api
    assert api.perception is not None
    working, release = threading.Event(), threading.Event()

    def hold() -> None:
        working.set()
        assert release.wait(30)

    api.perception.on_represent = hold
    source = await imported(api, path=str(api.image()))
    async with WsClient(api.app, api.secret) as client:
        await client.next_event()
        run = await process(api, source)
        try:
            await anyio.to_thread.run_sync(working.wait, 30)  # the executor is mid-work
            running = await client.next_event_of("processing_run.updated")
        finally:
            release.set()
        await finished(api, run["id"])

    assert running["resource"]["id"] == run["id"]
    assert running["data"]["state"] == "RUNNING"


async def test_cancelling_is_announced_once_and_a_repeat_says_nothing(processing_api: Api) -> None:
    api = processing_api
    api.backend.wake_scheduler = lambda: None  # type: ignore[method-assign]  # stays queued
    source = await imported(api, path=str(api.image()))
    run = await process(api, source)
    async with WsClient(api.app, api.secret) as client:
        await client.next_event()  # hello

        await api.client.post(f"/api/v1/processing-runs/{run['id']}/cancel")
        await api.client.post(f"/api/v1/processing-runs/{run['id']}/cancel")  # a repeat
        first = await client.next_event()
        api.backend.events.publish("probe.done", "probe", "p")  # what a repeat would precede
        second = await client.next_event()

    assert (first["type"], first["data"]["state"]) == ("processing_run.updated", "CANCELLED")
    assert second["type"] == "probe.done"  # nothing was announced for the repeat


async def test_a_retry_is_announced_as_a_new_run(processing_api: Api) -> None:
    api = processing_api
    source = await imported(api, path=str(api.image()))
    old = await process(api, source)
    await finished(api, old["id"])
    assert api.backend.library is not None
    with api.backend.library.session_factory() as session:
        session.execute(update(ProcessingRun).values(state="FAILED", failure_code="X"))
        session.execute(update(Job).values(state="FAILED", failure_code="X"))
        session.commit()
    async with WsClient(api.app, api.secret) as client:
        await client.next_event()

        retried = (await api.client.post(f"/api/v1/processing-runs/{old['id']}/retry")).json()
        event = await client.next_event_of("processing_run.created")

    assert event["resource"]["id"] == retried["id"] != old["id"]


async def test_a_notification_that_fails_does_not_fail_the_work(processing_api: Api) -> None:
    api = processing_api

    def broken(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("the hub is broken")

    api.backend.events.publish = broken  # type: ignore[method-assign, assignment]

    source = await imported(api, path=str(api.image()))  # committed: still 201
    run = await process(api, source)  # committed: still 202
    done = await finished(api, run["id"])  # and the scheduler's own notifications fail quietly

    assert done["state"] == "COMPLETED"


async def test_events_are_stamped_with_the_applications_clock(processing_api: Api) -> None:
    api = processing_api
    api.clock.advance(seconds=5)

    event = api.backend.events.publish("a.b", "a", "1")

    assert datetime.fromisoformat(event["occurred_at"]) == EPOCH + timedelta(seconds=5)
