"""The camera routes over HTTP with a scripted camera (M7 step 5; API section 4 decision
2026-11-11; TST-071).

The application runs with processing on, painted perception (no model) and a planted frame source
(no camera): configure a camera, start a session, watch it run (status, preview), stop it, read
what it kept (unplaced faces and their crops), delete history, remove the camera.
"""

import base64
import sys
import threading
import time
import uuid
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import anyio
import pytest
from sqlalchemy import func, select

from backend.api.routes import cameras as camera_routes
from backend.api.startup import (
    MediaLimits,
    ProcessingUnavailableError,
    create_backend_app,
)
from backend.app.cameras.session import CameraSettings
from backend.app.memory.models import Observation
from backend.app.sources.models import Source
from backend.infrastructure.media.camera import (
    CameraAccessDeniedError,
    CameraError,
    CameraInUseError,
    CameraStalledError,
    CameraStreamError,
    CaptureDevice,
    LiveFrame,
)
from backend.infrastructure.media.video import FFMPEG_DIR_ENV
from tests.fixtures.api import (
    MAX_BYTES,
    MAX_PIXELS,
    Api,
    error,
    library_settings,
    processing_app,
    serving,
)
from tests.fixtures.camera_pipeline import PaintedCameraPerception, picture
from tests.fixtures.deterministic import FrozenClock, SeededUUIDs

DEADLINE = 20.0
TOKEN = base64.urlsafe_b64encode(bytes(32)).rstrip(b"=").decode("ascii")


class Planted:
    """A camera that shows `script` (pictures), then waits until it is stopped."""

    def __init__(
        self,
        script: list[Any],
        fail: CameraError | None = None,
        then: CameraError | None = None,
    ) -> None:
        """`fail`: refused at the start; `then`: raised once the script is shown."""
        self.script, self.fail, self.then = list(script), fail, then
        self.dropped = 0
        self.stopped = threading.Event()
        self.sequence = 0

    def start(self) -> None:
        if self.fail is not None:
            raise self.fail

    def latest(self, timeout: float) -> LiveFrame:
        if self.stopped.is_set():
            raise CameraStreamError("the capture was stopped")
        if self.script:
            self.sequence += 1
            return LiveFrame(self.sequence, self.sequence / 5, self.script.pop(0))
        if self.then is not None:
            raise self.then
        if self.stopped.wait(timeout):
            raise CameraStreamError("the capture was stopped")
        raise CameraStalledError("silent")

    def stop(self) -> None:
        self.stopped.set()


class Cameras:
    """What the planted cameras show, by device name."""

    def __init__(self) -> None:
        self.next: dict[str, Planted] = {}
        self.opened: list[str] = []

    def open(self, device: CaptureDevice, _settings: CameraSettings) -> Planted:
        self.opened.append(device.name)
        return self.next.pop(device.name, Planted([]))


@pytest.fixture
def cameras() -> Cameras:
    return Cameras()


@pytest.fixture
async def api(
    tmp_path: Path,
    clock: FrozenClock,
    new_id: SeededUUIDs,
    monkeypatch: pytest.MonkeyPatch,
    cameras: Cameras,
) -> AsyncIterator[Api]:
    async with processing_app(
        tmp_path, clock, new_id, monkeypatch,
        perceive=PaintedCameraPerception, open_camera=cameras.open,
    ) as running:  # fmt: skip
        yield running


async def eventually(check: Callable[[], Any]) -> Any:
    """Poll (the session runs on its own thread) until `check()` is truthy."""
    deadline = time.monotonic() + DEADLINE
    while not (value := await check()):
        assert time.monotonic() < deadline, "the condition never held"
        await anyio.sleep(0.02)
    return value


