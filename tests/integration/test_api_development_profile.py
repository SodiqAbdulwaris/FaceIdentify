"""The development profile through the real sidecar host (M4; plan decision 1).

The host is started in this process on a real loopback socket, exactly as the desktop shell would
start it (`--development-profile`), and driven over HTTP: import images, process them with the fake
perception, read the results, stop it, start it again on the same library and carry on. Nothing is
planted by the test; the fake catalog, planner and perception are the production development
profile.
"""

import asyncio
import base64
import io
import json
import os
import secrets
import sqlite3
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest
from PIL import Image
from sqlalchemy import func, select

from backend.api import development
from backend.api.development import (
    DIMENSION,
    POLICY_VERSION,
    DevelopmentPerception,
    development_plan,
    development_request,
    register_development_catalog,
)
from backend.api.host import HostOptions, parse_options, serve
from backend.api.startup import ProcessingUnavailableError
from backend.app.lifecycle import open_library
from backend.app.runtime.models import Component, ModelExport
from backend.app.runtime.perception_client import Represented
from backend.app.sources.models import Artifact
from tests.fixtures.api import library_settings
from tests.fixtures.deterministic import FrozenClock, SeededUUIDs


def a_token() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")


def picture(folder: Path, name: str, colour: tuple[int, int, int]) -> Path:
    path = folder / name
    Image.new("RGB", (8, 6), colour).save(path, format="PNG")
    return path


async def until(condition: Callable[[], bool], seconds: float = 30) -> None:
    async with asyncio.timeout(seconds):
        while not condition():
            await asyncio.sleep(0.02)


@asynccontextmanager
async def host(tmp_path: Path, *, development_profile: bool) -> AsyncIterator[httpx.AsyncClient]:
    """The sidecar host serving the library under `tmp_path`, as a client for it."""
    (tmp_path / "library").mkdir(exist_ok=True)
    options = HostOptions(
        tmp_path / "library", tmp_path / "local", os.getpid(), development_profile
    )
    secret, out, alive = a_token(), io.StringIO(), True
    task = asyncio.create_task(
        serve(options, secret, out=out, parent_alive_check=lambda _pid: alive, poll_seconds=0.02)
    )
    await until(lambda: out.getvalue().endswith("\n") or task.done())
    assert not task.done(), "the host stopped before its handshake"
    port = json.loads(out.getvalue())["port"]
    async with httpx.AsyncClient(
        base_url=f"http://127.0.0.1:{port}", headers={"Authorization": f"Bearer {secret}"}
    ) as client:
        async with asyncio.timeout(60):
            while (await client.get("/readiness")).json()["state"] not in ("READY", "DEGRADED"):
                await asyncio.sleep(0.05)
        try:
            yield client
        finally:
            alive = False  # the shell has gone: the host shuts down
            await asyncio.wait_for(task, 30)


async def process_and_wait(client: httpx.AsyncClient, source_id: str) -> dict[str, Any]:
    response = await client.post(f"/api/v1/sources/{source_id}/process")
    assert response.status_code == 202, response.text
    run: dict[str, Any] = response.json()
    async with asyncio.timeout(60):
        while True:
            current: dict[str, Any] = (
                await client.get(f"/api/v1/processing-runs/{run['id']}")
            ).json()
            if current["state"] == "COMPLETED":
                return current
            assert current["state"] not in ("FAILED", "NOT_RESUMABLE", "CANCELLED"), current
            await asyncio.sleep(0.05)


async def import_image(client: httpx.AsyncClient, path: Path) -> dict[str, Any]:
    response = await client.post("/api/v1/sources/import", json={"path": str(path)})
    assert response.status_code == 201, response.text
    source: dict[str, Any] = response.json()
    return source


