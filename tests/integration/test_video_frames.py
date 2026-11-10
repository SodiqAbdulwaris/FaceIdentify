"""Sampling a video's frames by presentation time over the pinned ffmpeg (M6 step 4; TST-063).

Clips are FFmpeg's own test patterns, made by the pinned build: no face, no user media.
"""

import math
import re
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from backend.infrastructure.media import frames as frames_module
from backend.infrastructure.media.frames import sampled_frames
from backend.infrastructure.media.video import CorruptVideoError
from tests.fixtures.media import installed_tools, make_clip, rotate


def test_two_frames_a_second_by_presentation_time(tmp_path: Path) -> None:
    clip = make_clip(tmp_path / "a.mp4", seconds=3, rate=25)

    frames = list(sampled_frames(installed_tools(), clip, width=160, height=120))

    assert [f.slot for f in frames] == [0, 1, 2, 3, 4, 5]
    assert [f.timestamp_ms for f in frames] == [0, 520, 1000, 1520, 2000, 2520]  # (25 fps grid)
    assert all(f.pixels.shape == (120, 160, 3) and f.pixels.dtype == np.uint8 for f in frames)


def test_an_odd_frame_rate_still_samples_by_time(tmp_path: Path) -> None:
    clip = make_clip(tmp_path / "b.mkv", seconds=2, rate=7, encode=("-c:v", "mpeg4"))

    frames = list(sampled_frames(installed_tools(), clip, width=160, height=120))

    assert [f.slot for f in frames] == [0, 1, 2, 3]
    assert [f.timestamp_ms for f in frames] == [0, 571, 1000, 1571]  # 0/7, 4/7, 7/7, 11/7 s


def test_resuming_after_a_slot_gives_exactly_the_rest(tmp_path: Path) -> None:
    clip = make_clip(tmp_path / "c.mp4", seconds=4)
    tools = installed_tools()
    whole = list(sampled_frames(tools, clip, width=160, height=120))

    rest = list(sampled_frames(tools, clip, width=160, height=120, after_slot=3))

    assert [f.slot for f in rest] == [f.slot for f in whole if f.slot > 3]
    assert [f.timestamp_ms for f in rest] == [f.timestamp_ms for f in whole if f.slot > 3]
    for again, first in zip(rest, whole[4:], strict=True):
        assert np.abs(again.pixels.astype(int) - first.pixels.astype(int)).mean() < 2


def test_a_different_rate_can_be_chosen(tmp_path: Path) -> None:
    clip = make_clip(tmp_path / "d.mp4", seconds=2)

    slots = [f.slot for f in sampled_frames(installed_tools(), clip, width=160, height=120, rate=1)]

    assert slots == [0, 1]


def test_frames_come_as_the_source_shows_them(tmp_path: Path) -> None:
    clip = rotate(make_clip(tmp_path / "flat.mp4", seconds=1), tmp_path / "side.mp4", 90)

    frames = list(sampled_frames(installed_tools(), clip, width=120, height=160))

    assert frames[0].pixels.shape == (160, 120, 3)


def test_a_wrong_size_or_a_damaged_file_is_a_corrupt_video(tmp_path: Path) -> None:
    clip = make_clip(tmp_path / "e.mp4", seconds=2)
    damaged = tmp_path / "cut.mp4"
    damaged.write_bytes(clip.read_bytes()[:3000])

    with pytest.raises(CorruptVideoError, match="inside a frame"):
        list(sampled_frames(installed_tools(), clip, width=150, height=110))
    with pytest.raises(CorruptVideoError, match="could not be decoded"):
        list(sampled_frames(installed_tools(), damaged, width=160, height=120))


def test_stopping_early_ends_the_decoder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    clip = make_clip(tmp_path / "f.mp4", seconds=4)
    started: list[subprocess.Popen[bytes]] = []
    real = subprocess.Popen

    def recorded(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        process = real(*args, **kwargs)  # type: ignore[call-overload]
        started.append(process)
        return process  # type: ignore[no-any-return]

    monkeypatch.setattr(subprocess, "Popen", recorded)
    stream = sampled_frames(installed_tools(), clip, width=160, height=120)
    next(stream)
    stream.close()

    assert started[0].returncode is not None  # killed and waited for, not left running


def test_a_frame_without_a_time_is_a_corrupt_video(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # (tiny frames: ffmpeg writes them all and exits, so its log ends before the frame is read)
    clip = make_clip(tmp_path / "g.mp4", seconds=1, size="16x16", encode=("-c:v", "mpeg4"))
    monkeypatch.setattr(frames_module, "_PTS_TIME", re.compile(rb"never"))

    with pytest.raises(CorruptVideoError, match="has no time"):
        list(sampled_frames(installed_tools(), clip, width=16, height=16))


def test_a_second_frame_in_a_slot_already_given_is_dropped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clip = make_clip(tmp_path / "i.mp4", seconds=2)
    monkeypatch.setattr(math, "floor", lambda value: 0)  # (as if every time fell in slot 0)

    assert [f.slot for f in sampled_frames(installed_tools(), clip, width=160, height=120)] == [0]


def test_a_frame_whose_time_never_comes_is_a_corrupt_video(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clip = make_clip(tmp_path / "h.mp4", seconds=1)
    monkeypatch.setattr(frames_module, "FRAME_TIMEOUT_SECONDS", 0)
    monkeypatch.setattr(frames_module, "_read_times", drain)  # never reports a time

    with pytest.raises(CorruptVideoError, match="no time"):
        list(sampled_frames(installed_tools(), clip, width=160, height=120))


def drain(stream: Any, times: Any, tail: Any) -> None:
    for _line in stream:
        pass


def test_a_variable_frame_rate_is_sampled_by_its_own_times(tmp_path: Path) -> None:
    # Frames every 0.12 s, then a 0.56 s gap after 0.88 s (VFR, Matroska keeps the times).
    clip = make_clip(
        tmp_path / "vfr.mkv",
        encode=("-vf", "setpts='(N*0.13+gte(N,8)*0.4)/TB'", "-fps_mode", "vfr", "-c:v", "mpeg4"),
    )
    tools = installed_tools()

    whole = list(sampled_frames(tools, clip, width=160, height=120))
    rest = list(sampled_frames(tools, clip, width=160, height=120, after_slot=1))

    assert [(f.slot, f.timestamp_ms) for f in whole[:4]] == [(0, 0), (1, 520), (2, 1440), (3, 1560)]
    assert [(f.slot, f.timestamp_ms) for f in rest] == [(f.slot, f.timestamp_ms) for f in whole[2:]]


def test_a_resume_never_skips_a_frame_on_a_slot_boundary(tmp_path: Path) -> None:
    clip = make_clip(tmp_path / "thirty.mp4", seconds=2, rate=30)  # a frame at exactly 2/3 s
    tools = installed_tools()

    whole = list(sampled_frames(tools, clip, width=160, height=120, rate=3))
    rest = list(sampled_frames(tools, clip, width=160, height=120, rate=3, after_slot=1))

    expected = [(f.slot, f.timestamp_ms) for f in whole if f.slot > 1]
    assert [(f.slot, f.timestamp_ms) for f in rest] == expected


@pytest.mark.parametrize(
    ("rate", "width"), [(0, 160), (2, 0), (float("nan"), 160), (float("inf"), 160)]
)
def test_a_rate_and_a_size_must_be_positive(tmp_path: Path, rate: float, width: int) -> None:
    with pytest.raises(ValueError, match="positive"):
        next(
            sampled_frames(installed_tools(), tmp_path / "x.mp4", width=width, height=1, rate=rate)
        )