async def configure(api: Api, name: str = "Doorway", device: str = "Integrated Camera") -> str:
    response = await api.client.post(
        "/api/v1/cameras",
        json={"display_name": name, "device_name": device, "device_path": f"@{device}"},
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    assert body["session"]["state"] is None
    return str(body["id"])


async def status(api: Api, camera: str) -> dict[str, Any]:
    response = await api.client.get(f"/api/v1/cameras/{camera}/status")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_a_camera_is_configured_listed_and_read(api: Api) -> None:
    camera = await configure(api)

    listed = (await api.client.get("/api/v1/cameras")).json()
    assert [(c["id"], c["display_name"], c["device_path"]) for c in listed] == [
        (camera, "Doorway", "@Integrated Camera")
    ]
    one = (await api.client.get(f"/api/v1/cameras/{camera}")).json()
    assert one["device_name"] == "Integrated Camera"
    missing = uuid.uuid4()
    for response in (
        await api.client.get(f"/api/v1/cameras/{missing}"),
        await api.client.get(f"/api/v1/cameras/{missing}/status"),
        await api.client.post(f"/api/v1/cameras/{missing}/start"),
        await api.client.delete(f"/api/v1/cameras/{missing}"),
        await api.client.delete(f"/api/v1/cameras/{missing}", params={"history": "true"}),
        await api.client.post(f"/api/v1/cameras/{missing}/history/delete", json={}),
    ):
        error(response, 404, "CAMERA_NOT_FOUND")
    error(
        await api.client.post("/api/v1/cameras", json={"display_name": "", "device_name": "x"}),
        422,
        "VALIDATION_ERROR",
    )


async def test_a_session_runs_shows_a_preview_stops_and_keeps_its_faces(
    api: Api, cameras: Cameras
) -> None:
    camera = await configure(api)
    cameras.next["Integrated Camera"] = Planted([picture(("green", 20, 40))] * 5)

    started = await api.client.post(f"/api/v1/cameras/{camera}/start")
    assert started.status_code == 202, started.text
    assert started.json()["job_id"]
    running = await eventually(lambda: _when(status(api, camera), lambda s: s["frames"] == 5 and s))
    assert running["state"] == "RUNNING"
    assert running["open_encounters"] == 1
    preview = await api.client.get(f"/api/v1/cameras/{camera}/preview")
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "image/jpeg"
    assert preview.headers["cache-control"] == "no-store"
    assert preview.content[:2] == b"\xff\xd8"
    error(await api.client.post(f"/api/v1/cameras/{camera}/start"), 409, "CAMERA_BUSY")
    error(await api.client.delete(f"/api/v1/cameras/{camera}"), 409, "CAMERA_BUSY")
    error(
        await api.client.post(f"/api/v1/cameras/{camera}/history/delete", json={}),
        409,
        "CAMERA_BUSY",
    )

    stopped = await api.client.post(f"/api/v1/cameras/{camera}/stop")
    assert stopped.status_code == 202
    assert (stopped.json()["state"], stopped.json()["encounters"]) == ("STOPPED", 1)
    error(await api.client.get(f"/api/v1/cameras/{camera}/preview"), 404, "MEDIA_NOT_FOUND")
    faces = (await api.client.get(f"/api/v1/sources/{camera}/unresolved-faces")).json()["items"]
    assert faces  # the unknown face waits to be placed; no identity was made
    assert all(face["seen_at_ms"] is not None for face in faces)
    crop = await api.client.get(f"/api/v1/cameras/{camera}/faces/{faces[0]['observation_id']}/crop")
    assert crop.status_code == 200
    assert crop.content[:2] == b"\xff\xd8"
    error(
        await api.client.get(f"/api/v1/cameras/{camera}/faces/{uuid.uuid4()}/crop"),
        404,
        "MEDIA_NOT_FOUND",
    )
    assert (await api.client.post(f"/api/v1/cameras/{camera}/stop")).json()["state"] == "STOPPED"

    deleted = await api.client.post(f"/api/v1/cameras/{camera}/history/delete", json={})
    assert deleted.json() == {"faces": len(faces), "encounters": 0, "complete": True}
    assert (await api.client.get(f"/api/v1/sources/{camera}/unresolved-faces")).json()[
        "items"
    ] == []
    error(
        await api.client.post(
            f"/api/v1/cameras/{camera}/history/delete", json={"start_ms": 5, "end_ms": 4}
        ),
        422,
        "VALIDATION_ERROR",
    )


async def _now(value: Any) -> Any:
    return value


async def _when(awaitable: Any, test: Callable[[Any], Any]) -> Any:
    return test(await awaitable)


async def test_a_camera_that_cannot_be_opened_ends_its_session_with_the_reason(
    api: Api, cameras: Cameras
) -> None:
    camera = await configure(api)
    cameras.next["Integrated Camera"] = Planted([], fail=CameraAccessDeniedError("refused"))

    assert (await api.client.post(f"/api/v1/cameras/{camera}/start")).status_code == 202
    ended = await eventually(
        lambda: _when(status(api, camera), lambda s: s["state"] == "FAILED" and s)
    )

    assert ended["failure_code"] == "CAMERA_ACCESS_DENIED"
    assert (await api.client.post(f"/api/v1/cameras/{camera}/stop")).json()["state"] == "FAILED"


async def test_removing_a_camera_keeps_its_history_unless_asked(api: Api, cameras: Cameras) -> None:
    kept, gone = await configure(api, "Hall"), await configure(api, "Gate", device="USB")

    assert (await api.client.delete(f"/api/v1/cameras/{kept}")).status_code == 204
    assert (
        await api.client.delete(f"/api/v1/cameras/{gone}", params={"history": "true"})
    ).status_code == 204

    assert (await api.client.get("/api/v1/cameras")).json() == []
    assert api.backend.library is not None
    with api.backend.library.session_factory() as session:
        states = dict(session.execute(select(Source.display_name, Source.state)).tuples().all())
    assert states["Hall"] == "UNAVAILABLE"  # its history is still in the library
    assert "Gate" not in states  # deleted for good: only a nameless tombstone is left
    error(await api.client.post(f"/api/v1/cameras/{kept}/start"), 404, "CAMERA_NOT_FOUND")


async def test_devices_are_listed_from_the_pinned_tool(
    api: Api, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        camera_routes, "list_devices", lambda _tools: [CaptureDevice("Integrated Camera", "@p")]
    )
    monkeypatch.setenv(FFMPEG_DIR_ENV, str(_tools(tmp_path)))
    listed = (await api.client.get("/api/v1/cameras/devices")).json()
    assert listed == [{"name": "Integrated Camera", "path": "@p"}]

    def broken(_tools: Any) -> list[CaptureDevice]:
        raise CameraError("listing failed")

    monkeypatch.setattr(camera_routes, "list_devices", broken)
    error(await api.client.get("/api/v1/cameras/devices"), 503, "CAMERA_DISCONNECTED")
    monkeypatch.setenv(FFMPEG_DIR_ENV, str(tmp_path / "nothing-here"))
    error(await api.client.get("/api/v1/cameras/devices"), 503, "MEDIA_TOOLS_UNAVAILABLE")


def _tools(tmp_path: Path) -> Path:
    folder = tmp_path / "tools"
    folder.mkdir()
    for name in ("ffmpeg.exe", "ffprobe.exe", "ffmpeg", "ffprobe"):
        (folder / name).write_bytes(b"")
    return folder


async def test_without_processing_the_camera_routes_are_unavailable(
    tmp_path: Path, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    app = create_backend_app(
        TOKEN,
        library_settings(tmp_path, clock, new_id),
        media_limits=MediaLimits(max_pixels=MAX_PIXELS, max_bytes=MAX_BYTES),
    )
    async with serving(app, TOKEN, tmp_path / "f", clock) as plain:
        error(await plain.client.get("/api/v1/cameras"), 503, "PROCESSING_UNAVAILABLE")


async def test_a_camera_that_breaks_is_reconnecting_until_it_comes_back(
    api: Api, cameras: Cameras
) -> None:
    camera = await configure(api)
    cameras.next["Integrated Camera"] = Planted(
        [picture()] * 2, then=CameraStreamError("unplugged")
    )
    error(await api.client.get(f"/api/v1/cameras/{camera}/preview"), 404, "MEDIA_NOT_FOUND")

    assert (await api.client.post(f"/api/v1/cameras/{camera}/start")).status_code == 202
    await eventually(lambda: _when(status(api, camera), lambda s: s["state"] == "RECONNECTING"))

    await eventually(lambda: _now(len(cameras.opened) == 2))  # it is opened again after a pause
    stopped = (await api.client.post(f"/api/v1/cameras/{camera}/stop")).json()
    assert stopped["state"] == "STOPPED"


async def test_a_session_that_crashes_is_failed_with_the_reason(api: Api, cameras: Cameras) -> None:
    camera = await configure(api)
    cameras.next["Integrated Camera"] = Planted([picture(("green", 20, 40))] * 2)
    assert api.perception is not None
    api.perception.fail_represent = RuntimeError("the worker went away")  # type: ignore[attr-defined]

    assert (await api.client.post(f"/api/v1/cameras/{camera}/start")).status_code == 202
    await eventually(lambda: _when(status(api, camera), lambda s: s["frames"] == 2))
    ended = (await api.client.post(f"/api/v1/cameras/{camera}/stop")).json()

    assert (ended["state"], ended["failure_code"]) == ("FAILED", "RuntimeError")


async def test_a_camera_and_its_history_are_not_deleted_while_it_runs(
    api: Api, cameras: Cameras
) -> None:
    camera = await configure(api)
    assert (await api.client.post(f"/api/v1/cameras/{camera}/start")).status_code == 202

    error(
        await api.client.delete(f"/api/v1/cameras/{camera}", params={"history": "true"}),
        409,
        "CAMERA_BUSY",
    )
    await api.client.post(f"/api/v1/cameras/{camera}/stop")


async def test_deletions_that_cannot_finish_yet_mark_recovery_degraded(
    api: Api, cameras: Cameras, monkeypatch: pytest.MonkeyPatch
) -> None:
    camera = await configure(api)
    cameras.next["Integrated Camera"] = Planted([picture(("green", 20, 40))] * 3)
    await api.client.post(f"/api/v1/cameras/{camera}/start")
    await eventually(lambda: _when(status(api, camera), lambda s: s["frames"] == 3))
    await api.client.post(f"/api/v1/cameras/{camera}/stop")
    assert api.backend.library is not None

    def locked(_key: str) -> None:
        raise PermissionError("the file is open")

    monkeypatch.setattr(api.backend.library.store, "delete", locked)
    deleted = (await api.client.post(f"/api/v1/cameras/{camera}/history/delete", json={})).json()
    assert deleted["complete"] is False
    assert api.backend.capabilities["recovery"] == "DEGRADED"

    api.backend.capabilities["recovery"] = "READY"
    other = await configure(api, "Gate", device="USB")
    cameras.next["USB"] = Planted([picture(("green", 20, 40))] * 3)
    await api.client.post(f"/api/v1/cameras/{other}/start")
    await eventually(lambda: _when(status(api, other), lambda s: s["frames"] == 3))
    await api.client.post(f"/api/v1/cameras/{other}/stop")
    gone = await api.client.delete(f"/api/v1/cameras/{other}", params={"history": "true"})
    assert gone.status_code == 204
    assert api.backend.capabilities["recovery"] == "DEGRADED"


async def test_a_start_without_a_processing_configuration_is_unavailable(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    camera = await configure(api)
    assert api.backend.cameras is not None

    def unavailable(_session: Any) -> dict[str, Any]:
        raise ProcessingUnavailableError("no policy")

    monkeypatch.setattr(api.backend.cameras, "_request_for", unavailable)
    error(await api.client.post(f"/api/v1/cameras/{camera}/start"), 503, "PROCESSING_UNAVAILABLE")


@pytest.mark.skipif(sys.platform != "win32", reason="DirectShow and the pinned build")
async def test_the_real_capture_reports_a_missing_device(
    tmp_path: Path, clock: FrozenClock, new_id: SeededUUIDs, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No planted camera: the session opens the device through the pinned ffmpeg, which has no
    such device, and the session ends with that reason (no camera is used)."""
    async with processing_app(
        tmp_path, clock, new_id, monkeypatch, perceive=PaintedCameraPerception
    ) as real:
        camera = await configure(real, device="FaceIdentify Test Camera That Does Not Exist")
        assert (await real.client.post(f"/api/v1/cameras/{camera}/start")).status_code == 202
        ended = await eventually(
            lambda: _when(status(real, camera), lambda s: s["state"] == "FAILED" and s)
        )
        assert ended["failure_code"] == "CAMERA_DISCONNECTED"


# --- search with the camera (M7 step 6; spec 10.4; plan C10) -----------------------------------


def small() -> Any:
    """A green face on a picture within the test library's pixel limit (10,000)."""
    return picture(("green", 20, 40))[30:90, 0:80].copy()


async def test_a_face_in_front_of_the_camera_is_searched_and_nothing_is_kept(
    api: Api, cameras: Cameras
) -> None:
    camera = await configure(api)
    planted = Planted([small()])
    cameras.next["Integrated Camera"] = planted
    assert api.backend.library is not None
    with api.backend.library.session_factory() as session:
        before = session.scalar(select(func.count()).select_from(Observation))

    found = await api.client.post(f"/api/v1/cameras/{camera}/search")

    assert found.status_code == 200, found.text
    (face,) = found.json()["faces"]
    assert face["status"] in ("UNKNOWN", "POSSIBLE_PEOPLE")
    assert planted.stopped.is_set()  # the device was closed again at once
    with api.backend.library.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Observation)) == before
    assert api.perception is not None
    assert api.perception.classes[0] == "detect:INTERACTIVE"  # type: ignore[attr-defined]


async def test_a_search_while_the_camera_runs_uses_its_newest_frame(
    api: Api, cameras: Cameras
) -> None:
    camera = await configure(api)
    cameras.next["Integrated Camera"] = Planted([small()] * 2)
    await api.client.post(f"/api/v1/cameras/{camera}/start")
    await eventually(lambda: _when(status(api, camera), lambda s: s["frames"] == 2))

    found = await api.client.post(f"/api/v1/cameras/{camera}/search")

    assert found.status_code == 200, found.text
    assert len(found.json()["faces"]) == 1
    assert cameras.opened == ["Integrated Camera"]  # not opened a second time
    await api.client.post(f"/api/v1/cameras/{camera}/stop")

    cameras.next["Integrated Camera"] = Planted([small()])
    again = await api.client.post(f"/api/v1/cameras/{camera}/search")  # (the session has ended)
    assert again.status_code == 200, again.text
    assert cameras.opened == ["Integrated Camera", "Integrated Camera"]


@pytest.mark.parametrize(
    ("failure", "status_code", "code"),
    [
        (CameraInUseError("busy"), 409, "CAMERA_IN_USE"),
        (CameraAccessDeniedError("refused"), 403, "CAMERA_ACCESS_DENIED"),
        (CameraStalledError("silent"), 503, "CAMERA_DISCONNECTED"),
    ],
)
async def test_a_camera_that_gives_no_picture_is_reported(
    api: Api, cameras: Cameras, failure: CameraError, status_code: int, code: str
) -> None:
    camera = await configure(api)
    cameras.next["Integrated Camera"] = Planted([], fail=failure)

    error(await api.client.post(f"/api/v1/cameras/{camera}/search"), status_code, code)
    error(await api.client.post(f"/api/v1/cameras/{uuid.uuid4()}/search"), 404, "CAMERA_NOT_FOUND")


async def test_a_camera_search_waits_its_turn_with_the_other_searches(api: Api) -> None:
    camera = await configure(api)
    slots = api.backend.face_search_slots
    taken = 0
    while slots.acquire(blocking=False):
        taken += 1
    try:
        error(await api.client.post(f"/api/v1/cameras/{camera}/search"), 429, "FACE_SEARCH_BUSY")
    finally:
        for _ in range(taken):
            slots.release()
