"""The label-review tool (R5): decisions are kept, replayed and exported only when earned."""

import hashlib
import http.client
import json
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

from evaluation import label_review
from evaluation.label_review import Review, ReviewError, serve


@pytest.fixture
def dataset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "datasets"
    monkeypatch.setattr(label_review, "DATASETS_ROOT", root.resolve())
    folder = root / "set"
    manifest: dict[str, list[dict[str, str]]] = {}
    for name, count in (("Ada Lovelace", 6), ("Bob Barker", 3)):
        (folder / name).mkdir(parents=True)
        manifest[name] = []
        for index in range(count):
            file = f"{name}/{index:02}.jpg"
            (folder / file).write_bytes(f"{name} {index}".encode())
            manifest[name].append({"file": file, "title": f"File:{index}.jpg"})
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return folder


def test_a_decision_needs_a_reviewer_a_known_photograph_and_a_known_decision(dataset: Path) -> None:
    with pytest.raises(ReviewError, match="reviewer"):
        Review(dataset).decide("Ada Lovelace/00.jpg", "VERIFIED")
    review = Review(dataset, "sodiq")
    with pytest.raises(ReviewError, match="manifest"):
        review.decide("Ada Lovelace/99.jpg", "VERIFIED")
    with pytest.raises(ReviewError, match="decision is one of"):
        review.decide("Ada Lovelace/00.jpg", "PROBABLY")
    with pytest.raises(ReviewError, match="unknown flags"):
        review.decide("Ada Lovelace/00.jpg", "VERIFIED", flags=("BLURRY",))
    with pytest.raises(ReviewError, match="INCORRECT"):
        review.decide("Ada Lovelace/00.jpg", "VERIFIED", corrected_identity="Someone Else")


def test_the_latest_decision_counts_older_ones_stay_and_a_restart_resumes(dataset: Path) -> None:
    first = Review(dataset, "sodiq")
    first.decide("Ada Lovelace/00.jpg", "VERIFIED")
    first.decide("Ada Lovelace/00.jpg", "UNCERTAIN", note="looks different")

    again = Review(dataset, "another-reviewer")  # a new run resumes from the log

    assert again.current()["Ada Lovelace/00.jpg"]["decision"] == "UNCERTAIN"
    assert [r["decision"] for r in again.history()] == ["VERIFIED", "UNCERTAIN"]
    assert again.status()["unreviewed"] == 8
    assert again.status()["UNCERTAIN"] == 1


def test_the_original_manifest_and_photographs_are_never_touched(dataset: Path) -> None:
    before = {
        p: hashlib.sha256(p.read_bytes()).hexdigest() for p in dataset.rglob("*") if p.is_file()
    }
    review = Review(dataset, "sodiq")
    review.decide("Ada Lovelace/00.jpg", "VERIFIED")
    review.write_export()

    after = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in before}
    assert after == before


def test_only_earned_labels_enter_the_verified_set(dataset: Path) -> None:
    review = Review(dataset, "sodiq")
    review.decide("Ada Lovelace/00.jpg", "VERIFIED")
    review.decide("Ada Lovelace/01.jpg", "UNCERTAIN")
    review.decide("Ada Lovelace/02.jpg", "EXCLUDED")
    review.decide("Ada Lovelace/03.jpg", "VERIFIED", flags=("MULTI_PERSON",))
    review.decide("Ada Lovelace/04.jpg", "INCORRECT")  # wrong, and nobody says who
    review.decide("Ada Lovelace/05.jpg", "INCORRECT", corrected_identity="Bob Barker")
    review.decide("Bob Barker/00.jpg", "VERIFIED")
    # the other two photographs of Bob Barker were never looked at

    document = review.export()

    assert {n: [e["file"] for e in items] for n, items in document["people"].items()} == {
        "Ada Lovelace": ["Ada Lovelace/00.jpg"],
        "Bob Barker": ["Ada Lovelace/05.jpg", "Bob Barker/00.jpg"],
    }
    corrected = document["people"]["Bob Barker"][0]
    assert (
        corrected["corrected"] is True
    )  # a human said so, and the export says it was a correction
    left = document["left_out"]
    assert left["flagged"] == ["Ada Lovelace/03.jpg"]
    assert sorted(left["not_verified"]) == [
        "Ada Lovelace/01.jpg",
        "Ada Lovelace/02.jpg",
        "Ada Lovelace/04.jpg",
        "Bob Barker/01.jpg",
        "Bob Barker/02.jpg",
    ]
    assert document["reviewers"] == ["sodiq"]
    assert document["source_manifest_sha256"] == review.manifest_sha256


