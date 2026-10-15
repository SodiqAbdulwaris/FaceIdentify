"""A missing original comes back: on-access verification, Recheck File and Locate Original (#179).

Owner decision 2026-10-14: a source whose original is MISSING is verified again when it is opened
or used and on request; a referenced original can be located; a file that differs from the
recorded one is never accepted; failure leaves the source missing with a reason; a repeat is
harmless; the result survives a restart. Real application, real library, real files.
"""

import base64
import secrets
import shutil
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from sqlalchemy import select

from backend.api.startup import MediaLimits, create_backend_app
from backend.app.sources import recheck as recheck_module
from backend.app.sources import referenced_artifacts
from backend.app.sources.artifact_storage import ArtifactStateError
from backend.app.sources.models import Artifact, ArtifactState, Source
from backend.app.sources.recheck import recheck_original
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

V1 = "/api/v1/sources"


def _original(api: Api, source_id: str) -> Artifact:
    assert api.backend.library is not None
    with api.backend.library.session_factory() as session:
        artifact = session.scalars(
            select(Artifact)
            .join(Source, Source.original_artifact_id == Artifact.id)
            .where(Source.id == uuid.UUID(source_id))
        ).one()
        session.expunge(artifact)
        return artifact


def _mark_missing(api: Api, source_id: str, code: str) -> None:
    """What startup recovery does when it finds the file gone."""
    assert api.backend.library is not None
    with api.backend.library.session_factory() as session:
        artifact = session.get(Artifact, _original(api, source_id).id)
        assert artifact is not None
        artifact.state, artifact.failure_code = ArtifactState.MISSING, code
        session.commit()


def _managed_path(api: Api, source_id: str) -> Path:
    key = _original(api, source_id).storage_key
    assert key is not None
    assert api.backend.library is not None
    return api.backend.library.store.roots.path_for(key)


def _other_image(path: Path) -> None:
    Image.new("RGB", (4, 3), "black").save(path, format="PNG")  # same name, different media


async def _detail(api: Api, source_id: str) -> dict[str, Any]:
    response = await api.client.get(f"{V1}/{source_id}")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


# --- on access ------------------------------------------------------------------------------


async def test_opening_a_source_whose_referenced_file_came_back_makes_it_available(
    api: Api,
) -> None:
    path = api.image("trip.png")
    source = await imported(api, path=str(path), storage_mode="REFERENCED")
    kept = api.folder / "kept.png"
    shutil.move(path, kept)  # the user moved the file away
    _mark_missing(api, source["id"], "REFERENCED_FILE_MISSING")

    while_gone = await _detail(api, source["id"])
    shutil.move(kept, path)  # and put it back
    back = await _detail(api, source["id"])

    assert while_gone["availability"] == "MISSING"
    assert while_gone["availability_reason"] == "REFERENCED_FILE_MISSING"
    assert while_gone["original"] is None
    assert back["availability"] == "AVAILABLE"
    assert back["availability_reason"] is None
    assert back["original"] is not None
    assert (await api.client.get(back["original"]["url"])).content == path.read_bytes()
    assert (back["id"], back["display_name"]) == (source["id"], source["display_name"])


async def test_opening_a_source_never_accepts_a_different_file_in_the_originals_place(
    api: Api,
) -> None:
    path = api.image("portrait.png")
    source = await imported(api, path=str(path), storage_mode="REFERENCED")
    _mark_missing(api, source["id"], "REFERENCED_FILE_MISSING")
    _other_image(path)  # something else now has the name

    detail = await _detail(api, source["id"])

    assert detail["availability"] == "MISSING"
    assert detail["availability_reason"] == "REFERENCED_CONTENT_CHANGED"
    error(await api.client.get(f"{V1}/{source['id']}/media"), 404, "SOURCE_FILE_MISSING")


async def test_a_listing_does_not_verify_anything(api: Api) -> None:
    path = api.image("quiet.png")
    source = await imported(api, path=str(path), storage_mode="REFERENCED")
    _mark_missing(api, source["id"], "REFERENCED_FILE_MISSING")

    listed = (await api.client.get(V1)).json()["items"]

    assert [item["availability"] for item in listed] == ["MISSING"]  # no library-wide scan
    assert _original(api, source["id"]).state == ArtifactState.MISSING


async def test_processing_a_source_whose_file_came_back_verifies_it_first(
    processing_api: Api,
) -> None:
    api = processing_api
    source = await imported(api, path=str(api.image()))
    _mark_missing(api, source["id"], "MANAGED_FILE_MISSING")  # flagged, but the file is there

    response = await api.client.post(f"{V1}/{source['id']}/process")

    assert response.status_code == 202, response.text
    assert _original(api, source["id"]).state == ArtifactState.AVAILABLE


# --- Recheck File ---------------------------------------------------------------------------


