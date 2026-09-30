"""The USearch approximate-nearest-neighbour index for one RepresentationSpace.

PERSISTENCE_IMPLEMENTATION.md §23: "Build one USearch index per RepresentationSpace, never a mixed
index. Index directory manifests contain `index_format_version`, `representation_space_id`,
`generation_id`, and `built_at`... atomically persists the index/manifest generation... A missing,
corrupt, mismatched, or unsupported index is quarantined/discarded and rebuilt by streaming active
eligible representations from SQLite." ANN output is only candidate keys; SQLite revalidates them
(§23), and USearch never decides identity truth. This module knows nothing about the database: it
takes keys and vectors, and the coordinator (TST-028) decides what belongs in it.

On disk, one directory per space::

    <indexes>/<representation space id>/
        manifest.json               # the commit point: names the live index file
        index.<generation id>.usearch
        quarantine/<n>/...          # files from an index found unusable, kept for diagnosis

A generation's index file is written first and is invisible until `manifest.json` is atomically
replaced to name it, so a crash at any point leaves either the old generation or the new one,
never a half-written index that looks valid. Files no manifest names are leftovers and are
removed on open.

ponytail: quarantined indexes are kept and never pruned (they are rare and small next to the
library); add a retention limit if they ever pile up. The manifest records size and count, not a
hash, so a same-size corruption that still loads is not detected; add a SHA-256 if that matters.
"""

import contextlib
import json
import os
import re
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from usearch.index import Index

INDEX_FORMAT_VERSION = 1
MANIFEST_NAME = "manifest.json"
QUARANTINE_DIRECTORY = "quarantine"
_INDEX_FILE = re.compile(r"index\.[0-9a-f]{32}\.usearch")

Vector = NDArray[np.float32]


class IndexUnusableError(Exception):
    """The persisted index cannot be used as it is: missing, corrupt, mismatched or unsupported.
    The caller quarantines it and rebuilds from SQLite (§23); the message says why."""


@dataclass(frozen=True)
class IndexManifest:
    index_format_version: int
    representation_space_id: uuid.UUID
    generation_id: uuid.UUID
    built_at: datetime
    ndim: int
    metric: str
    index_file: str
    size_bytes: int
    count: int

    def to_json(self) -> str:
        return json.dumps(
            {
                "index_format_version": self.index_format_version,
                "representation_space_id": str(self.representation_space_id),
                "generation_id": str(self.generation_id),
                "built_at": self.built_at.isoformat(),
                "ndim": self.ndim,
                "metric": self.metric,
                "index_file": self.index_file,
                "size_bytes": self.size_bytes,
                "count": self.count,
            },
            indent=2,
        )

    @classmethod
    def from_json(cls, text: str) -> "IndexManifest":
        try:
            raw = json.loads(text)
            return cls(
                index_format_version=_integer(raw["index_format_version"]),
                representation_space_id=uuid.UUID(_string(raw["representation_space_id"])),
                generation_id=uuid.UUID(_string(raw["generation_id"])),
                built_at=datetime.fromisoformat(_string(raw["built_at"])),
                ndim=_integer(raw["ndim"]),
                metric=_string(raw["metric"]),
                index_file=_string(raw["index_file"]),
                size_bytes=_integer(raw["size_bytes"]),
                count=_integer(raw["count"]),
            )
        except (ValueError, KeyError, TypeError) as error:
            raise IndexUnusableError(f"manifest is not readable: {error!r}") from error


def _integer(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"expected an integer, got {value!r}")
    return value


