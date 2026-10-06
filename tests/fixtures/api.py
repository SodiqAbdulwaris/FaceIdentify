"""A running API application on a real temporary library, for the route tests (M4 W3).

The lifespan opens the library (migrations and recovery included) and the test waits for it, so a
route is exercised exactly as in the sidecar: authenticated HTTP through the real application.
"""

import base64
import secrets
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import anyio.to_thread
import httpx
import pytest
from fastapi import FastAPI
from PIL import Image

from backend.api.startup import Backend, LibrarySettings, MediaLimits, create_backend_app
from backend.app.memory.index_coordinator import RetryPolicy
from backend.infrastructure.db.unit_of_work import TransactionRetry
from tests.fixtures.deterministic import FrozenClock, SeededUUIDs

MAX_PIXELS = 10_000
MAX_BYTES = 100_000


@dataclass
class Api:
    client: httpx.AsyncClient
    app: FastAPI
    backend: Backend
    secret: str
    folder: Path  # where tests put the files they import (outside the library)

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
    folder = tmp_path / "user-files"
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
            yield Api(client, app, backend, secret, folder)
