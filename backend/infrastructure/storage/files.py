"""Managed bytes on disk: crash-safe writes, reads, integrity checks and deletion.

This module knows nothing about the database. It never decides *whether* bytes should exist
(API and Contracts.md §51: "StorageManager does not decide..."); callers in the application layer
coordinate it with the `artifacts` table.

A write goes to `staging/<name>.part`, is hashed while it streams, fsynced, and only then renamed
onto its final key (API and Contracts.md §55: "Never write directly to final destination"). A file
at a final path is therefore always complete; a `.part` file never is.
"""

import contextlib
import hashlib
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from backend.infrastructure.storage.layout import MANAGED_DIRECTORIES, StorageRoots

CHUNK_SIZE = 1024 * 1024
STAGING_SUFFIX = ".part"


class BytesMissingError(FileNotFoundError):
    """No managed file exists for the storage key."""


class ExistingContentError(FileExistsError):
    """A different file already occupies the storage key; managed content is never overwritten."""


@dataclass(frozen=True)
class StoredBytes:
    sha256: bytes
    size_bytes: int


def _digest_stream(stream: BinaryIO) -> StoredBytes:
    digest = hashlib.sha256()
    size = 0
    while chunk := stream.read(CHUNK_SIZE):
        digest.update(chunk)
        size += len(chunk)
    return StoredBytes(digest.digest(), size)


class ManagedFileStore:
    def __init__(self, roots: StorageRoots) -> None:
        self.roots = roots

    def staging_path(self, storage_key: str) -> Path:
        """Where an in-flight write for `storage_key` lives: `staging/<artifact id hex>.part`.

        Derived from the key (whose last part is the artifact id), so startup recovery can find
        what an interrupted write for a given artifact left behind.
        """
        return self.roots.staging / f"{PurePosixPath(storage_key).name}{STAGING_SUFFIX}"

    def store(self, storage_key: str, source: BinaryIO) -> StoredBytes:
        """Write `source` to `storage_key` atomically and return its hash and size.

        Storing identical bytes to a key that already holds them is a no-op, which makes a retried
        finalization safe; different bytes are refused (`ExistingContentError`).
        """
        final = self.roots.path_for(storage_key)
        staged = self.staging_path(storage_key)
        try:
            digest = hashlib.sha256()
            size = 0
            # "wb", not "xb": the name is this artifact's own, so a leftover .part from an earlier
            # crash of the same write is ours to overwrite.
            with staged.open("wb") as out:
                while chunk := source.read(CHUNK_SIZE):
                    out.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
                out.flush()
                os.fsync(out.fileno())
            stored = StoredBytes(digest.digest(), size)

            final.parent.mkdir(parents=True, exist_ok=True)
            try:
                # os.rename, not os.replace: on Windows (the only supported platform) it refuses an
                # existing destination atomically, so "never overwrite" is not a check-then-act.
                # ponytail: atomic on NTFS but not write-through; a power cut just after it can
                # lose the rename (never tear the file). Use MoveFileEx(WRITE_THROUGH) if needed.
                os.rename(staged, final)
            except FileExistsError:
                if self.digest(storage_key) != stored:
                    raise ExistingContentError(
                        f"different content already at {storage_key!r}"
                    ) from None
            return stored
        finally:
            # A locked staging file must not replace the error that actually happened; recovery
            # removes it once its artifact is settled.
            with contextlib.suppress(OSError):
                staged.unlink(missing_ok=True)

    def open(self, storage_key: str) -> BinaryIO:
        path = self.roots.path_for(storage_key)
        try:
            return path.open("rb")
        except FileNotFoundError as missing:
            raise BytesMissingError(f"no managed file for {storage_key!r}") from missing

    def digest(self, storage_key: str) -> StoredBytes | None:
        """Hash and size of the file at the key, or None if there is no file."""
        path = self.roots.path_for(storage_key)
        if not path.is_file():
            return None
        with path.open("rb") as stream:
            return _digest_stream(stream)

    def delete(self, storage_key: str) -> None:
        """Remove the file at the key. Idempotent: an already-absent file is success."""
        self.roots.path_for(storage_key).unlink(missing_ok=True)

    def managed_files(self) -> Iterator[str]:
        """The storage key of every file currently under the managed directories."""
        for directory in sorted(MANAGED_DIRECTORIES):
            for path in sorted((self.roots.library_root / directory).rglob("*")):
                if path.is_file():
                    yield self.roots.key_for(path)

    def staging_files(self) -> list[Path]:
        return sorted(self.roots.staging.glob(f"*{STAGING_SUFFIX}"))