def _string(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError(f"expected a string, got {value!r}")
    return value


@dataclass(frozen=True)
class Candidate:
    """An ANN hit: a key and its distance. Only a candidate; SQLite revalidates it (§23)."""

    key: int
    distance: float


def _checked(vector: Vector, ndim: int) -> Vector:
    array = np.asarray(vector, dtype=np.float32)
    if array.shape != (ndim,):
        raise ValueError(f"expected a vector of {ndim} dimensions, got shape {array.shape}")
    if not np.isfinite(array).all():
        raise ValueError("a vector must be finite (no NaN or infinity)")
    return array


def _checked_key(key: int) -> int:
    if isinstance(key, bool) or not 0 <= key < 2**64:
        raise ValueError(f"an index key is an unsigned 64-bit integer, got {key!r}")
    return key


class RepresentationIndex:
    """One space's index in memory, persisted as generations. The coordinator is its only writer."""

    def __init__(
        self,
        directory: Path,
        *,
        representation_space_id: uuid.UUID,
        ndim: int,
        metric: str,
        index: Index,
        manifest: IndexManifest | None,
    ) -> None:
        self.directory = directory
        self.representation_space_id = representation_space_id
        self.ndim = ndim
        self.metric = metric
        self._index = index
        self.manifest = manifest  # None until the first persist

    # --- creating and opening -------------------------------------------------------------

    @staticmethod
    def _new_index(ndim: int, metric: str) -> Index:
        return Index(ndim=ndim, metric=metric, dtype="f32")

    @classmethod
    def empty(
        cls, directory: Path, *, representation_space_id: uuid.UUID, ndim: int, metric: str
    ) -> "RepresentationIndex":
        """A new, empty, not yet persisted index."""
        return cls(
            directory,
            representation_space_id=representation_space_id,
            ndim=ndim,
            metric=metric,
            index=cls._new_index(ndim, metric),
            manifest=None,
        )

    @classmethod
    def open(
        cls, directory: Path, *, representation_space_id: uuid.UUID, ndim: int, metric: str
    ) -> "RepresentationIndex":
        """Load the live generation, or raise `IndexUnusableError` saying why it cannot be used.

        Every way the persisted index can disagree with what the caller expects is checked: no
        manifest, an unreadable or unsupported one, another space's, another dimension or metric,
        a missing, resized or unreadable index file, or a different entry count than recorded.
        """
        manifest_path = directory / MANIFEST_NAME
        try:
            text = manifest_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise IndexUnusableError("no manifest") from None
        except (OSError, UnicodeDecodeError) as error:
            raise IndexUnusableError(f"manifest cannot be read: {error!r}") from error
        manifest = IndexManifest.from_json(text)

        if manifest.index_format_version != INDEX_FORMAT_VERSION:
            raise IndexUnusableError(
                f"unsupported index format {manifest.index_format_version}, "
                f"expected {INDEX_FORMAT_VERSION}"
            )
        if manifest.representation_space_id != representation_space_id:
            raise IndexUnusableError(
                f"index belongs to space {manifest.representation_space_id}, "
                f"not {representation_space_id}"
            )
        if (manifest.ndim, manifest.metric) != (ndim, metric):
            raise IndexUnusableError(
                f"index is {manifest.ndim}-dimensional {manifest.metric}, "
                f"expected {ndim}-dimensional {metric}"
            )
        if not _INDEX_FILE.fullmatch(manifest.index_file):
            raise IndexUnusableError(f"manifest names an unexpected file {manifest.index_file!r}")

        index_path = directory / manifest.index_file
        try:
            size = index_path.stat().st_size
        except FileNotFoundError:
            raise IndexUnusableError("the index file the manifest names is missing") from None
        if size != manifest.size_bytes:
            raise IndexUnusableError(
                f"index file is {size} bytes, the manifest recorded {manifest.size_bytes}"
            )

        index = cls._new_index(ndim, metric)
        try:
            index.load(str(index_path))
        except (RuntimeError, ValueError, OSError) as error:
            raise IndexUnusableError(f"index file cannot be loaded: {error}") from error
        # `load` adopts the file's own dimension and metric without complaint.
        if index.ndim != ndim:
            raise IndexUnusableError(f"index file is {index.ndim}-dimensional, expected {ndim}")
        if len(index) != manifest.count:
            raise IndexUnusableError(
                f"index file holds {len(index)} entries, the manifest recorded {manifest.count}"
            )

        opened = cls(
            directory,
            representation_space_id=representation_space_id,
            ndim=ndim,
            metric=metric,
            index=index,
            manifest=manifest,
        )
        opened._remove_leftovers()
        return opened

    @classmethod
    def build(
        cls,
        directory: Path,
        *,
        representation_space_id: uuid.UUID,
        ndim: int,
        metric: str,
        entries: Iterable[tuple[int, Vector]],
        clock: Callable[[], datetime],
        new_id: Callable[[], uuid.UUID],
    ) -> "RepresentationIndex":
        """Build a fresh generation from `entries` (streamed from SQLite) and persist it."""
        built = cls.empty(
            directory, representation_space_id=representation_space_id, ndim=ndim, metric=metric
        )
        for key, vector in entries:
            if not built.add(key, vector):
                raise ValueError(f"key {key} appears twice in the entries")
        built.persist(clock=clock, new_id=new_id)
        return built

    # --- desired-state operations ---------------------------------------------------------

    def add(self, key: int, vector: Vector) -> bool:
        """Make `key` present. True if it was added, False if it was already there. Idempotent:
        a representation's vector never changes, so a key that is present is left as it is."""
        _checked_key(key)
        array = _checked(vector, self.ndim)
        if self._index.contains(key):
            return False
        self._index.add(key, array)
        return True

    def remove(self, key: int) -> bool:
        """Make `key` absent. True if it was removed, False if it was not there (idempotent)."""
        return bool(self._index.remove(_checked_key(key)))

    def contains(self, key: int) -> bool:
        return bool(self._index.contains(_checked_key(key)))

    def __len__(self) -> int:
        return len(self._index)

    def search(self, vector: Vector, k: int) -> list[Candidate]:
        """The up-to-`k` nearest keys, nearest first. Candidates only (§23)."""
        if k < 1:
            raise ValueError("k must be at least 1")
        matches = self._index.search(_checked(vector, self.ndim), k)
        return [
            Candidate(int(key), float(distance))
            for key, distance in zip(matches.keys, matches.distances, strict=True)
        ]

    # --- persistence ----------------------------------------------------------------------

    def persist(
        self, *, clock: Callable[[], datetime], new_id: Callable[[], uuid.UUID]
    ) -> IndexManifest:
        """Write a new generation and make it the live one, atomically.

        The index file is written under its own generation name, then the manifest is replaced
        (write, fsync, rename) to name it. Until that rename, the previous generation is the live
        one; after it, the previous index file is a leftover and is removed.
        """
        self.directory.mkdir(parents=True, exist_ok=True)
        generation_id = new_id()
        index_file = f"index.{generation_id.hex}.usearch"
        index_path = self.directory / index_file
        self._index.save(str(index_path))
        manifest = IndexManifest(
            index_format_version=INDEX_FORMAT_VERSION,
            representation_space_id=self.representation_space_id,
            generation_id=generation_id,
            built_at=clock(),
            ndim=self.ndim,
            metric=self.metric,
            index_file=index_file,
            size_bytes=index_path.stat().st_size,
            count=len(self._index),
        )
        staged = self.directory / f"{MANIFEST_NAME}.tmp"
        with staged.open("w", encoding="utf-8") as out:
            out.write(manifest.to_json())
            out.flush()
            os.fsync(out.fileno())
        os.replace(staged, self.directory / MANIFEST_NAME)
        self.manifest = manifest
        self._remove_leftovers()
        return manifest

    def _remove_leftovers(self) -> None:
        """Delete index files and staged manifests that no manifest names (an interrupted persist,
        or a superseded generation). Only files named in this module's exact patterns."""
        live = self.manifest.index_file if self.manifest is not None else None
        for path in self.directory.iterdir():
            stale_index = _INDEX_FILE.fullmatch(path.name) and path.name != live
            if stale_index or path.name == f"{MANIFEST_NAME}.tmp":
                with contextlib.suppress(OSError):  # locked: the next open retries
                    path.unlink()


def quarantine(directory: Path) -> Path | None:
    """Move an unusable index out of the way, keeping it for diagnosis. Returns where it went, or
    None if there was nothing to move. Only this module's own files are moved."""
    own = [
        path
        for path in (directory.iterdir() if directory.is_dir() else [])
        if path.name == MANIFEST_NAME or _INDEX_FILE.fullmatch(path.name)
    ]
    if not own:
        return None
    root = directory / QUARANTINE_DIRECTORY
    root.mkdir(exist_ok=True)
    number = 1 + max((int(p.name) for p in root.iterdir() if p.name.isdigit()), default=0)
    target = root / str(number)
    target.mkdir()
    for path in own:
        os.replace(path, target / path.name)
    return target


@dataclass(frozen=True)
class OpenResult:
    index: RepresentationIndex
    rebuilt: bool
    reason: str | None  # why the old index was not usable, when it was rebuilt


def open_or_rebuild(
    directory: Path,
    *,
    representation_space_id: uuid.UUID,
    ndim: int,
    metric: str,
    entries: Callable[[], Iterable[tuple[int, Vector]]],
    clock: Callable[[], datetime],
    new_id: Callable[[], uuid.UUID],
) -> OpenResult:
    """The startup path (§23, §28): use the persisted index if it is sound, otherwise quarantine it
    and rebuild from `entries()`, which streams the space's active representations from SQLite.
    `entries` is only called when a rebuild is needed. A directory with nothing in it is a first
    build, not a failure."""
    try:
        opened = RepresentationIndex.open(
            directory, representation_space_id=representation_space_id, ndim=ndim, metric=metric
        )
    except IndexUnusableError as error:
        moved = quarantine(directory)
        rebuilt = RepresentationIndex.build(
            directory,
            representation_space_id=representation_space_id,
            ndim=ndim,
            metric=metric,
            entries=entries(),
            clock=clock,
            new_id=new_id,
        )
        return OpenResult(rebuilt, True, str(error) if moved is not None else None)
    return OpenResult(opened, False, None)
