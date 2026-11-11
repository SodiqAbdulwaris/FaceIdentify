"""A camera's frames across interruptions, and the parts of the ffmpeg adapter that need no tool
(M7 step 2; plan C2, C7; TST-071, TST-072). Scripted frame sources and a fake clock: no camera, no
waiting."""

import threading
from collections.abc import Callable, Iterator
from pathlib import Path

import numpy as np
import pytest

from backend.app.cameras.capture import BACKOFF_SECONDS, Gap, LiveCamera
from backend.infrastructure.media.camera import (
    CameraAccessDeniedError,
    CameraError,
    CameraInUseError,
    CameraNotFoundError,
    CameraStalledError,
    CameraStreamError,
    CaptureDevice,
    LiveFrame,
    capture_command,
    classify,
    device_input,
    parse_devices,
)
from backend.infrastructure.media.video import MediaTools

# What `ffmpeg -list_devices true -f dshow -i dummy` printed on the development machine
# (2026-11-11), with a second, invented camera and an audio device between them.
LISTING = """\
[in#0 @ 000002028658f8c0] "Integrated Camera" (video)
[in#0 @ 000002028658f8c0]   Alternative name "@device_pnp_\\\\?\\usb#vid_30c9&pid_00ac#global"
[in#0 @ 000002028658f8c0] "Microphone Array (Realtek(R) Audio)" (audio)
[in#0 @ 000002028658f8c0]   Alternative name "@device_cm_{33D9A762}\\wave_{5F0AFFBC}"
[in#0 @ 000002028658f8c0] "USB Capture (2)" (video)
Error opening input file dummy.
"""


def frame(sequence: int) -> LiveFrame:
    return LiveFrame(sequence, float(sequence), np.zeros((1, 1, 3), dtype=np.uint8))


class Scripted:
    """A frame source that gives its script in order, then stalls."""

    def __init__(self, *script: LiveFrame | CameraError, dropped: int = 0) -> None:
        self.script = list(script)
        self.dropped = dropped
        self.started = self.stopped = False

    def start(self) -> None:
        self.started = True

    def latest(self, timeout: float) -> LiveFrame:
        item = self.script.pop(0) if self.script else CameraStalledError("silent")
        if isinstance(item, CameraError):
            raise item
        return item

    def stop(self) -> None:
        self.stopped = True


class Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.waits: list[float] = []

    def __call__(self) -> float:
        return self.now

    def wait(self, closed: threading.Event, seconds: float) -> bool:
        self.waits.append(seconds)
        self.now += seconds
        return closed.is_set()


def opener(*sources: Scripted | CameraError) -> Callable[[], Scripted]:
    queue = list(sources)

    def open_source() -> Scripted:
        item = queue.pop(0)
        if isinstance(item, CameraError):
            raise item
        return item

    return open_source


def camera(*sources: Scripted | CameraError, clock: Clock | None = None) -> LiveCamera:
    clock = clock or Clock()
    return LiveCamera(
        opener(*sources), reconnect_timeout=30, frame_timeout=5, clock=clock, wait=clock.wait
    )


def take(stream: Iterator[LiveFrame | Gap], count: int) -> list[int | Gap]:
    """The next items: a frame by its sequence (its pixels are an array), a gap as it is."""
    return [seq(next(stream)) for _ in range(count)]


def seq(item: LiveFrame | Gap) -> int | Gap:
    return item.sequence if isinstance(item, LiveFrame) else item


def test_devices_are_parsed_with_their_paths_and_audio_is_left_out() -> None:
    assert parse_devices(LISTING) == [
        CaptureDevice("Integrated Camera", "@device_pnp_\\\\?\\usb#vid_30c9&pid_00ac#global"),
        CaptureDevice("USB Capture (2)", None),
    ]
    assert parse_devices("nothing here") == []


def test_a_device_is_opened_by_its_path_when_it_has_one() -> None:
    assert device_input(CaptureDevice("Cam", "@device_pnp_x"))[-1] == "video=@device_pnp_x"
    assert device_input(CaptureDevice("Cam", None))[-1] == "video=Cam"


def test_the_capture_command_samples_and_bounds_the_size_inside_the_tool() -> None:
    tools = MediaTools(Path("ffmpeg"), Path("ffprobe"))
    command = capture_command(tools, ["-i", "x"], rate=5, max_side=640)

    assert command[command.index("-vf") + 1].startswith("fps=5,scale='min(640,iw)'")
    assert command[-4:] == ["ppm", "-f", "image2pipe", "pipe:1"]
    with pytest.raises(ValueError, match="positive"):
        capture_command(tools, [], rate=0)
    with pytest.raises(ValueError, match="positive"):
        capture_command(tools, [], max_side=0)


@pytest.mark.parametrize(
    ("log", "error"),
    [
        ("Could not find video device with name [X] among source devices", CameraNotFoundError),
        ("Could not run graph (sometimes caused by a device already in use", CameraInUseError),
        ("Error: Access is denied.", CameraAccessDeniedError),
        ("returned 0x80070005", CameraAccessDeniedError),
        ("Error during demuxing: I/O error", CameraStreamError),
    ],
)
def test_a_failed_capture_is_classified_by_its_log(log: str, error: type[CameraError]) -> None:
    assert classify(log) is error


