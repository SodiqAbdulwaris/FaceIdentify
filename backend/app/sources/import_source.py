"""ImportSourceUseCase: an image becomes a Source (API and Contracts.md sections 5.1, 55 and 57;
PERSISTENCE_IMPLEMENTATION.md section 4.1).

Import creates the application's knowledge of an image; it does not process it. Either the bytes are
copied into managed storage (`import_managed`) or a verified reference to the user's own file is
recorded (`import_referenced`, which never copies or touches the file). The image is read once, into
memory, and decoded before anything is written, so what is validated is exactly what is stored, a
file that is not a usable image leaves nothing behind, and a file that changes meanwhile cannot be
stored as something it was not.

Managed creation is the three-step protocol, each transaction short and none held across the file
write: reserve a `PENDING` artifact (so its final key exists before any byte); write the bytes to
that key; then, in ONE transaction, make the artifact `AVAILABLE` and add the Source. A crash
leaves only what startup recovery already settles: a reservation with no file becomes `MISSING`
(`WRITE_NOT_COMPLETED`), and a written file with no Source is finalised as an `AVAILABLE` artifact
that nothing refers to, never as a half-made Source.

Importing the same file twice makes two Sources: the specs ask for no deduplication, and a Source
is the user's own entry, not a unique file.

A video (M6 step 3, chosen by its file name, `is_video_name`) is never read into memory: ffprobe
reads its facts from the file first, so a file that is not a usable video leaves nothing behind,
and then the bytes are streamed into managed storage (or, referenced, hashed where they are). The
facts must describe the bytes recorded, so the file's size and modification time are taken before
the probe and must be the same after it and at the end of the copy (which also stops at that size):
a file that changes or grows meanwhile is refused and leaves nothing behind.
"""

import contextlib
import hashlib
import io
import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, cast

from sqlalchemy.orm import Session

from backend.app.sources.artifact_storage import (
    mark_artifact_available,
    mark_write_not_completed,
    reserve_managed_artifact,
)
from backend.app.sources.models import ArtifactKind, Source, SourceKind, SourceState
from backend.app.sources.referenced_artifacts import add_referenced_artifact
from backend.app.sources.repository import SourceRepository
from backend.infrastructure.db.unit_of_work import UnitOfWork
from backend.infrastructure.media.image import decode_image
from backend.infrastructure.media.video import VideoFacts, is_video_name
from backend.infrastructure.storage.files import ManagedFileStore, StoredBytes
from backend.infrastructure.storage.referenced import ReferencedFileError, inspect_referenced_file


class SourceImportError(Exception):
    """A file that cannot be imported. Nothing of it is left behind."""


class ImportFileError(SourceImportError):
    """The file cannot be read."""


class ImportFileTooLargeError(SourceImportError):
    """The file has more bytes than the caller allows."""


@dataclass(frozen=True, slots=True)
class VideoImport:
    """How videos are read: the probe (`probe_video` bound to the installed tools) and the largest
    file allowed."""

    probe: Callable[[Path], VideoFacts]
    max_bytes: int


@dataclass(frozen=True, slots=True)
class _Facts:
    """What a Source records about its media."""

    kind: SourceKind
    mime_type: str
    width: int
    height: int
    duration_ms: int | None = None
    frame_rate: tuple[int, int] | None = None


class _Unchanged:
    """The file's bytes for the copy, refused (`ImportFileError`) if there are more of them than
    when it was probed or if, at their end, the file is no longer the one probed."""

    def __init__(self, stream: BinaryIO, path: Path, before: os.stat_result) -> None:
        self._stream, self._path, self._before, self._read = stream, path, before, 0

    def read(self, size: int = -1) -> bytes:
        data = self._stream.read(size)
        self._read += len(data)
        if self._read > self._before.st_size or (not data and self._read != self._before.st_size):
            raise ImportFileError(f"{self._path.name} changed while it was being read")
        if not data:
            _require_unchanged(self._path, self._before)
        return data


def _stat(path: Path) -> os.stat_result:
    try:
        return path.stat()
    except OSError as error:
        raise ImportFileError(f"cannot read {path.name} ({type(error).__name__})") from error


