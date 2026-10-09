"""Permanently deleting a Source through the API (M5 step 4b; API section 5.7; TST-059).

Deleting is only for a Source already in the Recycle Bin. Afterwards the image is gone from every
view, its faces and (when nothing else shows them) their identities with it, and the application
starts cleanly on a library whose deletion a crash cut short.
"""

import base64
import io
import secrets
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select, update

from backend.api.startup import MediaLimits, create_backend_app
from backend.app.lifecycle import open_library
from backend.app.memory.models import Representation
from backend.app.processing.models import ProcessingRun
from backend.app.sources.models import Artifact, ArtifactState, Source
from backend.app.sources.permanent_delete import PermanentSourceDeletion
from backend.infrastructure.storage.files import ManagedFileStore
from tests.factories.models import ModelFactory
from tests.fixtures.api import (
    MAX_BYTES,
    MAX_PIXELS,
    Api,
    error,
    imported,
    library_settings,
    serving,
)
from tests.fixtures.deterministic import FrozenClock, SeededUUIDs
from tests.integration.test_api_memory import processed

SOURCES = "/api/v1/sources"
IDENTITIES = "/api/v1/identities"
DELETE = "permanent-delete"


async def recycled(api: Api, **body: Any) -> dict[str, Any]:
    source = await imported(api, path=str(api.image()), **body)
    assert (await api.client.delete(f"{SOURCES}/{source['id']}")).status_code == 204
    return source


async def listed(api: Api, **query: str) -> list[str]:
    response = await api.client.get(SOURCES, params=query)
    return [item["id"] for item in response.json()["items"]]


async def assert_gone_from_every_route(api: Api, source_id: str) -> None:
    """A source whose deletion is pending (or done) is found by no route that serves sources."""
    base = f"{SOURCES}/{source_id}"
    for response in (
        await api.client.get(base),
        await api.client.get(f"{base}/media"),
        await api.client.get(f"{base}/occurrences"),
        await api.client.get(f"{base}/unresolved-faces"),
        await api.client.get(f"{base}/processing-runs"),
        await api.client.delete(base),
        await api.client.post(f"{base}/restore"),
    ):
        error(response, 404, "SOURCE_NOT_FOUND")
    assert source_id not in await listed(api)
    assert source_id not in await listed(api, state="RECYCLED")


async def test_a_recycled_source_is_deleted_for_good_and_announced_once(api: Api) -> None:
    source = await recycled(api)
    subscription = api.backend.events.subscribe()
    try:
        deleted = await api.client.post(f"{SOURCES}/{source['id']}/{DELETE}")
        again = await api.client.post(f"{SOURCES}/{source['id']}/{DELETE}")
        events = []
        while not subscription.queue.empty():
            events.append(subscription.queue.get_nowait())
    finally:
        api.backend.events.unsubscribe(subscription)

    assert (deleted.status_code, again.status_code) == (204, 204)  # a repeat is harmless
    assert deleted.content == b""
    assert await listed(api) == []
    assert await listed(api, state="RECYCLED") == []
    assert (await api.client.get(f"{SOURCES}/{source['id']}")).status_code == 404
    assert (await api.client.get(f"{SOURCES}/{source['id']}/media")).status_code in (404, 410)
    assert [(e["type"], e["resource"]["id"]) for e in events] == [("source.updated", source["id"])]
    assert api.backend.library is not None
    with api.backend.library.session_factory() as session:
        [original] = session.scalars(select(Artifact))
        assert original.state == ArtifactState.DELETED
        assert api.backend.library.store.digest(f"originals/{original.id.hex}") is None


async def test_a_source_in_the_library_cannot_be_deleted(api: Api) -> None:
    source = await imported(api, path=str(api.image()))

    body = error(
        await api.client.post(f"{SOURCES}/{source['id']}/{DELETE}"), 409, "SOURCE_NOT_RECYCLED"
    )

    assert body["details"] == {"source_id": source["id"]}
    assert await listed(api) == [source["id"]]
    assert (await api.client.get(f"{SOURCES}/{source['id']}/media")).status_code == 200


