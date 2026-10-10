"""The arithmetic and selection rules of the assisted-recognition gate script (M5 step 8)."""

import json
from pathlib import Path

from evaluation.assisted_recognition_gate import choose_people, metrics, ranking, subject


def face(width: float, height: float) -> dict[str, dict[str, float]]:
    return {"bounding_box": {"x": 0, "y": 0, "width": width, "height": height}}


def query(person: str, offered: list[str] | None, *, eligible: bool = True) -> dict[str, object]:
    return {
        "person": person,
        "eligible": eligible,
        "offered": None if offered is None else [{"person": p, "similarity": 0.5} for p in offered],
    }


def test_a_subject_is_the_only_face_or_one_clearly_larger_than_the_rest() -> None:
    assert subject([], "bounding_box") is None
    only = face(0.2, 0.2)
    assert subject([only], "bounding_box") is only
    big, small = face(0.4, 0.4), face(0.3, 0.3)  # 0.16 against 0.09: not 2.5 times
    assert subject([big, small], "bounding_box") is None
    assert subject([face(0.5, 0.5), face(0.2, 0.2)], "bounding_box") is not None


def test_recall_and_reciprocal_rank_count_only_eligible_queries_with_a_subject() -> None:
    results = [
        query("a", ["a", "b"]),  # rank 1
        query("b", ["a", "b"]),  # rank 2
        query("c", ["a", "b"]),  # not offered
        query("d", None),  # no subject face: left out
        query("e", ["e"], eligible=False),  # too few enrolled photographs: left out
    ]

    found = metrics(results)

    assert found["queries"] == 3
    assert found["recall_at_1"] == 0.333
    assert found["recall_at_5"] == 0.667
    assert found["mrr"] == 0.5
    assert found["ineligible_or_no_subject"] == 2


def test_no_eligible_query_gives_no_numbers() -> None:
    found = metrics([query("a", None)])

    assert (found["queries"], found["recall_at_1"], found["mrr"]) == (0, None, None)


def test_the_people_offered_for_the_subject_face_come_best_first() -> None:
    answer = {
        "faces": [
            {
                **face(0.5, 0.5),
                "possible_people": [
                    {"identity": {"person": {"display_name": "Ada"}}, "similarity": 0.81234},
                    {"identity": {"person": None}, "similarity": 0.4},
                ],
            }
        ]
    }

    assert ranking(answer) == [
        {"person": "Ada", "similarity": 0.8123},
        {"person": None, "similarity": 0.4},
    ]
    assert ranking({"faces": []}) is None


def test_people_are_chosen_by_a_stable_order_and_hold_out_a_quarter_of_their_photographs(
    tmp_path: Path,
) -> None:
    manifest: dict[str, list[dict[str, str]]] = {}
    for name, count in (("Ada", 8), ("Bob", 5), ("Cy", 2)):
        (tmp_path / name).mkdir()
        manifest[name] = []
        for index in range(count):
            file = f"{name}/{index:02}.jpg"
            (tmp_path / file).write_bytes(b"x")
            manifest[name].append({"file": file})
    (tmp_path / "Bob" / "04.jpg").unlink()  # listed but missing: not counted

    chosen = choose_people(json.loads(json.dumps(manifest)), tmp_path, count=5, minimum=4)

    assert sorted(p["name"] for p in chosen) == ["Ada", "Bob"]  # Cy has too few
    by_name = {p["name"]: p for p in chosen}
    assert (len(by_name["Ada"]["enrol"]), len(by_name["Ada"]["query"])) == (6, 2)
    assert (len(by_name["Bob"]["enrol"]), len(by_name["Bob"]["query"])) == (3, 1)
    assert choose_people(manifest, tmp_path, count=5, minimum=4) == chosen
