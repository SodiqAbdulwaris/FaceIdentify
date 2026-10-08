"""The real models through the real host profile (M5 R2/R3; TST-038, TST-039 on the real path).

Unlike `test_real_models.py` (the worker alone), this runs the application: the real profile
registers the installed `buffalo_l` package in the library catalog, builds the processing request
from it and the measured abstain-only policy file, and the scheduler, executor, supervised worker,
recognition and acceptance process real photographs; then the application restarts on the same
library.

It is **assisted** recognition evidence only (owner decision 2026-10-08): with automatic matching
off, the same person's photograph is not matched, but the right identity is ranked first among the
possible matches. Automatic recognition (TST-057B) is blocked and is not claimed here.

Excluded from the default run (local weights and pictures; never in CI). Prerequisites are those of
`test_real_models.py`, plus the measured policy file
`local-models/state/policies/insightface-buffalo-l.json` written by
`evaluation/measure_operating_point.py --conservative --write-policy ...`.
`FACEIDENTIFY_PROVIDERS` and `FACEIDENTIFY_ORT_GPU_DIR` select CUDA as in the application.

    uv run pytest -m e2e tests/e2e/test_real_host.py
"""

import asyncio
import base64
import os
import secrets
import shutil
import sqlite3
import uuid
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from backend.api.real import PACKAGE_KEY, policy_path, providers_from, real_processing
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
    if not policy_path(STATE, PACKAGE_KEY).exists():
        pytest.skip("the measured policy file is missing: see this file's docstring")
    if not (IMAGES / "collins1.jpg").exists():
        pytest.skip(f"no test pictures in {IMAGES}")


@pytest.fixture(autouse=True)
def clean_indexes() -> Iterator[None]:
    """The vector indexes live in the machine-local state this test shares with the real models, so
    the test removes the ones it made (and uses random ids: a seeded id would give every run's
    library the same space id, and so the same index folder, and stale vectors would be found)."""
    before = set((STATE / "indexes").glob("*")) if (STATE / "indexes").exists() else set()
    yield
    if (STATE / "indexes").exists():
        for folder in set((STATE / "indexes").glob("*")) - before:
            shutil.rmtree(folder, ignore_errors=True)


def application(tmp_path: Path, clock: FrozenClock) -> tuple[Any, str]:
    ids: Any = uuid.uuid4  # (random: see `clean_indexes`)
    settings = replace(library_settings(tmp_path, clock, ids), local_state_root=STATE)
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
    app, secret = application(tmp_path, clock)

    async with serving(app, secret, tmp_path / "files-a", clock) as api:
        ready = (await api.client.get("/readiness")).json()
        assert ready["capabilities"]["ml_worker"] == "READY"

        first = await imported(api, path=str(IMAGES / "collins1.jpg"))
        run = await process_and_wait(api, first["id"])
        assert run["policy"]["automatic_matching"] is False
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