async def test_an_unknown_source_is_not_found(api: Api) -> None:
    missing = "00000000-0000-0000-0000-00000000dead"

    error(await api.client.post(f"{SOURCES}/{missing}/{DELETE}"), 404, "SOURCE_NOT_FOUND")


async def test_a_source_being_processed_is_busy(processing_api: Api) -> None:
    api = processing_api
    source = await recycled(api)
    assert api.backend.library is not None
    with api.backend.library.session_factory() as session:
        build = ModelFactory(session, api.clock, api.backend.settings.new_id)  # type: ignore[arg-type]
        build.run(source_id=uuid.UUID(source["id"]), state="RUNNING")
        session.commit()

    error(await api.client.post(f"{SOURCES}/{source['id']}/{DELETE}"), 409, "SOURCE_BUSY")

    with api.backend.library.session_factory() as session:
        assert session.scalar(select(Source.state)) == "RECYCLED"


async def test_deleting_the_only_image_of_a_face_removes_the_face_and_its_identity(
    processing_api: Api,
) -> None:
    api = processing_api
    source = await processed(api, "alice.png")
    [identity] = (await api.client.get(IDENTITIES)).json()["items"]
    await api.client.delete(f"{SOURCES}/{source['id']}")

    assert (await api.client.post(f"{SOURCES}/{source['id']}/{DELETE}")).status_code == 204

    assert (await api.client.get(IDENTITIES)).json()["items"] == []  # nothing left to show
    detail = await api.client.get(f"{IDENTITIES}/{identity['id']}")
    assert detail.status_code == 404 or detail.json()["state"] == "DELETED"
    assert api.backend.library is not None
    with api.backend.library.session_factory() as session:
        assert session.scalars(select(ProcessingRun.id)).all() == []


