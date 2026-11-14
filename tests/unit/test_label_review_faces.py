"""Issue 181: which face carries the label. Synthetic pictures only; no model, no photograph."""

import hashlib
import http.client
import io
import json
import threading
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

from evaluation import label_review
from evaluation.label_review import Review, ReviewError, serve
from evaluation.review_detections import Seen, detect_dataset, suggest

ADA = "Ada Lovelace"
FILE = f"{ADA}/00.jpg"
LEFT = [0.1, 0.2, 0.3, 0.6]  # two faces of a picture of two people
RIGHT = [0.6, 0.2, 0.8, 0.6]
PROVENANCE = {
    "package_key": "insightface-buffalo-l",
    "package_version": "1",
    "detector": {"file_sha256": "a" * 64, "contract": {"score_threshold": 0.5}},
}


def jpeg(colour: int, size: tuple[int, int] = (100, 80)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (colour, 0, 0)).save(out, "JPEG")
    return out.getvalue()


@pytest.fixture
def dataset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "datasets"
    monkeypatch.setattr(label_review, "DATASETS_ROOT", root.resolve())
    folder = root / "set"
    (folder / ADA).mkdir(parents=True)
    manifest: dict[str, list[dict[str, str]]] = {ADA: []}
    for index in range(6):
        (folder / ADA / f"{index:02}.jpg").write_bytes(jpeg(20 + 40 * index))
        manifest[ADA].append({"file": f"{ADA}/{index:02}.jpg", "title": f"File:{index}"})
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return folder


def run(
    review: Review,
    faces: list[list[float]] = (LEFT, RIGHT),  # type: ignore[assignment]
    suggestion: list[float] | None = LEFT,
    *,
    file: str = FILE,
    provenance: dict[str, Any] = PROVENANCE,
    size: tuple[int, int] = (100, 80),
) -> dict[str, Any]:
    """Store one detection run of a photograph, as `review_detections.py` does."""
    return review.append_detection(
        {
            "file": file,
            "sha256": review.digest(file),
            "image_size": list(size),
            "faces": [{"box": box, "score": 0.9} for box in faces],
            "suggestion": None
            if suggestion is None
            else {"box": suggestion, "basis": "label_recurrence", "score": 0.5, "rationale": "r"},
            "provenance": provenance,
        }
    )


def test_an_unconfirmed_suggestion_never_becomes_ground_truth(dataset: Path) -> None:
    review = Review(dataset, "sodiq")
    run(review)

    people, left = review.verified()
    assert people == {}  # offered, never taken
    assert FILE in left["not_verified"]
    # nothing is chosen on the reviewer's behalf: a verdict without a face is refused
    with pytest.raises(ReviewError, match="choose the face"):
        review.decide(FILE, "VERIFIED")
    assert review.history() == []
    # saying "none" is not confirming either
    record = review.decide(FILE, "UNCERTAIN", none_or_cannot_determine=True)
    assert record["suggestion"]["outcome"] == "REJECTED"
    assert record["face"] is None
    assert review.verified()[0] == {}
    with pytest.raises(ReviewError, match="UNCERTAIN or EXCLUDED"):
        review.decide(FILE, "VERIFIED", none_or_cannot_determine=True)


def test_explicitly_confirming_the_suggested_face_exports_that_face(dataset: Path) -> None:
    review = Review(dataset, "sodiq")
    detection = run(review)

    record = review.decide(FILE, "VERIFIED", face=LEFT)

    assert record["suggestion"]["outcome"] == "CONFIRMED"
    assert record["suggestion"]["offered"]["box"] == LEFT
    assert record["face"]["source"] == "DETECTED"
    assert record["face"]["image_size"] == [100, 80]
    assert record["detection"] == {"record_id": detection["id"], "provenance": PROVENANCE}
    [item] = review.export()["people"][ADA]
    assert item["face"]["box"] == LEFT
    assert item["review"]["suggestion_outcome"] == "CONFIRMED"
    assert item["review"]["decision_id"] == record["id"]
    assert item["sha256"] == hashlib.sha256((dataset / FILE).read_bytes()).hexdigest()


