"""`POST /api/v1/sources/{id}/reprocess` over HTTP (API and Contracts 5.4; M6 step 1, issue 180):
202 with a run that names the generation it replaces, the 409s, `process` refused once a result
exists, and `source.updated` when the new generation is accepted."""

from tests.fixtures.api import Api, error, imported
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