def test_a_changed_or_repeated_photograph_is_left_out(dataset: Path) -> None:
    (dataset / "Ada Lovelace/02.jpg").write_bytes(b"Ada Lovelace 0")  # the same bytes as 00
    review = Review(dataset, "sodiq")
    for index in range(4):
        review.decide(f"Ada Lovelace/{index:02}.jpg", "VERIFIED")
    (dataset / "Ada Lovelace/03.jpg").write_bytes(b"replaced afterwards")

    again = Review(dataset, "sodiq")  # (it hashes the files as they are now)
    people, left = again.verified()

    assert [e["file"] for e in people["Ada Lovelace"]] == [
        "Ada Lovelace/00.jpg",
        "Ada Lovelace/01.jpg",
    ]
    assert left["duplicates_dropped"] == ["Ada Lovelace/02.jpg"]
    assert left["stale_needs_review"] == ["Ada Lovelace/03.jpg"]


def test_the_export_reports_the_shortfall_against_the_targets_and_never_pads(dataset: Path) -> None:
    review = Review(dataset, "sodiq")
    for index in range(6):
        review.decide(f"Ada Lovelace/{index:02}.jpg", "VERIFIED")

    document = review.export()

    assert document["counts"]["identities_with_enough_images"] == 1
    assert document["counts"]["held_out_queries"] == 1  # 6 images hold out one
    assert document["shortfall"] == {
        "verified_identities": 39,
        "identities_with_two_queries": 1,
        "verified_queries": 79,
    }


def test_the_export_is_written_and_versioned(dataset: Path) -> None:
    review = Review(dataset, "sodiq")
    review.decide("Ada Lovelace/00.jpg", "VERIFIED")

    path = review.write_export()

    written = json.loads(path.read_text(encoding="utf-8"))
    assert path.parent == dataset / "review" / "exports"
    assert (written["schema_version"], written["kind"]) == (1, "verified-manifest")
    assert written["decisions_sha256"] == hashlib.sha256(review.log_path.read_bytes()).hexdigest()


def test_a_dataset_outside_the_datasets_folder_is_refused(dataset: Path, tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="must be inside"):
        Review(tmp_path)


def test_a_manifest_entry_outside_the_dataset_stops_the_tool(dataset: Path, tmp_path: Path) -> None:
    (tmp_path / "datasets" / "elsewhere.jpg").write_bytes(b"x")
    (dataset / "manifest.json").write_text(
        json.dumps({"Ada": [{"file": "../elsewhere.jpg"}]}), encoding="utf-8"
    )

    with pytest.raises(SystemExit, match="outside the dataset"):
        Review(dataset, "sodiq")


