"""Live camera frames over the pinned ffmpeg (M7 step 2; plan C1, C2 and C12).

A camera is a DirectShow device opened by the pinned LGPL `ffmpeg` (`-f dshow`): no new
dependency, and frames never pass through the web view. Sampling happens inside the subprocess
(`fps` filter, the largest side bounded by `max_side`), so the pipe never carries more than the
pipeline asks for. Each frame is written as a binary PPM (`P6`), which carries its own size, so
nothing is read from the tool's log to frame the stream and a stream whose size changes is still
read correctly.

`FfmpegFrameSource` is bounded by construction: a reader thread keeps **only the newest frame** (a
buffer of one) and counts every frame replaced before it was taken (`dropped`), so a slow consumer
never builds a backlog and always gets the freshest picture. `latest()` waits for a frame newer than
the last one taken; a stream that ends, fails or stays silent too long raises a `CameraError`, whose
type says why (the device is missing, in use by another program, refused by Windows, or the stream
broke or stalled). The subprocess is stopped and reaped on every exit path (`stop()`, which the
context manager calls).

The same class reads any command that writes PPM frames, so the tests replay ffmpeg's own synthetic
sources through the identical parser; no test needs a camera.
"""

import re
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import IO

import numpy as np
from numpy.typing import NDArray

from backend.infrastructure.media.video import NO_WINDOW, MediaTools

SAMPLE_FPS = 5.0  # detection rate (plan C2: `camera.sample_fps`)
MAX_SIDE = 1920  # the largest side a frame is given at (as for videos)
LIST_TIMEOUT_SECONDS = 20
_DEVICE = re.compile(r'"(?P<name>[^"]+)"\s+\((?P<kinds>[^)]*)\)')
_ALTERNATIVE = re.compile(r'Alternative name\s+"(?P<path>[^"]+)"')


@dataclass(frozen=True, slots=True)
class CaptureDevice:
    """A video capture device the computer offers: its shown name and stable path (if any)."""

    name: str
    path: str | None


@dataclass(frozen=True, slots=True)
class LiveFrame:
    sequence: int  # 1, 2, ... in the order the stream gave them (gaps are dropped frames)
    received_at: float  # monotonic seconds when the frame was read
    pixels: NDArray[np.uint8]  # height x width x 3, RGB


class CameraError(Exception):
    """The camera gave no (more) frames. `code` is the API error code."""

    code = "CAMERA_DISCONNECTED"


class CameraNotFoundError(CameraError):
    """No such device is present (never plugged in, or unplugged)."""


class CameraInUseError(CameraError):
    code = "CAMERA_IN_USE"


class CameraAccessDeniedError(CameraError):
    code = "CAMERA_ACCESS_DENIED"


class CameraStreamError(CameraError):
    """The stream ended, broke or sent something that is not a frame."""


class CameraStalledError(CameraStreamError):
    """No frame arrived in time."""


