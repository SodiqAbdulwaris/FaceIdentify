"""The rules of the Commons portrait collector: titles, categories, licences, faces, duplicates."""

import argparse
import io
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

from evaluation import collect_commons_portraits as collector


@pytest.mark.parametrize(
    "title",
    [
        "File:Jason Statham Signature.jpg",
        "File:Zendaya dress at gala.jpg",
        "File:Album cover.jpg",
        "File:Statue of X.jpg",
        "File:Wax figure of Y.jpg",
        "File:Logo.svg",
        "Category:Zendaya by clothing wearing a dress",
    ],
)
def test_unusable_titles_are_rejected(title: str) -> None:
    assert collector.BAD.search(title)


@pytest.mark.parametrize(
    "title",
    [
        "File:Tom Hanks at the Silicon Valley summit 2019.jpg",
        "File:Vin Diesel Discovery Channel panel.jpg",
        "File:Kevin Hart addresses the crowd.jpg",
        "File:Jennifer Lopez at Shoemaker event.jpg",
        "File:Idris Elba - Iconic Awards.jpg",
        "File:Jason Statham 2013.jpg",
    ],
)
def test_words_that_merely_contain_a_bad_word_are_kept(title: str) -> None:
    assert collector.BAD.search(title) is None


def test_only_the_persons_own_category_forms_are_followed() -> None:
    follow = collector.follows
    assert follow("Jennifer Lawrence", "Category:Jennifer Lawrence by year")
    assert follow("Jennifer Lawrence", "Category:Jennifer Lawrence in 2013")
    assert follow("Jennifer Lawrence", "Category:Jennifer Lawrence at the Met Gala")
    assert follow("Chris Evans (actor)", "Category:Chris Evans in 2019")
    assert follow("Zendaya", "Category:Portraits of Zendaya")
    assert not follow("Zendaya", "Category:Tom Holland (actor) and Zendaya")
    assert not follow("Zendaya", "Category:Zendaya with Tom Holland in 2021")
    assert not follow("Zendaya", "Category:Zendaya by clothing")
    assert not follow("Zendaya", "Category:Signatures of Zendaya")
    assert not follow("Jennifer Lawrence", "Category:Katniss Everdeen")
    assert not follow("Jennifer Lawrence", "Category:Jennifer Lopez in 2013")


def test_the_crawl_reads_each_category_once_and_skips_pairs() -> None:
    tree = {
        "Category:Ann": [("subcat", "Category:Ann by year"), ("file", "File:a0.jpg")],
        "Category:Ann by year": [
            ("subcat", "Category:Ann in 2020"),
            ("subcat", "Category:Ann and Bob in 2020"),
        ],
        "Category:Ann in 2020": [
            ("file", "File:a1.jpg"),
            ("file", "File:Ann signature.jpg"),
            ("subcat", "Category:Ann by year"),  # a cycle
        ],
        "Category:Ann and Bob in 2020": [("file", "File:ab.jpg")],
    }
    asked: list[str] = []

    def reader(category: str, member_type: str, maximum: int) -> list[str]:
        asked.append(category)
        return [t for kind, t in tree.get(category, []) if kind == member_type][:maximum]

    files = collector.candidates("Ann", 3, 100, reader)
    assert files == ["File:a0.jpg", "File:a1.jpg"]  # no signature, nothing from the pair category
    assert "Category:Ann and Bob in 2020" not in asked
    assert asked.count("Category:Ann by year") <= 2  # (once as files, once as subcats)


def meta(name: str, url: str = "", copyrighted: str = "", non_free: str = "") -> dict[str, Any]:
    return {
        "LicenseShortName": {"value": name},
        "LicenseUrl": {"value": url},
        "Copyrighted": {"value": copyrighted},
        "NonFree": {"value": non_free},
    }


def test_licences() -> None:
    cc = "https://creativecommons.org/licenses/by-sa/4.0"
    pd = "https://creativecommons.org/publicdomain/zero/1.0/"
    assert collector.license_ok(meta("Public domain", copyrighted="False"), "pd")
    assert collector.license_ok(meta("CC0", pd), "pd")
    assert not collector.license_ok(meta("CC BY-SA 4.0", cc), "pd")
    assert collector.license_ok(meta("CC BY-SA 4.0", cc), "free")
    assert collector.license_ok(
        meta("CC BY 2.5", "https://creativecommons.org/licenses/by/2.5/"), "free"
    )
    assert not collector.license_ok(meta("CC BY-NC 2.0", cc), "free")
    assert not collector.license_ok(meta("CC BY-SA 4.0", ""), "free")  # no licence URL
    assert not collector.license_ok(meta("CC BY 2.0", cc, non_free="true"), "free")
    assert not collector.license_ok(meta("", cc), "free")


def face(x0: float, y0: float, x1: float, y1: float) -> dict[str, Any]:
    return {"box": [x0, y0, x1, y1], "score": 0.9}


def test_a_picture_needs_one_dominant_face_that_is_large_enough() -> None:
    big, small = face(0.2, 0.2, 0.6, 0.7), face(0.7, 0.1, 0.8, 0.2)
    assert collector.subject_ok([big], 800, 800, 75)
    assert collector.subject_ok([big, small], 800, 800, 75)  # the other face is much smaller
    assert not collector.subject_ok([], 800, 800, 75)
    assert not collector.subject_ok([big, face(0.65, 0.2, 0.95, 0.6)], 800, 800, 75)  # a second
    assert not collector.subject_ok([face(0.4, 0.4, 0.45, 0.45)], 800, 800, 75)  # 40 px


