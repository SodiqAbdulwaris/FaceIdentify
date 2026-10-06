"""A running API application on a real temporary library, for the route tests (M4 W3).

The lifespan opens the library (migrations and recovery included) and the test waits for it, so a
route is exercised exactly as in the sidecar: authenticated HTTP through the real application.
"""

import base64
import secrets
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import anyio.to_thread
import httpx
import pytest
from fastapi import FastAPI
from PIL import Image

from backend.api.startup import (
    Backend,
    LibrarySettings,
    MediaLimits,
    ProcessingSettings,
    create_backend_app,
)
from backend.app.lifecycle import open_library
from backend.app.memory.index_coordinator import RetryPolicy
from backend.app.processing.execute_job import ExecuteProcessingJob
from backend.app.runtime.worker_config import PerceptionPlan
from backend.infrastructure.db.unit_of_work import TransactionRetry
from tests.fixtures.deterministic import FrozenClock, SeededUUIDs
from tests.fixtures.pipeline import NDIM, PlantedPerception, prepare_catalog, variant_from_json

MAX_PIXELS = 10_000
MAX_BYTES = 100_000


@dataclass
class Api:
    client: httpx.AsyncClient
    app: FastAPI
    backend: Backend
    secret: str
    folder: Path  # where tests put the files they import (outside the library)
    clock: FrozenClock

    def image(
        self, name: str = "photo.png", size: tuple[int, int] = (4, 3), fmt: str = "PNG"
    ) -> Path:
        path = self.folder / name
        Image.new("RGB", size, "white").save(path, format=fmt)
        return path


def library_settings(tmp_path: Path, clock: FrozenClock, new_id: SeededUUIDs) -> LibrarySettings:
    (tmp_path / "library").mkdir(exist_ok=True)
    return LibrarySettings(
        library_root=tmp_path / "library",
        local_state_root=tmp_path / "local",
        clock=clock,
        new_id=new_id,
        retry=RetryPolicy(max_attempts=3, backoff=lambda n: timedelta(minutes=n)),
        transaction_retry=TransactionRetry(max_attempts=3, backoff=lambda n: 0.1 * n),
        index_batch=50,
        max_index_passes=5,
    )


@pytest.fixture
async def api(tmp_path: Path, clock: FrozenClock, new_id: SeededUUIDs) -> AsyncIterator[Api]:
    secret = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
    app = create_backend_app(
        secret,
        library_settings(tmp_path, clock, new_id),
        media_limits=MediaLimits(max_pixels=MAX_PIXELS, max_bytes=MAX_BYTES),
    )
    async with serving(app, secret, tmp_path / "user-files", clock) as running:
        yield running


@pytest.fixture
async def processing_api(
    tmp_path: Path, clock: FrozenClock, new_id: SeededUUIDs, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[Api]:
    """The application with processing on: a registered fake catalog and planted perception (no
    weights), the real scheduler, executor, acceptance and index. The catalog is registered by a
    first open of the library, which is closed again before the application starts on it."""
    settings = library_settings(tmp_path, clock, new_id)
    with open_library(
        library_root=settings.library_root, local_state_root=settings.local_state_root,
        clock=clock, new_id=new_id, retry=settings.retry,
        transaction_retry=settings.transaction_retry, index_batch=50, max_index_passes=5,
    ) as lib:  # fmt: skip
        catalog = prepare_catalog(lib, clock, new_id)
    detector, embedder = (
        variant_from_json(catalog["detector"]),
        variant_from_json(catalog["embedder"]),
    )
    perception = PlantedPerception(detector, embedder)
    plan = PerceptionPlan(uuid.UUID(catalog["space_id"]), NDIM, (detector,), (embedder,))
    monkeypatch.setattr(ExecuteProcessingJob, "_plan", lambda _self, _session, _frozen: plan)
    secret = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
    app = create_backend_app(
        secret,
        settings,
        processing=ProcessingSettings(
            client_for=lambda _plan: perception,
            request_for=lambda _session: catalog["request"],
            max_pixels=MAX_PIXELS,
            recognition_k=2,
            lease_for=timedelta(minutes=5),
            idle_seconds=60.0,
            owner="api-test",
        ),
        media_limits=MediaLimits(max_pixels=MAX_PIXELS, max_bytes=MAX_BYTES),
    )
    async with serving(app, secret, tmp_path / "user-files", clock) as running:
        yield running


@asynccontextmanager
async def serving(
    app: FastAPI, secret: str, folder: Path, clock: FrozenClock
) -> AsyncIterator[Api]:
    folder.mkdir()
    async with app.router.lifespan_context(app):
        backend: Backend = app.state.backend
        assert await anyio.to_thread.run_sync(backend.settled.wait, 60)
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"Authorization": f"Bearer {secret}"},
        ) as client:
            yield Api(client, app, backend, secret, folder, clock)


async def imported(api: Api, **body: Any) -> dict[str, Any]:
    response = await api.client.post("/api/v1/sources/import", json=body)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


def error(response: Any, status: int, code: str) -> dict[str, Any]:
    """The response's error body, after checking its status and code."""
    assert response.status_code == status, response.text
    body: dict[str, Any] = response.json()["error"]
    assert body["code"] == code
    return body
