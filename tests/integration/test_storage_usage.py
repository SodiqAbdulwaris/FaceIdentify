"""Storage usage reporting against a real database, real files and the real volume (M2: TST-025
"storage usage"; processing-architecture-v1.md §11).

The report says what the library holds and what a Recycle Bin purge would free. It counts only what
this application owns: AVAILABLE managed artifacts, and never the user's referenced originals.
"""

import io
import os
import shutil
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.sources.artifact_storage import create_managed_artifact
from backend.app.sources.storage_usage import (
    KindUsage,
    Measured,
    measure_directory,
    storage_usage,
)
from backend.infrastructure.db.engine import create_session_factory
from backend.infrastructure.storage.files import ManagedFileStore
from backend.infrastructure.storage.layout import StorageRoots
from backend.infrastructure.storage.workspaces import WorkspaceManager
from tests.factories.models import ModelFactory
from tests.fixtures.links import link_directory


@pytest.fixture
def workspaces(storage_roots: StorageRoots) -> WorkspaceManager:
    return WorkspaceManager(storage_roots)


@pytest.fixture
def factory(sqlite_engine: Engine) -> sessionmaker[Session]:
    return create_session_factory(sqlite_engine)


# --- an empty library ------------------------------------------------------------------------


def test_an_empty_library_uses_nothing_and_the_volume_is_reported(
    db_session: Session, storage_roots: StorageRoots, workspaces: WorkspaceManager
) -> None:
    report = storage_usage(db_session, storage_roots, workspaces)

    assert report.managed == []
    assert (report.managed_bytes, report.recycled_bytes, report.workspace_bytes) == (0, 0, 0)
    assert (report.referenced_artifacts, report.referenced_bytes) == (0, 0)
    assert (report.referenced_size_unknown, report.workspace_unreadable) == (0, 0)
    free = shutil.disk_usage(storage_roots.library_root).free
    assert 0 < report.volume_free_bytes <= report.volume_total_bytes
    assert abs(report.volume_free_bytes - free) < 50 * 1024 * 1024  # the same volume, ~now


# --- managed usage ---------------------------------------------------------------------------


def test_only_available_managed_artifacts_are_counted_by_kind(
    db_session: Session, storage_roots: StorageRoots, workspaces: WorkspaceManager,
    build: ModelFactory,
) -> None:  # fmt: skip
    build.artifact(kind="SOURCE_ORIGINAL", size_bytes=1000)
    build.artifact(kind="SOURCE_ORIGINAL", size_bytes=500)
    build.artifact(kind="FACE_CROP", size_bytes=40)
    build.artifact(kind="THUMBNAIL", size_bytes=7)
    for state in ("PENDING", "MISSING", "DELETING", "DELETE_FAILED", "DELETED"):
        build.artifact(kind="SOURCE_ORIGINAL", state=state, size_bytes=99999)
    db_session.commit()

    report = storage_usage(db_session, storage_roots, workspaces)

    assert report.managed == [
        KindUsage("FACE_CROP", 1, 40),
        KindUsage("SOURCE_ORIGINAL", 2, 1500),
        KindUsage("THUMBNAIL", 1, 7),
    ]
    assert report.managed_bytes == 1547


def test_referenced_originals_are_reported_apart_and_never_counted_as_ours(
    db_session: Session, storage_roots: StorageRoots, workspaces: WorkspaceManager,
    build: ModelFactory,
) -> None:  # fmt: skip
    build.artifact(size_bytes=10)
    for size, state in ((2_000_000, "AVAILABLE"), (3_000_000, "AVAILABLE"), (9_999, "MISSING")):
        build.artifact(
            storage_mode="REFERENCED", storage_key=None, external_path=f"D:/movies/{size}.mkv",
            size_bytes=size, state=state,
        )  # fmt: skip
    db_session.commit()

    report = storage_usage(db_session, storage_roots, workspaces)

    assert report.managed_bytes == 10
    assert (report.referenced_artifacts, report.referenced_bytes) == (2, 5_000_000)
    assert report.referenced_size_unknown == 0


