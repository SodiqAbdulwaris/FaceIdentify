"""The processing routes: request processing, read runs, retry one (M4 W3.3; TST-045).

The application runs with a registered fake catalog and planted perception (no weights), and the
real scheduler, executor and acceptance, so a requested run is really processed.
"""

import asyncio
import uuid
from dataclasses import replace
from typing import Any

from sqlalchemy import update

from backend.api.pagination import encode_cursor
from backend.api.startup import ProcessingUnavailableError
from backend.app.jobs.models import Job
from backend.app.processing.models import ProcessingRun
from backend.app.sources.models import Artifact
from tests.fixtures.api import Api, error, imported

RUNS = "/api/v1/processing-runs"


async def process(api: Api, source: dict[str, Any], *, tick: bool = True) -> dict[str, Any]:
    if tick:
        api.clock.advance(seconds=1)  # runs are ordered by creation time
    response = await api.client.post(f"/api/v1/sources/{source['id']}/process")
    assert response.status_code == 202, response.text
    run: dict[str, Any] = response.json()
    return run


async def finished(api: Api, run_id: str, state: str = "COMPLETED") -> dict[str, Any]:
    """Poll the run over HTTP until it reaches `state` (the scheduler works in the background)."""
    async with asyncio.timeout(30):
        while True:
            run: dict[str, Any] = (await api.client.get(f"{RUNS}/{run_id}")).json()
            if run["state"] == state:
                return run
            assert run["state"] not in ("FAILED", "NOT_RESUMABLE"), run
            await asyncio.sleep(0.02)


def break_run(api: Api, run_id: str) -> None:
    """Leave a run and its job as a crash or a failure would: FAILED."""
    assert api.backend.library is not None
    with api.backend.library.session_factory() as session:
        run_uuid = uuid.UUID(run_id)
        now = api.backend.settings.clock()
        session.execute(
            update(ProcessingRun)
            .where(ProcessingRun.id == run_uuid)
            .values(state="FAILED", failed_at=now, failure_code="TEST_FAILURE")
        )
        session.execute(
            update(Job)
            .where(Job.processing_run_id == run_uuid)
            .values(state="FAILED", ended_at=now, failure_code="TEST_FAILURE")
        )
        session.commit()


# --- process --------------------------------------------------------------------------------


async def test_processing_a_source_is_accepted_tracked_and_completed(processing_api: Api) -> None:
    api = processing_api
    source = await imported(api, path=str(api.image()))

    accepted = await process(api, source)

    assert accepted["source_id"] == source["id"]
    assert accepted["state"] in ("PENDING", "RUNNING", "FINALIZING", "COMPLETED")
    assert accepted["job"]["priority"] == "INTERACTIVE"
    assert accepted["parent_run_id"] is None
    run = await finished(api, accepted["id"])
    assert run["job"]["state"] == "COMPLETED"
    assert run["job"]["id"] == accepted["job"]["id"]
    detail = (await api.client.get(f"/api/v1/sources/{source['id']}")).json()
    assert detail["processing_status"] == "COMPLETED"
    assert detail["latest_processing_run"] == {"id": accepted["id"], "state": "COMPLETED"}


async def test_processing_an_unknown_source_is_404(processing_api: Api) -> None:
    missing = uuid.uuid4()

    body = error(
        await processing_api.client.post(f"/api/v1/sources/{missing}/process"),
        404,
        "SOURCE_NOT_FOUND",
    )

    assert body["details"] == {"source_id": str(missing)}


async def test_a_source_whose_original_is_gone_cannot_be_processed(processing_api: Api) -> None:
    api = processing_api
    source = await imported(api, path=str(api.image()))
    assert api.backend.library is not None
    with api.backend.library.session_factory() as session:
        session.execute(update(Artifact).values(state="MISSING"))
        session.commit()

    body = error(
        await api.client.post(f"/api/v1/sources/{source['id']}/process"),
        409,
        "SOURCE_NOT_PROCESSABLE",
    )

    assert "not available" in body["details"]["reason"]
    assert (await api.client.get(RUNS)).json()["items"] == []  # nothing was queued


