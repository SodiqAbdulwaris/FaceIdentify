"""Configured cameras and their running session (M7 step 5; plan C2, C4, section 5).

`CameraService` is what the camera routes call. It configures cameras (a `CAMERA` Source and its
device row), starts one session at a time on its own thread (`start_camera_session`, then
`CameraSessionExecutor.run` over a `LiveCamera`), stops it, and reports it: the session's state,
how many frames it saw and dropped, how many encounters are open, and why it ended. The preview is
the newest frame with its detected faces outlined, kept **only in memory** and replaced by the next
one (C3, C4): it is encoded as a JPEG only when asked for and is never written anywhere.

Nothing starts on its own (C4): a session begins only through `start`. `close()` (application
shutdown) stops a running session, which then records its open encounters and ends `COMPLETED`.
"""

import io
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageDraw
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.cameras.capture import FrameSource, LiveCamera
from backend.app.cameras.models import CameraSourceMetadata
from backend.app.cameras.session import (
    CameraBusyError,
    CameraNotConfiguredError,
    CameraSessionExecutor,
    CameraSettings,
    Seen,
    running_session,
    start_camera_session,
)
from backend.app.sources.models import Source, SourceKind, SourceState
from backend.infrastructure.db.unit_of_work import UnitOfWork
from backend.infrastructure.media.camera import CameraError, CaptureDevice

PREVIEW_MAX_SIDE = 640
CAPTURE_SECONDS = 10.0  # the longest a search waits for a camera's first picture
PREVIEW_QUALITY = 75
STOP_SECONDS = 30.0  # the longest a stop waits for the session to record and end


class SessionState(StrEnum):
    STARTING = "STARTING"  # started, no frame yet
    RUNNING = "RUNNING"
    RECONNECTING = "RECONNECTING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class CameraStatus:
    camera_id: uuid.UUID
    state: SessionState | None  # None: no session since the application started
    job_id: uuid.UUID | None = None
    frames: int = 0
    dropped: int = 0
    open_encounters: int = 0
    encounters: int = 0  # encounters recorded by this session
    failure_code: str | None = None


@dataclass
class _Session:
    camera_id: uuid.UUID
    job_id: uuid.UUID
    live: LiveCamera
    thread: threading.Thread | None = None
    frames: int = 0
    open_encounters: int = 0
    encounters: int = 0
    ended: SessionState | None = None
    failure_code: str | None = None
    last: Seen | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


