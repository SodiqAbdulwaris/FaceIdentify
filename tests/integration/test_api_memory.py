"""Identities and occurrences through the API (M4 W3.5; TST-045).

The library really processes the images (planted perception, no weights), so what is read is what
the pipeline made authoritative. Anything still private (`PENDING`) must never be shown.
"""

import uuid
from typing import Any

import pytest
from sqlalchemy import update

from backend.api.pagination import encode_cursor
from backend.app.identities.models import Identity
from backend.app.memory.models import Observation, Occurrence
from backend.app.runtime.perception_client import Detected
from backend.ml.contracts.messages import Detection
from tests.fixtures.api import Api, error, imported
from tests.fixtures.pipeline import unit
from tests.integration.test_api_processing_routes import finished, process

IDENTITIES = "/api/v1/identities"


async def processed(api: Api, name: str, *, tick: bool = True) -> dict[str, Any]:
    """Import and process an image, and wait until its result is authoritative."""
    source = await imported(api, path=str(api.image(name)), display_name=name)
    run = await process(api, source, tick=tick)
    await finished(api, run["id"])
    return source


def set_state(api: Api, model: Any, state: str) -> None:
    assert api.backend.library is not None
    with api.backend.library.session_factory() as session:
        session.execute(update(model).values(state=state))
        session.commit()


async def test_a_processed_image_shows_its_face_and_the_identity_made_for_it(
    processing_api: Api,
) -> None:
    api = processing_api
    assert api.perception is not None
    detector = api.perception.detector
    api.perception.detect = lambda _pixels: Detected(  # type: ignore[method-assign, assignment]
        (Detection(0, 0, (0.1, 0.2, 0.5, 0.9), 0.9, None),), detector
    )
    source = await processed(api, "alice.png")

    occurrences = (await api.client.get(f"/api/v1/sources/{source['id']}/occurrences")).json()
    identities = (await api.client.get(IDENTITIES)).json()

    [occurrence] = occurrences["items"]
    assert occurrence["source_id"] == source["id"]
    assert occurrence["source_display_name"] == "alice.png"
    assert occurrence["kind"] == "IMAGE"
    box = occurrence["representative_observation"]["bounding_box"]
    assert box == pytest.approx({"x": 0.1, "y": 0.2, "width": 0.4, "height": 0.7})
    assert occurrence["representative_observation"]["face_crop"] is None  # none exist yet
    [identity] = identities["items"]
    assert identity["id"] == occurrence["identity_id"]
    assert identity["state"] == "ACTIVE"
    assert (identity["occurrence_count"], identity["source_count"]) == (1, 1)
    assert identity["representative_observation"]["source_id"] == source["id"]
    assert (await api.client.get(f"{IDENTITIES}/{identity['id']}")).json() == identity
    of_identity = (await api.client.get(f"{IDENTITIES}/{identity['id']}/occurrences")).json()
    assert of_identity["items"] == occurrences["items"]


async def test_a_named_identity_shows_its_person_on_its_occurrences(
    processing_api: Api,
) -> None:
    api = processing_api
    source = await processed(api, "alice.png")
    [identity] = (await api.client.get(IDENTITIES)).json()["items"]
    [before] = (await api.client.get(f"/api/v1/sources/{source['id']}/occurrences")).json()["items"]
    assert before["person"] is None

    named = await api.client.post(
        "/api/v1/people", json={"display_name": "Alice", "identity_id": identity["id"]}
    )

    [after] = (await api.client.get(f"/api/v1/sources/{source['id']}/occurrences")).json()["items"]
    assert after["person"] == {"id": named.json()["id"], "display_name": "Alice", "revision": 1}


async def test_the_same_face_in_two_images_is_one_identity_with_two_occurrences(
    processing_api: Api,
) -> None:
    api = processing_api
    first = await processed(api, "a.png")
    second = await processed(api, "b.png")

    identities = (await api.client.get(IDENTITIES)).json()["items"]

    [identity] = identities
    assert (identity["occurrence_count"], identity["source_count"]) == (2, 2)
    occurrences = (await api.client.get(f"{IDENTITIES}/{identity['id']}/occurrences")).json()
    assert [o["source_id"] for o in occurrences["items"]] == [second["id"], first["id"]]
    url = f"{IDENTITIES}/{identity['id']}/occurrences"
    head = (await api.client.get(url, params={"limit": 1})).json()
    tail = (
        await api.client.get(url, params={"limit": 1, "cursor": head["page"]["next_cursor"]})
    ).json()
    assert [o["source_id"] for o in head["items"] + tail["items"]] == [second["id"], first["id"]]
    assert (head["page"]["has_more"], tail["page"]["has_more"]) == (True, False)