async def test_recheck_brings_back_a_restored_managed_original(api: Api) -> None:
    source = await imported(api, path=str(api.image("home.png")))
    managed = _managed_path(api, source["id"])
    saved = managed.read_bytes()
    managed.unlink()
    _mark_missing(api, source["id"], "MANAGED_FILE_MISSING")

    still = (await api.client.post(f"{V1}/{source['id']}/recheck")).json()
    managed.write_bytes(saved)  # restored from a backup
    back = (await api.client.post(f"{V1}/{source['id']}/recheck")).json()

    assert still["availability"] == "MISSING"
    assert still["availability_reason"] == "MANAGED_FILE_MISSING"
    assert back["availability"] == "AVAILABLE"
    assert (await api.client.get(f"{V1}/{source['id']}/media")).content == saved


async def test_recheck_keeps_a_managed_original_missing_when_its_bytes_differ(api: Api) -> None:
    source = await imported(api, path=str(api.image("home.png")))
    managed = _managed_path(api, source["id"])
    _mark_missing(api, source["id"], "MANAGED_FILE_MISSING")
    _other_image(managed)

    after = (await api.client.post(f"{V1}/{source['id']}/recheck")).json()

    assert after["availability"] == "MISSING"


async def test_recheck_is_harmless_to_repeat_and_to_an_available_original(api: Api) -> None:
    source = await imported(api, path=str(api.image()))
    before = _original(api, source["id"])

    first = (await api.client.post(f"{V1}/{source['id']}/recheck")).json()
    second = (await api.client.post(f"{V1}/{source['id']}/recheck")).json()

    after = _original(api, source["id"])
    assert first["availability"] == second["availability"] == "AVAILABLE"
    assert (after.state, after.failure_code, after.available_at) == (
        before.state,
        before.failure_code,
        before.available_at,
    )


async def test_recheck_of_an_unknown_source_is_404(api: Api) -> None:
    error(await api.client.post(f"{V1}/{uuid.UUID(int=1)}/recheck"), 404, "SOURCE_NOT_FOUND")