class CameraService:
    def __init__(
        self,
        uow: UnitOfWork,
        *,
        new_id: Callable[[], uuid.UUID],
        clock: Callable[[], datetime],
        executor: Callable[[], CameraSessionExecutor],
        request_for: Callable[[Session], dict[str, Any]],
        open_source: Callable[[CaptureDevice, CameraSettings], FrameSource],
        settings: CameraSettings | None = None,
        announce: Callable[[str, uuid.UUID, dict[str, Any]], None] = lambda *_: None,
    ) -> None:
        self._uow = uow
        self._new_id = new_id
        self._clock = clock
        self._executor = executor
        self._request_for = request_for
        self._open_source = open_source
        self._settings = settings or CameraSettings()
        self._announce = announce
        self._lock = threading.Lock()
        self._sessions: dict[uuid.UUID, _Session] = {}  # the latest session of each camera

    # --- configuration ----------------------------------------------------------------------

    def configure(self, display_name: str, device: CaptureDevice) -> uuid.UUID:
        def add(session: Session) -> uuid.UUID:
            now = self._clock()
            source = Source(
                id=self._new_id(),
                kind=SourceKind.CAMERA,
                state=SourceState.ACTIVE,
                display_name=display_name,
                original_artifact_id=None,
                created_at=now,
                updated_at=now,
            )
            session.add(source)
            session.flush()
            session.add(
                CameraSourceMetadata(
                    source_id=source.id, device_name=device.name, device_path=device.path
                )
            )
            session.flush()
            return source.id

        return self._uow.write(add)

    def device(self, session: Session, camera_id: uuid.UUID) -> CaptureDevice:
        """The device of an active camera (`CameraNotConfiguredError` otherwise)."""
        row = session.execute(
            select(CameraSourceMetadata)
            .join(Source, Source.id == CameraSourceMetadata.source_id)
            .where(Source.id == camera_id, Source.state == SourceState.ACTIVE)
        ).scalar_one_or_none()
        if row is None:
            raise CameraNotConfiguredError(f"no active camera {camera_id}")
        return CaptureDevice(row.device_name, row.device_path)

    def remove(self, camera_id: uuid.UUID) -> None:
        """Remove a camera's configuration; its history stays (C9). Refused while it runs."""

        def remove(session: Session) -> None:
            self.device(session, camera_id)
            if running_session(session) == camera_id:
                raise CameraBusyError("stop the camera before removing it")
            source = session.get(Source, camera_id)
            assert source is not None
            source.state = SourceState.UNAVAILABLE
            source.updated_at = self._clock()
            source.revision += 1

        self._uow.write(remove)

    # --- sessions ---------------------------------------------------------------------------

    def start(self, camera_id: uuid.UUID) -> uuid.UUID:
        """Start a session on its own thread; returns its job. `CameraBusyError` while one runs,
        `CameraNotConfiguredError` for an unknown or removed camera."""
        with self._lock:

            def begin(session: Session) -> tuple[Any, CaptureDevice]:
                device = self.device(session, camera_id)
                started = start_camera_session(
                    session,
                    camera_id,
                    processing_request=self._request_for(session),
                    settings=self._settings,
                    new_id=self._new_id,
                    now=self._clock(),
                )
                return started, device

            started, device = self._uow.write(begin)
            job_id: uuid.UUID = started.job.id
            live = LiveCamera(
                lambda: self._open_source(device, self._settings),
                reconnect_timeout=self._settings.reconnect_timeout_seconds,
            )
            running = _Session(camera_id, started.job.id, live)
            running.thread = threading.Thread(
                target=self._run, args=(running, started), name=f"camera-{camera_id}", daemon=True
            )
            self._sessions[camera_id] = running
            running.thread.start()
        self._announce("camera.session.updated", camera_id, {"state": SessionState.STARTING})
        return job_id

    def stop(self, camera_id: uuid.UUID, *, wait: float = STOP_SECONDS) -> bool:
        """Stop the camera's session, if one runs here; True if it was running."""
        with self._lock:
            running = self._sessions.get(camera_id)
        if running is None or running.ended is not None:
            return False
        running.live.close()
        assert running.thread is not None  # (set before the session is published)
        running.thread.join(wait)
        return True

    def close(self) -> None:
        """Stop every running session (application shutdown)."""
        with self._lock:
            cameras = list(self._sessions)
        for camera_id in cameras:
            self.stop(camera_id)

    def status(self, camera_id: uuid.UUID) -> CameraStatus:
        with self._lock:
            running = self._sessions.get(camera_id)
        if running is None:
            return CameraStatus(camera_id, None)
        with running.lock:
            if running.ended is not None:
                state = running.ended
            elif running.live.reconnecting:
                state = SessionState.RECONNECTING
            else:
                state = SessionState.RUNNING if running.frames else SessionState.STARTING
            return CameraStatus(
                camera_id,
                state,
                running.job_id,
                running.frames,
                running.live.dropped,
                running.open_encounters,
                running.encounters,
                running.failure_code,
            )

    def preview(self, camera_id: uuid.UUID) -> bytes | None:
        """The newest frame with its faces outlined, as a JPEG, while a session runs; else None."""
        with self._lock:
            running = self._sessions.get(camera_id)
        if running is None:
            return None
        with running.lock:
            last = running.last if running.ended is None else None
        if last is None:
            return None
        return _annotated(last.frame.pixels, [d.box for d in last.detected.detections])

    def capture(self, camera_id: uuid.UUID) -> bytes:
        """One picture from the camera, as a PNG held in memory, for a search (spec 10.4; plan C10):
        the running session's newest frame when this camera runs (the device cannot be opened
        twice), else one frame read from the device and the device closed again. Nothing is
        stored. `CameraNotConfiguredError` for an unknown camera; `CameraError` (with its code) when
        the device gives no picture."""
        with self._lock:
            running = self._sessions.get(camera_id)
        if running is not None:
            with running.lock:
                last = running.last if running.ended is None else None
            if last is not None:
                return _png(last.frame.pixels)
        device = self._uow.read(lambda session: self.device(session, camera_id))
        source = self._open_source(device, self._settings)
        source.start()
        try:
            return _png(source.latest(CAPTURE_SECONDS).pixels)
        finally:
            source.stop()

    # --- the session's thread ---------------------------------------------------------------

    def _run(self, running: _Session, started: Any) -> None:
        def seen(item: Seen) -> None:
            with running.lock:
                running.frames += 1
                running.open_encounters = item.open_encounters
                running.last = item

        def closed(occurrence: uuid.UUID | None) -> None:
            with running.lock:
                running.encounters += 1
            self._announce(
                "camera.encounter.closed",
                running.camera_id,
                {"occurrence_id": None if occurrence is None else str(occurrence)},
            )

        ended, code = SessionState.STOPPED, None
        try:
            self._executor().run(started, running.live.frames(), seen=seen, closed=closed)
        except CameraError as error:
            ended, code = SessionState.FAILED, error.code
        except Exception as error:  # noqa: BLE001 - the session is settled FAILED by the executor
            ended, code = SessionState.FAILED, type(error).__name__
        finally:
            running.live.close()
        with running.lock:
            running.ended, running.failure_code, running.last = ended, code, None
        self._announce(
            "camera.session.updated", running.camera_id, {"state": ended, "failure_code": code}
        )


def _annotated(pixels: NDArray[np.uint8], boxes: list[tuple[float, float, float, float]]) -> bytes:
    image = Image.fromarray(pixels, "RGB")
    image.thumbnail((PREVIEW_MAX_SIDE, PREVIEW_MAX_SIDE))
    draw = ImageDraw.Draw(image)
    width, height = image.size
    for x0, y0, x1, y1 in boxes:
        draw.rectangle(
            (x0 * width, y0 * height, x1 * width, y1 * height), outline=(255, 210, 0), width=2
        )
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=PREVIEW_QUALITY)
    return buffer.getvalue()


def _png(pixels: NDArray[np.uint8]) -> bytes:
    buffer = io.BytesIO()
    Image.fromarray(pixels, "RGB").save(buffer, format="PNG")
    return buffer.getvalue()
