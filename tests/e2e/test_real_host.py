"""The real models through the real host profile (M5 R2/R3; TST-038, TST-039 on the real path).

Unlike `test_real_models.py` (the worker alone), this runs the application: the real profile
registers the installed `buffalo_l` package in the library catalog, builds the processing request
from it and a decision policy, and the scheduler, executor, supervised worker,
recognition and acceptance process real photographs; then the application restarts on the same
library.

Each test writes its own policy into a private state, whatever policy the machine has installed:
the first runs the abstain-only policy (**assisted** recognition, owner decision 2026-10-08: the
same person's photograph is not matched, but the right identity is ranked first among the possible
matches); the second runs the owner-approved operating point of `APPROVED_MATCHING` (automatic
recognition, TST-057B, owner decision 2026-10-15): the same person is matched and a different person
waits.

Excluded from the default run (local weights and pictures; never in CI). Prerequisites are those of
`test_real_models.py`.
`FACEIDENTIFY_PROVIDERS` and `FACEIDENTIFY_ORT_GPU_DIR` select CUDA as in the application.

    uv run pytest -m e2e tests/e2e/test_real_host.py
"""

import asyncio
import base64
import json
import os
import secrets
import sqlite3
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from backend.api.real import (
    APPROVED_MATCHING,
    PACKAGE_KEY,
    policy_path,
    providers_from,
    real_processing,
)
from backend.api.startup import MediaLimits, create_backend_app
from backend.app.runtime.package_store import RuntimePackageStore
from backend.infrastructure.storage.layout import StorageRoots
from tests.fixtures.api import Api, imported, library_settings, serving
from tests.fixtures.deterministic import FrozenClock

ROOT = Path(__file__).resolve().parents[2] / "local-models"
STATE = ROOT / "state"
IMAGES = ROOT / "images"

pytestmark = pytest.mark.e2e


def needs_local_models() -> None:
    store = RuntimePackageStore(StorageRoots(Path(), STATE), new_id=uuid.uuid4)
    if store.get(PACKAGE_KEY) is None:
        pytest.skip(f"{PACKAGE_KEY} is not installed under {STATE}")
    if not (IMAGES / "collins1.jpg").exists():
        pytest.skip(f"no test pictures in {IMAGES}")


ABSTAIN_ONLY: dict[str, Any] = {
    "schema_version": 1,
    "version": "buffalo-l-abstain-only-v1",
    "min_detection_score": 0.5,
    "new_identity_ceiling": -1.0,
    "match_threshold": 2.0,
    "margin": 2.0,
}
APPROVED: dict[str, Any] = {
    "schema_version": 1,
    "version": next(iter(APPROVED_MATCHING)),
    **next(iter(APPROVED_MATCHING.values())),
}


def isolated_state(tmp_path: Path, policy: dict[str, Any]) -> Path:
    """A private machine-local state for this test: a verified copy of the installed model package
    and the given policy. The test then never writes into the shared `local-models/state` (its
    vector indexes, recovery and workspaces stay in the temporary folder)."""
    state = tmp_path / "state"
    installed = RuntimePackageStore(StorageRoots(Path(), STATE), new_id=uuid.uuid4).get(PACKAGE_KEY)
    assert installed is not None
    RuntimePackageStore(StorageRoots(Path(), state), new_id=uuid.uuid4).install(installed.path, {})
    target = policy_path(state, PACKAGE_KEY)
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(policy), encoding="utf-8")
    return state


def application(tmp_path: Path, clock: FrozenClock) -> tuple[Any, str]:
    ids: Any = uuid.uuid4  # random ids, as in production
    settings = replace(library_settings(tmp_path, clock, ids), local_state_root=tmp_path / "state")
    secret = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
    app = create_backend_app(
        secret,
        settings,
        processing=real_processing(settings, providers=providers_from(os.environ)),
        media_limits=MediaLimits(max_pixels=100_000_000, max_bytes=50_000_000),
    )
    return app, secret


async def process_and_wait(api: Api, source_id: str) -> dict[str, Any]:
    response = await api.client.post(f"/api/v1/sources/{source_id}/process")
    assert response.status_code == 202, response.text
    run_id = response.json()["id"]
    async with asyncio.timeout(300):  # the first run loads the models
        while True:
            run: dict[str, Any] = (await api.client.get(f"/api/v1/processing-runs/{run_id}")).json()
            if run["state"] == "COMPLETED":
                return run
            assert run["state"] not in ("FAILED", "NOT_RESUMABLE"), run
            await asyncio.sleep(0.2)


async def unresolved(api: Api, source_id: str) -> list[dict[str, Any]]:
    response = await api.client.get(f"/api/v1/sources/{source_id}/unresolved-faces")
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()["items"]
    return items


