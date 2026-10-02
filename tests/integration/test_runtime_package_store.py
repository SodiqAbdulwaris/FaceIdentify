"""Installing runtime packages: stage, verify while copying, publish atomically, recover.

A crash is simulated by an exception that is not an `Exception` raised at a named step (the way a
killed process runs no cleanup), then a fresh store recovers from what is on disk.
"""

import hashlib
import os
import shutil
import uuid
from pathlib import Path

import pytest

from backend.app import runtime
from backend.app.runtime import package_store
from backend.app.runtime.package_store import (
    MANIFEST_FILE,
    MARKER_FILE,
    IncompatiblePackageError,
    InvalidPackageError,
    PackageExistsError,
    PackageInstallError,
    RuntimePackageStore,
)
from backend.infrastructure.storage.layout import StorageRoots
from tests.fixtures.deterministic import SeededUUIDs
from tests.fixtures.runtime_packages import DETECTOR, EMBEDDER, FACTS, build_package

assert runtime  # (the package itself)


class Crash(BaseException):
    """The process died here. Not an Exception, so no cleanup code runs, like a real kill."""


def store_for(
    roots: StorageRoots, new_id: SeededUUIDs, *, crash_at: str | None = None
) -> RuntimePackageStore:
    def checkpoint(step: str) -> None:
        if step == crash_at:
            raise Crash(step)

    return RuntimePackageStore(roots, new_id=new_id, checkpoint=checkpoint)


@pytest.fixture
def source(tmp_path: Path) -> Path:
    return build_package(tmp_path / "source")


def staging_names(roots: StorageRoots) -> list[str]:
    return sorted(p.name for p in roots.installation.iterdir())


# --- installing -------------------------------------------------------------------------------


def test_a_package_is_installed_complete_and_nothing_is_left_staged(
    storage_roots: StorageRoots, new_id: SeededUUIDs, source: Path
) -> None:
    store = store_for(storage_roots, new_id)

    package = store.install(source, FACTS)

    assert package.key == "reference-cpu"
    assert package.path == storage_roots.runtime_packages / "reference-cpu"
    assert (package.path / "models" / "detector.onnx").read_bytes() == DETECTOR
    assert (package.path / "models" / "embedder.onnx").read_bytes() == EMBEDDER
    assert (package.path / MANIFEST_FILE).read_bytes() == (source / MANIFEST_FILE).read_bytes()
    assert (package.path / MARKER_FILE).read_text() == hashlib.sha256(
        (source / MANIFEST_FILE).read_bytes()
    ).hexdigest()
    assert store.installed() == [package]
    assert store.get("reference-cpu") == package
    assert store.verify("reference-cpu") == []
    assert staging_names(storage_roots) == []


def test_installing_the_same_package_again_changes_nothing(
    storage_roots: StorageRoots, new_id: SeededUUIDs, source: Path
) -> None:
    store = store_for(storage_roots, new_id)
    first = store.install(source, FACTS)
    marker = (first.path / MARKER_FILE).stat().st_mtime_ns

    second = store.install(source, FACTS)

    assert second == first
    assert (first.path / MARKER_FILE).stat().st_mtime_ns == marker
    assert staging_names(storage_roots) == []


def test_installing_what_is_already_installed_does_not_even_stage_it(
    storage_roots: StorageRoots, new_id: SeededUUIDs, source: Path
) -> None:
    steps: list[str] = []
    store = RuntimePackageStore(storage_roots, new_id=new_id, checkpoint=steps.append)
    store.install(source, FACTS)
    steps.clear()

    store.install(source, FACTS)

    assert steps == []


