"""Regression tests for verified manifests in operating-point measurement."""

import hashlib
import json
from pathlib import Path

import pytest

from evaluation.measure_operating_point import cache_path, read_manifest


def test_verified_manifest_is_read_and_digest_is_checked(tmp_path: Path) -> None:
    image = tmp_path / "subject.jpg"
    image.write_bytes(b"reviewed photo")
    digest = hashlib.sha256(image.read_bytes()).hexdigest()
    export = tmp_path / "verified.json"
    payload = {
        "kind": "verified-manifest",
        "schema_version": 1,
        "people": {"Person": [{"file": "subject.jpg", "sha256": digest}]},
    }
    export.write_text(json.dumps(payload), encoding="utf-8")
    people, verified, manifest_hash, _, _ = read_manifest(tmp_path, export)
    assert verified
    assert people == payload["people"]
    assert manifest_hash == hashlib.sha256(export.read_bytes()).hexdigest()

    image.write_bytes(b"modified after review")
    with pytest.raises(SystemExit, match="changed after it was verified"):
        read_manifest(tmp_path, export)


def test_verified_manifest_rejects_missing_photo_and_missing_digest(tmp_path: Path) -> None:
    export = tmp_path / "verified.json"
    photo = {"file": "missing.jpg", "sha256": "a" * 64}
    payload = {"kind": "verified-manifest", "schema_version": 1, "people": {"Person": [photo]}}
    export.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SystemExit, match="missing"):
        read_manifest(tmp_path, export)
    del photo["sha256"]
    export.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SystemExit, match="no verified digest"):
        read_manifest(tmp_path, export)


def test_manifest_rejects_escape_and_invalid_verified_schema(tmp_path: Path) -> None:
    export = tmp_path / "verified.json"
    payload = {"kind": "verified-manifest", "schema_version": 2, "people": {}}
    export.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SystemExit, match="not schema 1"):
        read_manifest(tmp_path, export)
    payload["schema_version"] = 1
    payload["people"] = {"Person": [{"file": "../escape.jpg", "sha256": "a" * 64}]}
    export.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SystemExit, match="outside the dataset"):
        read_manifest(tmp_path, export)


def test_default_manifest_remains_supported(tmp_path: Path) -> None:
    (tmp_path / "photo.jpg").write_bytes(b"legacy")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"Person": [{"file": "photo.jpg"}]}), encoding="utf-8")
    people, verified, _, _, _ = read_manifest(tmp_path, manifest)
    assert not verified
    assert people["Person"][0]["file"] == "photo.jpg"


def test_byte_identical_copies_are_used_once(tmp_path: Path) -> None:
    (tmp_path / "a.jpg").write_bytes(b"same picture")
    (tmp_path / "b.jpg").write_bytes(b"same picture")
    (tmp_path / "c.jpg").write_bytes(b"another picture")
    manifest = tmp_path / "manifest.json"
    people = {"One": [{"file": "a.jpg"}, {"file": "c.jpg"}], "Two": [{"file": "b.jpg"}]}
    manifest.write_text(json.dumps(people), encoding="utf-8")
    kept, _, _, _, duplicates = read_manifest(tmp_path, manifest)
    assert duplicates == 1
    assert kept == {"One": [{"file": "a.jpg"}, {"file": "c.jpg"}], "Two": []}


def test_cache_key_follows_picture_bytes_and_selection(tmp_path: Path) -> None:
    (tmp_path / "a.jpg").write_bytes(b"first")
    (tmp_path / "b.jpg").write_bytes(b"second")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"P": [{"file": "a.jpg"}, {"file": "b.jpg"}]}), "utf-8")
    key = read_manifest(tmp_path, manifest)[3]
    assert read_manifest(tmp_path, manifest)[3] == key  # the same pictures reuse the cache

    (tmp_path / "a.jpg").write_bytes(b"edited")  # a legacy manifest has no digest to catch this
    edited = read_manifest(tmp_path, manifest)[3]
    manifest.write_text(json.dumps({"P": [{"file": "b.jpg"}]}), "utf-8")
    narrower = read_manifest(tmp_path, manifest)[3]
    assert len({key, edited, narrower}) == 3
    paths = {cache_path(tmp_path, "w" * 64, k) for k in (key, edited, narrower)}
    assert len(paths) == 3