def test_an_override_exports_the_box_the_reviewer_chose_not_the_suggestion(dataset: Path) -> None:
    review = Review(dataset, "sodiq")
    run(review)

    record = review.decide(FILE, "VERIFIED", face=RIGHT, flags=("MULTI_PERSON",))

    assert record["suggestion"]["outcome"] == "OVERRIDDEN"
    document = review.export()
    [item] = document["people"][ADA]  # (several people is no doubt once a face is selected)
    assert item["face"]["box"] == RIGHT
    assert document["counts"]["verified_with_a_selected_face"] == 1


def test_no_suggestion_is_recorded_as_none_offered_and_a_drawn_box_is_a_correction(
    dataset: Path,
) -> None:
    review = Review(dataset, "sodiq")
    run(review, faces=[], suggestion=None)  # the detector found nothing

    record = review.decide(FILE, "VERIFIED", face=[0.2, 0.2, 0.5, 0.7])

    assert record["suggestion"] == {"outcome": "NONE_OFFERED", "offered": None}
    assert record["face"]["source"] == "CORRECTED"
    assert review.export()["people"][ADA][0]["face"]["source"] == "CORRECTED"


def test_a_picture_with_no_detection_run_works_as_before_and_a_box_can_still_be_drawn(
    dataset: Path,
) -> None:
    review = Review(dataset, "sodiq")

    plain = review.decide("Ada Lovelace/01.jpg", "VERIFIED")  # no detections: the old workflow
    drawn = review.decide("Ada Lovelace/02.jpg", "VERIFIED", face=[0, 0, 0.5, 0.5])

    assert plain["face"] is None
    assert plain["detection"] is None
    assert drawn["face"]["image_size"] == [100, 80]  # read from the picture, as shown upright
    people = review.export()["people"][ADA]
    assert "face" not in people[0]
    assert people[1]["face"]["box"] == [0, 0, 0.5, 0.5]


@pytest.mark.parametrize(
    "box",
    [[0.1, 0.1, 0.2], [0.5, 0.1, 0.4, 0.5], [-0.1, 0, 0.5, 0.5], [0, 0, 1.2, 1], ["a"] * 4, "box"]
    + [[float("nan"), 0, 1, 1], [0.1, 0.1, 0.1, 0.5]],
)
def test_a_face_box_is_four_numbers_with_an_area_inside_the_picture(
    dataset: Path, box: object
) -> None:
    with pytest.raises(ReviewError):
        Review(dataset, "sodiq").decide(FILE, "VERIFIED", face=box)  # type: ignore[arg-type]


def test_the_order_of_the_detected_faces_never_changes_the_selection(dataset: Path) -> None:
    review = Review(dataset, "sodiq")
    run(review, faces=[LEFT, RIGHT])
    review.decide(FILE, "VERIFIED", face=RIGHT)
    before = review.export()["people"][ADA][0]["face"]

    run(review, faces=[RIGHT, LEFT])  # a new run lists the same faces the other way round

    assert review.status()["stale_needs_review"] == 0
    assert review.export()["people"][ADA][0]["face"] == before
    shown = review.face_view(FILE, review.detections()[FILE])
    assert shown is not None
    assert [f["box"] for f in shown["faces"]] == [LEFT, RIGHT]  # shown left to right, always


def test_a_changed_photograph_label_or_size_needs_a_new_review(dataset: Path) -> None:
    review = Review(dataset, "sodiq")
    for index in range(3):
        run(review, file=f"{ADA}/{index:02}.jpg")
        review.decide(f"{ADA}/{index:02}.jpg", "VERIFIED", face=LEFT)
    (dataset / ADA / "00.jpg").write_bytes(jpeg(200))  # other bytes
    manifest = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))
    manifest[ADA][1]["file"] = f"{ADA}/01.jpg"
    (dataset / "manifest.json").write_text(
        json.dumps({"Someone Else": [manifest[ADA][1]], ADA: [manifest[ADA][0], manifest[ADA][2]]}),
        encoding="utf-8",
    )

    again = Review(dataset, "sodiq")
    again.append_detection(  # a later run of picture 02 says it is a different size
        {
            "file": f"{ADA}/02.jpg",
            "sha256": again.digest(f"{ADA}/02.jpg"),
            "image_size": [80, 100],
            "faces": [{"box": LEFT, "score": 0.9}],
            "suggestion": None,
            "provenance": PROVENANCE,
        }
    )
    document = again.export()

    assert document["people"] == {}
    assert document["stale_reasons"] == {
        "photograph_changed": [f"{ADA}/00.jpg"],
        "label_changed": [f"{ADA}/01.jpg"],
        "geometry_changed": [f"{ADA}/02.jpg"],
    }
    assert document["counts"]["status"]["stale_needs_review"] == 3


