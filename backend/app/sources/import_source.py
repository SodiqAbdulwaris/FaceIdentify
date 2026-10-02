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
"""

import contextlib
import hashlib
import io
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

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
from backend.infrastructure.media.image import DecodedImage, decode_image
from backend.infrastructure.storage.files import ManagedFileStore, StoredBytes
from backend.infrastructure.storage.referenced import ReferencedFileError, inspect_referenced_file


class SourceImportError(Exception):
    """A file that cannot be imported. Nothing of it is left behind."""


class ImportFileError(SourceImportError):
    """The file cannot be read."""


class ImportFileTooLargeError(SourceImportError):
    """The file has more bytes than the caller allows."""


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
    ) -> None:
        """`max_pixels` and `max_bytes` bound one image's memory and the file read for it; neither
        has a default, because both are measured choices."""
        self._uow = unit_of_work
        self._store = store
        self._new_id = new_id
        self._clock = clock
        self._max_pixels = max_pixels
        self._max_bytes = max_bytes
        self._checkpoint = checkpoint

    # --- managed -----------------------------------------------------------------------------

    def import_managed(self, path: Path, *, display_name: str | None = None) -> ImportedSource:
        """Copy an image into the library. Raises `ImageError`, `SourceImportError` or
        `ValueError` (an empty name) before anything is written."""
        name = self._name(path, display_name)
        data = self._read(path)
        decoded = decode_image(data, max_pixels=self._max_pixels)
        mime_type = decoded.header.mime_type

        artifact_id, key = self._uow.write(
            lambda session: self._reserve(session, path.name, mime_type)
        )
        self._checkpoint("reserved")
        try:
            stored = self._store.store(key, io.BytesIO(data))
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
            lambda session: self._publish(session, artifact_id, stored, name, decoded)
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
        decoded: DecodedImage,
    ) -> uuid.UUID:
        mark_artifact_available(session, artifact_id, stored, clock=self._clock)
        return self._add_source(session, artifact_id, name, decoded)

    # --- referenced --------------------------------------------------------------------------

    def import_referenced(self, path: Path, *, display_name: str | None = None) -> ImportedSource:
        """Record an image that stays where the user keeps it. The file is hashed, read and
        decoded, never written, moved or copied. Raises `ReferencedFileError` for a path that
        cannot be referenced (relative, unreadable, inside the application's own storage)."""
        name = self._name(path, display_name)
        try:  # the size first: inspecting a file hashes all of it
            size = path.stat().st_size
        except OSError as error:
            raise ImportFileError(f"cannot read {path.name} ({type(error).__name__})") from error
        if size > self._max_bytes:
            raise ImportFileTooLargeError(
                f"{path.name} is larger than the {self._max_bytes} allowed"
            )
        referenced = inspect_referenced_file(path, self._store.roots)
        data = self._read(referenced.path)
        if hashlib.sha256(data).digest() != referenced.stored.sha256:
            raise ReferencedFileError(f"{path} changed while it was being read")
        decoded = decode_image(data, max_pixels=self._max_pixels)

        def record(session: Session) -> ImportedSource:
            artifact = add_referenced_artifact(
                session,
                referenced,
                new_id=self._new_id,
                clock=self._clock,
                mime_type=decoded.header.mime_type,
            )
            return ImportedSource(
                self._add_source(session, artifact.id, name, decoded), artifact.id
            )

        return self._uow.write(record)

    # --- shared ------------------------------------------------------------------------------

    @staticmethod
    def _name(path: Path, display_name: str | None) -> str:
        name = (path.stem if display_name is None else display_name).strip()
        if not name:
            raise ValueError("a source needs a name")
        return name

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
        self, session: Session, artifact_id: uuid.UUID, name: str, decoded: DecodedImage
    ) -> uuid.UUID:
        now = self._clock()
        source = SourceRepository(session).add(
            Source(
                id=self._new_id(),
                kind=SourceKind.IMAGE,
                state=SourceState.ACTIVE,
                display_name=name,
                original_artifact_id=artifact_id,
                width=decoded.width,  # as it is shown: the orientation is applied
                height=decoded.height,
                created_at=now,
                updated_at=now,
            )
        )
        return source.id
