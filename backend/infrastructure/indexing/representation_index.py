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
        manifest.json               # the commit point: names the live index file and its hash
        index.<generation id>.usearch
        quarantine/<n>/...          # files from an index found unusable, kept for diagnosis

A generation's index file is written, flushed and hashed first, and is invisible until
`manifest.json` is atomically replaced to name it, so a *process* crash at any point leaves either
the old generation or the new one, never a half-written index that looks valid.

Durability is deliberately weaker than that: after a power cut the new generation may be lost or the
old one may be stale (Windows cannot flush a directory), which is acceptable because the index is
derived and rebuildable (§23): whatever is found is checked against the manifest's size, hash,
count, dimension and metric, and anything that does not match is rebuilt from SQLite.

Concurrency: one process, one writer (the coordinator, §23). `open`, `persist`, `quarantine` and
`remove_leftovers` must not run concurrently for one space. `open` is read-only, so opening never
removes a file another call just published; leftovers are removed only by the writer's own paths
(`persist` and `open_or_rebuild`).

ponytail: quarantined indexes are kept and never pruned (they are rare and small next to the
library); add a retention limit if they ever pile up.
"""

import contextlib
import hashlib
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

from backend.infrastructure.storage.plain import is_plain_directory, is_plain_file

INDEX_FORMAT_VERSION = 1
MANIFEST_NAME = "manifest.json"
QUARANTINE_DIRECTORY = "quarantine"
_INDEX_FILE = re.compile(r"index\.[0-9a-f]{32}\.usearch")
_SHA256 = re.compile(r"[0-9a-f]{64}")
CHUNK_SIZE = 1024 * 1024

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
    sha256: str
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
                "sha256": self.sha256,
                "count": self.count,
            },
            indent=2,
        )

    @classmethod
    def from_json(cls, text: str) -> "IndexManifest":
        try:
            raw = json.loads(text)
            sha256 = _string(raw["sha256"])
            if _SHA256.fullmatch(sha256) is None:
                raise ValueError(f"not a SHA-256 digest: {sha256!r}")
            return cls(
                index_format_version=_integer(raw["index_format_version"]),
                representation_space_id=uuid.UUID(_string(raw["representation_space_id"])),
                generation_id=uuid.UUID(_string(raw["generation_id"])),
                built_at=datetime.fromisoformat(_string(raw["built_at"])),
                ndim=_integer(raw["ndim"]),
                metric=_string(raw["metric"]),
                index_file=_string(raw["index_file"]),
                size_bytes=_integer(raw["size_bytes"]),
                sha256=sha256,
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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


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

        Read-only: nothing on disk is changed. Every way the persisted index can disagree with
        what the caller expects is checked: a link where the directory or a file should be, no
        manifest, an unreadable or unsupported one, another space's, another dimension or metric,
        an index file that is not this generation's, is missing, or differs in size, SHA-256,
        loadability, dimension, metric or entry count from what the manifest recorded.
        """
        if directory.exists() and not is_plain_directory(directory):
            raise IndexUnusableError("the index directory is not a plain directory")
        manifest_path = directory / MANIFEST_NAME
        if manifest_path.exists() and not is_plain_file(manifest_path):
            raise IndexUnusableError("the manifest is not a plain file")
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
        if manifest.index_file != f"index.{manifest.generation_id.hex}.usearch":
            raise IndexUnusableError(
                f"manifest names {manifest.index_file!r}, which is not its own generation's file"
            )

        index_path = directory / manifest.index_file
        if not is_plain_file(index_path):
            raise IndexUnusableError("the index file the manifest names is missing or not a file")
        size = index_path.stat().st_size
        if size != manifest.size_bytes:
            raise IndexUnusableError(
                f"index file is {size} bytes, the manifest recorded {manifest.size_bytes}"
            )
        try:
            digest = _sha256(index_path)
        except OSError as error:
            raise IndexUnusableError(f"index file cannot be read: {error!r}") from error
        if digest != manifest.sha256:
            raise IndexUnusableError("index file does not match the SHA-256 the manifest recorded")

        index = cls._new_index(ndim, metric)
        # `Index.load` silently adopts the file's own dimension, and worse, keeps *computing* the
        # file's own metric while `index.metric` goes on reporting the one it was constructed with
        # (probed: an L2 file loaded into a cosine index answers with L2 distances). So the file's
        # header is what must be checked, before loading.
        try:
            header = Index.metadata(str(index_path))
            index.load(str(index_path))
        except (RuntimeError, ValueError, OSError, KeyError) as error:
            raise IndexUnusableError(f"index file cannot be loaded: {error}") from error
        assert header is not None  # typed Optional, but a damaged file raises ValueError instead
        if header["dimensions"] != ndim:
            raise IndexUnusableError(
                f"index file is {header['dimensions']}-dimensional, expected {ndim}"
            )
        if header["kind_metric"] != index.metric:
            raise IndexUnusableError(
                f"index file uses metric {header['kind_metric']}, expected {metric}"
            )
        if len(index) != manifest.count:
            raise IndexUnusableError(
                f"index file holds {len(index)} entries, the manifest recorded {manifest.count}"
            )

        return cls(
            directory,
            representation_space_id=representation_space_id,
            ndim=ndim,
            metric=metric,
            index=index,
            manifest=manifest,
        )

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
        """Write a new generation and make it the live one.

        The generation's file is written, flushed to disk and hashed under its own name; then the
        manifest is replaced (write, fsync, rename) to name it. Until that rename the previous
        generation is the live one; after it, the previous file is a leftover and is removed.
        """
        if self.directory.exists() and not is_plain_directory(self.directory):
            raise ValueError(f"{self.directory} is not a plain directory")
        self.directory.mkdir(parents=True, exist_ok=True)
        generation_id = new_id()
        index_file = f"index.{generation_id.hex}.usearch"
        index_path = self.directory / index_file
        self._index.save(str(index_path))
        with index_path.open("rb+") as written:
            os.fsync(written.fileno())
        manifest = IndexManifest(
            index_format_version=INDEX_FORMAT_VERSION,
            representation_space_id=self.representation_space_id,
            generation_id=generation_id,
            built_at=clock(),
            ndim=self.ndim,
            metric=self.metric,
            index_file=index_file,
            size_bytes=index_path.stat().st_size,
            sha256=_sha256(index_path),
            count=len(self._index),
        )
        staged = self.directory / f"{MANIFEST_NAME}.tmp"
        with staged.open("w", encoding="utf-8") as out:
            out.write(manifest.to_json())
            out.flush()
            os.fsync(out.fileno())
        os.replace(staged, self.directory / MANIFEST_NAME)
        self.manifest = manifest
        self.remove_leftovers()
        return manifest

    def stale_files(self) -> list[Path]:
        """Index files and staged manifests the live manifest does not name: what an interrupted
        persist or a superseded generation leaves behind. Only this module's own plain files, by
        exact name. A stale index file still holds every vector it was built with."""
        return _unnamed_files(
            self.directory, self.manifest.index_file if self.manifest is not None else None
        )

    def remove_leftovers(self) -> None:
        """Delete `stale_files()`; a locked one is skipped and retried on the next call. Writer
        only: it judges "live" by this object's manifest, so it must not run concurrently with
        another writer."""
        for path in self.stale_files():
            with contextlib.suppress(OSError):
                path.unlink()


