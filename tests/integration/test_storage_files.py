"""The storage layout and the managed byte store, on real temporary directories (M2: TST-025;
TESTING_STRATEGY.md §7.2: hashing, artifact staging, atomic finalization).

Nothing here touches the database: `backend/infrastructure/storage` only knows about bytes.
"""

import hashlib
import io
import os
import subprocess
import sys
import uuid
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

HEX = "0123456789abcdef0123456789abcdef"


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


def new_key(directory: str = "originals") -> str:
    return f"{directory}/{uuid.uuid4().hex}"


def _link_directory(link: Path, target: Path) -> None:
    """A directory link: a junction on Windows (no privilege needed), a symlink elsewhere."""
    if sys.platform == "win32":  # not os.name: mypy narrows on sys.platform, e.g. in Linux CI
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:  # pragma: no cover - the suite runs on Windows
        link.symlink_to(target, target_is_directory=True)


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


# --- key validation ----------------------------------------------------------------------------


@pytest.mark.parametrize("directory", ["originals", "crops", "thumbnails", "models"])
def test_generated_keys_resolve_inside_their_directory(
    storage_roots: StorageRoots, directory: str
) -> None:
    key = f"{directory}/{HEX}"
    path = storage_roots.path_for(key)
    assert path == storage_roots.library_root / directory / HEX
    assert storage_roots.key_for(path) == key


@pytest.mark.parametrize(
    "key",
    [
        "",
        "originals",
        f"/originals/{HEX}",
        f"C:/originals/{HEX}",
        f"originals\\{HEX}",
        f"originals/../database/{HEX}",
        f"originals/./{HEX}",
        f"originals//{HEX}",
        f"originals/{HEX}/",
        f"originals/sub/{HEX}",  # one flat directory per kind
        f"database/{HEX}",  # exists in the library, but is not managed artifact storage
        f"staging/{HEX}",
        f"derived/{HEX}",
        # Windows aliases of `originals/<hex>` or of devices, which a lenient check would accept:
        f"originals/{HEX}.",
        f"originals/{HEX} ",
        f"originals/{HEX.upper()}",
        f"ORIGINALS/{HEX}",
        f"originals/{HEX}:stream",
        "originals/NUL",
        "originals/CON",
        f"originals/{HEX[:-1]}",  # not a full id
        f"originals/{HEX}\x00",
        f"\\\\?\\C:\\originals\\{HEX}",
    ],
)
def test_anything_but_a_generated_key_is_refused(storage_roots: StorageRoots, key: str) -> None:
    with pytest.raises(UnsafeStorageKeyError):
        storage_roots.path_for(key)


def test_a_managed_directory_redirected_by_a_junction_is_refused(
    storage_roots: StorageRoots, tmp_path: Path
) -> None:
    """A junction in place of `crops/` must not let reads, writes or deletes land elsewhere, even
    somewhere else inside the library (here: the database directory)."""
    crops = storage_roots.library_root / "crops"
    crops.rmdir()
    _link_directory(crops, storage_roots.library_root / "database")
    (storage_roots.library_root / "database" / HEX).write_bytes(b"not a crop")

    with pytest.raises(UnsafeStorageKeyError, match="escapes"):
        storage_roots.path_for(f"crops/{HEX}")