async def test_processing_waits_for_a_configured_processing_profile(processing_api: Api) -> None:
    api = processing_api
    source = await imported(api, path=str(api.image()))
    assert api.backend.processing is not None

    def no_profile(_session: Any) -> dict[str, Any]:
        raise ProcessingUnavailableError

    api.backend.processing = replace(api.backend.processing, request_for=no_profile)

    error(
        await api.client.post(f"/api/v1/sources/{source['id']}/process"),
        503,
        "PROCESSING_UNAVAILABLE",
    )
    assert (await api.client.get(RUNS)).json()["items"] == []


async def test_processing_is_unavailable_when_it_is_not_configured(api: Api) -> None:
    source = await imported(api, path=str(api.image()))

    error(
        await api.client.post(f"/api/v1/sources/{source['id']}/process"),
        503,
        "PROCESSING_UNAVAILABLE",
    )


# --- reads ----------------------------------------------------------------------------------


async def test_runs_are_listed_newest_first_and_filtered(processing_api: Api) -> None:
    api = processing_api
    first = await imported(api, path=str(api.image("a.png")))
    second = await imported(api, path=str(api.image("b.png")))
    run_a = await process(api, first)
    await finished(api, run_a["id"])
    run_b = await process(api, second)
    await finished(api, run_b["id"])
    break_run(api, run_a["id"])

    everything = (await api.client.get(RUNS)).json()
    of_first = (await api.client.get(RUNS, params={"source_id": first["id"]})).json()
    of_source = (await api.client.get(f"/api/v1/sources/{first['id']}/processing-runs")).json()
    failed = (await api.client.get(RUNS, params={"state": "FAILED"})).json()

    assert [r["id"] for r in everything["items"]] == [run_b["id"], run_a["id"]]
    assert (
        [r["id"] for r in of_first["items"]]
        == [run_a["id"]]
        == [r["id"] for r in of_source["items"]]
    )
    assert [r["id"] for r in failed["items"]] == [run_a["id"]]
    assert failed["items"][0]["failure_code"] == "TEST_FAILURE"
    assert failed["items"][0]["job"]["state"] == "FAILED"


async def test_runs_are_paged_by_cursor_and_the_cursor_is_bound_to_the_query(
    processing_api: Api,
) -> None:
    api = processing_api
    source = await imported(api, path=str(api.image()))
    ids = []
    for _ in range(3):
        run = await process(api, source)
        await finished(api, run["id"])
        ids.append(run["id"])

    seen: list[str] = []
    cursor: str | None = None
    for _ in range(3):
        params: dict[str, Any] = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        body = (await api.client.get(RUNS, params=params)).json()
        seen += [r["id"] for r in body["items"]]
        cursor = body["page"]["next_cursor"]
        if cursor is None:
            break

    assert sorted(seen) == sorted(ids)
    assert seen == ids[::-1]  # newest first
    first_page = (await api.client.get(RUNS, params={"limit": 1})).json()
    wrong = first_page["page"]["next_cursor"]
    error(
        await api.client.get(RUNS, params={"state": "COMPLETED", "cursor": wrong}),
        400,
        "INVALID_CURSOR",
    )
    error(await api.client.get(RUNS, params={"cursor": "junk"}), 400, "INVALID_CURSOR")
    forged = encode_cursor("runs:None:None", ["not-a-date", "not-an-id"])
    error(await api.client.get(RUNS, params={"cursor": forged}), 400, "INVALID_CURSOR")


async def test_runs_created_at_the_same_instant_are_paged_without_loss_or_repeats(
    processing_api: Api,
) -> None:
    api = processing_api
    source = await imported(api, path=str(api.image()))
    ids = []
    for _ in range(4):  # the clock is frozen: every run has the same creation time
        run = await process(api, source, tick=False)
        await finished(api, run["id"])
        ids.append(run["id"])

    seen: list[str] = []
    cursor: str | None = None
    for _ in range(6):  # bounded: a broken cursor must fail the test, not hang it
        params: dict[str, Any] = {"limit": 1} | ({"cursor": cursor} if cursor else {})
        body = (await api.client.get(RUNS, params=params)).json()
        seen += [r["id"] for r in body["items"]]
        cursor = body["page"]["next_cursor"]
        if cursor is None:
            break

    assert sorted(seen) == sorted(ids)  # none lost, none repeated
    assert seen == sorted(ids, reverse=True)  # ties break by id, descending


