"""A camera's frames across interruptions (M7 step 2; plan C7 and C12).

`LiveCamera` turns a frame-source factory into one stream of frames and gaps. Before the first
frame any failure is raised as it is (the session fails to start with a reason the user can act on:
the camera is missing, in use, refused by Windows or gave nothing). Once frames have flowed, a
failure is a `Gap` (every open track ends there: no continuity is invented across unobserved
time) followed by reconnection with backoff; if the camera does not come back within
`reconnect_timeout` seconds the stream ends with `CameraError` (`CAMERA_DISCONNECTED`). `close()`
ends it from any thread.

The frame source is a port: `FfmpegFrameSource` is the real adapter (the pinned ffmpeg), and the
tests use scripted fakes and ffmpeg's synthetic sources, never a camera.
"""

import threading
import time
from collections.abc import Callable, Generator
from dataclasses import dataclass
from typing import Protocol

from backend.infrastructure.media.camera import CameraError, LiveFrame

FRAME_TIMEOUT_SECONDS = 5.0  # silence longer than this is a gap
RECONNECT_TIMEOUT_SECONDS = 30.0  # plan C7: `camera.reconnect_timeout_seconds`
BACKOFF_SECONDS = (0.5, 1.0, 2.0, 4.0)  # then the last value again


class FrameSource(Protocol):
    @property
    def dropped(self) -> int: ...

    def start(self) -> None: ...

    def latest(self, timeout: float) -> LiveFrame: ...

    def stop(self) -> None: ...


@dataclass(frozen=True, slots=True)
class Gap:
    """The frames stopped (`reason`); whatever follows is a new stretch of observation."""

    reason: str


class LiveCamera:
    def __init__(
        self,
        open_source: Callable[[], FrameSource],
        *,
        frame_timeout: float = FRAME_TIMEOUT_SECONDS,
        reconnect_timeout: float = RECONNECT_TIMEOUT_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        wait: Callable[[threading.Event, float], object] = threading.Event.wait,
    ) -> None:
        self._open = open_source
        self._wait = wait  # (the backoff pause; tests pass one that advances their clock)
        self._frame_timeout = frame_timeout
        self._reconnect_timeout = reconnect_timeout
        self._clock = clock
        self._closed = threading.Event()
        self._lock = threading.Lock()
        self._source: FrameSource | None = None
        self._dropped_before = 0  # frames dropped by sources already stopped
        self.reconnecting = False

    @property
    def dropped(self) -> int:
        with self._lock:
            current = self._source.dropped if self._source is not None else 0
            return self._dropped_before + current

    def close(self) -> None:
        """End the stream: the current source stops and `frames()` returns."""
        self._closed.set()
        with self._lock:
            source = self._source
        if source is not None:
            source.stop()

    def frames(self) -> Generator[LiveFrame | Gap]:
        started = False  # a frame has come since the start: later failures are gaps
        gap_began: float | None = None  # when the current gap began (None while frames flow)
        attempt = 0
        try:
            while not self._closed.is_set():
                try:
                    if self._source is None:
                        self._replace(self._open())
                    if self._source is None:  # (closed while it was being opened)
                        return
                    frame = self._source.latest(self._frame_timeout)
                except CameraError as error:
                    if self._closed.is_set():
                        return
                    if not started:
                        raise
                    self._replace(None)
                    if gap_began is None:
                        gap_began, attempt, self.reconnecting = self._clock(), 0, True
                        yield Gap(str(error))
                    left = self._reconnect_timeout - (self._clock() - gap_began)
                    if left <= 0:
                        raise CameraError(
                            "the camera did not come back within"
                            f" {self._reconnect_timeout:g} seconds: {error}"
                        ) from error
                    delay = BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)]
                    attempt += 1
                    self._wait(self._closed, min(delay, left))
                    continue
                started, gap_began, self.reconnecting = True, None, False
                yield frame
        finally:
            self.reconnecting = False
            self._replace(None)

    def _replace(self, source: FrameSource | None) -> None:
        """Stop the current source (keeping its drop count) and start `source` in its place."""
        with self._lock:
            old, self._source = self._source, None
        if old is not None:
            old.stop()
            with self._lock:
                self._dropped_before += old.dropped
        if source is None:
            return
        source.start()
        with self._lock:
            self._source = source
        if self._closed.is_set():  # (closed while it started: stop it too)
            self._replace(None)
