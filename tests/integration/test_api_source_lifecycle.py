"""Recycling and restoring a Source through the API (M5 step 4a; API sections 5.5 and 5.6).

A recycled Source leaves the library view and nothing else: its bytes, its faces, the identities
made from them, their counts and its history all stay, the faces marked as coming from a recycled
Source.
"""

import uuid
from typing import Any

import pytest
from sqlalchemy import update

from backend.app.processing.models import ProcessingRun
from backend.app.sources.models import Artifact, ArtifactState, Source
from tests.factories.models import ModelFactory
from tests.fixtures.api import Api, error, imported
from tests.fixtures.deterministic import FrozenClock, SeededUUIDs
from tests.integration.test_api_memory import processed

SOURCES = "/api/v1/sources"
IDENTITIES = "/api/v1/identities"


async def ids(api: Api, **query: str) -> list[str]:
    response = await api.client.get(SOURCES, params=query)
    assert response.status_code == 200, response.text
    return [item["id"] for item in response.json()["items"]]


def events_of(api: Api) -> Any:
    return api.backend.events.subscribe()


def drained(subscription: Any) -> list[dict[str, Any]]:
    seen = []
    while not subscription.queue.empty():
        seen.append(subscription.queue.get_nowait())
    return seen


async def test_a_recycled_source_leaves_the_library_view_and_keeps_everything_else(
    api: Api,
) -> None:
    source = await imported(api, path=str(api.image()))
    subscription = events_of(api)
    try:
        recycled = await api.client.delete(f"{SOURCES}/{source['id']}")
        events = drained(subscription)
    finally:
        api.backend.events.unsubscribe(subscription)

    assert recycled.status_code == 204
    assert recycled.content == b""
    assert await ids(api) == []  # normal browsing hides it
    assert await ids(api, state="RECYCLED") == [source["id"]]  # the Recycle Bin shows it
    detail = (await api.client.get(f"{SOURCES}/{source['id']}")).json()
    assert detail["state"] == "RECYCLED"
    assert detail["recycled_at"] is not None
    assert (
        await api.client.get(f"{SOURCES}/{source['id']}/media")
    ).status_code == 200  # bytes stay
    assert [(e["type"], e["resource"]["id"]) for e in events] == [("source.updated", source["id"])]


async def test_restoring_brings_the_source_back_and_a_repeat_is_harmless(api: Api) -> None:
    source = await imported(api, path=str(api.image()))
    await api.client.delete(f"{SOURCES}/{source['id']}")
    subscription = events_of(api)
    try:
        restored = await api.client.post(f"{SOURCES}/{source['id']}/restore")
        again = await api.client.post(f"{SOURCES}/{source['id']}/restore")
        events = drained(subscription)
    finally:
        api.backend.events.unsubscribe(subscription)

    assert restored.status_code == 200
    assert restored.json()["state"] == "ACTIVE"
    assert restored.json()["recycled_at"] is None
    assert again.status_code == 200
    assert again.json() == restored.json()
    assert await ids(api) == [source["id"]]
    assert await ids(api, state="RECYCLED") == []
    assert len(events) == 1  # only the real change was announced


async def test_recycling_twice_is_harmless_and_announced_once(api: Api) -> None:
    source = await imported(api, path=str(api.image()))
    subscription = events_of(api)
    try:
        first = await api.client.delete(f"{SOURCES}/{source['id']}")
        second = await api.client.delete(f"{SOURCES}/{source['id']}")
        events = drained(subscription)
    finally:
        api.backend.events.unsubscribe(subscription)

    assert (first.status_code, second.status_code) == (204, 204)
    assert len(events) == 1


async def test_an_unknown_source_is_not_found_either_way(api: Api) -> None:
    missing = "00000000-0000-0000-0000-00000000dead"

    error(await api.client.delete(f"{SOURCES}/{missing}"), 404, "SOURCE_NOT_FOUND")
    error(await api.client.post(f"{SOURCES}/{missing}/restore"), 404, "SOURCE_NOT_FOUND")