def test_names_and_folders() -> None:
    assert collector.parse_person("Chris Evans = Chris Evans (actor)") == (
        "Chris Evans",
        "Chris Evans (actor)",
    )
    assert collector.parse_person("Zendaya") == ("Zendaya", "Zendaya")
    assert collector.slug("Beyoncé") == "Beyonce"
    assert collector.slug("Zoe Saldaña") == "Zoe_Saldana"
    assert collector.slug("Michael B. Jordan") == "Michael_B_Jordan"


def noise(seed: int) -> bytes:
    rng = np.random.default_rng(seed)
    array = rng.integers(0, 255, (520, 520, 3), dtype=np.uint8)
    buffer = io.BytesIO()
    Image.fromarray(array).save(buffer, format="JPEG")
    return buffer.getvalue()


class FakeDetector:
    """One dominant face for every picture except the ones listed as having a crowd."""

    def __init__(self, crowded: set[int] | None = None) -> None:
        self.crowded = crowded or set()
        self.calls = 0

    def faces(self, pixels: np.ndarray) -> list[dict[str, Any]]:
        self.calls += 1
        if self.calls in self.crowded:
            return [face(0.1, 0.1, 0.5, 0.5), face(0.5, 0.1, 0.9, 0.5)]
        return [face(0.25, 0.2, 0.7, 0.8)]


def page(title: str, licence: str = "CC BY 2.0", mime: str = "image/jpeg") -> dict[str, Any]:
    return {
        "title": title,
        "imageinfo": [
            {
                "mime": mime, "thumburl": f"https://upload.example/{title}", "url": "u",
                "width": 1600, "height": 1200, "descriptionurl": f"https://commons/{title}",
                "extmetadata": meta(licence, "https://creativecommons.org/licenses/by/2.0/"),
            }
        ],
    }  # fmt: skip


def arguments(**over: Any) -> argparse.Namespace:
    values = {
        "per_person": 3, "licence": "free", "depth": 2, "max_candidates": 50,
        "min_dimension": 400, "min_face": 75, "hash_distance": 5, "dry_run": False,
    }  # fmt: skip
    return argparse.Namespace(**{**values, **over})


def test_collect_keeps_free_single_subject_pictures_once_and_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "set"
    out.mkdir()
    pictures = {f"File:p{i}.jpg": noise(i) for i in range(1, 6)}
    pictures["File:copy.jpg"] = pictures["File:p1.jpg"]  # the same picture under another title
    pages = [page(t) for t in pictures] + [
        page("File:nc.jpg", licence="CC BY-NC 2.0"),
        page("File:vector.png", mime="image/png"),
    ]
    monkeypatch.setattr(collector, "candidates", lambda *a, **k: [p["title"] for p in pages])
    monkeypatch.setattr(
        collector, "info_pages", lambda titles: [p for p in pages if p["title"] in titles]
    )
    monkeypatch.setattr(
        collector, "get_bytes", lambda url: pictures[url.removeprefix("https://upload.example/")]
    )
    manifest: dict[str, list[dict[str, Any]]] = {}
    hashes: list[int] = []

    first = collector.collect(
        "Ann Example", "Ann Example", arguments(), out, manifest, hashes, FakeDetector()
    )
    folder = out / "Ann_Example"
    assert sorted(p.name for p in folder.glob("*.jpg")) == ["001.jpg", "002.jpg", "003.jpg"]
    assert len(first) == 3
    assert all(r["licence_policy"] == "free" and r["identity_verified"] is False for r in first)
    assert len({r["title"] for r in first}) == 3
    saved = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert [r["file"] for r in saved["Ann Example"]] == [
        f"Ann_Example/{n:03d}.jpg" for n in (1, 2, 3)
    ]

    # a second run with a bigger target adds to it and never repeats or renames
    before = {p.name: p.read_bytes() for p in folder.glob("*.jpg")}
    again = collector.collect(
        "Ann Example", "Ann Example", arguments(per_person=5), out, manifest, hashes, FakeDetector()
    )
    assert len(again) == 5
    assert {n: (folder / n).read_bytes() for n in before} == before
    assert len({r["sha256"] for r in again}) == 5


def test_a_picture_already_saved_for_another_person_is_not_saved_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "set"
    out.mkdir()
    shared = noise(7)
    pages = [page("File:shared.jpg")]
    monkeypatch.setattr(collector, "candidates", lambda *a, **k: ["File:shared.jpg"])
    monkeypatch.setattr(collector, "info_pages", lambda titles: pages)
    monkeypatch.setattr(collector, "get_bytes", lambda url: shared)
    manifest: dict[str, list[dict[str, Any]]] = {}
    hashes: list[int] = []
    one = collector.collect("A One", "A One", arguments(), out, manifest, hashes, FakeDetector())
    two = collector.collect("B Two", "B Two", arguments(), out, manifest, hashes, FakeDetector())
    assert len(one) == 1
    assert two == []
    assert not list((out / "B_Two").glob("*.jpg"))


def test_a_dry_run_downloads_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = tmp_path / "set"
    out.mkdir()
    monkeypatch.setattr(collector, "candidates", lambda *a, **k: ["File:x.jpg"])
    monkeypatch.setattr(collector, "info_pages", lambda titles: [page("File:x.jpg")])

    def refuse(url: str) -> bytes:
        raise AssertionError("a dry run must not download a picture")

    monkeypatch.setattr(collector, "get_bytes", refuse)
    result = collector.collect("A One", "A One", arguments(dry_run=True), out, {}, [], None)
    assert result == []
    assert not (out / "manifest.json").exists()


def test_output_outside_the_datasets_folder_is_refused(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        collector.main(["--out", str(tmp_path / "elsewhere"), "--dry-run"])