async def test_counts_and_cursors_know_the_difference_between_sources_and_occurrences(
    processing_api: Api,
) -> None:
    api = processing_api
    first = await processed(api, "a.png")
    second = await processed(api, "b.png")
    assert api.backend.library is not None
    with api.backend.library.session_factory() as session:  # two appearances in one source
        session.execute(update(Occurrence).values(source_id=uuid.UUID(first["id"])))
        session.commit()
    [identity] = (await api.client.get(IDENTITIES)).json()["items"]
    assert api.perception is not None
    api.perception.vector = unit(0, 1, 0, 0)  # another face: a second identity
    await processed(api, "c.png")
    [other] = [
        i for i in (await api.client.get(IDENTITIES)).json()["items"] if i["id"] != identity["id"]
    ]
    in_source = f"/api/v1/sources/{first['id']}/occurrences"
    in_identity = f"{IDENTITIES}/{identity['id']}/occurrences"

    assert (identity["occurrence_count"], identity["source_count"]) == (2, 1)
    from_source = (await api.client.get(in_source, params={"limit": 1})).json()
    from_identity = (await api.client.get(in_identity, params={"limit": 1})).json()
    source_cursor = from_source["page"]["next_cursor"]
    identity_cursor = from_identity["page"]["next_cursor"]
    assert source_cursor is not None
    assert identity_cursor is not None
    for url, cursor in [
        (in_identity, source_cursor),  # a cursor belongs to the query that made it
        (in_source, identity_cursor),
        (f"/api/v1/sources/{second['id']}/occurrences", source_cursor),  # and to its source
        (f"{IDENTITIES}/{other['id']}/occurrences", identity_cursor),  # or its identity
    ]:
        error(await api.client.get(url, params={"cursor": cursor}), 400, "INVALID_CURSOR")


async def test_identities_and_occurrences_are_paged_newest_first_without_loss_or_repeats(
    processing_api: Api,
) -> None:
    api = processing_api
    assert api.perception is not None
    await processed(api, "a.png", tick=False)
    api.perception.vector = unit(0, 1, 0, 0)  # a different face: a new identity
    await processed(api, "b.png", tick=False)
    api.perception.vector = unit(0, 0, 1, 0)
    await processed(api, "c.png", tick=False)  # all at one instant: ties break by id

    async def walk(url: str) -> tuple[list[str], list[str]]:
        seen: list[str] = []
        cursor: str | None = None
        for _ in range(6):  # bounded: a broken cursor must fail the test, not hang it
            params: dict[str, Any] = {"limit": 1} | ({"cursor": cursor} if cursor else {})
            body = (await api.client.get(url, params=params)).json()
            seen += [item["id"] for item in body["items"]]
            cursor = body["page"]["next_cursor"]
            if cursor is None:
                break
        everything = (await api.client.get(url)).json()["items"]
        return seen, [item["id"] for item in everything]

    identities, listed_identities = await walk(IDENTITIES)
    assert len(identities) == 3
    assert identities == listed_identities == sorted(identities, reverse=True)
    one = identities[0]
    occurrences, listed = await walk(f"{IDENTITIES}/{one}/occurrences")
    assert occurrences == listed
    assert len(occurrences) == 1


async def test_private_output_is_never_shown(processing_api: Api) -> None:
    api = processing_api
    source = await processed(api, "alice.png")
    [identity] = (await api.client.get(IDENTITIES)).json()["items"]
    sources_url = f"/api/v1/sources/{source['id']}/occurrences"

    set_state(api, Observation, "PENDING")
    no_face = (await api.client.get(sources_url)).json()["items"][0]
    assert no_face["representative_observation"] is None
    assert (await api.client.get(f"{IDENTITIES}/{identity['id']}")).json()[
        "representative_observation"
    ] is None

    set_state(api, Occurrence, "PENDING")
    assert (await api.client.get(sources_url)).json()["items"] == []
    assert (await api.client.get(f"{IDENTITIES}/{identity['id']}/occurrences")).json()[
        "items"
    ] == []
    counted = (await api.client.get(f"{IDENTITIES}/{identity['id']}")).json()
    assert (counted["occurrence_count"], counted["source_count"]) == (0, 0)

    set_state(api, Identity, "PENDING")
    assert (await api.client.get(IDENTITIES)).json()["items"] == []
    error(await api.client.get(f"{IDENTITIES}/{identity['id']}"), 404, "IDENTITY_NOT_FOUND")
    error(
        await api.client.get(f"{IDENTITIES}/{identity['id']}/occurrences"),
        404,
        "IDENTITY_NOT_FOUND",
    )


async def test_unknown_sources_and_identities_are_404_and_cursors_are_bound(
    processing_api: Api,
) -> None:
    api = processing_api
    missing = uuid.uuid4()
    error(await api.client.get(f"/api/v1/sources/{missing}/occurrences"), 404, "SOURCE_NOT_FOUND")
    body = error(await api.client.get(f"{IDENTITIES}/{missing}"), 404, "IDENTITY_NOT_FOUND")
    assert body["details"] == {"identity_id": str(missing)}
    error(await api.client.get(f"{IDENTITIES}/{missing}/occurrences"), 404, "IDENTITY_NOT_FOUND")

    source = await processed(api, "alice.png")
    [identity] = (await api.client.get(IDENTITIES)).json()["items"]
    key = ["2026-01-01T00:00:00+00:00", str(uuid.uuid4())]
    elsewhere = encode_cursor("identities-elsewhere", key)
    error(await api.client.get(IDENTITIES, params={"cursor": elsewhere}), 400, "INVALID_CURSOR")
    error(await api.client.get(IDENTITIES, params={"cursor": "junk"}), 400, "INVALID_CURSOR")
    other_scope = encode_cursor(f"occurrences:source:{source['id']}", key)
    error(
        await api.client.get(
            f"{IDENTITIES}/{identity['id']}/occurrences", params={"cursor": other_scope}
        ),
        400,
        "INVALID_CURSOR",
    )
    error(
        await api.client.get(
            f"/api/v1/sources/{source['id']}/occurrences", params={"cursor": other_scope[:-2]}
        ),
        400,
        "INVALID_CURSOR",
    )
