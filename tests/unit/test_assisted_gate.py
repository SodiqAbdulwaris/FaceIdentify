"""The arithmetic and selection rules of the assisted-recognition gate script (M5 step 8)."""

import hashlib
import json
from pathlib import Path

import pytest

from evaluation.assisted_recognition_gate import (
    choose_people,
    faces_of,
    load_provenance,
    metrics,
    open_set,
    partition_people,
    per_identity,
    pick_hard_negatives,
    pool_candidates,
    positive_seconds,
    ranking,
    subject,
    wilson,
)


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
        {"person": "Ada", "similarity": 0.81234},  # (full precision)
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
            (tmp_path / file).write_bytes(file.encode())  # (every picture different)
            manifest[name].append({"file": file})
    (tmp_path / "Bob" / "04.jpg").unlink()  # listed but missing: not counted

    chosen = choose_people(json.loads(json.dumps(manifest)), tmp_path, count=5, minimum=4)

    assert sorted(p["name"] for p in chosen) == ["Ada", "Bob"]  # Cy has too few
    by_name = {p["name"]: p for p in chosen}
    assert (len(by_name["Ada"]["enrol"]), len(by_name["Ada"]["query"])) == (6, 2)
    assert (len(by_name["Bob"]["enrol"]), len(by_name["Bob"]["query"])) == (3, 1)
    assert choose_people(manifest, tmp_path, count=5, minimum=4) == chosen


def test_a_picture_is_used_once_even_when_listed_twice_or_copied_under_another_name(
    tmp_path: Path,
) -> None:
    (tmp_path / "Ada").mkdir()
    entries = []
    for index in range(8):
        file = f"Ada/{index:02}.jpg"
        (tmp_path / file).write_bytes(
            f"picture {index % 6}".encode()
        )  # 00 and 06 are the same bytes
        entries.append({"file": file})
    entries.append({"file": "Ada/00.jpg"})  # listed twice

    [ada] = choose_people({"Ada": entries}, tmp_path, count=1, minimum=4)

    used = [path.read_bytes() for path in ada["enrol"] + ada["query"]]
    assert len(used) == len(set(used)) == 6  # six distinct pictures
    assert not set(ada["enrol"]) & set(ada["query"])  # nothing is on both sides


def test_a_listed_file_outside_the_dataset_is_refused(tmp_path: Path) -> None:
    dataset = tmp_path / "set"
    dataset.mkdir()
    (tmp_path / "elsewhere.jpg").write_bytes(b"x")

    with pytest.raises(SystemExit, match="outside the dataset folder"):
        choose_people({"Ada": [{"file": "../elsewhere.jpg"}]}, dataset, count=1, minimum=1)


async def test_placed_and_unplaced_faces_are_both_considered() -> None:
    class Gate:
        async def get(self, path: str) -> dict[str, list[dict[str, object]]]:
            box = {"x": 0, "y": 0, "width": 0.5, "height": 0.5}
            if path.endswith("unresolved-faces"):
                return {"items": [{"bounding_box": box, "representation_id": "r1"}]}
            return {
                "items": [
                    {
                        "id": "o1",
                        "identity_id": "i1",
                        "representative_observation": {"bounding_box": box},
                    },
                    {"id": "o2", "identity_id": "i2", "representative_observation": None},
                ]
            }

    faces = await faces_of(Gate(), "s1")  # type: ignore[arg-type]

    assert [f["representation_id"] for f in faces] == ["r1", None]
    assert [f["occurrence"] and f["occurrence"]["id"] for f in faces] == [None, "o1"]


def test_a_verified_photograph_that_changed_or_vanished_stops_the_run(tmp_path: Path) -> None:
    (tmp_path / "Ada").mkdir()
    for index in range(5):
        (tmp_path / "Ada" / f"{index}.jpg").write_bytes(f"photo {index}".encode())
    good = hashlib.sha256(b"photo 0").hexdigest()
    entries = [
        {"file": f"Ada/{i}.jpg", "sha256": hashlib.sha256(f"photo {i}".encode()).hexdigest()}
        for i in range(5)
    ]
    assert choose_people({"Ada": entries}, tmp_path, count=1, minimum=4)  # as verified

    changed = [{**entries[0], "sha256": "0" * 64}, *entries[1:]]
    with pytest.raises(SystemExit, match="changed after it was verified"):
        choose_people({"Ada": changed}, tmp_path, count=1, minimum=4)

    (tmp_path / "Ada" / "0.jpg").unlink()
    with pytest.raises(SystemExit, match="verified but is missing"):
        choose_people(
            {"Ada": [{"file": "Ada/0.jpg", "sha256": good}, *entries[1:]]},
            tmp_path,
            count=1,
            minimum=4,
        )