def _require_unchanged(path: Path, before: os.stat_result) -> None:
    after = _stat(path)
    if (after.st_size, after.st_mtime_ns) != (before.st_size, before.st_mtime_ns):
        raise ImportFileError(f"{path.name} changed while it was being read")


@dataclass(frozen=True, slots=True)
class ImportedSource:
    source_id: uuid.UUID
    artifact_id: uuid.UUID


def _no_checkpoint(step: str) -> None:
    """The import announces its steps here so a test can stop the process after any one."""


class ImportSourceUseCase:
    def __init__(
        self,
        unit_of_work: UnitOfWork,
        store: ManagedFileStore,
        *,
        new_id: Callable[[], uuid.UUID],
        clock: Callable[[], datetime],
        max_pixels: int,
        max_bytes: int,
        checkpoint: Callable[[str], None] = _no_checkpoint,
        video: Callable[[], VideoImport] | None = None,
    ) -> None:
        """`max_pixels` and `max_bytes` bound one image's memory and the file read for it; neither
        has a default, because both are measured choices. `video` is called only when a video
        arrives, so a missing FFmpeg install fails that import alone; without it a video is
        refused as unreadable."""
        self._uow = unit_of_work
        self._store = store
        self._new_id = new_id
        self._clock = clock
        self._max_pixels = max_pixels
        self._max_bytes = max_bytes
        self._checkpoint = checkpoint
        self._video = video

    # --- managed -----------------------------------------------------------------------------

    def import_managed(self, path: Path, *, display_name: str | None = None) -> ImportedSource:
        """Copy an image or a video into the library. Raises `ImageError`, `VideoError`,
        `SourceImportError` or `ValueError` (an empty name) before anything is written."""
        name = self._name(path, display_name)
        if is_video_name(path):
            video = self._video_import()
            before = self._check_size(path, video.max_bytes)
            facts = self._video_facts(video, path, before)
            try:
                stream = path.open("rb")
            except OSError as error:
                raise ImportFileError(
                    f"cannot read {path.name} ({type(error).__name__})"
                ) from error
            with stream:
                return self._store_managed(
                    cast(BinaryIO, _Unchanged(stream, path, before)), path.name, name, facts
                )
        data = self._read(path)
        return self._store_managed(io.BytesIO(data), path.name, name, self._image_facts(data))

    def _store_managed(
        self, data: BinaryIO, filename: str, name: str, facts: _Facts
    ) -> ImportedSource:
        artifact_id, key = self._uow.write(
            lambda session: self._reserve(session, filename, facts.mime_type)
        )
        self._checkpoint("reserved")
        try:
            stored = self._store.store(key, data)
        except Exception as error:
            detail = f"{type(error).__name__}: {error}"
            # Best effort: if even this write fails, the caller must still see why the file could
            # not be written, and the reservation stays PENDING for startup recovery to settle.
            with contextlib.suppress(Exception):
                self._uow.write(
                    lambda session: mark_write_not_completed(session, artifact_id, detail)
                )
            raise
        self._checkpoint("stored")
        source_id = self._uow.write(
            lambda session: self._publish(session, artifact_id, stored, name, facts)
        )
        self._checkpoint("committed")
        return ImportedSource(source_id, artifact_id)

    def _reserve(self, session: Session, filename: str, mime_type: str) -> tuple[uuid.UUID, str]:
        artifact = reserve_managed_artifact(
            session,
            ArtifactKind.SOURCE_ORIGINAL,
            new_id=self._new_id,
            clock=self._clock,
            mime_type=mime_type,
            original_filename=filename,
        )
        assert artifact.storage_key is not None  # (a managed artifact always has its key)
        return artifact.id, artifact.storage_key

    def _publish(
        self,
        session: Session,
        artifact_id: uuid.UUID,
        stored: StoredBytes,
        name: str,
        facts: _Facts,
    ) -> uuid.UUID:
        mark_artifact_available(session, artifact_id, stored, clock=self._clock)
        return self._add_source(session, artifact_id, name, facts)

    # --- referenced --------------------------------------------------------------------------

    def import_referenced(self, path: Path, *, display_name: str | None = None) -> ImportedSource:
        """Record an image or a video that stays where the user keeps it. The file is hashed and
        read, never written, moved or copied. Raises `ReferencedFileError` for a path that cannot
        be referenced (relative, unreadable, inside the application's own storage)."""
        name = self._name(path, display_name)
        if is_video_name(path):
            video = self._video_import()
            before = self._check_size(path, video.max_bytes)  # first: inspecting hashes all of it
            referenced = inspect_referenced_file(path, self._store.roots)
            if referenced.stored.size_bytes != before.st_size:
                raise ReferencedFileError(f"{path} changed while it was being read")
            facts = self._video_facts(video, referenced.path, before)
        else:
            self._check_size(path, self._max_bytes)
            referenced = inspect_referenced_file(path, self._store.roots)
            data = self._read(referenced.path)
            if hashlib.sha256(data).digest() != referenced.stored.sha256:
                raise ReferencedFileError(f"{path} changed while it was being read")
            facts = self._image_facts(data)

        def record(session: Session) -> ImportedSource:
            artifact = add_referenced_artifact(
                session,
                referenced,
                new_id=self._new_id,
                clock=self._clock,
                mime_type=facts.mime_type,
            )
            return ImportedSource(self._add_source(session, artifact.id, name, facts), artifact.id)

        return self._uow.write(record)

    # --- shared ------------------------------------------------------------------------------

    @staticmethod
    def _name(path: Path, display_name: str | None) -> str:
        name = (path.stem if display_name is None else display_name).strip()
        if not name:
            raise ValueError("a source needs a name")
        return name

    def _video_import(self) -> VideoImport:
        if self._video is None:
            raise ImportFileError("videos cannot be imported here")
        return self._video()

    @staticmethod
    def _check_size(path: Path, max_bytes: int) -> os.stat_result:
        found = _stat(path)
        if found.st_size > max_bytes:
            raise ImportFileTooLargeError(f"{path.name} is larger than the {max_bytes} allowed")
        return found

    def _image_facts(self, data: bytes) -> _Facts:
        decoded = decode_image(data, max_pixels=self._max_pixels)
        return _Facts(SourceKind.IMAGE, decoded.header.mime_type, decoded.width, decoded.height)

    @staticmethod
    def _video_facts(video: VideoImport, path: Path, before: os.stat_result) -> _Facts:
        facts = video.probe(path)
        _require_unchanged(path, before)
        rate = facts.frame_rate
        return _Facts(
            SourceKind.VIDEO,
            facts.mime_type,
            facts.width,
            facts.height,
            duration_ms=facts.duration_ms,
            frame_rate=None if rate is None else (rate.numerator, rate.denominator),
        )

    def _read(self, path: Path) -> bytes:
        """The whole file, up to the byte limit (one byte more is read to know it was exceeded)."""
        try:
            with path.open("rb") as stream:
                data = stream.read(self._max_bytes + 1)
        except OSError as error:
            raise ImportFileError(f"cannot read {path.name} ({type(error).__name__})") from error
        if len(data) > self._max_bytes:
            raise ImportFileTooLargeError(
                f"{path.name} is larger than the {self._max_bytes} allowed"
            )
        return data

    def _add_source(
        self, session: Session, artifact_id: uuid.UUID, name: str, facts: _Facts
    ) -> uuid.UUID:
        now = self._clock()
        rate = facts.frame_rate
        source = SourceRepository(session).add(
            Source(
                id=self._new_id(),
                kind=facts.kind,
                state=SourceState.ACTIVE,
                display_name=name,
                original_artifact_id=artifact_id,
                width=facts.width,  # as it is shown: the orientation is applied
                height=facts.height,
                media_duration_ms=facts.duration_ms,
                frame_rate_num=None if rate is None else rate[0],
                frame_rate_den=None if rate is None else rate[1],
                created_at=now,
                updated_at=now,
            )
        )
        return source.id