def test_the_error_codes_are_the_api_codes() -> None:
    assert CameraNotFoundError.code == CameraStreamError.code == "CAMERA_DISCONNECTED"
    assert CameraInUseError.code == "CAMERA_IN_USE"
    assert CameraAccessDeniedError.code == "CAMERA_ACCESS_DENIED"


def test_frames_flow_and_the_source_is_stopped_at_the_end() -> None:
    source = Scripted(frame(1), frame(2), dropped=3)
    live = camera(source)
    stream = live.frames()

    assert take(stream, 2) == [1, 2]
    assert live.dropped == 3
    stream.close()
    assert source.started
    assert source.stopped
    assert live.dropped == 3  # (kept after the source stopped)


@pytest.mark.parametrize(
    "error", [CameraInUseError("busy"), CameraAccessDeniedError("no"), CameraNotFoundError("gone")]
)
def test_a_failure_before_the_first_frame_is_raised_as_it_is(error: CameraError) -> None:
    source = Scripted(error)
    with pytest.raises(type(error)):
        next(camera(source).frames())
    assert source.stopped


def test_a_device_that_cannot_be_opened_at_the_start_is_raised() -> None:
    with pytest.raises(CameraNotFoundError):
        next(camera(CameraNotFoundError("absent")).frames())


def test_a_break_is_a_gap_then_frames_resume_after_backoff() -> None:
    clock = Clock()
    first = Scripted(frame(1), CameraStreamError("unplugged"), dropped=2)
    second = Scripted(frame(1))
    live = camera(first, CameraNotFoundError("still unplugged"), second, clock=clock)
    stream = live.frames()

    assert seq(next(stream)) == 1
    gap = next(stream)
    assert isinstance(gap, Gap)
    assert "unplugged" in gap.reason
    reconnecting_in_the_gap = live.reconnecting
    assert seq(next(stream)) == 1  # the new stream's own first frame: new tracks begin
    assert (reconnecting_in_the_gap, live.reconnecting) == (True, False)
    assert clock.waits == list(BACKOFF_SECONDS[:2])
    assert first.stopped
    assert live.dropped == 2
    stream.close()


def test_a_reconnected_source_that_fails_before_a_frame_keeps_reconnecting() -> None:
    clock = Clock()
    live = camera(
        Scripted(frame(1), CameraStalledError("silent")),
        Scripted(CameraInUseError("taken by another program")),
        Scripted(frame(1)),
        clock=clock,
    )
    stream = live.frames()

    assert [type(item) for item in take(stream, 3)] == [int, Gap, int]  # one gap
    stream.close()


def test_a_camera_that_does_not_come_back_ends_the_stream_after_the_timeout() -> None:
    clock = Clock()
    live = camera(
        Scripted(frame(1), CameraStreamError("unplugged")),
        *[CameraNotFoundError("gone")] * 20,
        clock=clock,
    )
    stream = live.frames()
    take(stream, 2)

    with pytest.raises(CameraError, match="within 30 seconds") as raised:
        next(stream)

    assert raised.value.code == "CAMERA_DISCONNECTED"
    assert sum(clock.waits) == pytest.approx(30)
    assert max(clock.waits) == BACKOFF_SECONDS[-1]
    assert not live.reconnecting


def test_closing_ends_the_stream_quietly_even_while_reconnecting() -> None:
    clock = Clock()
    live = camera(Scripted(frame(1), CameraStreamError("unplugged")), clock=clock)
    stream = live.frames()
    take(stream, 2)

    live.close()

    assert list(stream) == []


def test_closing_stops_the_current_source_and_its_failure_is_not_raised() -> None:
    source = Scripted(frame(1), CameraStreamError("the capture was stopped"))
    live = camera(source)
    stream = live.frames()
    next(stream)

    live.close()

    assert source.stopped
    assert list(stream) == []
    live.close()  # (twice is harmless)


def test_a_source_started_after_close_is_stopped_at_once() -> None:
    late = Scripted(frame(1))
    live: LiveCamera

    def open_and_close() -> Scripted:
        live.close()  # (closed while the source was being opened)
        return late

    live = LiveCamera(open_and_close)

    assert list(live.frames()) == []
    assert late.started
    assert late.stopped


def test_a_failure_caused_by_closing_is_not_raised() -> None:
    """`close()` from another thread stops the source while `latest` waits on it."""
    live: LiveCamera

    class ClosedWhileWaiting(Scripted):
        def latest(self, timeout: float) -> LiveFrame:
            if self.script:
                return super().latest(timeout)
            live.close()
            raise CameraStreamError("the capture was stopped")

    source = ClosedWhileWaiting(frame(1))
    live = camera(source)

    assert [seq(item) for item in live.frames()] == [1]  # then it ends quietly
    assert source.stopped