def test_the_sizes_match_real_files(
    factory: sessionmaker[Session], file_store: ManagedFileStore, storage_roots: StorageRoots,
    workspaces: WorkspaceManager, build: ModelFactory,
) -> None:  # fmt: skip
    payloads = [b"a" * 1000, b"b" * 2500]
    for payload in payloads:
        create_managed_artifact(
            factory, file_store, "SOURCE_ORIGINAL", io.BytesIO(payload),
            new_id=build.new_id, clock=build.clock,
        )  # fmt: skip

    with factory() as session:
        report = storage_usage(session, storage_roots, workspaces)

    on_disk = sum(
        path.stat().st_size for path in (storage_roots.library_root / "originals").iterdir()
    )
    assert report.managed_bytes == on_disk == 3500
    assert report.managed == [KindUsage("SOURCE_ORIGINAL", 2, 3500)]


# --- the Recycle Bin -------------------------------------------------------------------------


def test_the_recycle_bin_share_counts_each_artifact_once(
    db_session: Session, storage_roots: StorageRoots, workspaces: WorkspaceManager,
    build: ModelFactory,
) -> None:  # fmt: skip
    shared_thumbnail = build.artifact(kind="THUMBNAIL", size_bytes=10)
    build.source(
        state="RECYCLED", original_artifact_id=build.artifact(size_bytes=100).id,
        thumbnail_artifact_id=shared_thumbnail.id,
    )  # fmt: skip
    build.source(
        state="RECYCLED", original_artifact_id=build.artifact(size_bytes=200).id,
        thumbnail_artifact_id=shared_thumbnail.id,
    )  # fmt: skip
    build.source(
        state="ACTIVE", original_artifact_id=build.artifact(size_bytes=5000).id,
        thumbnail_artifact_id=build.artifact(kind="THUMBNAIL", size_bytes=300).id,
    )  # fmt: skip
    for state in ("DELETING", "UNAVAILABLE"):  # not in the bin, so a purge would not free them
        build.source(state=state, original_artifact_id=build.artifact(size_bytes=70).id)
    build.source(state="RECYCLED", original_artifact_id=build.artifact(size_bytes=1).id)
    db_session.commit()

    report = storage_usage(db_session, storage_roots, workspaces)

    assert report.recycled_bytes == 100 + 200 + 10 + 1  # the shared thumbnail counted once
    assert report.managed_bytes == 100 + 200 + 10 + 5000 + 300 + 70 + 70 + 1


def test_an_unknown_referenced_size_is_counted_as_unknown_not_as_zero(
    db_session: Session, storage_roots: StorageRoots, workspaces: WorkspaceManager,
    build: ModelFactory,
) -> None:  # fmt: skip
    for n, size in enumerate((2_000, None, None)):
        build.artifact(
            storage_mode="REFERENCED", storage_key=None, external_path=f"D:/movies/{n}.mkv",
            size_bytes=size, sha256=None,
        )  # fmt: skip
    db_session.commit()

    report = storage_usage(db_session, storage_roots, workspaces)

    assert (report.referenced_artifacts, report.referenced_bytes) == (3, 2_000)
    assert report.referenced_size_unknown == 2


def test_an_artifact_shared_with_an_active_source_is_still_counted_as_recycled_once(
    db_session: Session, storage_roots: StorageRoots, workspaces: WorkspaceManager,
    build: ModelFactory,
) -> None:  # fmt: skip
    """`recycled_bytes` is an upper bound on what purging frees: a shared original stays in use."""
    shared = build.artifact(size_bytes=400)
    build.source(state="RECYCLED", original_artifact_id=shared.id)
    build.source(state="ACTIVE", original_artifact_id=shared.id)
    db_session.commit()

    report = storage_usage(db_session, storage_roots, workspaces)

    assert (report.recycled_bytes, report.managed_bytes) == (400, 400)


def test_a_recycled_source_with_a_referenced_original_frees_nothing(
    db_session: Session, storage_roots: StorageRoots, workspaces: WorkspaceManager,
    build: ModelFactory,
) -> None:  # fmt: skip
    original = build.artifact(
        storage_mode="REFERENCED", storage_key=None, external_path="D:/movies/a.mkv",
        size_bytes=4_000_000,
    )  # fmt: skip
    build.source(state="RECYCLED", original_artifact_id=original.id)
    db_session.commit()

    report = storage_usage(db_session, storage_roots, workspaces)

    assert (report.recycled_bytes, report.referenced_bytes) == (0, 4_000_000)


# --- workspaces ------------------------------------------------------------------------------


