"""The storage layout and the managed byte store, on real temporary directories (M2: TST-025;
TESTING_STRATEGY.md §7.2: hashing, artifact staging, atomic finalization).

Nothing here touches the database: `backend/infrastructure/storage` only knows about bytes.
"""

import hashlib
import io
import os
from pathlib import Path
from typing import BinaryIO, cast

import pytest

from backend.infrastructure.storage.files import (
    CHUNK_SIZE,
    BytesMissingError,
    ExistingContentError,
    ManagedFileStore,
    StoredBytes,
)
from backend.infrastructure.storage.layout import (
    LIBRARY_DIRECTORIES,
    LOCAL_STATE_DIRECTORIES,
    StorageRoots,
    UnsafeStorageKeyError,
)
from tests.fixtures.persistence import AppDirs


class SimulatedCrash(BaseException):
    """Stands in for the process dying; not an `Exception`, so no handler 'recovers' from it."""


class ExplodingStream:
    """Yields `good` bytes, then fails, like a source file on a disconnected drive."""

    def __init__(self, good: bytes, error: BaseException) -> None:
        self.remaining, self.error = good, error

    def read(self, size: int = -1) -> bytes:
        if not self.remaining:
            raise self.error
        chunk, self.remaining = self.remaining[:size], self.remaining[size:]
        return chunk


def expected(data: bytes) -> StoredBytes:
    return StoredBytes(hashlib.sha256(data).digest(), len(data))


# --- layout ------------------------------------------------------------------------------------


def test_ensure_layout_creates_both_roots_and_is_idempotent(tmp_path: Path) -> None:
    roots = StorageRoots(library_root=tmp_path / "lib", local_state_root=tmp_path / "local")
    roots.ensure_layout()
    keep = roots.library_root / "originals" / "keep"
    keep.write_bytes(b"x")
    roots.ensure_layout()

    for name in LIBRARY_DIRECTORIES:
        assert (roots.library_root / name).is_dir()
    for name in LOCAL_STATE_DIRECTORIES:
        assert (roots.local_state_root / name).is_dir()
    assert keep.read_bytes() == b"x"  # never removes anything


def test_the_database_lives_in_the_library(storage_roots: StorageRoots, app_dirs: AppDirs) -> None:
    """tech-stack.md §15: the database travels with the library it describes."""
    assert storage_roots.database_path == storage_roots.library_root / "database" / "library.db"
    assert storage_roots.database_path == app_dirs.database_path


def test_staging_is_inside_the_library_root(storage_roots: StorageRoots) -> None:
    """So the final rename never crosses a drive (decision 2026-09-25)."""
    assert storage_roots.staging.parent == storage_roots.library_root


@pytest.mark.parametrize("key", ["originals/abc", "crops/abc", "thumbnails/a/b", "models/abc"])
def test_valid_keys_resolve_inside_the_library(storage_roots: StorageRoots, key: str) -> None:
    path = storage_roots.path_for(key)
    assert path.is_relative_to(storage_roots.library_root)
    assert storage_roots.key_for(path) == key


@pytest.mark.parametrize(
    "key",
    [
        "",
        "originals",  # a directory, not a file key
        "/originals/abc",
        "C:/originals/abc",
        "originals\\abc",
        "originals/../database/library.db",
        "../outside",
        "originals/./abc",  # non-canonical: would name the same file under a second key
        "originals//abc",
        "originals/abc/",
        "database/library.db",  # exists in the library, but is not managed artifact storage
        "staging/abc.part",
        "derived/abc",
    ],
)
def test_unsafe_or_unmanaged_keys_are_refused(storage_roots: StorageRoots, key: str) -> None:
    with pytest.raises(UnsafeStorageKeyError):
        storage_roots.path_for(key)


def _link_directory(link: Path, target: Path) -> None:
    """A directory link: a junction on Windows (no privilege needed), a symlink elsewhere."""
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:  # pragma: no cover - the suite runs on Windows
        link.symlink_to(target, target_is_directory=True)


