"""Linking a video's face detections into tracks, and choosing which to keep (M6 step 5; D6).

NumPy only (D6): a detection joins the live track whose predicted box overlaps it most (IoU at least
`min_iou`), each track and each detection used once, best overlap first. The prediction is a small
motion model: the last box moved by the track's last per-slot velocity. A track not seen for more
than `max_gap` slots ends; a detection that joins nothing starts a new track. Sampling is slow (2
frames a second, D4), so the overlap needed is low and the motion model carries a moving face.

The tracker's state is plain JSON (`state()` / `Tracker(state=...)`), so a chunk checkpoint carries
it and a track continues across a chunk boundary or a resume (processing spec 13: a chunk boundary
is not an identity boundary).

Selection keeps, per track and per chunk, the `keep` best detections by detection score times the
square root of the face's area (sharper and larger faces embed better), preferring ones at or above
the quality gate; only those are embedded and recorded, never every frame's face.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

Box = tuple[float, float, float, float]  # normalised x0, y0, x1, y1


def iou(a: NDArray[np.float64], b: NDArray[np.float64]) -> NDArray[np.float64]:
    """Pairwise intersection over union of two box arrays (n x 4 and m x 4)."""
    x0 = np.maximum(a[:, None, 0], b[None, :, 0])
    y0 = np.maximum(a[:, None, 1], b[None, :, 1])
    x1 = np.minimum(a[:, None, 2], b[None, :, 2])
    y1 = np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(x1 - x0, 0, None) * np.clip(y1 - y0, 0, None)
    area_a = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])
    area_b = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    union = area_a[:, None] + area_b[None, :] - inter
    return np.where(union > 0, inter / np.where(union > 0, union, 1), 0.0)


class Tracker:
    def __init__(
        self, *, min_iou: float = 0.2, max_gap: int = 2, state: dict[str, Any] | None = None
    ) -> None:
        self._min_iou = min_iou
        self._max_gap = max_gap
        state = state or {"next_id": 0, "live": []}
        self._next_id: int = state["next_id"]
        # each live track: [id, last slot, box (4), velocity per slot (4)]
        self._live: list[list[Any]] = [list(track) for track in state["live"]]

    def state(self) -> dict[str, Any]:
        return {"next_id": self._next_id, "live": [list(track) for track in self._live]}

    def update(self, slot: int, boxes: Sequence[Box]) -> list[int]:
        """The track of each box seen at `slot`, in order."""
        self._live = [t for t in self._live if slot - t[1] <= self._max_gap]
        assigned: list[int | None] = [None] * len(boxes)
        if boxes and self._live:
            predicted = np.array(
                [np.add(t[2], np.multiply(t[3], slot - t[1])) for t in self._live], dtype=float
            )
            overlap = iou(predicted, np.array(boxes, dtype=float))
            while overlap.size and overlap.max() >= self._min_iou:
                row, column = (
                    int(i) for i in np.unravel_index(int(overlap.argmax()), overlap.shape)
                )
                track = self._live[row]
                velocity = np.subtract(boxes[column], track[2]) / max(slot - track[1], 1)
                track[1], track[2], track[3] = slot, list(boxes[column]), velocity.tolist()
                assigned[column] = track[0]
                overlap[row, :] = -1
                overlap[:, column] = -1
        for index, box in enumerate(boxes):
            if assigned[index] is None:
                assigned[index] = self._next_id
                self._live.append([self._next_id, slot, list(box), [0.0, 0.0, 0.0, 0.0]])
                self._next_id += 1
        return [track for track in assigned if track is not None]


@dataclass(frozen=True, slots=True)
class Candidate:
    track: int
    score: float
    box: Box
    key: Any  # the caller's handle on the detection (its frame and index)

    @property
    def merit(self) -> float:
        x0, y0, x1, y1 = self.box
        return self.score * math.sqrt(max(x1 - x0, 0.0) * max(y1 - y0, 0.0))


def select_kept(candidates: Sequence[Candidate], *, keep: int, min_score: float) -> list[Candidate]:
    """Up to `keep` per track: the best at or above `min_score`, else the single best below it."""
    by_track: dict[int, list[Candidate]] = {}
    for candidate in candidates:
        by_track.setdefault(candidate.track, []).append(candidate)
    chosen: list[Candidate] = []
    for group in by_track.values():
        ranked = sorted(group, key=lambda c: -c.merit)
        good = [c for c in ranked if c.score >= min_score]
        chosen.extend(good[:keep] if good else ranked[:1])
    return chosen
