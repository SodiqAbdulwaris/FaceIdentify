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
    assert (await api.client.get(f"{SOURCES}/{source['id']}")).json()["state"] == "DELETING"
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
        assert (await running.client.get(f"{SOURCES}/{source_id}")).json()["state"] == "DELETING"