def _unnamed_files(directory: Path, live: str | None) -> list[Path]:
    return [
        path
        for path in directory.iterdir()
        if (
            (_INDEX_FILE.fullmatch(path.name) and path.name != live)
            or path.name == f"{MANIFEST_NAME}.tmp"
        )
        and is_plain_file(path)
    ]


def superseded_files(directory: Path) -> list[Path]:
    """The index files and staged manifests in a space's directory that its manifest, *as it is on
    disk now*, does not name: a fresh listing, for the check that an erasure's old generations are
    really gone (persistence section 23). A manifest that is missing or unreadable names nothing, so
    every index file is reported (the index is unusable and will be rebuilt)."""
    if not is_plain_directory(directory):
        return []
    live: str | None = None
    manifest = directory / MANIFEST_NAME
    if is_plain_file(manifest):
        with contextlib.suppress(IndexUnusableError, OSError, UnicodeDecodeError):
            live = IndexManifest.from_json(manifest.read_text(encoding="utf-8")).index_file
    return sorted(_unnamed_files(directory, live))


def retire_quarantine(directory: Path) -> list[Path]:
    """Delete the quarantined generations of a space and return what is *still there* afterwards,
    listed again from disk (persistence section 23: a copy of an erased vector is not diagnostic
    data, so erasure deletes them; no time-based retention).

    Only this module's own files are deleted, by exact name and never through a link; a quarantine
    folder or numbered folder that is a link, or an own-named entry that is not a plain file, cannot
    be judged and is reported as remaining. Other files stay where they are and are not reported.
    Emptied folders are removed. An empty result means nothing of the quarantine remains."""
    root = directory / QUARANTINE_DIRECTORY
    if not root.exists() and not root.is_symlink():
        return []
    if not is_plain_directory(root):
        return [root]
    for batch in sorted(root.iterdir()):
        if not is_plain_directory(batch):
            continue
        for path in batch.iterdir():
            if _is_own_name(path) and is_plain_file(path):
                with contextlib.suppress(OSError):
                    path.unlink()
        with contextlib.suppress(OSError):
            batch.rmdir()  # only when nothing is left in it
    with contextlib.suppress(OSError):
        root.rmdir()
    return _quarantined(root)