def test_workspace_bytes_are_measured_on_disk_without_following_links(
    db_session: Session, storage_roots: StorageRoots, workspaces: WorkspaceManager, tmp_path: Path
) -> None:
    outside = tmp_path / "user documents"
    outside.mkdir()
    (outside / "thesis.txt").write_bytes(b"x" * 100_000)
    first, second = uuid.uuid4(), uuid.uuid4()
    (workspaces.allocate(first) / "frames" / "0001.png").write_bytes(b"x" * 300)
    deep = workspaces.allocate(second) / "intermediate" / "a" / "b"
    deep.mkdir(parents=True)
    (deep / "blob.bin").write_bytes(b"x" * 1200)
    link_directory(workspaces.path_for(second) / "decode" / "shortcut", outside)

    report = storage_usage(db_session, storage_roots, workspaces)

    assert report.workspace_bytes == 1500  # the 100 kB behind the link is not ours
    assert report.workspace_unreadable == 0


def test_only_workspaces_the_manager_made_are_counted(
    db_session: Session, storage_roots: StorageRoots, workspaces: WorkspaceManager
) -> None:
    """Whatever else is under temp/jobs is not ours, so it is not reported as our scratch space."""
    (workspaces.allocate(uuid.uuid4()) / "frames" / "f.png").write_bytes(b"x" * 10)
    unmarked = workspaces.root / uuid.uuid4().hex  # the right name, never marked as ours
    unmarked.mkdir()
    (unmarked / "theirs.bin").write_bytes(b"x" * 5000)
    (workspaces.root / "notes.txt").write_bytes(b"x" * 7000)
    (workspaces.root / "scratch").mkdir()
    (workspaces.root / "scratch" / "other.bin").write_bytes(b"x" * 9000)

    assert storage_usage(db_session, storage_roots, workspaces).workspace_bytes == 10


def test_no_workspaces_is_zero_bytes(
    db_session: Session, storage_roots: StorageRoots, workspaces: WorkspaceManager
) -> None:
    assert not workspaces.root.exists()
    assert storage_usage(db_session, storage_roots, workspaces).workspace_bytes == 0


def test_measure_directory_counts_files_at_every_depth(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "one").write_bytes(b"x" * 10)
    (tmp_path / "two").write_bytes(b"x" * 5)

    assert measure_directory(tmp_path) == Measured(15, 0)
    assert measure_directory(tmp_path / "empty") == Measured(0, 0)  # absent is not an error


def test_a_deep_tree_is_measured(tmp_path: Path) -> None:
    deepest = tmp_path
    for _ in range(40):
        deepest = deepest / "d"
    deepest.mkdir(parents=True)
    (deepest / "blob.bin").write_bytes(b"x" * 123)

    assert measure_directory(tmp_path) == Measured(123, 0)


def scandir_failing_for(target: Path, error: OSError) -> Callable[[Path], Any]:
    real = os.scandir

    def scandir(path: Path) -> Any:
        if Path(path) == target:
            raise error
        return real(path)

    return scandir


def test_a_directory_that_vanishes_during_the_walk_is_simply_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "gone").mkdir()
    (tmp_path / "gone" / "f").write_bytes(b"x" * 50)
    (tmp_path / "kept").mkdir()
    (tmp_path / "kept" / "f").write_bytes(b"x" * 7)
    monkeypatch.setattr(
        os, "scandir", scandir_failing_for(tmp_path / "gone", FileNotFoundError("a job finished"))
    )

    assert measure_directory(tmp_path) == Measured(7, 0)


def test_a_directory_that_cannot_be_listed_is_reported_not_forgotten_or_fatal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "denied").mkdir()
    (tmp_path / "denied" / "f").write_bytes(b"x" * 50)
    (tmp_path / "kept").mkdir()
    (tmp_path / "kept" / "f").write_bytes(b"x" * 7)
    monkeypatch.setattr(
        os, "scandir", scandir_failing_for(tmp_path / "denied", PermissionError("access denied"))
    )

    assert measure_directory(tmp_path) == Measured(7, 1)


def test_an_unreadable_workspace_shows_up_in_the_report(
    db_session: Session, storage_roots: StorageRoots, workspaces: WorkspaceManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    job = uuid.uuid4()
    (workspaces.allocate(job) / "frames" / "f.png").write_bytes(b"x" * 10)
    monkeypatch.setattr(
        os, "scandir",
        scandir_failing_for(workspaces.path_for(job) / "frames", PermissionError("denied")),
    )  # fmt: skip

    report = storage_usage(db_session, storage_roots, workspaces)

    assert (report.workspace_bytes, report.workspace_unreadable) == (0, 1)
