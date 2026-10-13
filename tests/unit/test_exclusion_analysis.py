"""The classification rules of the exclusion diagnostic (M5, 2026-10-13): no model, no pictures."""

from typing import Any

import numpy as np
import pytest

from evaluation.analyse_exclusions import (
    _centre_distance,
    _overlap,
    _touches_border,
    area,
    counterfactuals,
    describe,
    look,
    verdict,
)
from evaluation.assisted_recognition_gate import DOMINANCE, subject


def face(x0: float, y0: float, x1: float, y1: float, score: float = 0.9) -> dict[str, Any]:
    return {"box": [x0, y0, x1, y1], "score": score}


def record(
    kept: list[dict[str, Any]],
    below: list[dict[str, Any]] | None = None,
    cut: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {"kept": kept, "below_floor": below or [], "border_dropped": cut or []}


def test_the_verdict_is_the_gates_subject_rule_on_the_same_faces() -> None:
    big, small = face(0.1, 0.1, 0.5, 0.5), face(0.6, 0.1, 0.9, 0.4)  # 0.16 against 0.09
    cases = [[], [big], [big, small], [big, face(0.6, 0.1, 0.7, 0.2)]]  # (the last: 16 times)
    for faces in cases:
        as_gate = [
            {
                "bounding_box": {
                    "width": f["box"][2] - f["box"][0],
                    "height": f["box"][3] - f["box"][1],
                }
            }
            for f in faces
        ]
        chosen = subject(as_gate, "bounding_box")
        expected = "no_face" if not faces else "ok" if chosen is not None else "no_subject"
        assert verdict(faces, DOMINANCE) == expected


def test_a_different_dominance_changes_only_the_ratio_test() -> None:
    faces = [face(0.1, 0.1, 0.5, 0.5), face(0.6, 0.1, 0.9, 0.4)]  # ratio 1.78
    assert verdict(faces, 2.5) == "no_subject"
    assert verdict(faces, 1.5) == "ok"
    assert verdict([], 1.0) == "no_face"


def test_describe_reports_facts_not_a_single_cause() -> None:
    nothing = describe(
        record([], below=[face(0.2, 0.2, 0.8, 0.8, 0.45)], cut=[face(0, 0, 0.1, 0.2)])
    )
    assert nothing["status"] == "no_face"
    assert nothing["below_floor_faces"] == 1
    assert nothing["border_dropped_faces"] == 1
    assert nothing["best_below_floor_score"] == pytest.approx(0.45)

    two = describe(record([face(0.2, 0.2, 0.6, 0.6, 0.9), face(0.7, 0.1, 1.0, 0.4, 0.6)]))
    assert two["status"] == "no_subject"
    assert two["bucket"] == "1.5-2.0"
    assert two["second_touches_border"] is True
    assert two["largest_is_most_central"] is True


def test_counterfactuals_show_each_rule_alone_against_the_baseline() -> None:
    records = [
        record([face(0.1, 0.1, 0.5, 0.5)]),  # ok
        record([face(0.1, 0.1, 0.5, 0.5), face(0.6, 0.1, 0.9, 0.4)]),  # ratio 1.78
        record([], below=[face(0.1, 0.1, 0.9, 0.9, 0.4)]),  # only below the floor
    ]
    table = counterfactuals(records)
    assert table["baseline"] == {"ok": 1, "no_subject": 1, "no_face": 1}
    assert table["floor_0.3_only"]["moved"] == {"no_face->ok": 1}
    assert table["dominance_1.5_only"]["moved"] == {"no_subject->ok": 1}
    assert table["largest_face_wins"]["statuses"] == {"ok": 2, "no_face": 1}


def test_geometry_helpers() -> None:
    assert area(face(0.0, 0.0, 0.5, 0.4)) == pytest.approx(0.2)
    assert _touches_border(face(0.5, 0.5, 0.6, 1.0)) is True
    assert _touches_border(face(0.2, 0.2, 0.6, 0.6)) is False
    assert _centre_distance(face(0.4, 0.4, 0.6, 0.6)) == pytest.approx(0.0)
    assert _overlap(face(0, 0, 1, 1), face(0.05, 0.05, 1, 1)) is True
    assert _overlap(face(0, 0, 0.4, 0.4), face(0.6, 0.6, 1, 1)) is False


class FakeSession:
    """A detector with one candidate at the middle of a 64 by 64 picture (the nine tensors)."""

    def __init__(
        self, score: float, offset: float = 0.0, batched: bool = False, reach: float = 5.0
    ) -> None:
        self.score, self.offset, self.batched, self.reach = score, offset, batched, reach

    def run(self, _names: None, _inputs: dict[str, Any]) -> list[np.ndarray]:
        outputs: list[np.ndarray] = []
        for stride in (8, 16, 32):
            rows = (640 // stride) ** 2 * 2
            outputs.append(np.zeros((rows, 1), dtype=np.float32))
        for stride in (8, 16, 32):
            rows = (640 // stride) ** 2 * 2
            outputs.append(np.full((rows, 4), self.reach * 8 / stride, dtype=np.float32))
        for stride in (8, 16, 32):
            rows = (640 // stride) ** 2 * 2
            outputs.append(np.zeros((rows, 10), dtype=np.float32))
        middle = 2 * (40 * 80 + 40)  # the anchor centred on (320, 320) at stride 8
        outputs[0][middle, 0] = self.score
        outputs[6][middle, 0] = self.offset  # one landmark's x offset, in strides
        if self.batched:
            outputs = [o[None] for o in outputs]
        return outputs


def picture() -> np.ndarray:
    return np.zeros((64, 64, 3), dtype=np.uint8)


def test_a_score_just_under_the_floor_stays_under_it_at_full_precision() -> None:
    seen = look(FakeSession(0.49996), "x", picture())
    assert seen["kept"] == []
    assert [f["score"] for f in seen["below_floor"]] == [pytest.approx(0.49996, abs=1e-7)]
    assert seen["below_floor"][0]["score"] < 0.5  # (a rounded 0.5 would pass the floor)
    assert [f["score"] for f in look(FakeSession(0.5), "x", picture())["kept"]] == [0.5]


def test_a_leading_batch_axis_of_one_is_read_like_production_reads_it() -> None:
    plain = look(FakeSession(0.9), "x", picture())
    batched = look(FakeSession(0.9, batched=True), "x", picture())
    assert plain["kept"] == batched["kept"]
    assert len(plain["kept"]) == 1


def test_a_landmark_outside_the_image_is_a_border_drop_and_an_empty_box_is_not() -> None:
    cut = look(FakeSession(0.9, offset=-100.0), "x", picture())
    assert cut["kept"] == []
    assert len(cut["border_dropped"]) == 1
    empty = look(FakeSession(0.9, reach=-5.0), "x", picture())  # a reversed box, landmarks inside
    assert empty["kept"] == []
    assert empty["border_dropped"] == []
