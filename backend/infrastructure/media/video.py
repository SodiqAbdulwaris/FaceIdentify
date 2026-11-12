"""Probing videos with the pinned FFmpeg tools (M6 step 3; D2 as confirmed 2026-11-10).

Video goes through the pinned LGPL `ffmpeg` and `ffprobe` executables over pipes, never a Python
binding (the PyAV wheel bundles GPL encoders, `docs/research/licensing-and-commercialization.md`
section 4.1). The binaries are not in the repository: `scripts/install_ffmpeg.py` verifies the
pinned build's SHA-256 and unpacks it into the machine-local state (`<local state>/runtime/ffmpeg`),
and `FACEIDENTIFY_FFMPEG_DIR` points elsewhere for development and CI. The installer ships the
same build in an `ffmpeg` folder beside the frozen backend's, which a packaged app uses first.

A video is accepted only in an MP4 or QuickTime, Matroska or WebM, or AVI container, with a video
stream that has a size and a duration. Its facts are what the Source records: the size as it is
shown (a rotation of 90 or 270 degrees swaps width and height, as an image's orientation does), the
duration and the average frame rate.
"""

import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

FFMPEG_DIR_ENV = "FACEIDENTIFY_FFMPEG_DIR"
MANIFEST = "SHA256SUMS"  # `<sha-256>  <file name>` per line, written when the tools were installed
_verified: set[Path] = set()  # the folders whose files matched their manifest, once per process
PROBE_TIMEOUT_SECONDS = 60
# (no console window flashes up when the desktop app runs a tool; the flag exists only on Windows)
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# A file is sent here by its name; its content then has to be one of these containers. Each family
# is what ffprobe calls it, and its MIME type follows the name where the family has two.
VIDEO_SUFFIXES = frozenset({".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi"})
_FAMILIES = {
    "mov,mp4,m4a,3gp,3g2,mj2": {".mov": "video/quicktime", "": "video/mp4"},
    "matroska,webm": {".webm": "video/webm", "": "video/x-matroska"},
    "avi": {"": "video/x-msvideo"},
}


class VideoError(Exception):
    """A file that cannot be imported as a video."""


class UnsupportedVideoError(VideoError):
    """Not a video in a supported container, or no video stream in it."""


class CorruptVideoError(VideoError):
    """A file named as a video that ffprobe cannot read."""


class MediaToolsMissingError(Exception):
    """The pinned ffmpeg and ffprobe are not installed."""


@dataclass(frozen=True, slots=True)
class MediaTools:
    ffmpeg: Path
    ffprobe: Path


@dataclass(frozen=True, slots=True)
class VideoFacts:
    mime_type: str
    width: int  # as it is shown: the rotation is applied
    height: int
    duration_ms: int
    frame_rate: Fraction | None  # the average rate; None when the file does not say
    rotation: int  # degrees, one of 0, 90, 180, 270