async def test_a_file_that_is_there_but_unreadable_changes_nothing(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = api.image("locked.png")
    source = await imported(api, path=str(path), storage_mode="REFERENCED")
    _mark_missing(api, source["id"], "REFERENCED_FILE_MISSING")

    def locked(_path: Path) -> Any:
        raise PermissionError("in use by another program")

    monkeypatch.setattr(referenced_artifacts, "digest_path", locked)

    refused = error(
        await api.client.post(f"{V1}/{source['id']}/recheck"), 409, "SOURCE_FILE_UNREADABLE"
    )
    opened = await _detail(api, source["id"])  # on access: best effort, still answers

    assert refused["details"] == {"source_id": source["id"]}
    assert opened["availability"] == "MISSING"
    assert _original(api, source["id"]).failure_code == "REFERENCED_FILE_MISSING"


# --- Locate Original ------------------------------------------------------------------------


async def test_locating_the_moved_original_relinks_it(api: Api) -> None:
    path = api.image("wedding.png")
    source = await imported(api, path=str(path), storage_mode="REFERENCED")
    moved = api.folder / "albums" / "wedding.png"
    moved.parent.mkdir()
    shutil.move(path, moved)
    _mark_missing(api, source["id"], "REFERENCED_FILE_MISSING")

    response = await api.client.post(f"{V1}/{source['id']}/relink", json={"path": str(moved)})

    assert response.status_code == 200, response.text
    relinked = response.json()
    assert relinked["availability"] == "AVAILABLE"
    assert str(moved) not in response.text  # paths are never answered
    assert (await api.client.get(relinked["original"]["url"])).content == moved.read_bytes()
    assert _original(api, source["id"]).external_path == str(moved.resolve())


async def test_locating_a_different_file_is_refused_and_leaves_the_source_missing(
    api: Api,
) -> None:
    path = api.image("wedding.png")
    source = await imported(api, path=str(path), storage_mode="REFERENCED")
    path.unlink()
    _mark_missing(api, source["id"], "REFERENCED_FILE_MISSING")
    impostor = api.folder / "wedding-copy.png"
    _other_image(impostor)

    error(
        await api.client.post(f"{V1}/{source['id']}/relink", json={"path": str(impostor)}),
        409,
        "SOURCE_RELINK_MISMATCH",
    )

    after = _original(api, source["id"])
    assert (after.state, after.external_path) == (ArtifactState.MISSING, str(path.resolve()))


async def test_locate_is_refused_where_it_does_not_apply(api: Api) -> None:
    managed = await imported(api, path=str(api.image("m.png")))
    path = api.image("r.png")
    present = await imported(api, path=str(path), storage_mode="REFERENCED")
    gone_path = api.image("g.png")
    gone = await imported(api, path=str(gone_path), storage_mode="REFERENCED")
    _mark_missing(api, gone["id"], "REFERENCED_FILE_MISSING")
    assert api.backend.library is not None
    inside = api.backend.library.roots.library_root / "planted.png"
    shutil.copy(gone_path, inside)
    post = api.client.post

    error(
        await post(f"{V1}/{managed['id']}/relink", json={"path": str(path)}),
        409,
        "SOURCE_NOT_REFERENCED",
    )
    conflict = error(
        await post(f"{V1}/{present['id']}/relink", json={"path": str(path)}),
        409,
        "SOURCE_STATE_CONFLICT",
    )
    error(
        await post(f"{V1}/{gone['id']}/relink", json={"path": str(inside)}),
        400,
        "REFERENCED_FILE_INVALID",
    )  # the library's own tree is never a referenced original
    error(
        await post(f"{V1}/{gone['id']}/relink", json={"path": "relative.png"}),
        422,
        "VALIDATION_ERROR",
    )
    error(
        await post(f"{V1}/{uuid.UUID(int=1)}/relink", json={"path": str(path)}),
        404,
        "SOURCE_NOT_FOUND",
    )
    assert conflict["details"]["availability"] == "AVAILABLE"


async def test_an_original_with_no_recorded_fingerprint_cannot_be_located(api: Api) -> None:
    path = api.image("old.png")
    source = await imported(api, path=str(path), storage_mode="REFERENCED")
    _mark_missing(api, source["id"], "REFERENCED_FILE_MISSING")
    assert api.backend.library is not None
    with api.backend.library.session_factory() as session:  # an import from before hashes
        artifact = session.get(Artifact, _original(api, source["id"]).id)
        assert artifact is not None
        artifact.sha256, artifact.size_bytes = None, None
        session.commit()

    error(
        await api.client.post(f"{V1}/{source['id']}/relink", json={"path": str(path)}),
        409,
        "SOURCE_RELINK_UNVERIFIABLE",
    )


# --- across a restart -----------------------------------------------------------------------


@asynccontextmanager
async def _running(
    tmp_path: Path, clock: FrozenClock, new_id: SeededUUIDs, folder: str
) -> AsyncIterator[Api]:
    secret = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
    app = create_backend_app(
        secret,
        library_settings(tmp_path, clock, new_id),
        media_limits=MediaLimits(max_pixels=MAX_PIXELS, max_bytes=MAX_BYTES),
    )
    async with serving(app, secret, tmp_path / folder, clock) as running:
        yield running


async def test_a_relinked_original_stays_available_after_a_restart(
    tmp_path: Path, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    async with _running(tmp_path, clock, new_id, "first") as api:
        path = api.image("kept.png")
        source = await imported(api, path=str(path), storage_mode="REFERENCED")
        moved = tmp_path / "elsewhere.png"
        shutil.move(path, moved)
        _mark_missing(api, source["id"], "REFERENCED_FILE_MISSING")
        relinked = await api.client.post(f"{V1}/{source['id']}/relink", json={"path": str(moved)})
        assert relinked.status_code == 200, relinked.text

    async with _running(tmp_path, clock, new_id, "second") as api:
        detail = await _detail(api, source["id"])
        media = await api.client.get(f"{V1}/{source['id']}/media")

    assert detail["availability"] == "AVAILABLE"
    assert media.content == moved.read_bytes()


# --- the use case's own edges ---------------------------------------------------------------


async def test_rechecking_a_source_that_does_not_exist_is_a_lookup_error(api: Api) -> None:
    assert api.backend.library is not None
    library = api.backend.library

    with pytest.raises(LookupError):
        recheck_original(library.session_factory, library.store, uuid.UUID(int=2), clock=api.clock)


async def test_a_recheck_that_races_another_answers_what_the_other_settled(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = api.image("raced.png")
    source = await imported(api, path=str(path), storage_mode="REFERENCED")
    _mark_missing(api, source["id"], "REFERENCED_FILE_MISSING")
    assert api.backend.library is not None
    library = api.backend.library
    artifact_id = _original(api, source["id"]).id

    def raced(session_factory: Any, artifact: uuid.UUID, **_: Any) -> str:
        # Another request brought it back first, so this one's guarded transition finds nothing.
        with session_factory() as session:
            row = session.get(Artifact, artifact)
            row.state, row.failure_code = ArtifactState.AVAILABLE, None
            session.commit()
        raise ArtifactStateError("settled by a concurrent recheck")

    monkeypatch.setattr(recheck_module, "reverify_referenced_artifact", raced)

    result = recheck_original(
        library.session_factory, library.store, uuid.UUID(source["id"]), clock=api.clock
    )

    assert (result.state, result.reason, result.recovered) == ("AVAILABLE", None, True)
    assert _original(api, source["id"]).id == artifact_id
