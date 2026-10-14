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


def every_file(folder: Path) -> list[bytes]:
    return [f.read_bytes() for f in folder.rglob("*") if f.is_file()]


def test_init_makes_a_folder_per_person_a_listing_and_instructions(root: Path) -> None:
    assert (root / "Jason_Statham").is_dir()
    assert (root / "Jennifer_Lopez").is_dir()
    assert "Jenna Ortega" in (root / "people.txt").read_text(encoding="utf-8")
    assert (root / "HOW_TO.txt").is_file()
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
    assert (plan["to_rename"], plan["to_skip"]) == (3, 4)
    assert not (root / "manifest.json").exists()

    tool.number(root, apply=True)
    numbered = sorted(p.name for p in folder.glob("[0-9][0-9][0-9].jpg"))
    assert numbered == ["001.jpg", "002.jpg", "003.jpg"]
    for name in numbered:
        with Image.open(folder / name) as opened:
            assert opened.format == "JPEG"
    # nothing was deleted: the originals are in _originals/, the rejects in _skipped/
    assert sorted(p.name for p in (folder / "_originals").iterdir()) == [
        "b.png", "c.webp", "copy of a.jpg",
    ]  # fmt: skip
    assert (folder / "_skipped" / "IMG 1.JPG").is_file()
    assert (folder / "_skipped" / "broken.jpg").is_file()
    assert (folder / "_skipped" / "photo.avif").is_file()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert [e["file"] for e in manifest["Jason Statham"]] == [
        f"Jason_Statham/{n}" for n in numbered
    ]
    assert manifest["Jason Statham"][0]["title"] == "b.png"
    log = [json.loads(ln) for ln in (root / "rename-log.jsonl").read_text("utf-8").splitlines()]
    assert {e["from"] for e in log} == {"b.png", "c.webp", "copy of a.jpg"}
    provenance = json.loads((root / "PROVENANCE.json").read_text(encoding="utf-8"))
    assert provenance["schema_version"] == 1
    assert "NOT verified" in provenance["label_status"]

    before = {n: (folder / n).read_bytes() for n in numbered}
    assert tool.number(root, apply=True)["people"]["Jason Statham"]["to_rename"] == 0
    (folder / "new.jpg").write_bytes(picture(99))
    tool.number(root, apply=True)
    assert (folder / "004.jpg").is_file()
    assert {n: (folder / n).read_bytes() for n in numbered} == before  # earlier numbers never move


def test_an_uppercase_numbered_name_is_numbered_and_is_never_deleted(root: Path) -> None:
    """Windows treats 001.JPG and 001.jpg as one file: that must not delete the only copy."""
    folder = root / "Zendaya"
    data = picture(42)
    (folder / "001.JPG").write_bytes(data)
    tool.number(root, apply=True)
    assert [f.read_bytes() for f in folder.iterdir() if f.is_file()].count(data) == 1
    (folder / "new.jpg").write_bytes(picture(43))
    tool.number(root, apply=True)
    assert data in every_file(folder)
    assert len([f for f in folder.iterdir() if f.is_file() and f.name[0].isdigit()]) == 2


def test_two_originals_with_the_same_name_in_separate_runs_are_both_kept(root: Path) -> None:
    folder = root / "Zendaya"
    (folder / "photo.png").write_bytes(picture(1, "PNG"))
    tool.number(root, apply=True)
    (folder / "photo.png").write_bytes(picture(2, "PNG"))  # a different picture, the same name
    tool.number(root, apply=True)
    kept = sorted(p.name for p in (folder / "_originals").iterdir())
    assert kept == ["photo-2.png", "photo.png"]
    assert (folder / "001.jpg").is_file()
    assert (folder / "002.jpg").is_file()


def test_a_crash_after_numbering_does_not_double_a_picture(root: Path) -> None:
    folder = root / "Zendaya"
    data = picture(5)
    (folder / "001.jpg").write_bytes(data)  # as if numbered, then the move of the original failed
    (folder / "original.jpg").write_bytes(data)
    tool.number(root, apply=True)
    assert [f.name for f in folder.glob("[0-9]*.jpg")] == ["001.jpg"]
    assert (folder / "_skipped" / "original.jpg").read_bytes() == data


def test_a_damaged_numbered_file_stops_the_run_untouched(root: Path) -> None:
    folder = root / "Zendaya"
    (folder / "007.jpg").write_bytes(b"damaged")
    (folder / "new.jpg").write_bytes(picture(8))
    with pytest.raises(SystemExit) as stopped:
        tool.number(root, apply=True)
    assert "007.jpg" in str(stopped.value)
    assert (folder / "new.jpg").is_file()
    assert not (root / "manifest.json").exists()


def test_a_picture_saved_for_two_people_is_kept_once_in_either_order(root: Path) -> None:
    (root / "Jason_Statham" / "x.jpg").write_bytes(picture(5))
    (root / "Zendaya" / "y.jpg").write_bytes(picture(5))
    tool.number(root, apply=True)
    assert (root / "Jason_Statham" / "001.jpg").is_file()
    assert not (root / "Zendaya" / "001.jpg").exists()
    assert (root / "Zendaya" / "_skipped" / "y.jpg").is_file()


def test_a_new_picture_already_numbered_under_a_later_person_is_not_numbered_again(
    root: Path,
) -> None:
    (root / "Zendaya" / "001.jpg").write_bytes(picture(9))  # Zendaya is listed after Jason Statham
    (root / "Jason_Statham" / "copy.jpg").write_bytes(picture(9))
    tool.number(root, apply=True)
    assert not (root / "Jason_Statham" / "001.jpg").exists()
    assert (root / "Jason_Statham" / "_skipped" / "copy.jpg").is_file()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert list(manifest) == ["Zendaya"]


def test_small_pictures_are_flagged_not_refused(root: Path) -> None:
    (root / "Zendaya" / "tiny.jpg").write_bytes(picture(7, size=(40, 40)))
    report = tool.number(root, apply=False)
    assert report["people"]["Zendaya"]["small"] == 1
    assert report["people"]["Zendaya"]["to_rename"] == 1


def test_it_refuses_a_folder_outside_the_datasets_folder(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        tool.main(["init", "--out", str(tmp_path / "elsewhere")])


def test_two_people_may_not_share_a_folder_name_even_by_case(root: Path) -> None:
    (root / "people.txt").write_text("Ann A\nAnn  A\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        tool.read_people(root)
    (root / "people.txt").write_text("Alice\nalice\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        tool.read_people(root)


def test_a_linked_person_folder_is_not_followed(root: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x.jpg").write_bytes(picture(3))
    (root / "Zendaya").rmdir()
    try:
        (root / "Zendaya").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks need a privilege this machine does not give")
    with pytest.raises(SystemExit):
        tool.number(root, apply=True)
    assert (outside / "x.jpg").is_file()  # untouched


def test_a_linked_metadata_file_is_not_followed(root: Path, tmp_path: Path) -> None:
    target = tmp_path / "elsewhere.json"
    try:
        (root / "manifest.json").symlink_to(target)
    except OSError:
        pytest.skip("symlinks need a privilege this machine does not give")
    with pytest.raises(SystemExit):
        tool.number(root, apply=True)
    assert not target.exists()
