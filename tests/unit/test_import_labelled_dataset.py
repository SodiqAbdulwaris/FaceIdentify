"""The importer of ready-labelled datasets (LFW, CelebA) for the evaluation scripts."""

import json
from pathlib import Path

import pytest

from evaluation import import_labelled_dataset as importer


@pytest.fixture
def datasets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "datasets"
    root.mkdir()
    monkeypatch.setattr(importer, "DATASETS_ROOT", root.resolve())
    return root


def lfw_source(tmp_path: Path) -> Path:
    source = tmp_path / "lfw"
    for name, count in (("Ada_Lovelace", 6), ("Bob_Barker", 5), ("Cy_Young", 2)):
        (source / name).mkdir(parents=True)
        for index in range(count):
            (source / name / f"{name}_{index + 1:04}.jpg").write_bytes(f"{name} {index}".encode())
    return source


def test_lfw_people_come_from_the_folder_names_and_need_enough_distinct_pictures(
    tmp_path: Path,
) -> None:
    source = lfw_source(tmp_path)
    (source / "Ada_Lovelace" / "copy.jpg").write_bytes(b"Ada_Lovelace 0")  # same bytes as a picture

    people = importer.read_lfw(source)
    chosen = importer.select(people, minimum=5, count=10, maximum=4)

    assert set(people) == {"Ada Lovelace", "Bob Barker", "Cy Young"}
    assert set(chosen) == {"Ada Lovelace", "Bob Barker"}  # Cy Young has two
    assert all(len(files) == 4 for files in chosen.values())  # capped
    assert len({f.read_bytes() for files in chosen.values() for f in files}) == 8  # distinct


def test_celeba_identities_come_from_the_table(tmp_path: Path) -> None:
    source = tmp_path / "celeba"
    images = source / "img_align_celeba"
    images.mkdir(parents=True)
    lines = []
    for index in range(1, 7):
        (images / f"{index:06}.jpg").write_bytes(f"picture {index}".encode())
        lines.append(f"{index:06}.jpg {10 if index <= 5 else 11}")
    lines.append("000099.jpg 12")  # listed but not present
    (source / "identity_CelebA.txt").write_text("\n".join(lines), encoding="utf-8")

    people = importer.read_celeba(source)

    assert {n: len(f) for n, f in people.items()} == {"identity 10": 5, "identity 11": 1}


def test_the_selection_is_stable_and_the_output_is_a_manifest_with_provenance(
    tmp_path: Path, datasets: Path
) -> None:
    source = lfw_source(tmp_path)
    chosen = importer.select(importer.read_lfw(source), minimum=5, count=10, maximum=12)

    provenance = importer.write("lfw", chosen, datasets / "lfw")

    manifest = json.loads((datasets / "lfw" / "manifest.json").read_text(encoding="utf-8"))
    assert set(manifest) == {"Ada Lovelace", "Bob Barker"}
    entry = manifest["Ada Lovelace"][0]
    assert (datasets / "lfw" / entry["file"]).is_file()
    assert len(entry["sha256"]) == 64
    assert "not verified" in entry["licence"]
    assert provenance["photographs"] == 11
    saved = json.loads((datasets / "lfw" / "PROVENANCE.json").read_text(encoding="utf-8"))
    assert "NOT verified" in saved["label_status"]
    assert importer.select(importer.read_lfw(source), minimum=5, count=10, maximum=12) == chosen


def test_an_existing_output_is_never_overwritten_and_only_the_datasets_folder_is_allowed(
    tmp_path: Path, datasets: Path
) -> None:
    chosen = importer.select(importer.read_lfw(lfw_source(tmp_path)), minimum=5, count=5, maximum=5)
    importer.write("lfw", chosen, datasets / "lfw")

    with pytest.raises(SystemExit, match="not empty"):
        importer.write("lfw", chosen, datasets / "lfw")
    with pytest.raises(SystemExit, match="must be inside"):
        importer.write("lfw", chosen, tmp_path / "elsewhere")


def test_a_table_cannot_name_files_outside_the_source_or_odd_identities(tmp_path: Path) -> None:
    source = tmp_path / "celeba"
    images = source / "img_align_celeba"
    images.mkdir(parents=True)
    (images / "000001.jpg").write_bytes(b"one")
    secret = tmp_path / "private.jpg"
    secret.write_bytes(b"private")
    lines = [
        "000001.jpg 7",
        f"{secret} 7",  # an absolute path
        "../../private.jpg 7",  # leaves the source
        "000001.jpg 1/../../../../escaped",  # an identity that is not a number
        "000001.txt 7",  # not a picture
    ]
    (source / "identity_CelebA.txt").write_text("\n".join(lines), encoding="utf-8")

    people = importer.read_celeba(source)

    assert {n: [f.name for f in files] for n, files in people.items()} == {
        "identity 7": ["000001.jpg"]
    }


def test_a_link_leaving_the_source_is_not_followed(tmp_path: Path) -> None:
    source = tmp_path / "lfw"
    (source / "Ada_Lovelace").mkdir(parents=True)
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"outside")
    try:
        (source / "Ada_Lovelace" / "linked.jpg").symlink_to(outside)
    except OSError:
        pytest.skip("symbolic links are not allowed here")
    (source / "Ada_Lovelace" / "real.jpg").write_bytes(b"real")

    people = importer.read_lfw(source)

    assert [f.name for f in people["Ada Lovelace"]] == ["real.jpg"]


def test_a_shared_picture_is_reserved_only_by_the_person_who_keeps_it(tmp_path: Path) -> None:
    def pictures(name: str, contents: list[bytes]) -> list[Path]:
        folder = tmp_path / name
        folder.mkdir()
        files = []
        for index, data in enumerate(contents):
            path = folder / f"{index}.jpg"
            path.write_bytes(data)
            files.append(path)
        return files

    # "A" (first in hash order or not) fails the minimum; "B" holds the picture too and must keep it
    people = {
        "A": pictures("A", [b"shared"]),
        "B": pictures("B", [b"shared", b"b1", b"b2"]),
        "C": pictures("C", [b"c1", b"c2", b"c3", b"c4"]),
    }

    chosen = importer.select(people, minimum=2, count=10, maximum=3)

    assert {n: len(f) for n, f in chosen.items()} == {"B": 3, "C": 3}
    # a picture beyond a person's cap is not taken from the pool either
    again = importer.select(
        {"B": people["B"], "D": pictures("D", [b"b2", b"d1", b"d2"])},
        minimum=2,
        count=10,
        maximum=2,
    )
    assert {n: len(f) for n, f in again.items()} == {"B": 2, "D": 2}
    assert b"b2" in [f.read_bytes() for f in again["D"]]  # B was capped before reaching it


@pytest.mark.parametrize("options", [["--people", "0"], ["--minimum", "0"], ["--maximum", "-1"]])
def test_non_positive_limits_are_refused(tmp_path: Path, options: list[str]) -> None:
    source = lfw_source(tmp_path)

    with pytest.raises(SystemExit, match="at least 1"):
        importer.main(["lfw", "--source", str(source), *options])
