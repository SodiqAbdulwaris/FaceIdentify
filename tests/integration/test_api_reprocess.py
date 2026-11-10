"""`POST /api/v1/sources/{id}/reprocess` over HTTP (API and Contracts 5.4; M6 step 1, issue 180):
202 with a run that names the generation it replaces, the 409s, `process` refused once a result
exists, and `source.updated` when the new generation is accepted."""

from tests.fixtures.api import Api, error, imported
from tests.fixtures.pipeline import unit
from tests.fixtures.ws import WsClient
from tests.integration.test_api_processing_routes import finished, process

V1 = "/api/v1/sources"


async def test_a_processed_source_is_reprocessed_and_announced_when_replaced(
    processing_api: Api,
) -> None:
    api = processing_api
    source = await imported(api, path=str(api.image()))
    first = await process(api, source)
    await finished(api, first["id"])

    async with WsClient(api.app, api.secret) as client:
        await client.next_event()
        response = await api.client.post(f"{V1}/{source['id']}/reprocess")
        assert response.status_code == 202, response.text
        run = response.json()
        updated = await client.next_event_of("source.updated")

    assert run["supersedes_run_id"] == first["id"]
    assert run["parent_run_id"] is None
    assert run["job"] is not None
    assert updated["resource"]["id"] == source["id"]
    await finished(api, run["id"])
    detail = (await api.client.get(f"/api/v1/processing-runs/{first['id']}")).json()
    assert detail["supersedes_run_id"] is None


async def test_processing_a_processed_source_is_refused(processing_api: Api) -> None:
    api = processing_api
    source = await imported(api, path=str(api.image()))
    await finished(api, (await process(api, source))["id"])

    body = error(
        await api.client.post(f"{V1}/{source['id']}/process"), 409, "SOURCE_ALREADY_PROCESSED"
    )
    assert "already has a result" in body["details"]["reason"]


async def test_a_source_without_a_result_cannot_be_reprocessed(processing_api: Api) -> None:
    api = processing_api
    source = await imported(api, path=str(api.image()))

    error(await api.client.post(f"{V1}/{source['id']}/reprocess"), 409, "SOURCE_STATE_CONFLICT")
    error(
        await api.client.post(f"{V1}/00000000-0000-0000-0000-000000000000/reprocess"),
        404,
        "SOURCE_NOT_FOUND",
    )


async def test_a_second_reprocess_while_one_is_in_flight_is_busy(processing_api: Api) -> None:
    api = processing_api
    source = await imported(api, path=str(api.image()))
    await finished(api, (await process(api, source))["id"])
    assert api.backend.scheduler is not None
    await api.backend.scheduler.stop()  # nothing claims the queued run: it stays in flight

    first = await api.client.post(f"{V1}/{source['id']}/reprocess")
    assert first.status_code == 202, first.text

    error(await api.client.post(f"{V1}/{source['id']}/reprocess"), 409, "SOURCE_BUSY")


async def test_a_source_shows_its_current_run(processing_api: Api) -> None:
    api = processing_api
    source = await imported(api, path=str(api.image()))
    assert (await api.client.get(f"{V1}/{source['id']}")).json()[
        "current_processing_run_id"
    ] is None

    first = await process(api, source)
    await finished(api, first["id"])

    shown = (await api.client.get(f"{V1}/{source['id']}")).json()
    assert shown["current_processing_run_id"] == first["id"]


async def test_a_named_face_that_was_not_found_again_is_listed_for_review(
    processing_api: Api,
) -> None:
    api = processing_api
    assert api.perception is not None
    source = await imported(api, path=str(api.image()))
    first = await process(api, source)
    await finished(api, first["id"])
    reviews = f"{V1}/{source['id']}/reprocess-reviews"
    assert (await api.client.get(reviews)).json() == {"items": []}
    (face,) = (await api.client.get(f"{V1}/{source['id']}/occurrences")).json()["items"]
    named = await api.client.post(
        "/api/v1/people", json={"display_name": "Ada", "identity_id": face["identity_id"]}
    )
    assert named.status_code == 201, named.text
    api.perception.vector = unit(0, 1, 0, 0)  # the same place, a different face

    again = await process(api, source, again=True)
    await finished(api, again["id"])

    (item,) = (await api.client.get(reviews)).json()["items"]
    assert item["identity_id"] == face["identity_id"]
    assert (item["person"], item["reason"]) == ("Ada", "NO_CORRESPONDENCE")
    assert item["processing_run_id"] == again["id"]

    # the person puts the new face where it belongs: the review is answered and leaves the list
    api.clock.advance(seconds=1)
    (new_face,) = (await api.client.get(f"{V1}/{source['id']}/occurrences")).json()["items"]
    moved = await api.client.post(
        f"/api/v1/occurrences/{new_face['id']}/reassign",
        json={"expected_identity_id": new_face["identity_id"], "identity_id": face["identity_id"]},
    )
    assert moved.status_code == 200, moved.text
    assert (await api.client.get(reviews)).json() == {"items": []}


async def test_review_items_of_an_unknown_source_are_not_found(processing_api: Api) -> None:
    api = processing_api
    error(
        await api.client.get(f"{V1}/00000000-0000-0000-0000-000000000000/reprocess-reviews"),
        404,
        "SOURCE_NOT_FOUND",
    )
