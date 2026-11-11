"""Live camera frames over the pinned ffmpeg (M7 step 2; TST-071, TST-072).

No camera is used: ffmpeg's own synthetic source (`lavfi`) stands in for the device and goes through
the identical PPM parser, and small Python writers stand in for broken streams. DirectShow itself is
asked only for a device that does not exist.
"""

import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from backend.infrastructure.media.camera import (
    CameraError,
    CameraNotFoundError,
    CameraStalledError,
    CameraStreamError,
    CaptureDevice,
    FfmpegFrameSource,
    capture_command,
    device_input,
    list_devices,
)
from backend.infrastructure.media.video import MediaTools
from tests.fixtures.media import installed_tools

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="DirectShow and the pinned build")


def synthetic(*, rate: float = 5, seconds: float | None = None, size: str = "64x48") -> list[str]:
    """ffmpeg's test pattern, paced in real time like a camera."""
    limit = [] if seconds is None else ["-t", str(seconds)]
    return capture_command(
        installed_tools(),
        ["-re", "-f", "lavfi", *limit, "-i", f"testsrc=size={size}:rate=25"],
        rate=rate,
        max_side=32,
    )


def writer(tmp_path: Path, body: str) -> list[str]:
    """A command that writes `body`'s bytes to standard output, then exits."""
    script = tmp_path / "writer.py"
    script.write_text(
        f"import sys, time\nout = sys.stdout.buffer\n{body}\nout.flush()\n", encoding="utf-8"
    )
    return [sys.executable, "-I", str(script)]


def test_frames_are_sampled_scaled_and_given_newest_first() -> None:
    with FfmpegFrameSource(synthetic(rate=10)) as source:
        first = source.latest(timeout=10)
        second = source.latest(timeout=10)

    assert first.pixels.shape == (24, 32, 3)  # 64x48 bounded to 32 on its larger side
    assert first.pixels.dtype.name == "uint8"
    assert second.sequence > first.sequence
    assert second.received_at >= first.received_at


def eventually(condition: Callable[[], bool], seconds: float = 20) -> None:
    """Wait (polling) until `condition()` holds; fail after `seconds`."""
    deadline = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < deadline, "the condition never held"
        time.sleep(0.01)


def test_a_stalled_consumer_holds_one_frame_and_counts_the_rest_as_dropped(
    tmp_path: Path,
) -> None:
    body = (
        "for n in range(6):\n"
        "    out.write(b'P6\\n1 1\\n255\\n' + bytes([n, n, n]))\n"
        "out.flush()\n"
        "time.sleep(30)"
    )
    command = writer(tmp_path, body)
    with FfmpegFrameSource(command) as source:
        eventually(lambda: source.dropped == 5)  # the consumer took nothing while six came
        newest = source.latest(timeout=10)
        with pytest.raises(CameraStalledError):
            source.latest(timeout=0.2)  # nothing older is kept to be given late

    assert newest.sequence == 6
    assert newest.pixels.tolist() == [[[5, 5, 5]]]


def test_the_end_of_the_stream_is_an_error_after_the_last_frame() -> None:
    source = FfmpegFrameSource(synthetic(rate=10, seconds=0.5))
    source.start()

    def drain() -> None:
        while True:
            frames.append(source.latest(timeout=10))

    frames: list[object] = []
    try:
        with pytest.raises(CameraStreamError, match="ended"):
            drain()
        assert frames
    finally:
        source.stop()
    source.stop()  # stopping twice is harmless


def test_a_stalled_producer_is_reported_after_the_timeout(tmp_path: Path) -> None:
    command = writer(tmp_path, "time.sleep(30)")
    with FfmpegFrameSource(command) as source, pytest.raises(CameraStalledError, match="0.3"):
        source.latest(timeout=0.3)


def test_stopping_mid_stream_reaps_the_tool_and_ends_the_stream() -> None:
    source = FfmpegFrameSource(synthetic(rate=10))
    source.start()
    source.latest(timeout=10)
    source.stop()

    with pytest.raises(CameraStreamError, match="stopped|ended|broke"):
        source.latest(timeout=1)


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("out.write(b'P5\\n2 2\\n255\\n' + bytes(4))", "not a PPM frame"),
        ("out.write(b'P6\\n2 x\\n255\\n')", "not a frame"),
        ("out.write(b'P6\\n2 2\\n65535\\n')", "not an 8-bit frame"),
        ("out.write(b'P6\\n0 2\\n255\\n')", "impossible size"),
        ("out.write(b'P6\\n2 2\\n255\\n' + bytes(5))", "ended inside a frame"),
    ],
)
def test_a_corrupt_frame_breaks_the_stream(tmp_path: Path, body: str, message: str) -> None:
    with (
        FfmpegFrameSource(writer(tmp_path, body)) as source,
        pytest.raises(CameraStreamError, match=message),
    ):
        source.latest(timeout=10)


def test_a_frame_read_before_the_stream_ends_is_still_given(tmp_path: Path) -> None:
    body = "out.write(b'P6\\n2 1\\n255\\n' + bytes(range(6)))"
    with FfmpegFrameSource(writer(tmp_path, body)) as source:
        frame = source.latest(timeout=10)
        with pytest.raises(CameraStreamError, match="ended"):
            source.latest(timeout=10)

    assert frame.pixels.tolist() == [[[0, 1, 2], [3, 4, 5]]]


def test_a_missing_device_is_reported_as_not_found() -> None:
    device = CaptureDevice("FaceIdentify Test Camera That Does Not Exist", None)
    command = capture_command(installed_tools(), device_input(device))
    with FfmpegFrameSource(command) as source, pytest.raises(CameraNotFoundError) as raised:
        source.latest(timeout=20)

    assert raised.value.code == "CAMERA_DISCONNECTED"


def test_a_capture_tool_that_cannot_start_is_a_camera_error(tmp_path: Path) -> None:
    source = FfmpegFrameSource([str(tmp_path / "no-such-tool.exe")])
    with pytest.raises(CameraError, match="could not be started"):
        source.start()
    source.stop()  # (nothing was started: harmless)


def test_a_source_starts_only_once() -> None:
    with FfmpegFrameSource(synthetic()) as source, pytest.raises(RuntimeError, match="already"):
        source.start()


def test_listing_devices_runs_the_pinned_tool() -> None:
    devices = list_devices(installed_tools())

    assert all(device.name for device in devices)  # (a CI machine has none; this one may have one)


def test_a_tool_that_cannot_run_cannot_list_devices(tmp_path: Path) -> None:
    tools = MediaTools(tmp_path / "no-such-ffmpeg.exe", tmp_path / "no-such-ffprobe.exe")
    with pytest.raises(CameraError, match="could not be listed"):
        list_devices(tools)
