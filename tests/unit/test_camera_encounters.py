"""Encounters from tracked faces, without the worker or the database (M7 step 4; plan C3, C8)."""

import numpy as np
import pytest

from backend.app.cameras.encounters import Encounters, crop_face
from backend.ml.contracts.messages import Detection

PIXELS = np.arange(100 * 200 * 3, dtype=np.uint32).astype(np.uint8).reshape(100, 200, 3)


def face(x0: float, score: float = 0.9) -> Detection:
    return Detection(0, 0, (x0, 0.2, x0 + 0.2, 0.6), score, ((x0 + 0.05, 0.3), (x0 + 0.15, 0.3)))


def test_a_crop_has_a_margin_and_the_detection_in_its_own_coordinates() -> None:
    crop, inner = crop_face(PIXELS, face(0.4))

    assert crop.shape == (80, 80, 3)  # 40 x 40 px box, 20 px more each side (rows clipped at 0)
    assert inner.box == pytest.approx((0.25, 0.0 + 20 / 80, 0.75, 60 / 80))
    assert inner.landmarks is not None
    assert [v for point in inner.landmarks for v in point] == pytest.approx(
        [0.375, 30 / 80, 0.625, 30 / 80]
    )
    assert (inner.score, inner.detection_index) == (0.9, 0)


def test_a_crop_at_the_edge_is_clipped_to_the_picture() -> None:
    crop, inner = crop_face(PIXELS, Detection(0, 0, (0.0, 0.0, 0.1, 0.1), 0.5, None))

    assert crop.shape == (15, 30, 3)
    assert inner.box == pytest.approx((0.0, 0.0, 20 / 30, 10 / 15))
    assert inner.landmarks is None


def test_an_encounter_closes_after_the_gap_and_keeps_its_best_sightings() -> None:
    encounters = Encounters(fps=5, gap_seconds=1, pool=2)
    scores = [0.6, 0.9, 0.5, 0.95]
    for n, score in enumerate(scores):
        assert encounters.see(
            elapsed=n / 5, sequence=n + 1, at_ms=1000 + 200 * n, pixels=PIXELS,
            detections=[face(0.4, score)],
        ) == []  # fmt: skip
    assert encounters.open == 1
    closed: list[object] = []
    for n in range(4, 11):  # a second and more without the face
        closed += encounters.see(
            elapsed=n / 5, sequence=n + 1, at_ms=1000 + 200 * n, pixels=PIXELS, detections=[]
        )

    (encounter,) = closed
    assert (encounter.start_ms, encounter.end_ms) == (1000, 1600)  # type: ignore[attr-defined]
    assert sorted(c.score for c in encounter.pool) == [0.9, 0.95]  # type: ignore[attr-defined]
    chosen = encounter.chosen(keep=3, min_score=0.5)  # type: ignore[attr-defined]
    assert [s.sequence for s in chosen] == [2, 4]  # in time order
    assert encounters.open == 0


def test_close_all_ends_every_encounter_and_starts_tracking_afresh() -> None:
    encounters = Encounters(fps=5, gap_seconds=1)
    encounters.see(elapsed=0, sequence=1, at_ms=0, pixels=PIXELS, detections=[face(0.1), face(0.6)])

    assert len(encounters.close_all()) == 2
    assert encounters.close_all() == []
    encounters.see(elapsed=0.2, sequence=2, at_ms=200, pixels=PIXELS, detections=[face(0.1)])
    assert [e.track for e in encounters.close_all()] == [0]  # a new tracker counts from zero


@pytest.mark.parametrize(("fps", "gap", "pool"), [(0, 1, 1), (5, 0, 1), (5, 1, 0)])
def test_the_rate_the_gap_and_the_pool_must_be_positive(fps: float, gap: float, pool: int) -> None:
    with pytest.raises(ValueError, match="positive"):
        Encounters(fps=fps, gap_seconds=gap, pool=pool)