def list_devices(
    tools: MediaTools, *, timeout: float = LIST_TIMEOUT_SECONDS
) -> list[CaptureDevice]:
    """The video capture devices DirectShow offers now, in its order. ffmpeg lists them on its log
    and then fails to open the dummy input, which is expected."""
    try:
        completed = subprocess.run(
            [str(tools.ffmpeg), "-hide_banner", "-list_devices", "true", "-f", "dshow"]
            + ["-i", "dummy"],
            capture_output=True,
            timeout=timeout,
            check=False,
            creationflags=NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise CameraError(f"the capture devices could not be listed: {error}") from error
    return parse_devices(completed.stderr.decode("utf-8", "replace"))


def parse_devices(log: str) -> list[CaptureDevice]:
    """Video devices from `ffmpeg -list_devices true -f dshow` output (each device line may be
    followed by its alternative name)."""
    devices: list[CaptureDevice] = []
    video = False  # (whether the alternative name that follows belongs to a video device)
    for line in log.splitlines():
        alternative = _ALTERNATIVE.search(line)
        if alternative:
            if video:
                devices[-1] = CaptureDevice(devices[-1].name, alternative.group("path"))
            continue
        device = _DEVICE.search(line)
        if device:
            video = "video" in device.group("kinds").split(",")
            if video:
                devices.append(CaptureDevice(device.group("name"), None))
    return devices


def device_input(device: CaptureDevice) -> list[str]:
    """ffmpeg input options that open a device, by its stable path when it has one. A small
    real-time buffer: a camera's frames are worth nothing once stale."""
    return ["-f", "dshow", "-rtbufsize", "16M", "-i", f"video={device.path or device.name}"]


def capture_command(
    tools: MediaTools,
    input_args: Sequence[str],
    *,
    rate: float = SAMPLE_FPS,
    max_side: int = MAX_SIDE,
) -> list[str]:
    """ffmpeg reading `input_args`, sampled to `rate` frames per second, the larger side at most
    `max_side` (aspect kept, never enlarged), written as PPM frames on standard output."""
    if not (rate > 0 and max_side > 0):
        raise ValueError("the rate and max_side must be positive")
    scale = f"scale='min({max_side},iw)':'min({max_side},ih)':force_original_aspect_ratio=decrease"
    return (
        [str(tools.ffmpeg), "-hide_banner", "-nostats", "-loglevel", "error", *input_args]
        + ["-an", "-sn", "-dn", "-vf", f"fps={rate!r},{scale}"]
        + ["-c:v", "ppm", "-f", "image2pipe", "pipe:1"]
    )


def classify(log: str) -> type[CameraError]:
    """The error a failed capture's log describes."""
    text = log.lower()
    # (a missing device, or a computer with no capture device at all)
    if (
        "could not find" in text and "device" in text
    ) or "could not enumerate video devices" in text:
        return CameraNotFoundError
    if "access is denied" in text or "0x80070005" in text or "e_accessdenied" in text:
        return CameraAccessDeniedError
    if "already in use" in text or "could not run graph" in text:
        return CameraInUseError
    return CameraStreamError


class FfmpegFrameSource:
    """The newest frame of a running capture command (see the module docstring)."""

    def __init__(
        self,
        command: Sequence[str],
        *,
        clock: Callable[[], float] = time.monotonic,
        max_pixels: int = MAX_SIDE * MAX_SIDE,
    ) -> None:
        """`max_pixels`: the most a frame may hold (the capture's `max_side` squared); a header
        claiming more is corrupt, and nothing is read for it."""
        self._command = list(command)
        self._clock = clock
        self._max_pixels = max_pixels
        self._stopping = threading.Lock()  # (one stop at a time: a second one waits, then returns)
        self._stopped = False
        self._condition = threading.Condition()
        self._frame: LiveFrame | None = None
        self._taken = 0  # the sequence of the last frame `latest` returned
        self._dropped = 0
        self._failure: CameraError | None = None
        self._process: subprocess.Popen[bytes] | None = None
        self._threads: list[threading.Thread] = []
        self._log: deque[str] = deque(maxlen=8)  # the tool's last log lines, for errors

    @property
    def dropped(self) -> int:
        """Frames replaced by a newer one before they were taken."""
        with self._condition:
            return self._dropped

    def start(self) -> None:
        if self._process is not None:
            raise RuntimeError("the capture is already started")
        try:
            process = subprocess.Popen(
                self._command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=NO_WINDOW,
            )
        except OSError as error:
            raise CameraError(f"the capture tool could not be started: {error}") from error
        self._process = process
        assert process.stdout is not None
        assert process.stderr is not None
        self._threads = [
            threading.Thread(target=self._read_log, args=(process.stderr,), daemon=True),
            threading.Thread(target=self._read_frames, args=(process.stdout,), daemon=True),
        ]
        for thread in self._threads:
            thread.start()

    def latest(self, timeout: float) -> LiveFrame:
        """The newest frame not yet taken, waiting up to `timeout` seconds for one."""
        with self._condition:
            ready = self._condition.wait_for(
                lambda: (
                    self._failure is not None
                    or (self._frame is not None and self._frame.sequence > self._taken)
                ),
                timeout=timeout,
            )
            frame = self._frame
            if frame is not None and frame.sequence > self._taken:
                self._taken = frame.sequence  # (a frame read before a failure is still given)
                return frame
            if self._failure is not None:
                raise self._failure
            assert not ready
            raise CameraStalledError(f"no frame arrived in {timeout:g} seconds")

    def wait_ended(self, timeout: float) -> bool:
        """Wait until the stream has ended (or the capture was stopped); False on timeout."""
        with self._condition:
            return self._condition.wait_for(lambda: self._failure is not None, timeout=timeout)

    def stop(self) -> None:
        """Stop the tool and reap it, and wait for the readers. Safe to call more than once and
        from several threads at once (a session stopping while its stream is being closed)."""
        with self._stopping:
            if self._stopped or self._process is None:
                return
            self._stopped = True
            self._stop(self._process)

    def _stop(self, process: subprocess.Popen[bytes]) -> None:
        if process.poll() is None:
            process.kill()
        process.wait()
        for thread in self._threads:
            thread.join()
        assert process.stdout is not None
        assert process.stderr is not None
        process.stdout.close()
        process.stderr.close()
        with self._condition:  # (whatever ended the stream, a stopped capture gives nothing more)
            self._frame = None
            self._failure = CameraStreamError("the capture was stopped")
            self._condition.notify_all()

    def __enter__(self) -> "FfmpegFrameSource":
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()

    def _read_log(self, stream: IO[bytes]) -> None:
        for line in stream:
            self._log.append(line.decode("utf-8", "replace").strip())

    def _read_frames(self, stream: IO[bytes]) -> None:
        sequence = 0
        failure: CameraError
        try:
            while (pixels := _read_ppm(stream, self._max_pixels)) is not None:
                sequence += 1
                frame = LiveFrame(sequence, self._clock(), pixels)
                with self._condition:
                    if self._frame is not None and self._frame.sequence > self._taken:
                        self._dropped += 1  # (replaced before anyone took it)
                    self._frame = frame
                    self._condition.notify_all()
            failure = self._ended()
        except CameraStreamError as error:
            failure = error
        with self._condition:
            self._failure = failure
            self._condition.notify_all()

    def _ended(self) -> CameraError:
        """Why the stream ended, from the tool's log once it has exited."""
        process = self._process
        assert process is not None
        process.wait()
        for thread in self._threads[:1]:
            thread.join()  # (the whole log, so the reason is in it)
        log = " ".join(self._log)
        return classify(log)(f"the camera stream ended: {log or 'no detail'}")


def _read_ppm(stream: IO[bytes], max_pixels: int) -> NDArray[np.uint8] | None:
    """One binary PPM frame (`P6`, maxval 255), or None at the end of the stream. A frame of more
    than `max_pixels` is refused before its bytes are read."""
    magic = stream.readline()
    if not magic:
        return None
    try:
        if magic.strip() != b"P6":
            raise ValueError("not a PPM frame")
        width, height = (int(part) for part in stream.readline().split())
        if int(stream.readline()) != 255:
            raise ValueError("not an 8-bit frame")
    except ValueError as error:
        raise CameraStreamError(
            f"the stream sent something that is not a frame: {error}"
        ) from error
    if not (width > 0 and height > 0 and width * height <= max_pixels):
        raise CameraStreamError(f"the stream sent a frame of an impossible size {width}x{height}")
    size = width * height * 3
    data = stream.read(size)
    if len(data) != size:
        raise CameraStreamError("the stream ended inside a frame")
    return np.frombuffer(data, dtype=np.uint8).reshape(height, width, 3)
