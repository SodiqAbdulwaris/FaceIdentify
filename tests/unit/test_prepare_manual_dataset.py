"""The folder structure and the numbering of a hand-collected set (no real pictures)."""

import io
import json
from pathlib import Path

import pytest
from PIL import Image

from evaluation import prepare_manual_dataset as tool


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    datasets = (tmp_path / "datasets").resolve()
    monkeypatch.setattr(tool, "DATASETS_ROOT", datasets)
    folder = datasets / "set"
    tool.init(folder)
    return folder


def picture(colour: int, kind: str = "JPEG", size: tuple[int, int] = (160, 160)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (colour, 40, 90)).save(buffer, format=kind)
    return buffer.getvalue()


def test_init_makes_a_folder_per_person_a_listing_and_instructions(root: Path) -> None:
    assert (root / "Jason_Statham").is_dir()
    assert (root / "Jennifer_Lopez").is_dir()
    assert "Jenna Ortega" in (root / "people.txt").read_text(encoding="utf-8")
    assert (root / "HOW_TO.txt").is_file()
    # a second run keeps the pictures that are already there and the owner's edits
    (root / "Jason_Statham" / "a.jpg").write_bytes(picture(1))
    (root / "people.txt").write_text("Jason Statham\nNew Person\n", encoding="utf-8")
    result = tool.init(root)
    assert (root / "Jason_Statham" / "a.jpg").is_file()
    assert (root / "New_Person").is_dir()
    assert result["people"] == 2


def test_numbering_is_a_dry_run_until_applied_then_stable(root: Path) -> None:
    folder = root / "Jason_Statham"
    (folder / "IMG 1.JPG").write_bytes(picture(10))
    (folder / "b.png").write_bytes(picture(20, "PNG"))
    (folder / "c.webp").write_bytes(picture(30, "WEBP"))
    (folder / "copy of a.jpg").write_bytes(picture(10))  # the same picture as IMG 1
    (folder / "broken.jpg").write_bytes(b"not a picture")
    (folder / "photo.avif").write_bytes(b"\x00\x00\x00\x1cftypavif")
    (folder / "notes.txt").write_text("hi", encoding="utf-8")

    dry = tool.number(root, apply=False)
    assert not (folder / "001.jpg").exists()  # nothing changed
    plan = dry["people"]["Jason Statham"]
    assert plan["to_rename"] == 3
    assert plan["to_skip"] == 4
    assert not (root / "manifest.json").exists()

    tool.number(root, apply=True)
    numbered = sorted(p.name for p in folder.glob("[0-9][0-9][0-9].jpg"))
    assert numbered == ["001.jpg", "002.jpg", "003.jpg"]
    assert (folder / "_skipped" / "broken.jpg").is_file()  # moved aside, never deleted
    assert (folder / "_skipped" / "photo.avif").is_file()
    for name in numbered:
        with Image.open(folder / name) as opened:
            assert opened.format == "JPEG"
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert [e["file"] for e in manifest["Jason Statham"]] == [
        f"Jason_Statham/{n}" for n in numbered
    ]
    assert manifest["Jason Statham"][0]["title"] == "b.png"  # where it came from
    log = json.loads((root / "rename-log.json").read_text(encoding="utf-8"))
    # of the two identical pictures the first by name is kept, the other is set aside
    assert {e["from"] for e in log} == {"b.png", "c.webp", "copy of a.jpg"}
    assert (folder / "_skipped" / "IMG 1.JPG").is_file()
    provenance = json.loads((root / "PROVENANCE.json").read_text(encoding="utf-8"))
    assert provenance["schema_version"] == 1
    assert "NOT verified" in provenance["label_status"]

    # nothing to do the second time, and a new picture continues the numbering
    before = {n: (folder / n).read_bytes() for n in numbered}
    again = tool.number(root, apply=True)
    assert again["people"]["Jason Statham"]["to_rename"] == 0
    (folder / "new.jpg").write_bytes(picture(99))
    tool.number(root, apply=True)
    assert (folder / "004.jpg").is_file()
    assert {n: (folder / n).read_bytes() for n in numbered} == before  # earlier numbers never move


def test_a_picture_saved_for_two_people_is_kept_once(root: Path) -> None:
    (root / "Jason_Statham" / "x.jpg").write_bytes(picture(5))
    (root / "Zendaya" / "y.jpg").write_bytes(picture(5))
    tool.number(root, apply=True)
    assert (root / "Jason_Statham" / "001.jpg").is_file()
    assert not (root / "Zendaya" / "001.jpg").exists()
    assert (root / "Zendaya" / "_skipped" / "y.jpg").is_file()


def test_small_pictures_are_flagged_not_refused(root: Path) -> None:
    (root / "Zendaya" / "tiny.jpg").write_bytes(picture(7, size=(40, 40)))
    report = tool.number(root, apply=False)
    assert report["people"]["Zendaya"]["small"] == 1
    assert report["people"]["Zendaya"]["to_rename"] == 1


def test_it_refuses_a_folder_outside_the_datasets_folder(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        tool.main(["init", "--out", str(tmp_path / "elsewhere")])


def test_two_people_may_not_share_a_folder_name(root: Path) -> None:
    (root / "people.txt").write_text("Ann A\nAnn  A\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        tool.read_people(root)