def test_a_detector_change_that_loses_the_face_needs_a_new_review_but_a_drawn_box_stays(
    dataset: Path,
) -> None:
    review = Review(dataset, "sodiq")
    run(review)
    review.decide(FILE, "VERIFIED", face=LEFT)  # a detected face
    run(review, file="Ada Lovelace/01.jpg", faces=[], suggestion=None)
    review.decide("Ada Lovelace/01.jpg", "VERIFIED", face=[0.2, 0.2, 0.5, 0.7])  # drawn

    # the same detector settings find the face a little to one side: it still corresponds
    run(review, faces=[[0.12, 0.2, 0.32, 0.6], RIGHT])
    assert review.status()["stale_needs_review"] == 0
    # a new model finds only other faces: nothing corresponds to the selection any more
    newer = {**PROVENANCE, "package_version": "2"}
    run(review, faces=[RIGHT], suggestion=None, provenance=newer)
    run(review, file="Ada Lovelace/01.jpg", faces=[[0.7, 0.7, 0.9, 0.9]], suggestion=None)

    document = review.export()
    assert document["stale_reasons"] == {"geometry_changed": [FILE]}
    assert [i["file"] for i in document["people"][ADA]] == ["Ada Lovelace/01.jpg"]


def test_a_selection_that_is_no_longer_a_valid_box_is_not_exported(dataset: Path) -> None:
    review = Review(dataset, "sodiq")
    review.decide(FILE, "VERIFIED", face=LEFT)
    lines = review.log_path.read_text(encoding="utf-8").splitlines()
    damaged = json.loads(lines[-1]) | {"face": {"box": [0.5, 0.5, 0.2, 0.2], "image_size": [1, 1]}}
    review.log_path.write_text(json.dumps(damaged) + "\n", encoding="utf-8")

    document = review.export()

    assert document["people"] == {}
    assert document["stale_reasons"] == {"geometry_invalid": [FILE]}


def test_detections_of_other_bytes_say_nothing_about_this_picture(dataset: Path) -> None:
    review = Review(dataset, "sodiq")
    run(review)
    with pytest.raises(ReviewError, match="changed while"):
        review.append_detection(
            {
                "file": FILE,
                "sha256": "0" * 64,
                "image_size": [100, 80],
                "faces": [],
                "suggestion": None,
                "provenance": PROVENANCE,
            }
        )
    (dataset / FILE).write_bytes(jpeg(222))  # the picture changed after the run

    assert Review(dataset, "sodiq").detections() == {}


def test_a_suggestion_made_for_another_label_is_not_shown(dataset: Path) -> None:
    review = Review(dataset, "sodiq")
    run(review)
    manifest = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))
    (dataset / "manifest.json").write_text(json.dumps({"Other": manifest[ADA]}), encoding="utf-8")

    again = Review(dataset, "sodiq")
    shown = again.face_view(FILE, again.detections()[FILE])

    assert shown is not None
    assert shown["suggestion"] is None
    assert len(shown["faces"]) == 2
    assert again.decide(FILE, "UNCERTAIN", none_or_cannot_determine=True)["suggestion"] == {
        "outcome": "NONE_OFFERED",
        "offered": None,
    }