def person(name: str, enrol: int, query: int = 1) -> dict[str, object]:
    return {
        "name": name,
        "enrol": [Path(f"{name}/{i}.jpg") for i in range(enrol)],
        "query": [Path(f"{name}/q{i}.jpg") for i in range(query)],
    }


def test_unknown_people_are_never_enrolled_and_all_their_photographs_are_queries() -> None:
    everyone = [person("A", 5), person("B", 1), person("C", 6), person("D", 2, 0)]

    people = partition_people(everyone, known_count=5, minimum=5, unknown_count=2)

    known = [p for p in people if not p.get("unknown")]
    unknown = [p for p in people if p.get("unknown")]
    assert [p["name"] for p in known] == ["A", "C"]  # 6 or 7 photographs
    assert [p["name"] for p in unknown] == ["B", "D"]  # the rest, whatever they have
    assert all(p["enrol"] == [] for p in unknown)
    assert [len(p["query"]) for p in unknown] == [2, 2]
    assert partition_people(everyone, known_count=5, minimum=5, unknown_count=0) == [
        everyone[0],
        everyone[2],
    ]


def ranked(
    person: str,
    offered: list[tuple[str | None, float]],
    *,
    unknown: bool = False,
    status: str = "POSSIBLE_PEOPLE",
) -> dict[str, object]:
    return {
        "person": person,
        "unknown": unknown,
        "eligible": not unknown,
        "offered": [{"person": n, "similarity": s} for n, s in offered],
        "status": status,
    }


def test_the_open_set_counts_strangers_accepted_at_each_cutoff_apart_from_known_people() -> None:
    results = [
        ranked("A", [("A", 0.80), ("B", 0.40)]),  # a known person, right
        ranked("A", [("B", 0.55), ("A", 0.50)]),  # a known person, wrong first
        ranked("Z", [("A", 0.60)], unknown=True),  # a stranger resembling A
        ranked("Z", [("B", 0.35)], unknown=True),
        ranked("Y", [], unknown=True, status="UNKNOWN"),  # a stranger nobody resembles
    ]

    found = open_set(results)

    assert (found["unknown_queries"], found["known_queries"]) == (3, 2)
    assert found["unknown_with_no_candidate"] == 1
    by = {row["cutoff"]: row for row in found["by_cutoff"]}
    assert by[0.5]["unknown_false_accepts"] == 1  # only the 0.60 stranger
    assert by[0.5]["known_accepted_correct"] == 1
    assert by[0.5]["known_accepted_wrong"] == 1
    assert by[0.7]["unknown_false_accepts"] == 0
    assert by[0.7]["known_accepted_correct"] == 1
    assert by[0.3]["unknown_false_accepts"] == 2
    assert found["policy"] == {
        "identity_answers_for_unknown_people": 0,
        "possible_people_offered_for_unknown_people": 2,
        "unknown_status_for_unknown_people": 1,
    }
    assert found["unknown_people"] == ["Y", "Z"]


def test_per_identity_retrieval_counts_first_place_and_top_five() -> None:
    results = [
        ranked("A", [("A", 0.9)]),
        ranked("A", [("B", 0.9), ("A", 0.8)]),
        ranked("B", [("A", 0.9)]),
        ranked("Z", [("A", 0.9)], unknown=True),
    ]

    table = per_identity(results)

    assert table == {
        "A": {"queries": 2, "recall_at_1": 1, "recall_at_5": 2},
        "B": {"queries": 1, "recall_at_1": 0, "recall_at_5": 0},
    }


def test_the_wilson_interval_is_between_zero_and_one_and_wider_for_fewer_queries() -> None:
    interval = wilson(0, 18)
    assert interval == [0.0, 0.176]
    few, many = wilson(5, 10), wilson(50, 100)
    assert few is not None
    assert many is not None
    assert few[1] - few[0] > many[1] - many[0]
    assert wilson(0, 0) is None  # nothing observed: no interval, not a zero-width one


