"""Reading a video's facts from ffprobe's JSON, and finding the tools (M6 step 3; TST-063)."""

import hashlib
import os
import shutil
import subprocess
import sys
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

from backend.infrastructure.media.video import (
    FFMPEG_DIR_ENV,
    MANIFEST,
    CorruptVideoError,
    MediaTools,
    MediaToolsMissingError,
    UnsupportedVideoError,
    is_video_name,
    media_tools,
    probe_video,
    video_facts,
)

MP4 = "mov,mp4,m4a,3gp,3g2,mj2"


def probe(stream: dict[str, Any] | None = None, **fmt: Any) -> dict[str, Any]:
    stream = {"codec_type": "video", "width": 160, "height": 120, **(stream or {})}
    return {"format": {"format_name": MP4, "duration": "2.0004", **fmt}, "streams": [stream]}


def test_the_facts_of_an_mp4() -> None:
    facts = video_facts(probe({"avg_frame_rate": "30000/1001"}), ".mp4")

    assert facts.mime_type == "video/mp4"
    assert (facts.width, facts.height, facts.rotation) == (160, 120, 0)
    assert facts.duration_ms == 2000  # rounded to the millisecond
    assert facts.frame_rate == Fraction(30000, 1001)


@pytest.mark.parametrize(
    ("family", "suffix", "mime"),
    [
        (MP4, ".mov", "video/quicktime"),
        (MP4, ".m4v", "video/mp4"),
        ("matroska,webm", ".webm", "video/webm"),
        ("matroska,webm", ".mkv", "video/x-matroska"),
        ("avi", ".avi", "video/x-msvideo"),
    ],
)
def test_the_mime_type_follows_the_container_and_the_name(
    family: str, suffix: str, mime: str
) -> None:
    assert video_facts(probe(format_name=family), suffix).mime_type == mime


@pytest.mark.parametrize(
    ("rotation", "shown"), [(90, (120, 160)), (-90, (120, 160)), (180, (160, 120))]
)
def test_a_rotation_of_a_quarter_turn_swaps_the_size_shown(
    rotation: int, shown: tuple[int, int]
) -> None:
    facts = video_facts(probe({"side_data_list": [{"other": 1}, {"rotation": rotation}]}), ".mp4")

    assert (facts.width, facts.height) == shown
    assert facts.rotation == rotation % 360


def test_the_stream_duration_is_used_when_the_container_has_none() -> None:
    assert video_facts(probe({"duration": "1.5"}, duration=None), ".mp4").duration_ms == 1500


@pytest.mark.parametrize(
    ("avg", "real", "expected"),
    [("0/0", "25/1", Fraction(25)), (None, None, None), ("0/0", "0/0", None), ("25/0", None, None)],
)
def test_a_missing_average_rate_falls_back_to_the_real_rate(
    avg: str | None, real: str | None, expected: Fraction | None
) -> None:
    facts = video_facts(probe({"avg_frame_rate": avg, "r_frame_rate": real}), ".mp4")

    assert facts.frame_rate == expected


def test_a_cover_picture_is_not_the_video_stream() -> None:
    data = probe({"disposition": {"attached_pic": 1}})

    with pytest.raises(UnsupportedVideoError):
        video_facts(data, ".mp4")


@pytest.mark.parametrize(
    "data",
    [
        {"format": {"format_name": "png_pipe"}, "streams": [{"codec_type": "video"}]},
        {"format": {"format_name": MP4}, "streams": [{"codec_type": "audio"}]},
        {},
    ],
)
def test_anything_but_a_video_in_a_supported_container_is_unsupported(
    data: dict[str, Any],
) -> None:
    with pytest.raises(UnsupportedVideoError):
        video_facts(data, ".mp4")


@pytest.mark.parametrize(
    "data", [probe({"width": 0}), probe({"height": 0}), probe(duration="0"), probe(duration=None)]
)
def test_a_video_without_a_size_or_a_duration_is_corrupt(data: dict[str, Any]) -> None:
    with pytest.raises(CorruptVideoError):
        video_facts(data, ".mp4")


def test_videos_are_recognised_by_their_name() -> None:
    assert is_video_name(Path("Film.MP4"))
    assert not is_video_name(Path("photo.png"))


def test_the_tools_are_found_in_the_local_state_or_where_the_environment_says(
    tmp_path: Path,
) -> None:
    installed = tmp_path / "runtime" / "ffmpeg"
    elsewhere = tmp_path / "elsewhere"
    suffix = ".exe" if os.name == "nt" else ""
    for folder in (installed, elsewhere):
        folder.mkdir(parents=True)
        (folder / f"ffmpeg{suffix}").write_bytes(b"")
        (folder / f"ffprobe{suffix}").write_bytes(b"")

    assert media_tools(tmp_path, {}).ffprobe == installed / f"ffprobe{suffix}"
    assert media_tools(tmp_path, {FFMPEG_DIR_ENV: str(elsewhere)}).ffmpeg.parent == elsewhere
    with pytest.raises(MediaToolsMissingError):
        media_tools(tmp_path / "nowhere", {})