@pytest.mark.parametrize(
    "state", ["RUNNING", "PENDING", "PAUSING", "PAUSED", "FINALIZING", "CANCELLING"]
)
async def test_a_source_being_processed_is_not_recycled_until_that_ends(
    api: Api, clock: FrozenClock, new_id: SeededUUIDs, state: str
) -> None:
    source = await imported(api, path=str(api.image()))
    assert api.backend.library is not None
    with api.backend.library.session_factory() as session:
        run = ModelFactory(session, clock, new_id).run(
            source_id=uuid.UUID(source["id"]), state=state
        )
        session.commit()
        run_id = run.id

    body = error(await api.client.delete(f"{SOURCES}/{source['id']}"), 409, "SOURCE_BUSY")

    assert body["details"] == {"source_id": source["id"]}
    assert await ids(api) == [source["id"]]  # nothing moved
    with api.backend.library.session_factory() as session:
        session.execute(
            update(ProcessingRun).where(ProcessingRun.id == run_id).values(state="FAILED")
        )
        session.commit()
    assert (await api.client.delete(f"{SOURCES}/{source['id']}")).status_code == 204


async def test_a_source_whose_original_is_being_deleted_cannot_be_moved(api: Api) -> None:
    source = await imported(api, path=str(api.image()))
    assert api.backend.library is not None
    with api.backend.library.session_factory() as session:
        session.execute(update(Artifact).values(state=ArtifactState.DELETING))
        session.commit()

    body = error(await api.client.delete(f"{SOURCES}/{source['id']}"), 409, "SOURCE_STATE_CONFLICT")

    assert body["details"]["state"] == "ACTIVE"
    assert await ids(api) == [source["id"]]


async def test_a_source_that_is_not_recycled_or_active_cannot_be_restored(api: Api) -> None:
    source = await imported(api, path=str(api.image()))
    assert api.backend.library is not None
    with api.backend.library.session_factory() as session:
        session.execute(update(Source).values(state="DELETING"))
        session.commit()

    body = error(
        await api.client.post(f"{SOURCES}/{source['id']}/restore"), 409, "SOURCE_STATE_CONFLICT"
    )

    assert body["details"]["state"] == "DELETING"


async def test_a_recycled_source_cannot_be_processed(processing_api: Api) -> None:
    api = processing_api
    source = await imported(api, path=str(api.image()))
    await api.client.delete(f"{SOURCES}/{source['id']}")

    refused = await api.client.post(f"{SOURCES}/{source['id']}/process")

    assert refused.status_code == 409  # a Source in the Recycle Bin is not processed


async def test_its_faces_stay_in_memory_counts_and_views_marked_as_recycled(
    processing_api: Api,
) -> None:
    api = processing_api
    source = await processed(api, "alice.png")
    [identity] = (await api.client.get(IDENTITIES)).json()["items"]
    assert (identity["occurrence_count"], identity["source_count"]) == (1, 1)
    [before] = (await api.client.get(f"{IDENTITIES}/{identity['id']}/occurrences")).json()["items"]
    assert before["source_recycled"] is False

    await api.client.delete(f"{SOURCES}/{source['id']}")

    [after] = (await api.client.get(f"{IDENTITIES}/{identity['id']}/occurrences")).json()["items"]
    assert after["source_recycled"] is True  # still there, and marked
    assert after | {"source_recycled": False} == before
    [same] = (await api.client.get(f"{SOURCES}/{source['id']}/occurrences")).json()["items"]
    assert same["source_recycled"] is True
    [counted] = (await api.client.get(IDENTITIES)).json()["items"]
    assert counted == identity  # the counts include the recycled source's face

    await api.client.post(f"{SOURCES}/{source['id']}/restore")

    [restored] = (await api.client.get(f"{IDENTITIES}/{identity['id']}/occurrences")).json()[
        "items"
    ]
    assert restored["source_recycled"] is False
