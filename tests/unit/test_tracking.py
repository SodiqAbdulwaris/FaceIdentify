"""Tracks across sampled frames, and which detections are kept (M6 step 5; D6; TST-063)."""

import json

import numpy as np
import pytest

from backend.app.processing.tracking import (
    Candidate,
    Tracker,
    agreement,
    iou,
    select_kept,
    shape,
)


def test_overlap_of_boxes() -> None:
    a = np.array([[0.0, 0.0, 0.2, 0.2], [0.0, 0.0, 0.0, 0.0]])
    b = np.array([[0.1, 0.0, 0.3, 0.2], [0.5, 0.5, 0.6, 0.6]])

    overlap = iou(a, b)

    assert overlap[0, 0] == pytest.approx(1 / 3)
    assert overlap[0, 1] == 0
    assert overlap[1, 0] == 0  # an empty box overlaps nothing, without dividing by zero


def test_a_face_moving_steadily_stays_one_track() -> None:
    tracker = Tracker()
    tracks = [tracker.update(slot, [(0.1 * slot, 0.2, 0.1 * slot + 0.2, 0.4)]) for slot in range(6)]

    assert tracks == [[0]] * 6  # the motion model follows it even where boxes barely overlap


def test_two_faces_keep_their_own_tracks_and_a_new_one_starts_its_own() -> None:
    tracker = Tracker()
    left, right = (0.1, 0.1, 0.3, 0.4), (0.6, 0.1, 0.8, 0.4)

    assert tracker.update(0, [left]) == [0]
    assert tracker.update(1, [right, left]) == [1, 0]
    assert tracker.update(2, [left, right]) == [0, 1]


def test_a_track_ends_after_a_gap_longer_than_allowed() -> None:
    tracker = Tracker(max_gap=2)
    box = (0.1, 0.1, 0.3, 0.4)

    assert tracker.update(0, [box]) == [0]
    assert tracker.update(2, [box]) == [0]  # missed one slot: the same face
    assert tracker.update(5, [box]) == [1]  # gone for three: someone (or something) new


def test_a_frame_with_no_face_changes_nothing_but_time() -> None:
    tracker = Tracker()
    tracker.update(0, [(0.1, 0.1, 0.3, 0.4)])

    assert tracker.update(1, []) == []
    assert tracker.update(2, [(0.1, 0.1, 0.3, 0.4)]) == [0]


def test_the_state_survives_json_so_a_track_crosses_a_chunk_or_a_restart() -> None:
    first = Tracker()
    for slot in range(3):
        first.update(slot, [(0.1 * slot, 0.2, 0.1 * slot + 0.2, 0.4)])

    resumed = Tracker(state=json.loads(json.dumps(first.state())))

    assert resumed.update(3, [(0.3, 0.2, 0.5, 0.4), (0.8, 0.8, 0.9, 0.9)]) == [0, 1]


def candidate(track: int, score: float, side: float, key: int) -> Candidate:
    return Candidate(track, score, (0.0, 0.0, side, side), key)


def test_selection_keeps_the_best_few_of_each_track() -> None:
    chosen = select_kept(
        [
            candidate(0, 0.9, 0.1, 1),
            candidate(0, 0.9, 0.3, 2),  # larger: better
            candidate(0, 0.8, 0.2, 3),
            candidate(0, 0.3, 0.9, 4),  # below the gate: not taken while better ones exist
            candidate(1, 0.95, 0.2, 5),
        ],
        keep=2,
        min_score=0.5,
    )

    assert [c.key for c in chosen] == [2, 3, 5]


def test_a_track_with_only_poor_faces_keeps_its_single_best() -> None:
    chosen = select_kept(
        [candidate(0, 0.3, 0.2, 1), candidate(0, 0.4, 0.2, 2)], keep=3, min_score=0.5
    )

    assert [c.key for c in chosen] == [2]


