"""The rules of the Commons portrait collector: titles, categories, licences, faces, duplicates."""

import argparse
import io
import json
import time
import urllib.error
import urllib.request
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


def test_a_licence_name_and_url_that_disagree_are_refused() -> None:
    by = "https://creativecommons.org/licenses/by/2.0/"
    assert not collector.license_ok(
        meta("CC BY 2.0", "https://creativecommons.org/licenses/by-nc/2.0/"), "free"
    )
    assert not collector.license_ok(
        meta("CC BY 2.0", "https://creativecommons.org/licenses/by-nd/2.0/"), "free"
    )
    assert not collector.license_ok(meta("CC BY 2.0 NC", by), "free")
    assert not collector.license_ok(meta("CC BY-SA 2.0", by), "free")  # family differs
    assert not collector.license_ok(meta("CC BY 3.0", by), "free")  # version differs
    assert not collector.license_ok(
        meta("CC BY 2.0", "https://evil.example/licenses/by/2.0/"), "free"
    )
    assert not collector.license_ok(
        meta("CC BY 2.0", "https://example.org/creativecommons.org/licenses/by/2.0/"), "free"
    )
    assert collector.license_ok(
        meta("CC BY 2.0", "https://creativecommons.org/licenses/by/2.0"), "free"
    )
    assert collector.license_ok(
        meta("CC BY 3.0 de", "https://creativecommons.org/licenses/by/3.0/de/"), "free"
    )
    pd_bad = meta("CC0", "https://evil.example/publicdomain/zero/1.0/")
    assert not collector.license_ok(pd_bad, "pd")


def test_longer_names_and_pairs_are_not_followed() -> None:
    follow = collector.follows
    assert not follow("Chris Evans (actor)", "Category:Chris Evans (presenter) in 2019")
    assert not follow("Jennifer Lopez", "Category:Jennifer Lopez Smith in 2019")
    assert not follow(
        "Jennifer Lopez", "Category:Jennifer Lopez & Marc Anthony at the Grammy Awards"
    )
    assert not follow("Jennifer Lopez", "Category:Jennifer Lopez, Ben Affleck in 2022")
    assert follow("Jennifer Lopez", "Category:Jennifer Lopez at the Grammy Awards")
    assert not follow("Zendaya", "Category:Zendaya's family in 2019")


def test_an_empty_or_non_latin_name_is_refused(tmp_path: Path) -> None:
    listing = tmp_path / "people.txt"
    listing.write_text("张伟\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        collector.read_people(listing)
    listing.write_text("Ann = \n", encoding="utf-8")  # the category defaults to the name: fine
    assert collector.read_people(listing) == [("Ann", "Ann")]


def test_a_picture_is_published_into_a_free_name_and_never_replaces(tmp_path: Path) -> None:
    folder = tmp_path / "Ann"
    folder.mkdir()
    (folder / "001.jpg").write_bytes(b"first")
    (folder / "002.JPG").write_bytes(b"second, upper case")
    name = collector.publish_picture(folder, b"third")
    assert name == "003.jpg"
    assert (folder / "001.jpg").read_bytes() == b"first"
    assert (folder / "002.JPG").read_bytes() == b"second, upper case"
    assert not [p for p in folder.iterdir() if p.name.endswith(".tmp")]


def test_an_interrupted_run_is_recovered_from_the_journal(tmp_path: Path) -> None:
    out = tmp_path / "set"
    (out / "Ann").mkdir(parents=True)
    data = b"picture bytes"
    (out / "Ann" / "001.jpg").write_bytes(data)
    import hashlib

    record = {
        "file": "Ann/001.jpg", "person": "Ann", "title": "File:a.jpg",
        "sha256": hashlib.sha256(data).hexdigest(),
    }  # fmt: skip
    ghost = {"file": "Ann/002.jpg", "person": "Ann", "title": "File:b.jpg", "sha256": "0" * 64}
    with (out / collector.JOURNAL).open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")
        handle.write(json.dumps(ghost) + "\n")  # journalled, but the picture never arrived
        handle.write('{"file": "Ann/003.jpg", "per')  # a torn last line
    manifest: dict[str, list[dict[str, Any]]] = {}
    assert collector.recover(out, manifest) == 1
    assert [r["title"] for r in manifest["Ann"]] == ["File:a.jpg"]
    assert collector.recover(out, manifest) == 0  # idempotent


def test_a_set_made_with_free_licences_is_not_resumed_as_public_domain() -> None:
    manifest = {"Ann": [{"licence_policy": "free"}]}
    assert collector.policy_conflict(manifest, "pd") is not None
    assert collector.policy_conflict(manifest, "free") is None
    assert collector.policy_conflict({}, "pd") is None


def test_two_runs_on_one_folder_are_refused_and_the_lock_is_released(tmp_path: Path) -> None:
    with collector.single_run(tmp_path):
        with pytest.raises(SystemExit):
            with collector.single_run(tmp_path):
                pass
    with collector.single_run(tmp_path):  # free again
        pass
    assert not (tmp_path / collector.LOCK).exists()


def test_a_linked_person_folder_is_not_written_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "set"
    out.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (out / "Ann_One").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks need a privilege this machine does not give")
    monkeypatch.setattr(collector, "candidates", lambda *a, **k: ["File:x.jpg"])
    monkeypatch.setattr(collector, "info_pages", lambda titles: [page("File:x.jpg")])
    monkeypatch.setattr(collector, "get_bytes", lambda url: noise(3))
    with pytest.raises(SystemExit):
        collector.collect("Ann One", "Ann One", arguments(), out, {}, [], FakeDetector())
    assert list(outside.iterdir()) == []


def test_rejections_are_counted_for_the_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from collections import Counter

    out = tmp_path / "set"
    out.mkdir()
    pages = [
        page("File:ok.jpg"),
        page("File:nc.jpg", licence="CC BY-NC 2.0"),
        page("File:v.png", mime="image/png"),
    ]
    monkeypatch.setattr(collector, "candidates", lambda *a, **k: [p["title"] for p in pages])
    monkeypatch.setattr(collector, "info_pages", lambda titles: pages)
    monkeypatch.setattr(collector, "get_bytes", lambda url: noise(9))
    stats: Counter[str] = Counter()
    collector.collect("A One", "A One", arguments(), out, {}, [], FakeDetector(crowded={1}), stats)
    assert stats["rejected_licence"] == 1
    assert stats["rejected_not_jpeg"] == 1
    assert stats["rejected_no_dominant_face"] == 1


def test_a_dropped_connection_is_retried_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def read(self) -> bytes:
            return b"ok"

    def flaky(request: object, timeout: int) -> Response:
        calls["n"] += 1
        if calls["n"] < 3:
            raise urllib.error.URLError("[WinError 10013] forbidden")
        return Response()

    monkeypatch.setattr(urllib.request, "urlopen", flaky)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    assert collector.get_bytes("https://commons.example/x") == b"ok"
    assert calls["n"] == 3


def test_a_connection_that_never_comes_back_raises_after_the_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def down(request: object, timeout: int) -> None:
        raise urllib.error.URLError("down")

    monkeypatch.setattr(urllib.request, "urlopen", down)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    with pytest.raises(urllib.error.URLError):
        collector.get_bytes("https://commons.example/x", retries=3)
