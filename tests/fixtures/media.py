"""Synthetic video clips made by the pinned FFmpeg (M6). No real face, no user media.

The tools are the installed pinned build: `FACEIDENTIFY_FFMPEG_DIR`, else the machine-local state
(`scripts/install_ffmpeg.py`). CI installs it the same way. A missing install fails these tests
loudly rather than skipping them.
"""

import subprocess
from collections.abc import Sequence
from functools import cache
from pathlib import Path

from backend.infrastructure.media.video import MediaTools, media_tools
from backend.infrastructure.storage.library_root import resolve_local_state_root


@cache
def installed_tools() -> MediaTools:
    return media_tools(resolve_local_state_root())


def make_clip(
    path: Path,
    *,
    seconds: float = 2,
    size: str = "160x120",
    rate: int = 25,
    source: str = "testsrc2",
    encode: Sequence[str] = ("-c:v", "libopenh264", "-pix_fmt", "yuv420p"),
    before: Sequence[str] = (),
) -> Path:
    """A clip of FFmpeg's own test pattern (`source` is any lavfi video source)."""
    subprocess.run(
        [str(installed_tools().ffmpeg), "-v", "error", "-y", *before, "-f", "lavfi"]
        + ["-i", f"{source}{':' if '=' in source else '='}size={size}:rate={rate}"]
        + ["-t", str(seconds), *encode, str(path)],
        check=True,
        capture_output=True,
    )
    return path


def rotate(clip: Path, path: Path, degrees: int) -> Path:
    """The same stream with a display rotation (no re-encoding)."""
    subprocess.run(
        [str(installed_tools().ffmpeg), "-v", "error", "-y", "-display_rotation", str(degrees)]
        + ["-i", str(clip), "-c", "copy", str(path)],
        check=True,
        capture_output=True,
    )
    return path