async def identities(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = (await client.get("/api/v1/identities")).json()["items"]
    return items


# --- the whole thing, over HTTP, across a restart -------------------------------------------


async def test_the_development_host_processes_images_and_remembers_them_across_a_restart(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "pictures"
    folder.mkdir()
    red, red_again = picture(folder, "red.png", (200, 0, 0)), picture(folder, "r2.png", (200, 0, 0))
    blue = picture(folder, "blue.png", (0, 0, 200))

    async with host(tmp_path, development_profile=True) as client:
        ready = (await client.get("/readiness")).json()
        assert ready["capabilities"]["scheduler"] == "READY"
        first = await import_image(client, red)
        run = await process_and_wait(client, first["id"])
        assert run["policy"] == {  # what the UI shows as the uncalibrated-policy notice
            "calibration_mode": "UNCALIBRATED",
            "decision_policy_version": POLICY_VERSION,
            "calibrated": False,
            "automatic_matching": True,
        }
        await process_and_wait(client, (await import_image(client, red_again))["id"])
        await process_and_wait(client, (await import_image(client, blue))["id"])

        found = await identities(client)
        assert sorted(i["occurrence_count"] for i in found) == [1, 2]  # same picture, same person
        faces = (await client.get(f"/api/v1/sources/{first['id']}/occurrences")).json()["items"]
        assert faces[0]["representative_observation"]["bounding_box"]["width"] > 0

    async with host(tmp_path, development_profile=True) as client:  # the application restarted
        after = await identities(client)
        assert {i["id"] for i in after} == {i["id"] for i in found}
        again = await import_image(client, picture(folder, "r3.png", (200, 0, 0)))
        await process_and_wait(client, again["id"])

        recognised = await identities(client)
        assert len(recognised) == 2  # the persisted memory recognised it: no third identity
        assert sorted(i["occurrence_count"] for i in recognised) == [1, 3]


async def test_without_the_development_profile_importing_works_and_processing_is_unavailable(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "pictures"
    folder.mkdir()

    async with host(tmp_path, development_profile=False) as client:
        source = await import_image(client, picture(folder, "a.png", (1, 2, 3)))
        refused = await client.post(f"/api/v1/sources/{source['id']}/process")

        assert refused.status_code == 503
        assert refused.json()["error"]["code"] == "PROCESSING_UNAVAILABLE"
        ready = (await client.get("/readiness")).json()
        # The real profile with no package and no measured policy: the scheduler runs (there is
        # nothing to claim) and the worker is reported unavailable, never substituted.
        assert ready["capabilities"]["scheduler"] == "READY"
        assert ready["capabilities"]["ml_worker"] == "UNAVAILABLE"
        assert ready["state"] == "DEGRADED"


def test_the_flag_is_off_by_default_and_on_when_asked(tmp_path: Path) -> None:
    base = ["--library-root", str(tmp_path / "l"), "--local-state-root", str(tmp_path / "s")]

    assert parse_options(base).development_profile is False
    assert parse_options([*base, "--development-profile"]).development_profile is True


# --- the pieces -----------------------------------------------------------------------------


def test_the_catalog_is_registered_once_and_survives_being_registered_again(
    tmp_path: Path, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    settings = library_settings(tmp_path, clock, new_id)
    with open_library(
        library_root=settings.library_root, local_state_root=settings.local_state_root,
        clock=clock, new_id=new_id, retry=settings.retry,
        transaction_retry=settings.transaction_retry, index_batch=50, max_index_passes=5,
    ) as library:  # fmt: skip
        first = register_development_catalog(library, clock, new_id)
    with open_library(
        library_root=settings.library_root, local_state_root=settings.local_state_root,
        clock=clock, new_id=new_id, retry=settings.retry,
        transaction_retry=settings.transaction_retry, index_batch=50, max_index_passes=5,
    ) as library:  # fmt: skip  # restarted: startup recovery has looked at the catalog's files
        again = register_development_catalog(library, clock, new_id)

        assert again == first
        with library.session_factory() as session:
            assert session.scalar(select(func.count()).select_from(Component)) == 2
            assert session.scalar(select(func.count()).select_from(ModelExport)) == 2
            artifacts = session.scalars(
                select(Artifact.state).where(Artifact.kind == "MODEL_EXPORT")
            )
            assert list(artifacts) == ["AVAILABLE", "AVAILABLE"]
            request = development_request(session)
            plan = development_plan(
                session,
                None,
                detector_component_version_id=first.detector_version_id,
                representation_space_id=first.space_id,
                providers=["CPUExecutionProvider"],
                detector_model_export_id=first.detector_export_id,
                embedder_model_export_id=first.embedder_export_id,
            )
        assert request["representation_space_id"] == str(first.space_id)
        assert request["decision_policy"] == {  # clearly named, provisional, and well separated
            "schema_version": 1,
            "version": "development-uncalibrated-v1",
            "min_detection_score": 0.1,
            "new_identity_ceiling": 0.5,
            "match_threshold": 0.9,
            "margin": 0.1,
        }
        assert request["calibration"]["mode"] == "UNCALIBRATED"
        assert plan.dimension == DIMENSION
        assert plan.detector[0].kind == "FACE_DETECTOR"
        assert plan.embedder[0].kind == "FACE_REPRESENTATION"


def test_a_request_cannot_be_built_before_the_catalog_is_registered(
    tmp_path: Path, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    settings = library_settings(tmp_path, clock, new_id)
    with open_library(
        library_root=settings.library_root, local_state_root=settings.local_state_root,
        clock=clock, new_id=new_id, retry=settings.retry,
        transaction_retry=settings.transaction_retry, index_batch=50, max_index_passes=5,
    ) as library:  # fmt: skip
        with library.session_factory() as session, pytest.raises(ProcessingUnavailableError):
            development_request(session)


def test_the_perception_is_deterministic_and_tells_pictures_apart(
    tmp_path: Path, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    settings = library_settings(tmp_path, clock, new_id)
    with open_library(
        library_root=settings.library_root, local_state_root=settings.local_state_root,
        clock=clock, new_id=new_id, retry=settings.retry,
        transaction_retry=settings.transaction_retry, index_batch=50, max_index_passes=5,
    ) as library:  # fmt: skip
        catalog = register_development_catalog(library, clock, new_id)
        with library.session_factory() as session:
            plan = development_plan(
                session, None,
                detector_component_version_id=catalog.detector_version_id,
                representation_space_id=catalog.space_id,
                providers=["CPUExecutionProvider"],
                detector_model_export_id=catalog.detector_export_id,
                embedder_model_export_id=catalog.embedder_export_id,
            )  # fmt: skip
    perception = DevelopmentPerception(plan)
    one = np.zeros((6, 8, 3), dtype=np.uint8)
    other = one.copy()
    other[0, 0, 0] = 1

    detected = perception.detect(one)
    a = perception.represent(one, detected.detections).vectors[0].vector
    again = perception.represent(one.copy(), detected.detections).vectors[0].vector
    b = perception.represent(other, detected.detections).vectors[0].vector

    assert perception.represent(one, ()) == Represented((), None)  # no face, nothing represented
    two = (*detected.detections, replace(detected.detections[0], detection_index=1))
    assert [v.detection_index for v in perception.represent(one, two).vectors] == [0, 1]
    assert detected.detections[0].box == (0.2, 0.2, 0.8, 0.8)
    assert np.array_equal(a, again)  # the same picture is the same vector
    assert float(np.linalg.norm(a)) == pytest.approx(1.0, abs=1e-5)
    assert float(a @ b) < 0.5  # a different picture is far away (below the new-identity ceiling)


async def test_a_profile_that_cannot_register_leaves_the_backend_failed_not_half_started(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("cannot register")

    monkeypatch.setattr(development, "register_development_catalog", broken)
    (tmp_path / "library").mkdir()
    options = HostOptions(tmp_path / "library", tmp_path / "local", os.getpid(), True)
    secret, out, alive = a_token(), io.StringIO(), True
    task = asyncio.create_task(
        serve(options, secret, out=out, parent_alive_check=lambda _pid: alive, poll_seconds=0.02)
    )
    await until(lambda: out.getvalue().endswith("\n") or task.done())
    port = json.loads(out.getvalue())["port"]
    async with httpx.AsyncClient(
        base_url=f"http://127.0.0.1:{port}", headers={"Authorization": f"Bearer {secret}"}
    ) as client:
        async with asyncio.timeout(60):
            while (await client.get("/readiness")).json()["state"] == "INITIALIZING":
                await asyncio.sleep(0.05)
        ready = (await client.get("/readiness")).json()

        assert ready["state"] == "FAILED"
        assert ready["failure"] == "RuntimeError"
        assert ready.get("capabilities", {}).get("scheduler") != "READY"
        alive = False
        await asyncio.wait_for(task, 30)


# --- the abstain-only policy (owner decisions 2026-10-07 and 2026-10-08) ----------------------

ABSTAIN_ONLY = {
    "schema_version": 1,
    "version": "abstain-only-regression-v1",
    "min_detection_score": 0.1,
    "new_identity_ceiling": -1.0,
    "match_threshold": 2.0,  # above any similarity: nothing is ever matched automatically
    "margin": 2.0,
}


def abstain_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run the development host under the abstain-only decision policy."""

    def request(session: Any) -> dict[str, Any]:
        return {**development_request(session), "decision_policy": dict(ABSTAIN_ONLY)}

    monkeypatch.setattr(development, "development_request", request)


async def unresolved(client: httpx.AsyncClient, source_id: str) -> list[dict[str, Any]]:
    response = await client.get(f"/api/v1/sources/{source_id}/unresolved-faces")
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()["items"]
    return items


async def occurrence_count(client: httpx.AsyncClient, source_id: str) -> int:
    page = (await client.get(f"/api/v1/sources/{source_id}/occurrences")).json()
    return len(page["items"])


def abstentions_on_record(tmp_path: Path) -> dict[str, tuple[str, str, list[str]]]:
    """Every recorded abstention: id -> (payload, creation time, the representations it cites)."""
    database = sqlite3.connect(tmp_path / "library" / "database" / "library.db")
    try:
        rows = database.execute(
            "SELECT id, payload_json, created_at FROM evidence WHERE kind = 'RECOGNITION_ABSTAINED'"
        ).fetchall()
        return {
            row[0]: (
                row[1],
                row[2],
                sorted(
                    r[0]
                    for r in database.execute(
                        "SELECT representation_id FROM evidence_representations"
                        " WHERE evidence_id = ?",
                        (row[0],),
                    )
                ),
            )
            for row in rows
        }
    finally:
        database.close()


async def test_under_abstain_only_the_first_face_creates_an_identity_and_no_later_face_is_matched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    abstain_only(monkeypatch)
    folder = tmp_path / "pictures"
    folder.mkdir()
    red, red_again = picture(folder, "red.png", (200, 0, 0)), picture(folder, "r2.png", (200, 0, 0))
    blue, red_third = (
        picture(folder, "blue.png", (0, 0, 200)),
        picture(folder, "r3.png", (200, 0, 0)),
    )

    async with host(tmp_path, development_profile=True) as client:
        first = await import_image(client, red)
        run = await process_and_wait(client, first["id"])
        assert run["policy"]["automatic_matching"] is False  # what the UI says: matching disabled
        assert run["policy"]["decision_policy_version"] == ABSTAIN_ONLY["version"]

        # The first face has nobody to be compared with: a persistent, unnamed identity is created.
        (identity,) = await identities(client)
        assert identity["person"] is None
        assert await occurrence_count(client, first["id"]) == 1
        assert await unresolved(client, first["id"]) == []

        # An identical picture is not matched to it, whatever the similarity: it waits for a person.
        second = await import_image(client, red_again)
        await process_and_wait(client, second["id"])
        assert [i["id"] for i in await identities(client)] == [identity["id"]]  # nothing merged
        assert await occurrence_count(client, second["id"]) == 0  # and nothing attached
        (waiting,) = await unresolved(client, second["id"])
        assert waiting["likely"][0]["identity_id"] == identity["id"]  # ranked, as a hint
        assert waiting["likely"][0]["similarity"] <= 1.0  # a score, never above a cosine's range

        # A different picture is not given an identity of its own automatically either.
        third = await import_image(client, blue)
        await process_and_wait(client, third["id"])
        assert [i["id"] for i in await identities(client)] == [identity["id"]]
        assert len(await unresolved(client, third["id"])) == 1

    async with host(tmp_path, development_profile=True) as client:  # the application restarted
        assert [i["id"] for i in await identities(client)] == [identity["id"]]  # it persisted
        assert await occurrence_count(client, first["id"]) == 1
        assert len(await unresolved(client, second["id"])) == 1  # so did the waiting faces

        # After the restart the persisted identity is still never matched automatically.
        fourth = await import_image(client, red_third)
        await process_and_wait(client, fourth["id"])
        assert [i["id"] for i in await identities(client)] == [identity["id"]]
        assert await occurrence_count(client, fourth["id"]) == 0
        (still_waiting,) = await unresolved(client, fourth["id"])

        # Manual resolution still works: a person can say "this is someone new".
        before = abstentions_on_record(tmp_path)
        placed = await client.post(
            f"/api/v1/representations/{still_waiting['representation_id']}/resolve",
            json={"identity_id": None},
        )
        assert placed.status_code == 200, placed.text
        everyone = await identities(client)
        assert len(everyone) == 2
        (new_identity,) = [i for i in everyone if i["id"] != identity["id"]]
        assert await unresolved(client, fourth["id"]) == []
        assert await occurrence_count(client, fourth["id"]) == 1  # the face now has its occurrence

    # The evidence is preserved and exactly right. No match was ever recorded; the first face made
    # one identity; every abstention is byte-for-byte what it was before the person resolved one;
    # and the manual "someone new" is one user correction that cites the abstention of *this* face
    # and ties this face's observation, representation and occurrence to the new identity.
    after = abstentions_on_record(tmp_path)
    assert after == before  # never rewritten, never removed, none added by the resolution
    assert len(after) == 3  # the identical, the different, the third
    database = sqlite3.connect(tmp_path / "library" / "database" / "library.db")
    try:
        kinds = [row[0] for row in database.execute("SELECT kind FROM evidence")]
        ((correction_id, payload),) = database.execute(
            "SELECT id, payload_json FROM evidence WHERE kind = 'USER_CORRECTION'"
        ).fetchall()
        face = still_waiting["representation_id"].replace("-", "")
        cited = json.loads(payload)["resolves_evidence_id"].replace("-", "")
        cited_face = database.execute(
            "SELECT representation_id FROM evidence_representations WHERE evidence_id = ?", (cited,)
        ).fetchall()
        correction_faces = database.execute(
            "SELECT representation_id, role FROM evidence_representations WHERE evidence_id = ?",
            (correction_id,),
        ).fetchall()
        (representation_identity,) = database.execute(
            "SELECT identity_id FROM representations WHERE id = ?", (face,)
        ).fetchone()
        ((occurrence_identity, occurrence_observation),) = database.execute(
            "SELECT identity_id, representative_observation_id FROM occurrences"
            " WHERE source_id = ?",
            (fourth["id"].replace("-", ""),),
        ).fetchall()
    finally:
        database.close()
    assert kinds.count("IDENTITY_MATCHED") == 0
    assert kinds.count("IDENTITY_CREATED") == 1
    assert json.loads(payload)["action"] == "RESOLVE_NEW"
    assert cited_face == [(face,)]  # the abstention it cites is this face's own
    assert correction_faces == [(face, "SUBJECT")]
    new = new_identity["id"].replace("-", "")
    assert representation_identity == new
    assert occurrence_identity == new
    assert occurrence_observation == still_waiting["observation_id"].replace("-", "")