def test_two_faces_crossing_keep_their_tracks() -> None:
    tracker = Tracker()
    tracks = []
    for slot in range(7):
        rightwards = (0.1 + 0.1 * slot, 0.3, 0.3 + 0.1 * slot, 0.5)
        leftwards = (0.7 - 0.1 * slot, 0.32, 0.9 - 0.1 * slot, 0.52)
        tracks.append(tracker.update(slot, [rightwards, leftwards]))

    assert tracks == [[0, 1]] * 7  # the motion model carries each through the other


LEVEL = ((0.3, 0.3), (0.7, 0.3), (0.5, 0.5), (0.35, 0.7), (0.65, 0.7))


def turned(dx: float) -> tuple[tuple[float, float], ...]:
    return tuple((x + dx if i == 2 else x, y) for i, (x, y) in enumerate(LEVEL))


def test_landmarks_decide_between_two_boxes_that_overlap_alike() -> None:
    box = (0.0, 0.0, 1.0, 1.0)
    tracker = Tracker()
    tracker.update(0, [box], [LEVEL])

    # Two detections overlap the track's box equally; the one whose landmarks agree joins it.
    assert tracker.update(1, [box, box], [turned(0.45), LEVEL]) == [1, 0]
    assert agreement(None, [0.0, 0.0]) == 1.0  # (no landmarks: the overlap alone decides)
    assert shape(box, None) is None


def test_a_frontal_face_is_kept_before_one_turned_away() -> None:
    profile = Candidate(0, 0.9, (0.0, 0.0, 0.4, 0.4), "profile", turned(0.18), slot=0)
    frontal = Candidate(0, 0.9, (0.0, 0.0, 0.4, 0.4), "frontal", LEVEL, slot=4)

    assert [c.key for c in select_kept([profile, frontal], keep=1, min_score=0.5)] == ["frontal"]
    assert frontal.frontal == 1.0
    assert (
        Candidate(0, 0.9, (0, 0, 1, 1), "flat", ((0.5, 0.5), (0.5, 0.5), (0.5, 0.5))).frontal == 0.1
    )


def test_kept_faces_are_spread_over_the_chunk() -> None:
    near = [Candidate(0, 0.9, (0.0, 0.0, 0.4, 0.4), slot, None, slot) for slot in (0, 1, 2)]
    far = Candidate(0, 0.9, (0.0, 0.0, 0.3, 0.3), "far", None, 9)  # smaller, so ranked last

    kept = select_kept([*near, far], keep=3, min_score=0.5)

    assert [c.key for c in kept] == [0, 2, "far"]  # 1 is next to 0; then the gap is filled
    assert [c.key for c in select_kept(near, keep=3, min_score=0.5)] == [0, 2, 1]


def test_a_track_keeps_a_few_faces_over_its_whole_life() -> None:
    tracker = Tracker()
    box = (0.1, 0.1, 0.3, 0.4)
    kept_per_chunk = []
    for chunk in range(4):  # one face on screen for four chunks, kept over a restart
        tracker = Tracker(state=tracker.state())
        faces = []
        for slot in range(chunk * 5, chunk * 5 + 5):
            (track,) = tracker.update(slot, [box])
            faces.append(Candidate(track, 0.9, box, slot, None, slot))
        kept = select_kept(
            faces, keep=3, min_score=0.5, room=lambda track, now=tracker: now.room(track, 7)
        )
        for face in kept:
            tracker.kept(face.track)
        kept_per_chunk.append(len(kept))

    assert kept_per_chunk == [3, 3, 1, 0]  # seven in all, however long it lasts
    assert (
        select_kept([Candidate(0, 0.1, box, "poor")], keep=1, min_score=0.5, room=lambda t: 0) == []
    )


def test_a_track_that_ends_drops_its_count() -> None:
    tracker = Tracker(max_gap=1)
    (track,) = tracker.update(0, [(0.1, 0.1, 0.3, 0.4)])
    tracker.kept(track)
    tracker.update(5, [])

    assert tracker.state()["kept"] == {}