def test_a_file_linked_out_of_its_directory_is_refused(
    storage_roots: StorageRoots, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    _link_directory(storage_roots.library_root / "originals" / HEX, outside)

    with pytest.raises(UnsafeStorageKeyError, match="escapes"):
        storage_roots.path_for(f"originals/{HEX}")


def test_a_link_loop_is_an_unusable_key_not_a_crash(storage_roots: StorageRoots) -> None:
    """Resolving a junction loop raises RuntimeError("Symlink loop"); recovery and the scan only
    tolerate UnsafeStorageKeyError, so path_for must translate it."""
    other = "b" * 32
    first, second = (storage_roots.library_root / "originals" / n for n in (HEX, other))
    second.mkdir()
    _link_directory(first, second)
    second.rmdir()
    subprocess.run(["cmd", "/c", "mklink", "/J", str(second), str(first)], check=True,
                   capture_output=True)  # fmt: skip
    try:
        with pytest.raises(UnsafeStorageKeyError, match="cannot resolve"):
            storage_roots.path_for(f"originals/{HEX}")
    finally:
        os.rmdir(first)
        os.rmdir(second)


# --- writing -----------------------------------------------------------------------------------


def test_store_writes_hashes_and_leaves_no_staging_file(file_store: ManagedFileStore) -> None:
    key, data = new_key(), b"face image bytes"
    stored = file_store.store(key, io.BytesIO(data))

    assert stored == expected(data)
    assert file_store.roots.path_for(key).read_bytes() == data
    assert file_store.staging_files() == []


def test_the_staging_name_is_the_artifact_id(file_store: ManagedFileStore) -> None:
    assert file_store.staging_path(f"crops/{HEX}") == file_store.roots.staging / f"{HEX}.part"


def test_store_streams_content_larger_than_one_chunk(file_store: ManagedFileStore) -> None:
    key, data = new_key(), os.urandom(3 * CHUNK_SIZE + 17)
    stored = file_store.store(key, io.BytesIO(data))
    assert stored == expected(data)
    assert file_store.digest(key) == stored


def test_storing_identical_bytes_again_is_a_no_op(file_store: ManagedFileStore) -> None:
    """A retried finalization must succeed rather than fail on its own earlier write."""
    key = new_key()
    first = file_store.store(key, io.BytesIO(b"same"))
    again = file_store.store(key, io.BytesIO(b"same"))
    assert first == again
    assert file_store.staging_files() == []


def test_different_bytes_never_overwrite_managed_content(file_store: ManagedFileStore) -> None:
    key = new_key()
    file_store.store(key, io.BytesIO(b"original"))
    with pytest.raises(ExistingContentError):
        file_store.store(key, io.BytesIO(b"imposter"))

    assert file_store.roots.path_for(key).read_bytes() == b"original"
    assert file_store.staging_files() == []


def test_a_file_appearing_at_the_key_during_the_write_is_not_overwritten(
    file_store: ManagedFileStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The no-overwrite check is the rename itself, not a check made before it."""
    key = new_key()
    final = file_store.roots.path_for(key)
    real_rename = os.rename

    def race_then_rename(src: Path, dst: Path) -> None:
        final.write_bytes(b"arrived first")  # after any pre-check, just before the rename
        real_rename(src, dst)

    monkeypatch.setattr(os, "rename", race_then_rename)
    with pytest.raises(ExistingContentError):
        file_store.store(key, io.BytesIO(b"ours"))
    assert final.read_bytes() == b"arrived first"


@pytest.mark.parametrize("error", [OSError("drive disconnected"), SimulatedCrash()])
def test_a_failed_write_leaves_neither_a_final_nor_a_staging_file(
    file_store: ManagedFileStore, error: BaseException
) -> None:
    key = new_key()
    source = cast("BinaryIO", ExplodingStream(b"x" * (CHUNK_SIZE + 5), error))
    with pytest.raises(type(error)):
        file_store.store(key, source)

    assert not file_store.roots.path_for(key).exists()
    assert file_store.staging_files() == []


def test_a_failed_rename_leaves_no_final_file(
    file_store: ManagedFileStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Up to the rename, only the staging file exists: nothing at a final path is ever partial."""

    def refuse(*_: object) -> None:
        raise PermissionError("rename refused")

    monkeypatch.setattr(os, "rename", refuse)
    key = new_key()
    with pytest.raises(PermissionError):
        file_store.store(key, io.BytesIO(b"data"))

    assert not file_store.roots.path_for(key).exists()
    assert file_store.staging_files() == []


def test_a_staging_file_left_by_an_earlier_crash_is_overwritten(
    file_store: ManagedFileStore,
) -> None:
    key = new_key()
    file_store.staging_path(key).write_bytes(b"torn half of an old write")
    stored = file_store.store(key, io.BytesIO(b"new"))
    assert stored == expected(b"new")
    assert file_store.roots.path_for(key).read_bytes() == b"new"


def test_the_write_is_fsynced_before_the_rename(
    file_store: ManagedFileStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    real_fsync, real_rename = os.fsync, os.rename

    def fsync(fd: int) -> None:
        events.append("fsync")
        real_fsync(fd)

    def rename(src: Path, dst: Path) -> None:
        events.append("rename")
        real_rename(src, dst)

    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(os, "rename", rename)
    file_store.store(new_key(), io.BytesIO(b"data"))
    assert events == ["fsync", "rename"]


def test_a_locked_staging_file_does_not_hide_the_real_error(
    file_store: ManagedFileStore,
) -> None:
    """An open handle (antivirus, indexer) blocks both the rename and the cleanup; the caller must
    see the rename's error, not the cleanup's."""
    key = new_key()
    staged = file_store.staging_path(key)
    staged.write_bytes(b"")
    with staged.open("rb"), pytest.raises(PermissionError) as raised:
        file_store.store(key, io.BytesIO(b"data"))
    assert raised.value.filename2 is not None  # the rename's error names both paths
    assert not file_store.roots.path_for(key).exists()
    staged.unlink()


# --- reading, deleting, listing ----------------------------------------------------------------


def test_open_digest_and_delete(file_store: ManagedFileStore) -> None:
    key = new_key("crops")
    file_store.store(key, io.BytesIO(b"crop"))
    with file_store.open(key) as stream:
        assert stream.read() == b"crop"

    file_store.delete(key)
    file_store.delete(key)  # idempotent

    assert file_store.digest(key) is None
    with pytest.raises(BytesMissingError):
        file_store.open(key)


def test_managed_files_lists_only_managed_directories(file_store: ManagedFileStore) -> None:
    roots = file_store.roots
    original, thumbnail = f"originals/{HEX}", f"thumbnails/{HEX}"
    file_store.store(original, io.BytesIO(b"o"))
    file_store.store(thumbnail, io.BytesIO(b"t"))
    (roots.library_root / "derived" / "cache.bin").write_bytes(b"d")
    (roots.library_root / "backups" / "old.db").write_bytes(b"b")
    file_store.staging_path(new_key()).write_bytes(b"s")
    stray_folder = roots.library_root / "originals" / "copied-by-hand"
    stray_folder.mkdir()
    (stray_folder / "photo.jpg").write_bytes(b"p")  # surfaces, so the scan can call it an orphan

    assert list(file_store.managed_files()) == [
        original, "originals/copied-by-hand/photo.jpg", thumbnail,
    ]  # fmt: skip
    assert len(file_store.staging_files()) == 1