def is_video_name(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_SUFFIXES


def _bundled_directory() -> Path | None:
    """The `ffmpeg` folder the installer puts beside the frozen backend's own folder, if this is
    that frozen backend (an installed application) and the folder is there."""
    if not getattr(sys, "frozen", False):
        return None
    beside = Path(sys.executable).resolve().parent.parent / "ffmpeg"
    return beside if beside.is_dir() else None


def media_tools(local_state_root: Path, environ: Mapping[str, str] | None = None) -> MediaTools:
    """The installed tools: `FACEIDENTIFY_FFMPEG_DIR`, else the folder the installer shipped beside
    the application, else `<local state>/runtime/ffmpeg`."""
    environment = os.environ if environ is None else environ
    given = environment.get(FFMPEG_DIR_ENV)
    directory = (
        Path(given) if given else _bundled_directory() or local_state_root / "runtime" / "ffmpeg"
    )
    suffix = ".exe" if os.name == "nt" else ""
    tools = MediaTools(directory / f"ffmpeg{suffix}", directory / f"ffprobe{suffix}")
    if not (tools.ffmpeg.is_file() and tools.ffprobe.is_file()):
        raise MediaToolsMissingError(f"ffmpeg and ffprobe are not installed in {directory}")
    _check_manifest(directory, required=not given)
    return tools


def _check_manifest(directory: Path, *, required: bool) -> None:
    """Before the tools are first used, every file the manifest lists must still have its hash (a
    damaged or swapped file is refused). The manifest itself is required of the shipped and the
    machine-local folders, so deleting it does not switch the check off; only a folder the
    developer names with `FACEIDENTIFY_FFMPEG_DIR` may go without one."""
    manifest = directory / MANIFEST
    if directory in _verified:
        return
    if not manifest.is_file():
        if required:
            raise MediaToolsMissingError(f"{directory} has no {MANIFEST} to check its files by")
        return
    for line in manifest.read_text(encoding="utf-8").splitlines():
        digest, _, name = line.partition("  ")
        file = directory / Path(name).name  # (a name in the manifest never leaves the folder)
        if not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest() != digest:
            raise MediaToolsMissingError(f"{name or line} in {directory} does not match its hash")
    _verified.add(directory)


def probe_video(tools: MediaTools, path: Path) -> VideoFacts:
    """Read a video's facts. Raises `UnsupportedVideoError` or `CorruptVideoError`."""
    try:
        completed = subprocess.run(
            [str(tools.ffprobe), "-v", "error", "-print_format", "json"]
            + ["-show_format", "-show_streams", str(path)],
            capture_output=True,
            timeout=PROBE_TIMEOUT_SECONDS,
            check=False,
            creationflags=NO_WINDOW,
        )
    except subprocess.TimeoutExpired as error:
        raise CorruptVideoError(f"{path.name} took too long to read") from error
    except OSError as error:  # the configured ffprobe cannot be started
        raise MediaToolsMissingError(f"ffprobe cannot run: {error}") from error
    if completed.returncode != 0:
        raise CorruptVideoError(f"{path.name} could not be read")
    try:
        return video_facts(json.loads(completed.stdout), path.suffix.lower())
    except (ValueError, TypeError, KeyError, AttributeError) as error:  # (output we cannot use)
        raise CorruptVideoError(f"{path.name} gave facts that cannot be read") from error


def video_facts(probe: Mapping[str, Any], suffix: str) -> VideoFacts:
    """The facts from ffprobe's JSON (`-show_format -show_streams`)."""
    family = _FAMILIES.get(probe.get("format", {}).get("format_name", ""))
    stream = next(
        (
            s
            for s in probe.get("streams", [])
            if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")
        ),
        None,
    )
    if family is None or stream is None:
        raise UnsupportedVideoError("not a video in a supported container")
    width, height = int(stream.get("width", 0)), int(stream.get("height", 0))
    seconds = float(probe["format"].get("duration") or stream.get("duration") or 0)
    if width <= 0 or height <= 0 or seconds <= 0:
        raise CorruptVideoError("the video has no size or no duration")
    rotation = _rotation(stream)
    if rotation in (90, 270):
        width, height = height, width
    return VideoFacts(
        mime_type=family.get(suffix, family[""]),
        width=width,
        height=height,
        duration_ms=round(seconds * 1000),
        frame_rate=_rate(stream.get("avg_frame_rate")) or _rate(stream.get("r_frame_rate")),
        rotation=rotation,
    )


def _rotation(stream: Mapping[str, Any]) -> int:
    for side_data in stream.get("side_data_list", []):
        if "rotation" in side_data:
            return round(float(side_data["rotation"]) / 90) * 90 % 360
    return 0


def _rate(value: str | None) -> Fraction | None:
    """`"30000/1001"` as a fraction; None for a missing or zero rate (`"0/0"`)."""
    numerator, _, denominator = (value or "0/0").partition("/")
    if int(numerator or 0) <= 0 or int(denominator or 0) <= 0:
        return None
    return Fraction(int(numerator), int(denominator))