def test_a_key_that_resolves_through_a_link_to_outside_the_library_is_refused(
    storage_roots: StorageRoots, tmp_path: Path
) -> None:
    """A junction planted inside originals/ must not let reads, writes or deletes escape."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "victim").write_bytes(b"not ours")
    _link_directory(storage_roots.library_root / "originals" / "escape", outside)

    with pytest.raises(UnsafeStorageKeyError, match="escapes"):
        storage_roots.path_for("originals/escape/victim")
    assert (outside / "victim").read_bytes() == b"not ours"


# --- writing -----------------------------------------------------------------------------------


def test_store_writes_hashes_and_leaves_no_staging_file(file_store: ManagedFileStore) -> None:
    data = b"face image bytes"
    stored = file_store.store("originals/a1", io.BytesIO(data), staging_name="a1")

    assert stored == expected(data)
    assert file_store.roots.path_for("originals/a1").read_bytes() == data
    assert file_store.staging_files() == []


def test_store_streams_content_larger_than_one_chunk(file_store: ManagedFileStore) -> None:
    data = os.urandom(3 * CHUNK_SIZE + 17)
    stored = file_store.store("originals/big", io.BytesIO(data), staging_name="big")
    assert stored == expected(data)
    assert file_store.digest("originals/big") == stored


def test_storing_identical_bytes_again_is_a_no_op(file_store: ManagedFileStore) -> None:
    """A retried finalization must succeed rather than fail on its own earlier write."""
    first = file_store.store("originals/a1", io.BytesIO(b"same"), staging_name="a1")
    again = file_store.store("originals/a1", io.BytesIO(b"same"), staging_name="a1")
    assert first == again
    assert file_store.staging_files() == []


def test_different_bytes_never_overwrite_managed_content(file_store: ManagedFileStore) -> None:
    file_store.store("originals/a1", io.BytesIO(b"original"), staging_name="a1")
    with pytest.raises(ExistingContentError):
        file_store.store("originals/a1", io.BytesIO(b"imposter"), staging_name="a1")

    assert file_store.roots.path_for("originals/a1").read_bytes() == b"original"
    assert file_store.staging_files() == []


@pytest.mark.parametrize("error", [OSError("drive disconnected"), SimulatedCrash()])
def test_a_failed_write_leaves_neither_a_final_nor_a_staging_file(
    file_store: ManagedFileStore, error: BaseException
) -> None:
    source = cast("BinaryIO", ExplodingStream(b"x" * (CHUNK_SIZE + 5), error))
    with pytest.raises(type(error)):
        file_store.store("originals/a1", source, staging_name="a1")

    assert not file_store.roots.path_for("originals/a1").exists()
    assert file_store.staging_files() == []


def test_a_failed_rename_leaves_no_final_file(
    file_store: ManagedFileStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Up to the rename, only the staging file exists: nothing at a final path is ever partial."""

    def refuse(*_: object) -> None:
        raise PermissionError("rename refused")

    monkeypatch.setattr(os, "replace", refuse)
    with pytest.raises(PermissionError):
        file_store.store("originals/a1", io.BytesIO(b"data"), staging_name="a1")

    assert not file_store.roots.path_for("originals/a1").exists()
    assert file_store.staging_files() == []


def test_a_staging_file_left_by_an_earlier_crash_is_overwritten(
    file_store: ManagedFileStore,
) -> None:
    file_store.staging_path("a1").write_bytes(b"torn half of an old write")
    stored = file_store.store("originals/a1", io.BytesIO(b"new"), staging_name="a1")
    assert stored == expected(b"new")
    assert file_store.roots.path_for("originals/a1").read_bytes() == b"new"


def test_the_write_is_fsynced_before_the_rename(
    file_store: ManagedFileStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    real_fsync, real_replace = os.fsync, os.replace

    def fsync(fd: int) -> None:
        events.append("fsync")
        real_fsync(fd)

    def replace(src: Path, dst: Path) -> None:
        events.append("replace")
        real_replace(src, dst)

    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(os, "replace", replace)
    file_store.store("originals/a1", io.BytesIO(b"data"), staging_name="a1")
    assert events == ["fsync", "replace"]


# --- reading, deleting, listing ----------------------------------------------------------------


def test_open_digest_and_delete(file_store: ManagedFileStore) -> None:
    file_store.store("crops/c1", io.BytesIO(b"crop"), staging_name="c1")
    with file_store.open("crops/c1") as stream:
        assert stream.read() == b"crop"

    file_store.delete("crops/c1")
    file_store.delete("crops/c1")  # idempotent

    assert file_store.digest("crops/c1") is None
    with pytest.raises(BytesMissingError):
        file_store.open("crops/c1")


def test_managed_files_lists_only_managed_directories(file_store: ManagedFileStore) -> None:
    roots = file_store.roots
    file_store.store("originals/o1", io.BytesIO(b"o"), staging_name="o1")
    file_store.store("thumbnails/t/1", io.BytesIO(b"t"), staging_name="t1")
    (roots.library_root / "derived" / "cache.bin").write_bytes(b"d")
    (roots.library_root / "backups" / "old.db").write_bytes(b"b")
    file_store.staging_path("x").write_bytes(b"s")

    assert list(file_store.managed_files()) == ["originals/o1", "thumbnails/t/1"]
    assert [p.name for p in file_store.staging_files()] == ["x.part"]