def test_a_cleanup_that_fails_does_not_hide_why_the_install_failed(
    storage_roots: StorageRoots, new_id: SeededUUIDs, source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(package_store, "file_problems", lambda root, manifest: [])
    (source / "models/embedder.onnx").write_bytes(b"X" * len(EMBEDDER))

    def locked(path: object, *args: object, **kwargs: object) -> None:
        if not kwargs.get("ignore_errors"):
            raise PermissionError("in use")

    monkeypatch.setattr(shutil, "rmtree", locked)

    with pytest.raises(InvalidPackageError, match="changed while"):
        store_for(storage_roots, new_id).install(source, FACTS)


def test_installing_replaces_a_published_directory_that_is_not_complete(
    storage_roots: StorageRoots, new_id: SeededUUIDs, source: Path
) -> None:
    store = store_for(storage_roots, new_id)
    package = store.install(source, FACTS)
    (package.path / MARKER_FILE).unlink()
    (package.path / "leftover.txt").write_text("from the damaged install")

    healed = store.install(source, FACTS)

    assert store.installed() == [healed]
    assert store.verify("reference-cpu") == []
    assert not (healed.path / "leftover.txt").exists()
    assert store.recover().invalid == []


def test_an_incomplete_directory_that_cannot_be_removed_stops_the_install_with_a_clear_error(
    storage_roots: StorageRoots, new_id: SeededUUIDs, source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = store_for(storage_roots, new_id)
    package = store.install(source, FACTS)
    (package.path / MARKER_FILE).unlink()

    def locked(path: object, *args: object, **kwargs: object) -> None:
        raise PermissionError("in use")

    monkeypatch.setattr(shutil, "rmtree", locked)

    with pytest.raises(PackageInstallError, match="cannot be removed"):
        store.install(source, FACTS)


def test_a_different_package_under_an_installed_key_is_refused_and_the_original_kept(
    storage_roots: StorageRoots, new_id: SeededUUIDs, source: Path, tmp_path: Path
) -> None:
    store = store_for(storage_roots, new_id)
    store.install(source, FACTS)
    other = build_package(tmp_path / "other", detector=b"different weights")

    with pytest.raises(PackageExistsError):
        store.install(other, FACTS)

    assert (storage_roots.runtime_packages / "reference-cpu/models/detector.onnx").read_bytes() == (
        DETECTOR
    )
    assert store.verify("reference-cpu") == []
    assert staging_names(storage_roots) == []


def test_a_package_for_another_machine_is_refused_before_anything_is_written(
    storage_roots: StorageRoots, new_id: SeededUUIDs, source: Path
) -> None:
    store = store_for(storage_roots, new_id)

    with pytest.raises(IncompatiblePackageError, match="os is 'linux'"):
        store.install(source, {"os": "linux", "architecture": "amd64"})

    assert store.installed() == []
    assert staging_names(storage_roots) == []


@pytest.mark.parametrize("damage", ["no-manifest", "bad-manifest", "missing-file", "bad-hash"])
def test_a_package_that_is_not_what_it_says_is_refused_before_anything_is_written(
    storage_roots: StorageRoots, new_id: SeededUUIDs, source: Path, damage: str
) -> None:
    if damage == "no-manifest":
        (source / MANIFEST_FILE).unlink()
    elif damage == "bad-manifest":
        (source / MANIFEST_FILE).write_text("{not json")
    elif damage == "missing-file":
        (source / "models/embedder.onnx").unlink()
    else:
        (source / "models/embedder.onnx").write_bytes(b"X" * len(EMBEDDER))
    store = store_for(storage_roots, new_id)

    with pytest.raises(InvalidPackageError):
        store.install(source, FACTS)

    assert store.installed() == []
    assert staging_names(storage_roots) == []


def test_what_is_installed_is_what_was_verified_while_copying(
    storage_roots: StorageRoots, new_id: SeededUUIDs, source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The source checked out when first looked at, then changed before it was copied.
    monkeypatch.setattr(package_store, "file_problems", lambda root, manifest: [])
    (source / "models/embedder.onnx").write_bytes(b"X" * len(EMBEDDER))
    store = store_for(storage_roots, new_id)

    with pytest.raises(InvalidPackageError, match="changed while it was being installed"):
        store.install(source, FACTS)

    assert store.installed() == []
    assert staging_names(storage_roots) == []


def test_a_file_of_the_wrong_size_is_caught_while_copying_too(
    storage_roots: StorageRoots, new_id: SeededUUIDs, source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(package_store, "file_problems", lambda root, manifest: [])
    (source / "models/embedder.onnx").write_bytes(EMBEDDER + b"!")

    with pytest.raises(InvalidPackageError, match="changed while"):
        store_for(storage_roots, new_id).install(source, FACTS)


def test_a_failure_to_publish_removes_the_staging_directory(
    storage_roots: StorageRoots, new_id: SeededUUIDs, source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(src: object, dst: object) -> None:
        raise PermissionError("denied")

    monkeypatch.setattr(os, "rename", refuse)

    with pytest.raises(PackageInstallError, match="denied"):
        store_for(storage_roots, new_id).install(source, FACTS)

    assert staging_names(storage_roots) == []
    assert not (storage_roots.runtime_packages / "reference-cpu").exists()


def test_two_installers_racing_for_one_key_leave_one_complete_package(
    storage_roots: StorageRoots, new_id: SeededUUIDs, source: Path
) -> None:
    rival = store_for(storage_roots, new_id)
    published: list[object] = []

    def checkpoint(step: str) -> None:
        if step == "marked" and not published:
            published.append(rival.install(source, FACTS))  # the other one wins first

    loser = RuntimePackageStore(storage_roots, new_id=new_id, checkpoint=checkpoint)

    package = loser.install(source, FACTS)

    assert published == [package]
    assert staging_names(storage_roots) == []
    assert loser.verify("reference-cpu") == []


def test_the_loser_of_a_race_over_a_different_package_is_refused(
    storage_roots: StorageRoots, new_id: SeededUUIDs, source: Path, tmp_path: Path
) -> None:
    rival = store_for(storage_roots, new_id)
    other = build_package(tmp_path / "other", detector=b"different weights")

    def checkpoint(step: str) -> None:
        if step == "marked":
            rival.install(other, FACTS)

    loser = RuntimePackageStore(storage_roots, new_id=new_id, checkpoint=checkpoint)

    with pytest.raises(PackageExistsError):
        loser.install(source, FACTS)

    assert staging_names(storage_roots) == []


def test_a_rival_that_leaves_an_incomplete_directory_in_the_way_is_not_taken_for_a_package(
    storage_roots: StorageRoots, new_id: SeededUUIDs, source: Path
) -> None:
    def checkpoint(step: str) -> None:
        if step == "marked":
            (storage_roots.runtime_packages / "reference-cpu").mkdir()

    loser = RuntimePackageStore(storage_roots, new_id=new_id, checkpoint=checkpoint)

    with pytest.raises(PackageExistsError):
        loser.install(source, FACTS)

    assert staging_names(storage_roots) == []


def test_an_installed_package_that_is_damaged_afterwards_is_found_by_verify(
    storage_roots: StorageRoots, new_id: SeededUUIDs, source: Path
) -> None:
    store = store_for(storage_roots, new_id)
    package = store.install(source, FACTS)
    (package.path / "models/detector.onnx").write_bytes(b"X" * len(DETECTOR))

    assert store.verify("reference-cpu") == [
        "models/detector.onnx: hash does not match the manifest"
    ]


def test_get_finds_the_package_with_that_key_among_several(
    storage_roots: StorageRoots, new_id: SeededUUIDs, source: Path, tmp_path: Path
) -> None:
    store = store_for(storage_roots, new_id)
    first = store.install(source, FACTS)
    second = store.install(build_package(tmp_path / "second", "second-cpu"), FACTS)

    assert store.get("second-cpu") == second
    assert store.get("reference-cpu") == first
    assert [p.key for p in store.installed()] == ["reference-cpu", "second-cpu"]


def test_an_unknown_or_unsafe_key_is_not_installed(
    storage_roots: StorageRoots, new_id: SeededUUIDs
) -> None:
    store = store_for(storage_roots, new_id)

    assert store.get("nothing") is None
    assert store.get("../escape") is None
    assert store.verify("nothing") == ["nothing: not installed"]
    assert store.installed() == []


# --- a crash at every step --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("step", "installed_after_recovery"),
    [("staged", False), ("copied", False), ("marked", True), ("published", True)],
)
def test_a_crash_at_any_step_recovers_to_absent_or_complete(
    storage_roots: StorageRoots,
    new_id: SeededUUIDs,
    source: Path,
    step: str,
    installed_after_recovery: bool,
) -> None:
    with pytest.raises(Crash):
        store_for(storage_roots, new_id, crash_at=step).install(source, FACTS)

    restarted = store_for(storage_roots, new_id)
    if step not in ("marked", "published"):
        assert restarted.installed() == []  # before the marker: never discoverable
    report = restarted.recover()

    assert [p.key for p in restarted.installed()] == (
        ["reference-cpu"] if installed_after_recovery else []
    )
    assert restarted.verify("reference-cpu") == (
        [] if installed_after_recovery else ["reference-cpu: not installed"]
    )
    assert staging_names(storage_roots) == []
    assert report.published == (["reference-cpu"] if step == "marked" else [])
    assert len(report.removed) == (1 if step in ("staged", "copied") else 0)
    assert report.invalid == []
    assert report.left == []
    assert restarted.recover() == type(report)()  # a second recovery has nothing to do


def test_after_a_crash_before_the_marker_the_package_can_be_installed_again(
    storage_roots: StorageRoots, new_id: SeededUUIDs, source: Path
) -> None:
    with pytest.raises(Crash):
        store_for(storage_roots, new_id, crash_at="copied").install(source, FACTS)
    restarted = store_for(storage_roots, new_id)

    package = restarted.install(source, FACTS)  # without recovering first

    assert restarted.installed() == [package]
    restarted.recover()  # and recovery then clears the abandoned staging
    assert staging_names(storage_roots) == []
    assert restarted.verify("reference-cpu") == []


# --- recovery ---------------------------------------------------------------------------------


def test_recovery_on_an_empty_installation_does_nothing(
    storage_roots: StorageRoots, new_id: SeededUUIDs
) -> None:
    report = store_for(storage_roots, new_id).recover()

    assert (report.published, report.removed, report.left, report.invalid) == ([], [], [], [])


def test_recovery_survives_the_directories_not_existing_at_all(
    storage_roots: StorageRoots, new_id: SeededUUIDs
) -> None:
    shutil.rmtree(storage_roots.installation)
    shutil.rmtree(storage_roots.local_state_root / "runtime")
    store = store_for(storage_roots, new_id)

    assert store.recover().removed == []
    assert store.installed() == []


def test_a_staging_directory_with_a_corrupt_marker_is_removed_not_published(
    storage_roots: StorageRoots, new_id: SeededUUIDs, source: Path
) -> None:
    with pytest.raises(Crash):
        store_for(storage_roots, new_id, crash_at="marked").install(source, FACTS)
    (next(storage_roots.installation.iterdir()) / MARKER_FILE).write_text("not the hash")
    store = store_for(storage_roots, new_id)

    report = store.recover()

    assert store.installed() == []
    assert len(report.removed) == 1
    assert report.published == []


def test_a_staging_directory_whose_manifest_was_changed_after_marking_is_removed(
    storage_roots: StorageRoots, new_id: SeededUUIDs, source: Path
) -> None:
    with pytest.raises(Crash):
        store_for(storage_roots, new_id, crash_at="marked").install(source, FACTS)
    (next(storage_roots.installation.iterdir()) / MANIFEST_FILE).write_text("{}")

    report = store_for(storage_roots, new_id).recover()

    assert len(report.removed) == 1
    assert report.published == []


def test_a_staging_directory_whose_manifest_is_unreadable_is_removed(
    storage_roots: StorageRoots, new_id: SeededUUIDs, source: Path
) -> None:
    with pytest.raises(Crash):
        store_for(storage_roots, new_id, crash_at="marked").install(source, FACTS)
    stage = next(storage_roots.installation.iterdir())
    bad = b"{not json"
    (stage / MANIFEST_FILE).write_bytes(bad)
    (stage / MARKER_FILE).write_text(hashlib.sha256(bad).hexdigest())  # marked, but not a manifest

    report = store_for(storage_roots, new_id).recover()

    assert len(report.removed) == 1
    assert report.published == []


def test_a_complete_staging_directory_for_a_key_already_installed_is_dropped(
    storage_roots: StorageRoots, new_id: SeededUUIDs, source: Path
) -> None:
    with pytest.raises(Crash):
        store_for(storage_roots, new_id, crash_at="marked").install(source, FACTS)
    # Meanwhile the same package got installed by another route.
    stage = next(storage_roots.installation.iterdir())
    shutil.copytree(stage, storage_roots.runtime_packages / "reference-cpu")
    store = store_for(storage_roots, new_id)

    report = store.recover()

    assert report.published == []
    assert len(report.removed) == 1
    assert [p.key for p in store.installed()] == ["reference-cpu"]


def test_recovery_publishes_a_complete_staged_package_over_an_incomplete_published_one(
    storage_roots: StorageRoots, new_id: SeededUUIDs, source: Path
) -> None:
    store = store_for(storage_roots, new_id)
    package = store.install(source, FACTS)
    (package.path / MARKER_FILE).unlink()  # damaged
    with pytest.raises(Crash):
        store_for(storage_roots, new_id, crash_at="marked").install(source, FACTS)
    # (that install replaced the damaged directory before it was killed; damage it again)
    assert not (storage_roots.runtime_packages / "reference-cpu").exists()
    damaged = storage_roots.runtime_packages / "reference-cpu"
    damaged.mkdir()
    (damaged / "partial.bin").write_bytes(b"half")

    report = store_for(storage_roots, new_id).recover()

    assert report.published == ["reference-cpu"]
    assert report.invalid == []
    assert store.verify("reference-cpu") == []


def test_a_staging_entry_that_is_not_named_key_dot_token_is_left_alone(
    storage_roots: StorageRoots, new_id: SeededUUIDs
) -> None:
    (storage_roots.installation / "nodot").mkdir()

    report = store_for(storage_roots, new_id).recover()

    assert report.left == [("nodot", "not a staging directory of ours")]
    assert (storage_roots.installation / "nodot").is_dir()
    assert report.removed == []


def test_a_checkpoint_that_fails_with_an_ordinary_error_cleans_up_after_itself(
    storage_roots: StorageRoots, new_id: SeededUUIDs, source: Path
) -> None:
    def checkpoint(step: str) -> None:
        if step == "staged":
            raise RuntimeError("boom")

    store = RuntimePackageStore(storage_roots, new_id=new_id, checkpoint=checkpoint)

    with pytest.raises(RuntimeError, match="boom"):
        store.install(source, FACTS)

    assert staging_names(storage_roots) == []


def test_a_staging_directory_for_the_wrong_key_is_removed(
    storage_roots: StorageRoots, new_id: SeededUUIDs, source: Path
) -> None:
    with pytest.raises(Crash):
        store_for(storage_roots, new_id, crash_at="marked").install(source, FACTS)
    stage = next(storage_roots.installation.iterdir())
    stage.rename(storage_roots.installation / f"other-key.{uuid.uuid4().hex}")

    report = store_for(storage_roots, new_id).recover()

    assert report.published == []
    assert len(report.removed) == 1
    assert not (storage_roots.runtime_packages / "other-key").exists()


def test_something_that_is_not_a_directory_in_staging_is_reported_and_not_deleted(
    storage_roots: StorageRoots, new_id: SeededUUIDs
) -> None:
    stray = storage_roots.installation / "notes.txt"
    stray.write_text("not ours")

    report = store_for(storage_roots, new_id).recover()

    assert [name for name, _why in report.left] == ["notes.txt"]
    assert stray.exists()


def test_a_directory_that_cannot_be_removed_is_left_and_the_rest_are_still_settled(
    storage_roots: StorageRoots, new_id: SeededUUIDs, monkeypatch: pytest.MonkeyPatch
) -> None:
    (storage_roots.installation / f"a-key.{'0' * 32}").mkdir()
    (storage_roots.installation / f"b-key.{'1' * 32}").mkdir()
    real = shutil.rmtree

    def locked(path: Path, *args: object, **kwargs: object) -> None:
        if "a-key" in str(path):
            raise PermissionError("in use")
        real(path)

    monkeypatch.setattr(shutil, "rmtree", locked)

    report = store_for(storage_roots, new_id).recover()

    assert report.left == [(f"a-key.{'0' * 32}", "PermissionError: in use")]
    assert report.removed == [f"b-key.{'1' * 32}"]


def test_a_complete_staging_directory_that_cannot_be_published_is_left(
    storage_roots: StorageRoots, new_id: SeededUUIDs, source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(Crash):
        store_for(storage_roots, new_id, crash_at="marked").install(source, FACTS)

    def refuse(src: object, dst: object) -> None:
        raise PermissionError("denied")

    monkeypatch.setattr(os, "rename", refuse)

    report = store_for(storage_roots, new_id).recover()

    assert [name for name, _why in report.left] == [next(storage_roots.installation.iterdir()).name]
    assert "denied" in report.left[0][1]
    assert report.published == []


def test_a_published_directory_that_is_not_complete_is_reported_and_never_listed(
    storage_roots: StorageRoots, new_id: SeededUUIDs, source: Path
) -> None:
    store = store_for(storage_roots, new_id)
    package = store.install(source, FACTS)
    (package.path / MARKER_FILE).unlink()  # someone tampered with it

    report = store.recover()

    assert report.invalid == ["reference-cpu"]
    assert store.installed() == []
    assert package.path.exists()  # reported, never deleted


def test_a_published_directory_under_the_wrong_name_is_reported_and_never_listed(
    storage_roots: StorageRoots, new_id: SeededUUIDs, source: Path
) -> None:
    store = store_for(storage_roots, new_id)
    package = store.install(source, FACTS)
    package.path.rename(storage_roots.runtime_packages / "renamed")

    assert store.installed() == []
    assert store.recover().invalid == ["renamed"]