def test_the_page_needs_its_token_serves_listed_photographs_and_records_decisions(
    dataset: Path,
) -> None:
    review = Review(dataset, "sodiq")
    server, token = serve(review)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = str(server.server_address[0]), int(server.server_address[1])
    first: dict[str, object] = {"file": "Ada Lovelace/00.jpg", "decision": "VERIFIED"}

    def call(method: str, path: str, body: dict[str, object] | None = None) -> tuple[int, bytes]:
        connection = http.client.HTTPConnection(host, port, timeout=5)
        connection.request(
            method,
            path,
            json.dumps(body) if body is not None else None,
            {"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        data = response.read()
        connection.close()
        return response.status, data

    try:
        assert call("GET", "/")[0] == 403  # no token
        assert call("GET", "/?t=wrong")[0] == 403
        assert call("GET", f"/?t={token}")[0] == 200
        state = json.loads(call("GET", f"/api/state?t={token}")[1])
        assert set(state["people"]) == {"Ada Lovelace", "Bob Barker"}
        status, data = call("GET", f"/image?f=Ada%20Lovelace/00.jpg&t={token}")
        assert (status, data) == (200, b"Ada Lovelace 0")
        assert call("GET", f"/image?f=../manifest.json&t={token}")[0] == 404  # not listed
        assert call("POST", "/api/decision", first)[0] == 403
        ok, _ = call("POST", f"/api/decision?t={token}", first)
        bad, message = call("POST", f"/api/decision?t={token}", {**first, "decision": "MAYBE"})
    finally:
        server.shutdown()
        server.server_close()

    assert ok == 200
    assert bad == 400
    assert b"decision is one of" in message
    assert review.current()["Ada Lovelace/00.jpg"]["decision"] == "VERIFIED"


def test_a_relabelled_photograph_must_be_reviewed_again(dataset: Path) -> None:
    Review(dataset, "sodiq").decide("Ada Lovelace/00.jpg", "VERIFIED")
    manifest = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))
    moved = manifest["Ada Lovelace"].pop(0)
    manifest["Bob Barker"].append(moved)  # the same file, now proposed as Bob
    (dataset / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    again = Review(dataset, "sodiq")
    document = again.export()

    assert "Ada Lovelace/00.jpg" not in [
        e["file"] for items in document["people"].values() for e in items
    ]
    assert document["left_out"]["stale_needs_review"] == ["Ada Lovelace/00.jpg"]
    assert again.status()["stale_needs_review"] == 1


def test_a_photograph_replaced_while_the_tool_runs_is_not_trusted(dataset: Path) -> None:
    review = Review(dataset, "sodiq")
    review.decide("Ada Lovelace/00.jpg", "VERIFIED")
    (dataset / "Ada Lovelace/00.jpg").write_bytes(b"a different photograph")  # no restart

    document = review.export()

    assert document["people"] == {}
    assert document["left_out"]["stale_needs_review"] == ["Ada Lovelace/00.jpg"]


def test_a_half_written_last_line_does_not_stop_a_resume(dataset: Path) -> None:
    review = Review(dataset, "sodiq")
    review.decide("Ada Lovelace/00.jpg", "VERIFIED")
    with review.log_path.open("ab") as log:
        log.write(b'{"file": "Ada Lovelace/01.jp')  # a crash in the middle of an append

    again = Review(dataset, "sodiq")
    assert again.current()["Ada Lovelace/00.jpg"]["decision"] == "VERIFIED"
    again.decide("Ada Lovelace/02.jpg", "VERIFIED")  # the next append starts a new line

    third = Review(dataset, "sodiq")
    assert sorted(third.current()) == ["Ada Lovelace/00.jpg", "Ada Lovelace/02.jpg"]
    torn = (dataset / "review" / "decisions.torn.jsonl").read_text(encoding="utf-8")
    assert "01.jp" in torn  # the fragment is kept, set aside, not deleted


def test_damage_before_the_end_of_the_log_is_not_hidden(dataset: Path) -> None:
    review = Review(dataset, "sodiq")
    review.decide("Ada Lovelace/00.jpg", "VERIFIED")
    review.decide("Ada Lovelace/01.jpg", "VERIFIED")
    lines = review.log_path.read_text(encoding="utf-8").splitlines()
    review.log_path.write_text("not json\n" + "\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="damaged"):
        review.current()


def test_two_exports_in_the_same_instant_are_two_files(
    dataset: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Frozen(datetime):
        @classmethod
        def now(cls, tz: object = None) -> "Frozen":
            return cls(2026, 10, 12, 12, 0, 0, tzinfo=UTC)

    monkeypatch.setattr(label_review, "datetime", Frozen)
    review = Review(dataset, "sodiq")
    review.decide("Ada Lovelace/00.jpg", "VERIFIED")

    first, second = review.write_export(), review.write_export()

    assert first != second
    assert first.exists()
    assert second.exists()


def test_a_link_out_of_the_dataset_cannot_carry_the_log_or_a_read(
    dataset: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (dataset / "review").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symbolic links are not allowed here")

    with pytest.raises(SystemExit, match="outside the dataset"):
        Review(dataset, "sodiq")


def test_titles_and_labels_are_drawn_as_text_never_as_markup() -> None:
    page = label_review.PAGE
    # data goes in through textContent, value or append of strings, never innerHTML
    assert "innerHTML" not in page
    assert "textContent:e.title" in page


def test_photographs_declared_the_same_picture_count_once_and_one_side_of_a_split(
    dataset: Path,
) -> None:
    (dataset / "Ada Lovelace/04.jpg").write_bytes(b"the same picture, re-encoded")
    review = Review(dataset, "sodiq")
    review.decide("Ada Lovelace/00.jpg", "VERIFIED")
    review.decide("Ada Lovelace/04.jpg", "VERIFIED", same_picture_as="Ada Lovelace/00.jpg")
    review.decide("Ada Lovelace/01.jpg", "VERIFIED")

    people, left = review.verified()

    assert [e["file"] for e in people["Ada Lovelace"]] == [
        "Ada Lovelace/00.jpg",
        "Ada Lovelace/01.jpg",
    ]
    assert left["duplicates_dropped"] == ["Ada Lovelace/04.jpg"]
    with pytest.raises(ReviewError, match="another photograph"):
        review.decide("Ada Lovelace/01.jpg", "VERIFIED", same_picture_as="Nowhere/99.jpg")


def test_the_page_can_be_limited_to_named_people_without_touching_the_rest(dataset: Path) -> None:
    review = Review(dataset, "sodiq")
    review.focus(["bob barker"])  # (case aside)
    server, token = serve(review)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = str(server.server_address[0]), int(server.server_address[1])
    try:
        connection = http.client.HTTPConnection(host, port, timeout=5)
        connection.request("GET", f"/api/state?t={token}")
        state = json.loads(connection.getresponse().read())
        connection.close()
    finally:
        server.shutdown()
        server.server_close()

    assert set(state["people"]) == {"Bob Barker"}
    assert state["status"]["photographs"] == 9  # the counts are about the whole dataset
    assert len(review.entries) == 9  # and so is what an export would use


def test_a_misspelt_person_stops_the_tool_with_a_hint(dataset: Path) -> None:
    review = Review(dataset, "sodiq")
    with pytest.raises(SystemExit) as stopped:
        review.focus(["Ada Lovlace"])
    assert "Ada Lovelace" in str(stopped.value)
    assert review.shown is None
    with pytest.raises(SystemExit):
        review.focus([])
