"""Encounters: who was in front of a camera, from when to when (M7 step 4; plan C3, C8).

Each sampled frame's detections go through M6's NumPy tracker (`tracking.Tracker`); a track is
an encounter. Time is cut into slots of `1 / fps` seconds of the session's monotonic clock, so a
dropped frame is a skipped slot, and a track not seen for `gap_seconds` ends: its encounter
closes. A `Gap` in the stream (the camera broke) closes every encounter and starts a new tracker,
so nothing is continued across unobserved time.

Memory is not every frame (identity model: "not every frame is a learning event"). While an
encounter is open it keeps only a small pool of its best sightings, each as a **face crop**
(the box widened by `CROP_MARGIN` on every side, so alignment has the whole face) with the
detection redrawn in the crop's own coordinates; the frame itself is never kept. When it
closes, M6's selection (`select_kept`) picks at most `keep` of them, spread over the encounter, to
be embedded and recorded. Nothing here touches the worker or the database.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from numpy.typing import NDArray

from backend.app.processing.tracking import Candidate, Tracker, select_kept
from backend.ml.contracts.messages import Detection

CROP_MARGIN = 0.5  # of the box's width and height, on each side
MIN_IOU = 0.2  # as for videos


@dataclass(frozen=True, slots=True)
class Sighting:
    """One face as kept: its crop, and the detection in the crop's coordinates."""

    sequence: int  # the frame's number in the stream (for display, like a video's frame index)
    at_ms: int  # UTC wall-clock milliseconds when the frame arrived
    crop: NDArray[np.uint8]
    detection: Detection
    detector: Any  # the detector variant that ran (`PlannedVariant`), for provenance


@dataclass(slots=True)
class Encounter:
    track: int
    start_ms: int
    end_ms: int
    start_sequence: int
    end_sequence: int
    pool: list[Candidate] = field(default_factory=list)  # each `key` is a `Sighting`

    def chosen(self, *, keep: int, min_score: float) -> list[Sighting]:
        """At most `keep` sightings to record, spread over the encounter, in time order."""
        kept = select_kept(self.pool, keep=keep, min_score=min_score)
        return [candidate.key for candidate in sorted(kept, key=lambda c: c.slot)]


def crop_face(
    pixels: NDArray[np.uint8], detection: Detection
) -> tuple[NDArray[np.uint8], Detection]:
    """The face with a margin, and its detection redrawn in the crop's coordinates (0 to 1)."""
    height, width = pixels.shape[:2]
    x0, y0, x1, y1 = detection.box
    mx, my = (x1 - x0) * CROP_MARGIN, (y1 - y0) * CROP_MARGIN
    # (pixel edges rounded first, so float noise such as 140.00000000000003 is not a pixel more)
    left = max(0, math.floor(round((x0 - mx) * width, 6)))
    top = max(0, math.floor(round((y0 - my) * height, 6)))
    right = min(width, max(left + 1, math.ceil(round((x1 + mx) * width, 6))))
    bottom = min(height, max(top + 1, math.ceil(round((y1 + my) * height, 6))))
    crop = np.ascontiguousarray(pixels[top:bottom, left:right])
    cw, ch = right - left, bottom - top

    def inside(x: float, y: float) -> tuple[float, float]:
        return (
            min(1.0, max(0.0, (x * width - left) / cw)),
            min(1.0, max(0.0, (y * height - top) / ch)),
        )

    (bx0, by0), (bx1, by1) = inside(x0, y0), inside(x1, y1)
    landmarks = (
        None if detection.landmarks is None else tuple(inside(x, y) for x, y in detection.landmarks)
    )
    return crop, Detection(0, 0, (bx0, by0, bx1, by1), detection.score, landmarks)


class Encounters:
    def __init__(self, *, fps: float, gap_seconds: float, pool: int = 8) -> None:
        if not (fps > 0 and gap_seconds > 0 and pool >= 1):
            raise ValueError("the rate, the gap and the pool must be positive")
        self._fps = fps
        self._gap_slots = max(1, math.ceil(gap_seconds * fps))
        self._pool = pool
        self._tracker = Tracker(min_iou=MIN_IOU, max_gap=self._gap_slots)
        self._open: dict[int, Encounter] = {}

    @property
    def open(self) -> int:
        return len(self._open)

    def see(
        self,
        *,
        elapsed: float,
        sequence: int,
        at_ms: int,
        pixels: NDArray[np.uint8],
        detections: Sequence[Detection],
        detector: Any = None,
    ) -> list[Encounter]:
        """Add one frame's faces (`elapsed`: monotonic seconds since the session began). Returns
        the encounters this frame closed: those whose track ended."""
        slot = math.floor(elapsed * self._fps)
        tracks = self._tracker.update(
            slot, [d.box for d in detections], [d.landmarks for d in detections]
        )
        for detection, track in zip(detections, tracks, strict=True):
            encounter = self._open.setdefault(
                track, Encounter(track, at_ms, at_ms, sequence, sequence)
            )
            encounter.end_ms, encounter.end_sequence = at_ms, sequence
            candidate = Candidate(
                track, detection.score, detection.box, None, detection.landmarks, slot
            )
            worst = min(encounter.pool, key=lambda c: c.merit, default=None)
            if len(encounter.pool) >= self._pool:
                assert worst is not None
                if candidate.merit <= worst.merit:
                    continue
                encounter.pool.remove(worst)
            crop, inner = crop_face(pixels, detection)
            encounter.pool.append(
                Candidate(
                    track,
                    detection.score,
                    detection.box,
                    Sighting(sequence, at_ms, crop, inner, detector),
                    detection.landmarks,
                    slot,
                )
            )
        live = {track[0] for track in self._tracker.state()["live"]}
        # (the tracker forgets a track at its next update after the gap: an empty frame ends it)
        ended = [track for track in self._open if track not in live]
        return [self._open.pop(track) for track in ended]

    def close_all(self) -> list[Encounter]:
        """Every open encounter (the stream broke or the session ends); tracking starts afresh."""
        closed = list(self._open.values())
        self._open.clear()
        self._tracker = Tracker(min_iou=MIN_IOU, max_gap=self._gap_slots)
        return closed