def test_the_history_stays_auditable_across_schema_versions_and_restarts(dataset: Path) -> None:
    review = Review(dataset, "sodiq")
    legacy = {  # a record as schema 1 wrote it: no id, no face
        "schema_version": 1,
        "at": "2026-10-12T10:00:00+00:00",
        "reviewer": "old",
        "file": FILE,
        "sha256": review.digest(FILE),
        "manifest_sha256": review.manifest_sha256,
        "original_identity": ADA,
        "decision": "VERIFIED",
        "corrected_identity": None,
        "flags": [],
        "note": "",
        "same_picture_as": None,
    }
    review.review_dir.mkdir()
    review.log_path.write_text(json.dumps(legacy) + "\n", encoding="utf-8")
    assert [i["file"] for i in review.export()["people"][ADA]] == [FILE]  # still counts, no face

    run(review)
    first = review.decide(FILE, "VERIFIED", face=LEFT)
    second = review.decide(FILE, "VERIFIED", face=RIGHT, note="on second thought")
    crashed = Review(dataset, "later")  # a restart, after a half-written line
    with review.log_path.open("ab") as log:
        log.write(b'{"schema_version": 2, "file": "Ada')
    third = crashed.decide(FILE, "UNCERTAIN", none_or_cannot_determine=True)

    history = Review(dataset).history()
    assert [r["schema_version"] for r in history] == [1, 2, 2, 2]
    assert [r.get("supersedes") for r in history[1:]] == [None, first["id"], second["id"]]
    assert history[3]["id"] == third["id"]
    assert Review(dataset).export()["people"] == {}  # the latest says: cannot determine
    assert (dataset / "review" / "decisions.torn.jsonl").is_file()
    assert len({r["id"] for r in history[1:]}) == 3


def test_a_log_from_a_newer_version_is_refused_not_guessed_at(dataset: Path) -> None:
    review = Review(dataset, "sodiq")
    review.review_dir.mkdir()
    review.log_path.write_text('{"schema_version": 3, "file": "x"}\n', encoding="utf-8")

    with pytest.raises(SystemExit, match="newer version"):
        review.status()


def test_the_page_shows_boxes_and_the_suggestion_as_unverified_and_records_a_face(
    dataset: Path,
) -> None:
    review = Review(dataset, "sodiq")
    run(review)
    server, token = serve(review)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    host, port = str(server.server_address[0]), int(server.server_address[1])

    def call(method: str, path: str, body: dict[str, object] | None = None) -> dict[str, Any]:
        connection = http.client.HTTPConnection(host, port, timeout=5)
        connection.request(method, path, json.dumps(body) if body else None)
        data = json.loads(connection.getresponse().read())
        connection.close()
        return data  # type: ignore[no-any-return]

    try:
        state = call("GET", f"/api/state?t={token}")
        shown = next(e for e in state["people"][ADA] if e["file"] == FILE)["detection"]
        refused = call("POST", f"/api/decision?t={token}", {"file": FILE, "decision": "VERIFIED"})
        saved = call(
            "POST",
            f"/api/decision?t={token}",
            {"file": FILE, "decision": "VERIFIED", "face": RIGHT},
        )
    finally:
        server.shutdown()
        server.server_close()

    assert [f["box"] for f in shown["faces"]] == [LEFT, RIGHT]
    assert shown["suggestion"]["box"] == LEFT
    assert shown["suggestion"]["basis"]
    assert "choose the face" in refused["error"]
    assert saved["face"]["box"] == RIGHT
    assert saved["suggestion"]["outcome"] == "OVERRIDDEN"
    page = label_review.PAGE
    assert "Suggestion - not verified" in page
    assert "None / cannot determine" in page
    assert "innerHTML" not in page  # (the boxes and their words are built as text)


# --- the suggestion ------------------------------------------------------------------------


def unit(*values: float) -> np.ndarray:
    vector = np.array(values, dtype=np.float32)
    return vector / np.linalg.norm(vector)


def seen(box: list[float], *vector: float) -> Seen:
    return Seen(box, 0.9, unit(*vector))


