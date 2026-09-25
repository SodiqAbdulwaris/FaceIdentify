"""Managed bytes on disk: crash-safe writes, reads, integrity checks and deletion.

This module knows nothing about the database. It never decides *whether* bytes should exist
(API and Contracts.md §51: "StorageManager does not decide..."); callers in the application layer
coordinate it with the `artifacts` table.

A write goes to `staging/<name>.part`, is hashed while it streams, fsynced, and only then renamed
onto its final key (API and Contracts.md §55: "Never write directly to final destination"). A file
at a final path is therefore always complete; a `.part` file never is.
"""

import hashlib
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
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

    def staging_path(self, staging_name: str) -> Path:
        return self.roots.staging / f"{staging_name}{STAGING_SUFFIX}"

    def store(self, storage_key: str, source: BinaryIO, *, staging_name: str) -> StoredBytes:
        """Write `source` to `storage_key` atomically and return its hash and size.

        `staging_name` names the in-flight `.part` file (callers use the artifact id), so startup
        recovery can find what an interrupted write left behind. Storing identical bytes to a key
        that already holds them is a no-op, which makes a retried finalization safe.
        """
        final = self.roots.path_for(storage_key)
        staged = self.staging_path(staging_name)
        try:
            digest = hashlib.sha256()
            size = 0
            # "wb", not "xb": the name is the caller's own (its artifact id), so a leftover .part
            # from an earlier crash of the same write is ours to overwrite.
            with staged.open("wb") as out:
                while chunk := source.read(CHUNK_SIZE):
                    out.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
                out.flush()
                os.fsync(out.fileno())
            stored = StoredBytes(digest.digest(), size)

            if final.exists():
                if self.digest(storage_key) != stored:
                    raise ExistingContentError(f"different content already at {storage_key!r}")
                staged.unlink()
                return stored
            final.parent.mkdir(parents=True, exist_ok=True)
            # ponytail: os.replace is atomic on NTFS but not write-through; a power cut just after
            # it can lose the rename (never tear the file). Use MoveFileEx(WRITE_THROUGH) if needed.
            os.replace(staged, final)
            return stored
        finally:
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