async def test_real_photographs_through_the_real_host_rank_the_right_identity_first(
    tmp_path: Path, clock: FrozenClock
) -> None:
    needs_local_models()
    isolated_state(tmp_path, ABSTAIN_ONLY)
    app, secret = application(tmp_path, clock)

    async with serving(app, secret, tmp_path / "files-a", clock) as api:
        ready = (await api.client.get("/readiness")).json()
        assert ready["capabilities"]["runtime_package"] == "READY"
        assert ready["capabilities"]["processing_policy"] == "READY"
        assert ready["capabilities"]["ml_worker"] == "NOT_STARTED"  # a job starts it

        first = await imported(api, path=str(IMAGES / "collins1.jpg"))
        run = await process_and_wait(api, first["id"])
        assert run["policy"]["automatic_matching"] is False
        ready = (await api.client.get("/readiness")).json()
        assert ready["capabilities"]["ml_worker"] == "READY"  # started by the job, handshake done
        # what ran, as readiness tells it: the preferred provider, with no fallback
        assert ready["capabilities"]["execution_provider"] == providers_from(os.environ)[0]
        assert ready["capabilities"]["provider_fallback"] == "NONE"
        assert run["policy"]["decision_policy_version"] == "buffalo-l-abstain-only-v1"
        (identity,) = (await api.client.get("/api/v1/identities")).json()["items"]
        assert (await unresolved(api, first["id"])) == []  # the first face made the identity

        second = await imported(api, path=str(IMAGES / "collins2.jpg"))
        await process_and_wait(api, second["id"])
        (same_person,) = await unresolved(api, second["id"])  # not matched: it waits
        ranked = same_person["likely"]
        assert ranked[0]["identity_id"] == identity["id"]  # Recall@1: the right identity is first
        assert -1.0 <= ranked[0]["similarity"] <= 1.0
        assert ranked[0]["similarity"] > 0.4  # a real, high similarity score for the same person

        other = await imported(api, path=str(IMAGES / "other1.jpg"))
        await process_and_wait(api, other["id"])
        (stranger,) = await unresolved(api, other["id"])
        assert stranger["likely"][0]["similarity"] < ranked[0]["similarity"]  # a different person

        assert len((await api.client.get("/api/v1/identities")).json()["items"]) == 1

    # Every result records the provider that actually produced it; the first one asked for ran it
    # (a silent fallback to the CPU would show here).
    database = sqlite3.connect(tmp_path / "library" / "database" / "library.db")
    try:
        providers = {
            row[0]
            for row in database.execute(
                "SELECT v.provider FROM representations r"
                " JOIN runtime_variants v ON v.id = r.runtime_variant_id"
            )
        }
    finally:
        database.close()
    assert providers == {providers_from(os.environ)[0]}

    # The application restarts on the same library: the identity and the waiting faces persist.
    app, secret = application(tmp_path, clock)
    async with serving(app, secret, tmp_path / "files-b", clock) as api:
        (still,) = (await api.client.get("/api/v1/identities")).json()["items"]
        assert still["id"] == identity["id"]
        (waiting,) = await unresolved(api, second["id"])
        assert waiting["likely"][0]["identity_id"] == identity["id"]  # still ranked first

        # Manual confirmation: one click places the face on the identity it ranked first.
        placed = await api.client.post(
            f"/api/v1/representations/{waiting['representation_id']}/resolve",
            json={"identity_id": identity["id"]},
        )
        assert placed.status_code == 200, placed.text
        assert await unresolved(api, second["id"]) == []


async def test_real_photographs_under_the_approved_point_match_the_same_person_only(
    tmp_path: Path, clock: FrozenClock
) -> None:
    needs_local_models()
    isolated_state(tmp_path, APPROVED)
    app, secret = application(tmp_path, clock)

    async with serving(app, secret, tmp_path / "files", clock) as api:
        assert (await api.client.get("/readiness")).json()["capabilities"][
            "processing_policy"
        ] == "READY"
        first = await imported(api, path=str(IMAGES / "collins1.jpg"))
        run = await process_and_wait(api, first["id"])
        assert run["policy"]["automatic_matching"] is True
        assert run["policy"]["decision_policy_version"] == APPROVED["version"]
        (identity,) = (await api.client.get("/api/v1/identities")).json()["items"]

        second = await imported(api, path=str(IMAGES / "collins2.jpg"))
        await process_and_wait(api, second["id"])
        assert await unresolved(api, second["id"]) == []  # matched automatically
        (still,) = (await api.client.get("/api/v1/identities")).json()["items"]
        assert still["id"] == identity["id"]  # to the same person, not a new one

        other = await imported(api, path=str(IMAGES / "other1.jpg"))
        await process_and_wait(api, other["id"])
        (stranger,) = await unresolved(api, other["id"])  # a different person waits
        assert stranger["likely"][0]["similarity"] < APPROVED["match_threshold"]
        assert len((await api.client.get("/api/v1/identities")).json()["items"]) == 1