def test_a_score_just_under_a_cutoff_is_not_accepted_and_the_median_is_exact() -> None:
    results = [
        ranked("Z", [("A", 0.29996)], unknown=True),  # would round up to 0.30
        ranked("Z", [("A", 0.20)], unknown=True),
        ranked("Y", [], unknown=True, status="UNKNOWN"),
        {"person": "X", "unknown": True, "eligible": False, "offered": None, "status": None},
    ]

    found = open_set(results)

    by = {row["cutoff"]: row for row in found["by_cutoff"]}
    assert by[0.3]["unknown_false_accepts"] == 0
    assert found["unknown_top1_similarity"]["median"] == pytest.approx(0.249980)  # of two scores
    assert found["unknown_queries_attempted"] == 4
    assert found["unknown_queries_without_a_subject_face"] == 1
    assert found["unknown_queries"] == 3


def test_provenance_is_checked_before_a_library_is_built(tmp_path: Path) -> None:
    path = tmp_path / "PROVENANCE.json"
    assert load_provenance(path) is None  # none: a Commons set

    path.write_text(
        json.dumps({"schema_version": 1, "dataset": "LFW", "labels_by": "its creators"})
    )
    assert load_provenance(path) == {
        "schema_version": 1,
        "dataset": "LFW",
        "labels_by": "its creators",
    }

    for bad in (
        '{"schema_version": 1}',
        "{}",
        "[]",
        "not json",
        '{"schema_version": 2, "dataset": "x", "labels_by": "y"}',
    ):
        path.write_text(bad)
        with pytest.raises(SystemExit, match="not a valid provenance"):
            load_provenance(path)


def test_a_wait_must_be_a_finite_number_above_zero() -> None:
    import argparse

    assert positive_seconds("3600") == 3600.0
    for bad in ("0", "-5", "nan", "inf", "soon"):
        with pytest.raises(argparse.ArgumentTypeError):
            positive_seconds(bad)


def test_hard_negatives_are_the_closest_ranked_candidates_in_a_stable_order() -> None:
    scored = [("Far", 0.10), ("Near", 0.40), ("NoFace", None), ("Close", 0.30), ("Tie", 0.30)]
    assert pick_hard_negatives(scored, 1) == ["Near"]
    two = pick_hard_negatives(scored, 3)
    assert two[0] == "Near"
    assert set(two[1:]) == {"Close", "Tie"}  # NoFace cannot be ranked
    assert pick_hard_negatives(list(reversed(scored)), 3) == two  # listing order never matters
    assert "NoFace" not in pick_hard_negatives(scored, 10)


def test_a_pool_person_selects_on_one_picture_and_is_scored_on_the_others(tmp_path: Path) -> None:
    def pictures(name: str, *contents: bytes) -> dict[str, object]:
        paths = []
        for i, content in enumerate(contents):
            path = tmp_path / f"{name}-{i}.jpg"
            path.write_bytes(content)
            paths.append(path)
        return {"name": name, "enrol": paths[1:], "query": paths[:1]}

    shared = b"a picture also in the main dataset"
    pool = [
        pictures("Tom_Hanks", b"t0", b"t1"),  # the same name as an enrolled person
        pictures("Stranger", b"s0", b"s1", b"s2"),
        pictures("Alias", shared, b"a1", b"a2"),  # one shared picture: the same person, out
        pictures("Single", b"only one"),
    ]
    taken = {hashlib.sha256(shared).hexdigest()}
    kept, dropped = pool_candidates(pool, ["Tom Hanks", "Emma Stone"], taken)
    assert dropped == {
        "same_name": ["Tom_Hanks"],
        "shared_a_picture": ["Alias"],
        "too_few_pictures": 1,
    }
    (stranger,) = kept
    assert stranger["name"] == "Stranger"
    assert stranger["select"] == tmp_path / "Stranger-0.jpg"
    assert stranger["score"] == [tmp_path / "Stranger-1.jpg", tmp_path / "Stranger-2.jpg"]
    assert stranger["select"] not in stranger["score"]