async def test_an_unknown_run_state_or_source_is_refused(processing_api: Api) -> None:
    api = processing_api

    error(await api.client.get(RUNS, params={"state": "NOPE"}), 422, "VALIDATION_ERROR")
    error(
        await api.client.get(f"/api/v1/sources/{uuid.uuid4()}/processing-runs"),
        404,
        "SOURCE_NOT_FOUND",
    )
    error(await api.client.get(f"{RUNS}/{uuid.uuid4()}"), 404, "RUN_NOT_FOUND")


async def test_a_run_with_no_job_is_listed_without_one(processing_api: Api) -> None:
    api = processing_api
    source = await imported(api, path=str(api.image()))
    run = await process(api, source)
    await finished(api, run["id"])
    assert api.backend.library is not None
    with api.backend.library.session_factory() as session:
        session.execute(update(Job).values(processing_run_id=None, type="CLEAN_STORAGE"))
        session.commit()

    assert (await api.client.get(f"{RUNS}/{run['id']}")).json()["job"] is None


async def test_a_jobs_progress_is_reported_once_recorded(processing_api: Api) -> None:
    api = processing_api
    source = await imported(api, path=str(api.image()))
    run = await process(api, source)
    done = await finished(api, run["id"])
    assert done["job"]["progress"] is None  # indeterminate until a count is recorded
    assert api.backend.library is not None
    with api.backend.library.session_factory() as session:
        session.execute(update(Job).values(progress_completed=2, progress_total=5))
        session.commit()

    reported = (await api.client.get(f"{RUNS}/{run['id']}")).json()["job"]["progress"]

    assert reported == {"completed": 2, "total": 5}


# --- retry ----------------------------------------------------------------------------------


async def test_a_failed_run_is_retried_once_as_a_new_linked_run(processing_api: Api) -> None:
    api = processing_api
    source = await imported(api, path=str(api.image()))
    old = await process(api, source)
    await finished(api, old["id"])
    break_run(api, old["id"])

    accepted = await api.client.post(f"{RUNS}/{old['id']}/retry")

    assert accepted.status_code == 202, accepted.text
    new = accepted.json()
    assert new["id"] != old["id"]
    assert new["source_id"] == source["id"]
    assert new["job"]["id"] != old["job"]["id"]
    await finished(api, new["id"])
    again = error(await api.client.post(f"{RUNS}/{old['id']}/retry"), 409, "RUN_NOT_RETRYABLE")
    assert "already been retried" in again["details"]["reason"]
    assert (await api.client.get(f"{RUNS}/{old['id']}")).json()["state"] == "FAILED"  # as it ended
    lineage = (await api.client.get(f"/api/v1/jobs/{new['job']['id']}")).json()
    assert lineage["previous_job_id"] == old["job"]["id"]  # a retry is a new job linked to the old
    assert new["parent_run_id"] == old["id"]


async def test_a_completed_or_unknown_run_cannot_be_retried(processing_api: Api) -> None:
    api = processing_api
    source = await imported(api, path=str(api.image()))
    run = await process(api, source)
    await finished(api, run["id"])

    error(await api.client.post(f"{RUNS}/{run['id']}/retry"), 409, "RUN_NOT_RETRYABLE")
    error(await api.client.post(f"{RUNS}/{uuid.uuid4()}/retry"), 404, "RUN_NOT_FOUND")


async def test_a_run_with_no_processing_job_cannot_be_retried(processing_api: Api) -> None:
    api = processing_api
    source = await imported(api, path=str(api.image()))
    run = await process(api, source)
    await finished(api, run["id"])
    assert api.backend.library is not None
    with api.backend.library.session_factory() as session:
        session.execute(update(Job).values(type="CLEAN_STORAGE"))
        session.commit()

    body = error(await api.client.post(f"{RUNS}/{run['id']}/retry"), 409, "RUN_NOT_RETRYABLE")

    assert "no processing job" in body["details"]["reason"]