def _is_own_name(path: Path) -> bool:
    return path.name == MANIFEST_NAME or _INDEX_FILE.fullmatch(path.name) is not None


def _quarantined(root: Path) -> list[Path]:
    """Own-named entries under the quarantine folder, and numbered folders that are links."""
    if not root.exists() and not root.is_symlink():
        return []
    remaining: list[Path] = []
    for batch in sorted(root.iterdir()):
        if not is_plain_directory(batch):
            remaining.append(batch)
            continue
        remaining += [path for path in sorted(batch.iterdir()) if _is_own_name(path)]
    return remaining


def quarantine(directory: Path) -> Path | None:
    """Move an unusable index out of the way, keeping it for diagnosis. Returns where it went, or
    None if nothing could be moved. Best effort: a file that is locked (an antivirus scan) stays
    where it is instead of stopping the rebuild, since the rebuilt generation's own manifest
    replaces the old one and `remove_leftovers` retries the old index file later. Only this
    module's own plain files are moved, and never through a link."""
    if not is_plain_directory(directory):
        return None
    own = [path for path in directory.iterdir() if _is_own_name(path) and is_plain_file(path)]
    if not own:
        return None
    root = directory / QUARANTINE_DIRECTORY
    if root.exists() and not is_plain_directory(root):
        return None
    root.mkdir(exist_ok=True)
    number = 1 + max(
        (int(p.name) for p in root.iterdir() if p.name.isdigit() and is_plain_directory(p)),
        default=0,
    )
    target = root / str(number)
    target.mkdir()
    moved = False
    for path in own:
        with contextlib.suppress(OSError):
            os.replace(path, target / path.name)
            moved = True
    return target if moved else None


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
    """The startup path (§23, §28), for the writer: use the persisted index if it is sound (and
    clear any leftovers of an interrupted persist), otherwise quarantine it and rebuild from
    `entries()`, which streams the space's active representations from SQLite and is only called
    when a rebuild is needed. An absent index is a first build, not a failure."""
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
        # Nothing to quarantine means nothing was there: a first build, not a failure.
        return OpenResult(rebuilt, True, str(error) if moved is not None else None)
    opened.remove_leftovers()
    return OpenResult(opened, False, None)
