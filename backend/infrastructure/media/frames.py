"""Sampled video frames over an ffmpeg pipe (M6 step 4; D4).

One `ffmpeg` process decodes the video from a position and writes raw RGB frames to a pipe, as the
Source shows them (rotation applied). Sampling is by presentation time, never by counting frames:
time is cut into slots of `1 / rate` seconds and the first frame of each slot is kept
(`select`), so the same video always gives the same frames, whether it is decoded in one go or
resumed after a slot. Each kept frame's presentation time comes from `showinfo` on standard error,
read on a thread so neither pipe can block the other.

Resuming after slot `k` seeks to the start of slot `k + 1` (`-ss` before `-i`, an exact seek, with
`-copyts` so times stay the file's own) and drops anything that still falls in a slot already done,
so a frame is never given twice. A decode that fails part way, or a pipe that ends inside a frame,
is a corrupt video; the frames already given stay valid.
"""

import math
import queue
import re
import subprocess
import threading
from collections import deque
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from backend.infrastructure.media.video import NO_WINDOW, CorruptVideoError, MediaTools

SAMPLE_RATE = 2  # frames per second given to detection (D4); the caller may choose another
FRAME_TIMEOUT_SECONDS = 120  # the longest wait for one frame's time before the video is given up
_PTS_TIME = re.compile(rb"\bn:\s*\d+\s+pts:\s*-?\d+\s+pts_time:(-?[0-9.]+)")
_DONE = object()


@dataclass(frozen=True, slots=True)
class Frame:
    slot: int  # floor(time * rate): resuming after a slot never gives it, or anything before, again
    timestamp_ms: int  # presentation time
    pixels: NDArray[np.uint8]  # height x width x 3, RGB


def sampled_frames(
    tools: MediaTools,
    path: Path,
    *,
    width: int,
    height: int,
    rate: float = SAMPLE_RATE,
    after_slot: int = -1,
    max_side: int | None = None,
) -> Generator[Frame]:
    """The first frame of every slot after `after_slot`, in order. `width` and `height` are the
    size the Source records (as shown); with `max_side`, a larger frame is scaled down (aspect
    kept, `frame_size`) after it is chosen, so a 4K video holds a quarter of the memory.
    Raises `CorruptVideoError` when decoding fails."""
    if (
        not (math.isfinite(rate) and rate > 0)
        or width <= 0
        or height <= 0
        or (max_side is not None and max_side <= 0)
    ):
        raise ValueError("the rate, the size and max_side must be positive (the rate finite)")
    # The seek is rounded DOWN to the microsecond, so a frame exactly on the slot boundary is never
    # skipped; a frame before it, still in a slot already given, is dropped below. One rendering of
    # the rate serves ffmpeg's select and the slot arithmetic here.
    start = math.floor((after_slot + 1) / rate * 1_000_000) / 1_000_000
    rate_text = repr(float(rate))
    command = [str(tools.ffmpeg), "-hide_banner", "-nostats", "-v", "info", "-copyts"]
    command += ["-ss", f"{start:.6f}", "-i", str(path), "-an", "-sn", "-dn"]
    command += ["-vf", f"select='isnan(prev_selected_t)+gt(floor(t*{rate_text}),"]
    scaled = frame_size(width, height, max_side)
    scale = "" if scaled == (width, height) else f"scale={scaled[0]}:{scaled[1]},"
    width, height = scaled
    command[-1] += f"floor(prev_selected_t*{rate_text}))',{scale}showinfo"
    command += ["-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=NO_WINDOW,
    )
    assert process.stdout is not None
    assert process.stderr is not None
    times: queue.Queue[object] = queue.Queue()
    tail: deque[bytes] = deque(maxlen=5)  # the last lines that were not frame times, for errors
    reader = threading.Thread(target=_read_times, args=(process.stderr, times, tail), daemon=True)
    reader.start()
    size = width * height * 3
    last = after_slot
    try:
        while data := process.stdout.read(size):
            if len(data) != size:
                raise CorruptVideoError(f"{path.name} ended inside a frame")
            seconds = _next_time(times, path)
            slot = math.floor(seconds * rate)
            if slot <= last:  # (the seek landed in a slot already given)
                continue
            last = slot
            pixels = np.frombuffer(data, dtype=np.uint8).reshape(height, width, 3)
            yield Frame(slot, round(seconds * 1000), pixels)
        if process.wait() != 0:
            detail = b" ".join(tail).decode("utf-8", "replace")
            raise CorruptVideoError(f"{path.name} could not be decoded: {detail}")
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        process.stdout.close()
        reader.join()
        process.stderr.close()


def frame_size(width: int, height: int, max_side: int | None) -> tuple[int, int]:
    """The size frames come in: as shown, or scaled so the longer side is at most `max_side`."""
    longest = max(width, height)
    if max_side is None or longest <= max_side:
        return width, height
    return max(1, round(width * max_side / longest)), max(1, round(height * max_side / longest))


def _read_times(stream: object, times: "queue.Queue[object]", tail: deque[bytes]) -> None:
    for line in stream:  # type: ignore[attr-defined]
        match = _PTS_TIME.search(line)
        if match:
            times.put(float(match.group(1)))
        else:
            tail.append(line.strip())
    times.put(_DONE)


def _next_time(times: "queue.Queue[object]", path: Path) -> float:
    try:
        value = times.get(timeout=FRAME_TIMEOUT_SECONDS)
    except queue.Empty as error:
        raise CorruptVideoError(f"{path.name}: no time for a decoded frame") from error
    if not isinstance(value, float):
        raise CorruptVideoError(f"{path.name}: a decoded frame has no time")
    return value