def test_the_suggestion_is_the_face_that_recurs_across_the_label_not_the_central_one() -> None:
    subject_vector = (1.0, 0.0, 0.0)
    label = {
        # the centred, largest face is a stranger; the small one at the edge recurs
        "a": [seen([0.4, 0.3, 0.6, 0.7], 0, 1, 0), seen([0.0, 0.0, 0.1, 0.1], *subject_vector)],
        "b": [seen([0.3, 0.3, 0.7, 0.8], 0, 0, 1), seen([0.8, 0.8, 0.9, 0.9], *subject_vector)],
        "c": [seen([0.5, 0.5, 0.6, 0.6], *subject_vector)],
    }

    offered = suggest("a", label)

    assert offered is not None
    assert offered["box"] == [0.0, 0.0, 0.1, 0.1]
    assert offered["basis"] == "label_recurrence"
    assert 0.99 < offered["score"] <= 1.0
    assert "not a probability" in offered["rationale"]
    reordered = {"a": list(reversed(label["a"])), "c": label["c"], "b": label["b"]}
    assert suggest("a", reordered) == offered  # nothing depends on order


def test_a_sole_face_is_suggested_as_that_and_nothing_else_is_guessed() -> None:
    only = seen([0.1, 0.1, 0.4, 0.4], 1, 0, 0)
    assert suggest("a", {"a": [only]})["basis"] == "sole_face"  # type: ignore[index]
    assert suggest("a", {"a": []}) is None
    pair = [seen([0, 0, 0.2, 0.2], 1, 0, 0), seen([0.5, 0, 0.7, 0.2], 0, 1, 0)]
    assert suggest("a", {"a": pair}) is None  # no other photograph to compare with
    assert suggest("a", {"a": pair, "b": [seen([0, 0, 0.2, 0.2], 1, 0, 0)]}) is None  # one other
    # the best face is no better than the next, or too weak: nothing is offered
    tie = {"a": pair, "b": [seen([0, 0, 1, 1], 1, 1, 0)], "c": [seen([0, 0, 1, 1], 1, 1, 0)]}
    assert suggest("a", tie) is None
    weak = {"a": pair, "b": [seen([0, 0, 1, 1], 0, 0, 1)], "c": [seen([0, 0, 1, 1], 0, 0, 1)]}
    assert suggest("a", weak) is None


def test_detection_records_every_face_with_provenance_and_a_rerun_adds_nothing(
    dataset: Path,
) -> None:
    review = Review(dataset, "sodiq")
    subject = (1.0, 0.0, 0.0)
    planted = {  # the first pixel of each decoded picture names its faces
        0: [seen(LEFT, *subject), seen(RIGHT, 0, 1, 0)],
        1: [seen(LEFT, 0, 0, 1), seen(RIGHT, *subject)],
        2: [seen(LEFT, *subject)],
        3: [],
        4: [seen(LEFT, 1, 0.01, 0), seen(RIGHT, 0, 1, 0)],
        5: [seen(RIGHT, 0, 1, 1)],
    }
    index = {(dataset / ADA / f"{i:02}.jpg").read_bytes(): i for i in range(6)}

    def decode(data: bytes) -> np.ndarray:
        pixels = np.zeros((80, 100, 3), dtype=np.uint8)
        pixels[0, 0, 0] = index[data]
        return pixels

    class Planted:
        provenance = PROVENANCE

        def see(self, pixels: np.ndarray) -> list[Seen]:
            return planted[int(pixels[0, 0, 0])]

    first = detect_dataset(review, Planted(), decode)
    second = detect_dataset(review, Planted(), decode)

    assert first["photographs"] == 6
    assert first["appended"] == 6
    assert (first["no_face"], first["one_face"], first["several_faces"]) == (1, 2, 3)
    assert second["appended"] == 0
    assert second["unchanged"] == 6
    found = review.detections()
    stored = found["Ada Lovelace/00.jpg"]
    assert stored["provenance"] == PROVENANCE
    assert stored["image_size"] == [100, 80]
    assert stored["suggestion"]["box"] == LEFT  # recurs across the label; the others agree
    assert "embedding" not in json.dumps(stored)
    assert "vector" not in json.dumps(stored)
    assert found["Ada Lovelace/03.jpg"]["faces"] == []
    assert found["Ada Lovelace/03.jpg"]["suggestion"] is None
    # what was suggested is still not a decision
    assert review.history() == []
    assert review.export()["people"] == {}
