"""Cancelling a run and reading jobs through the API (M4 W3.4; TST-045, TST-047).

The scheduler is not woken after a process command, so a requested run stays queued for as long as
a test needs; the use case's own tests cover stopping a running one.
"""

import uuid
from typing import Any

from sqlalchemy import update

from backend.api.pagination import encode_cursor
from backend.app.jobs.models import Job
from tests.fixtures.api import Api, error, imported
from tests.integration.test_api_processing_routes import finished, process

RUNS = "/api/v1/processing-runs"
JOBS = "/api/v1/jobs"


async def queued(api: Api, name: str = "photo.png", *, tick: bool = True) -> dict[str, Any]:
    """A source with a requested run that nothing will pick up."""
    api.backend.wake_scheduler = lambda: None  # type: ignore[method-assign]
    source = await imported(api, path=str(api.image(name)))
    return await process(api, source, tick=tick)


async def test_a_queued_run_is_cancelled_through_the_run_and_a_repeat_is_harmless(
    processing_api: Api,
) -> None:
    api = processing_api
    run = await queued(api)
    assert (run["state"], run["job"]["state"]) == ("PENDING", "QUEUED")

    cancelled = await api.client.post(f"{RUNS}/{run['id']}/cancel")
    again = await api.client.post(f"{RUNS}/{run['id']}/cancel")

    assert cancelled.status_code == again.status_code == 202
    body = cancelled.json()
    assert (body["id"], body["state"], body["job"]["state"]) == (
        run["id"],
        "CANCELLED",
        "CANCELLED",
    )
    assert again.json()["state"] == "CANCELLED"
    detail = (await api.client.get(f"/api/v1/sources/{run['source_id']}")).json()
    assert detail["processing_status"] == "CANCELLED"


async def test_a_queued_run_is_cancelled_through_its_job(processing_api: Api) -> None:
    api = processing_api
    run = await queued(api)

    response = await api.client.post(f"{JOBS}/{run['job']['id']}/cancel")

    assert response.status_code == 202, response.text
    assert response.json()["state"] == "CANCELLED"
    assert (await api.client.get(f"{JOBS}/{run['job']['id']}")).json()["state"] == "CANCELLED"


async def test_a_run_that_is_over_or_unknown_cannot_be_cancelled(processing_api: Api) -> None:
    api = processing_api
    source = await imported(api, path=str(api.image()))
    run = await process(api, source)
    await finished(api, run["id"])

    body = error(await api.client.post(f"{RUNS}/{run['id']}/cancel"), 409, "RUN_NOT_CANCELLABLE")

    assert "COMPLETED" in body["details"]["reason"]
    error(await api.client.post(f"{RUNS}/{uuid.uuid4()}/cancel"), 404, "RUN_NOT_FOUND")
    error(await api.client.post(f"{JOBS}/{uuid.uuid4()}/cancel"), 404, "JOB_NOT_FOUND")


async def test_a_job_with_no_run_has_nothing_to_cancel(processing_api: Api) -> None:
    api = processing_api
    run = await queued(api)
    assert api.backend.library is not None
    with api.backend.library.session_factory() as session:
        session.execute(update(Job).values(processing_run_id=None, type="CLEAN_STORAGE"))
        session.commit()

    body = error(
        await api.client.post(f"{JOBS}/{run['job']['id']}/cancel"), 409, "JOB_NOT_CANCELLABLE"
    )

    assert body["details"] == {"job_id": run["job"]["id"]}


async def test_a_job_is_read_with_its_run_and_lineage(processing_api: Api) -> None:
    api = processing_api
    run = await queued(api)

    job = (await api.client.get(f"{JOBS}/{run['job']['id']}")).json()

    assert job["id"] == run["job"]["id"]
    assert (job["type"], job["state"], job["priority"]) == (
        "PROCESS_SOURCE",
        "QUEUED",
        "INTERACTIVE",
    )
    assert job["processing_run_id"] == run["id"]
    assert job["previous_job_id"] is None
    assert job["failure_code"] is None
    assert job["ended_at"] is None


async def test_jobs_are_listed_newest_first_filtered_and_paged(processing_api: Api) -> None:
    api = processing_api
    first = await queued(api, "a.png")
    second = await queued(api, "b.png")
    third = await queued(api, "c.png", tick=False)  # the same instant as the second
    await api.client.post(f"{RUNS}/{first['id']}/cancel")

    everything = (await api.client.get(JOBS)).json()
    cancelled = (await api.client.get(JOBS, params={"state": "CANCELLED"})).json()
    cleaning = (await api.client.get(JOBS, params={"type": "CLEAN_STORAGE"})).json()
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(5):  # bounded: a broken cursor must fail the test, not hang it
        params: dict[str, Any] = {"limit": 1} | ({"cursor": cursor} if cursor else {})
        page = (await api.client.get(JOBS, params=params)).json()
        seen += [j["id"] for j in page["items"]]
        cursor = page["page"]["next_cursor"]
        if cursor is None:
            break

    ids = [first["job"]["id"], second["job"]["id"], third["job"]["id"]]
    listed = [j["id"] for j in everything["items"]]
    assert listed[-1] == first["job"]["id"]  # the oldest is last
    assert listed[:2] == sorted([second["job"]["id"], third["job"]["id"]], reverse=True)  # ties
    assert seen == listed  # paging one at a time reads the same order: nothing lost or repeated
    assert sorted(seen) == sorted(ids)
    assert [j["id"] for j in cancelled["items"]] == [first["job"]["id"]]
    assert cleaning["items"] == []


async def test_job_filters_and_cursors_are_validated(processing_api: Api) -> None:
    api = processing_api
    await queued(api, "a.png")
    await queued(api, "b.png")
    wrong = (await api.client.get(JOBS, params={"limit": 1})).json()["page"]["next_cursor"]

    error(
        await api.client.get(JOBS, params={"state": "QUEUED", "cursor": wrong}),
        400,
        "INVALID_CURSOR",
    )
    error(await api.client.get(JOBS, params={"state": "NOPE"}), 422, "VALIDATION_ERROR")
    error(await api.client.get(JOBS, params={"type": "NOPE"}), 422, "VALIDATION_ERROR")
    error(await api.client.get(JOBS, params={"cursor": "junk"}), 400, "INVALID_CURSOR")
    elsewhere = encode_cursor("runs:None:None", ["2026-01-01T00:00:00+00:00", str(uuid.uuid4())])
    error(await api.client.get(JOBS, params={"cursor": elsewhere}), 400, "INVALID_CURSOR")
    forged = encode_cursor("jobs:None:None", ["not-a-date", "not-an-id"])
    error(await api.client.get(JOBS, params={"cursor": forged}), 400, "INVALID_CURSOR")
    error(await api.client.get(f"{JOBS}/{uuid.uuid4()}"), 404, "JOB_NOT_FOUND")