def installed_with_manifest(folder: Path) -> Path:
    suffix = ".exe" if os.name == "nt" else ""
    folder.mkdir(parents=True)
    names = (f"ffmpeg{suffix}", f"ffprobe{suffix}", "avcodec.dll")
    for name in names:
        (folder / name).write_bytes(name.encode())
    sums = "".join(f"{hashlib.sha256(name.encode()).hexdigest()}  {name}\n" for name in names)
    (folder / MANIFEST).write_text(sums, encoding="utf-8")
    return folder


def test_tools_that_match_their_manifest_are_accepted_once_and_trusted_after(
    tmp_path: Path,
) -> None:
    folder = installed_with_manifest(tmp_path / "ffmpeg")
    environment = {FFMPEG_DIR_ENV: str(folder)}
    media_tools(tmp_path, environment)

    (folder / "avcodec.dll").write_bytes(b"swapped after the check")
    media_tools(tmp_path, environment)  # the check happens before the first use, not on every call


def test_a_changed_or_missing_file_is_refused_before_the_first_use(tmp_path: Path) -> None:
    changed = installed_with_manifest(tmp_path / "changed")
    (changed / "avcodec.dll").write_bytes(b"not what was installed")
    with pytest.raises(MediaToolsMissingError, match="avcodec.dll.*does not match"):
        media_tools(tmp_path, {FFMPEG_DIR_ENV: str(changed)})

    missing = installed_with_manifest(tmp_path / "missing")
    (missing / "avcodec.dll").unlink()
    with pytest.raises(MediaToolsMissingError, match="avcodec.dll"):
        media_tools(tmp_path, {FFMPEG_DIR_ENV: str(missing)})


def test_a_manifest_line_cannot_point_outside_its_folder(tmp_path: Path) -> None:
    folder = installed_with_manifest(tmp_path / "ffmpeg")
    (tmp_path / "outside.dll").write_bytes(b"x")
    line = f"{hashlib.sha256(b'x').hexdigest()}  ../outside.dll\n"
    with (folder / MANIFEST).open("a", encoding="utf-8") as manifest:
        manifest.write(line)
    with pytest.raises(MediaToolsMissingError, match="outside.dll"):
        media_tools(tmp_path, {FFMPEG_DIR_ENV: str(folder)})


def test_a_packaged_app_uses_the_ffmpeg_folder_its_installer_shipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shipped = installed_with_manifest(tmp_path / "app" / "ffmpeg")
    backend = tmp_path / "app" / "faceidentify-backend"
    backend.mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(backend / "faceidentify-backend.exe"))

    assert media_tools(tmp_path / "state", {}).ffmpeg.parent == shipped.resolve()

    shutil.rmtree(shipped)  # no shipped folder: the machine-local state is looked at instead
    with pytest.raises(MediaToolsMissingError, match="runtime"):
        media_tools(tmp_path / "state", {})


def test_a_probe_that_takes_too_long_is_a_corrupt_video(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def slow(*args: Any, **kwargs: Any) -> None:
        raise subprocess.TimeoutExpired("ffprobe", kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", slow)

    with pytest.raises(CorruptVideoError, match="too long"):
        probe_video(MediaTools(tmp_path / "ffmpeg", tmp_path / "ffprobe"), tmp_path / "a.mp4")


def test_an_ffprobe_that_cannot_start_means_the_tools_are_missing(tmp_path: Path) -> None:
    tools = MediaTools(tmp_path / "ffmpeg.exe", tmp_path / "absent-ffprobe.exe")

    with pytest.raises(MediaToolsMissingError, match="cannot run"):
        probe_video(tools, tmp_path / "a.mp4")


@pytest.mark.parametrize(
    "output",
    [
        b"not json",
        b"[]",
        b'{"format": {"format_name": "avi"}, "streams": [{"codec_type": "video", "width": "x"}]}',
    ],
)
def test_output_that_cannot_be_read_is_a_corrupt_video(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, output: bytes
) -> None:
    monkeypatch.setattr(
        subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, output, b"")
    )

    with pytest.raises(CorruptVideoError, match="cannot be read"):
        probe_video(MediaTools(tmp_path / "ffmpeg", tmp_path / "ffprobe"), tmp_path / "a.avi")