async def test_bytes_that_cannot_be_removed_leave_the_deletion_pending(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await recycled(api)
    assert api.backend.library is not None

    def locked(_key: str) -> None:
        raise PermissionError("in use")

    monkeypatch.setattr(api.backend.library.store, "delete", locked)
    pending = await api.client.post(f"{SOURCES}/{source['id']}/{DELETE}")

    assert pending.status_code == 202
    assert pending.json()["state"] == "DELETING"
    assert "PermissionError" in pending.json()["outstanding"][0]
    await assert_gone_from_every_route(api, source["id"])
    readiness = (await api.client.get("/readiness")).json()
    assert readiness["capabilities"]["recovery"] == "DEGRADED"  # the owed work stays visible
    monkeypatch.undo()

    assert (await api.client.post(f"{SOURCES}/{source['id']}/{DELETE}")).status_code == 204


def cut_short(
    tmp_path: Path, clock: FrozenClock, new_id: SeededUUIDs
) -> tuple[Any, uuid.UUID, str]:
    """A library whose deletion of one image began (intent recorded) and then stopped."""
    settings = library_settings(tmp_path, clock, new_id)
    with open_library(
        library_root=settings.library_root, local_state_root=settings.local_state_root,
        clock=clock, new_id=new_id, retry=settings.retry,
        transaction_retry=settings.transaction_retry, index_batch=50, max_index_passes=5,
    ) as lib:  # fmt: skip
        with lib.session_factory() as session:
            build = ModelFactory(session, clock, new_id)
            artifact = build.artifact()
            artifact.storage_key = f"originals/{artifact.id.hex}"
            lib.store.store(artifact.storage_key, io.BytesIO(b"an image"))
            source = build.source(original_artifact_id=artifact.id)
            session.commit()
            source_id, key = source.id, artifact.storage_key
        lib.unit_of_work.write(
            lambda session: session.execute(update(Source).values(state="RECYCLED"))
        )
        deletion = PermanentSourceDeletion(
            lib.session_factory, lib.unit_of_work, lib.eraser, lib.store, clock=clock
        )
        lib.unit_of_work.write(lambda session: deletion._begin(session, source_id, clock()))
        assert isinstance(lib.store, ManagedFileStore)
        assert lib.store.digest(key) is not None  # the crash came before the bytes were removed

    return settings, source_id, key


async def test_the_next_start_finishes_a_deletion_a_crash_cut_short(
    tmp_path: Path, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    settings, source_id, key = cut_short(tmp_path, clock, new_id)
    secret = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
    app = create_backend_app(
        secret, settings, media_limits=MediaLimits(max_pixels=MAX_PIXELS, max_bytes=MAX_BYTES)
    )
    async with serving(app, secret, tmp_path / "user-files", clock) as running:
        assert [(r.source_id, r.complete) for r in running.backend.deletions] == [(source_id, True)]
        assert running.backend.library is not None
        assert running.backend.library.store.digest(key) is None
        assert (await running.client.get(f"{SOURCES}/{source_id}")).status_code == 404
        assert "recovery" not in running.backend.capabilities or (
            running.backend.capabilities["recovery"] == "READY"
        )


async def test_a_deletion_still_owed_at_start_is_reported_as_degraded_recovery(
    tmp_path: Path, clock: FrozenClock, new_id: SeededUUIDs, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, source_id, _key = cut_short(tmp_path, clock, new_id)

    def locked(_self: Any, _key: str) -> None:
        raise PermissionError("in use")

    monkeypatch.setattr(ManagedFileStore, "delete", locked)
    secret = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
    app = create_backend_app(
        secret, settings, media_limits=MediaLimits(max_pixels=MAX_PIXELS, max_bytes=MAX_BYTES)
    )
    async with serving(app, secret, tmp_path / "user-files", clock) as running:
        assert [(r.source_id, r.complete) for r in running.backend.deletions] == [
            (source_id, False)
        ]
        assert running.backend.capabilities["recovery"] == "DEGRADED"
        await assert_gone_from_every_route(running, str(source_id))


async def assert_runs_and_jobs_are_gone(api: Api, source_id: str, run_id: str, job_id: str) -> None:
    runs = (await api.client.get("/api/v1/processing-runs")).json()["items"]
    assert run_id not in [run["id"] for run in runs]
    filtered = await api.client.get("/api/v1/processing-runs", params={"source_id": source_id})
    assert filtered.json()["items"] == []
    jobs = (await api.client.get("/api/v1/jobs")).json()["items"]
    assert job_id not in [job["id"] for job in jobs]
    error(await api.client.get(f"/api/v1/processing-runs/{run_id}"), 404, "RUN_NOT_FOUND")
    error(await api.client.post(f"/api/v1/processing-runs/{run_id}/retry"), 404, "RUN_NOT_FOUND")
    error(await api.client.post(f"/api/v1/processing-runs/{run_id}/cancel"), 404, "RUN_NOT_FOUND")
    error(await api.client.get(f"/api/v1/jobs/{job_id}"), 404, "JOB_NOT_FOUND")
    error(await api.client.post(f"/api/v1/jobs/{job_id}/cancel"), 404, "JOB_NOT_FOUND")
    error(await api.client.post(f"{SOURCES}/{source_id}/process"), 404, "SOURCE_NOT_FOUND")


async def test_the_runs_jobs_and_faces_of_a_pending_deletion_are_gone_too(
    processing_api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = processing_api
    source = await processed(api, "alice.png")
    [run] = (await api.client.get("/api/v1/processing-runs")).json()["items"]
    [job] = (await api.client.get("/api/v1/jobs")).json()["items"]
    assert api.backend.library is not None
    with api.backend.library.session_factory() as session:
        [face] = session.scalars(select(Representation.id))
    await api.client.delete(f"{SOURCES}/{source['id']}")

    def locked(_key: str) -> None:
        raise PermissionError("in use")

    monkeypatch.setattr(api.backend.library.store, "delete", locked)
    pending = await api.client.post(f"{SOURCES}/{source['id']}/{DELETE}")

    assert pending.status_code == 202
    await assert_runs_and_jobs_are_gone(api, source["id"], run["id"], job["id"])
    error(
        await api.client.post(
            f"/api/v1/representations/{face}/resolve", json={"identity_id": None}
        ),
        404,
        "FACE_NOT_FOUND",
    )
    monkeypatch.undo()

    assert (await api.client.post(f"{SOURCES}/{source['id']}/{DELETE}")).status_code == 204
    await assert_runs_and_jobs_are_gone(api, source["id"], run["id"], job["id"])


async def test_a_source_that_is_gone_is_not_found_even_when_processing_is_not_configured(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await recycled(api)
    assert api.backend.library is not None

    def locked(_key: str) -> None:
        raise PermissionError("in use")

    monkeypatch.setattr(api.backend.library.store, "delete", locked)
    assert (await api.client.post(f"{SOURCES}/{source['id']}/{DELETE}")).status_code == 202

    error(await api.client.post(f"{SOURCES}/{source['id']}/process"), 404, "SOURCE_NOT_FOUND")


async def test_a_run_deleted_while_it_is_being_cancelled_is_not_found(
    processing_api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.app.processing.cancel import CancelProcessingUseCase, RunNotFoundError

    api = processing_api
    await processed(api, "alice.png")
    [run] = (await api.client.get("/api/v1/processing-runs")).json()["items"]

    def vanished(_self: object, run_id: uuid.UUID) -> None:
        raise RunNotFoundError(f"run {run_id} does not exist")  # deleted after the check

    monkeypatch.setattr(CancelProcessingUseCase, "cancel", vanished)

    error(
        await api.client.post(f"/api/v1/processing-runs/{run['id']}/cancel"), 404, "RUN_NOT_FOUND"
    )


def begin_deleting(api: Api, source_id: str) -> None:
    """Commit the intent to delete a recycled source, as a deletion request does first."""
    assert api.backend.library is not None
    lib = api.backend.library
    steps = PermanentSourceDeletion(
        lib.session_factory, lib.unit_of_work, lib.eraser, lib.store,
        clock=api.backend.settings.clock,
    )  # fmt: skip
    lib.unit_of_work.write(
        lambda session: steps._begin(session, uuid.UUID(source_id), api.backend.settings.clock())
    )


@pytest.mark.parametrize("command", ["cancel", "retry", "process"])
async def test_a_command_refused_because_its_source_was_deleted_meanwhile_is_not_found(
    processing_api: Api, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    """The deletion begins after the route's visibility check and before the command's own write:
    the command's refusal (it names the run's state) must become the same 404 as everywhere else."""
    from backend.app.processing.cancel import CancelProcessingUseCase
    from backend.app.processing.process_source import ProcessSourceUseCase
    from backend.app.processing.retry import RetryProcessingUseCase

    api = processing_api
    source = await processed(api, "alice.png")
    [run] = (await api.client.get("/api/v1/processing-runs")).json()["items"]
    await api.client.delete(f"{SOURCES}/{source['id']}")
    runs = "/api/v1/processing-runs"
    cases = {
        "cancel": (CancelProcessingUseCase, f"{runs}/{run['id']}/cancel", "RUN_NOT_FOUND"),
        "retry": (RetryProcessingUseCase, f"{runs}/{run['id']}/retry", "RUN_NOT_FOUND"),
        "process": (ProcessSourceUseCase, f"{SOURCES}/{source['id']}/process", "SOURCE_NOT_FOUND"),
    }
    use_case, path, code = cases[command]
    method = command
    real = getattr(use_case, method)

    def deletion_begins_first(self: Any, *args: Any, **kwargs: Any) -> Any:
        begin_deleting(api, source["id"])
        return real(self, *args, **kwargs)

    monkeypatch.setattr(use_case, method, deletion_begins_first)

    error(await api.client.post(path), 404, code)
