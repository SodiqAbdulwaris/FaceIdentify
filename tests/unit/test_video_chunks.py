"""Video processing settings and frame numbers (M6 step 5)."""

import pytest

from backend.app.processing.video_chunks import VideoProcessing, frame_index


@pytest.mark.parametrize(
    "setting",
    ["rate", "chunk_frames", "frames_per_turn", "keep_per_track", "max_per_track", "max_side"],
)
def test_every_setting_must_be_positive(setting: str) -> None:
    with pytest.raises(ValueError, match="positive"):
        VideoProcessing(**{setting: 0})


def test_the_frame_is_found_from_the_time_and_the_rate() -> None:
    assert frame_index(1001, 30, (30000, 1001)) == 30  # 1.001 s at 29.97 fps
    assert frame_index(2520, 5, (25, 1)) == 63
    assert frame_index(2520, 5, None) == 5  # no rate: the slot stands in
