"""REFERENCED artifacts: external, user-owned originals the application never modifies or deletes.

API and Contracts.md §57: a referenced import inspects the external file first
(`backend.infrastructure.storage.referenced`), then one short transaction records
`Artifact(REFERENCED, AVAILABLE)` and its Source. `add_referenced_artifact` flushes but never
commits, for the same reason the managed primitives do.

The external file may later go missing, and that "is handled by availability state rather than
corrupting Source history" (§57). `reverify_referenced_artifact` moves an artifact between
AVAILABLE and MISSING; it never touches the Source row or the file. `relink_referenced_artifact`
points a MISSING artifact at a moved file, once it is verified to be the same media.
"""

import stat
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import cast

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.sources.artifact_storage import (
    ArtifactStateError,
    ArtifactStorageError,
    transition_artifact,
)
from backend.app.sources.models import Artifact, ArtifactKind, ArtifactState, StorageMode
from backend.infrastructure.storage.files import StoredBytes, digest_path
from backend.infrastructure.storage.layout import StorageRoots
from backend.infrastructure.storage.referenced import ReferencedFile, inspect_referenced_file

REFERENCED_FILE_MISSING = "REFERENCED_FILE_MISSING"
REFERENCED_CONTENT_CHANGED = "REFERENCED_CONTENT_CHANGED"


def add_referenced_artifact(
    session: Session,
    referenced: ReferencedFile,
    *,
    new_id: Callable[[], uuid.UUID],
    clock: Callable[[], datetime],
    mime_type: str | None = None,
) -> Artifact:
    """Record an inspected external file as an AVAILABLE referenced original."""
    now = clock()
    artifact = Artifact(
        id=new_id(),
        kind=ArtifactKind.SOURCE_ORIGINAL,
        storage_mode=StorageMode.REFERENCED,
        state=ArtifactState.AVAILABLE,
        external_path=str(referenced.path),
        sha256=referenced.stored.sha256,
        size_bytes=referenced.stored.size_bytes,
        mime_type=mime_type,
        original_filename=referenced.path.name,
        created_at=now,
        available_at=now,
    )
    session.add(artifact)
    session.flush()
    return artifact


def mark_missing_referenced_originals(
    session_factory: sessionmaker[Session], *, clock: Callable[[], datetime]
) -> list[uuid.UUID]:
    """Mark every AVAILABLE referenced original whose file is gone `MISSING`, by existence alone.

    Cheap enough for startup (IMPLEMENTATION_ARCHITECTURE.md §23.5, §25.13): it reads no file, so a
    library of large videos costs one `stat` each. It only ever moves AVAILABLE to MISSING. Whether
    a file that came back is the same media needs its content hashed, which is
    `reverify_referenced_artifact` or a relink, never a startup scan. A file that is present but
    cannot be examined (denied, unreachable drive) is left alone: that is not evidence it is gone.
    Returns the artifacts it marked; the Source rows are never touched.
    """
    with session_factory() as session:
        candidates = session.execute(
            select(Artifact.id, Artifact.external_path)
            .where(
                Artifact.storage_mode == StorageMode.REFERENCED,
                Artifact.state == ArtifactState.AVAILABLE,
            )
            .order_by(Artifact.created_at, Artifact.id)
        ).all()
    gone: list[uuid.UUID] = []
    for artifact_id, external_path in candidates:
        try:
            present = stat.S_ISREG(Path(cast("str", external_path)).stat().st_mode)
        except FileNotFoundError:
            present = False
        except OSError:
            continue
        if not present:
            gone.append(artifact_id)
    if not gone:
        return []
    with session_factory() as session:
        marked: list[uuid.UUID] = []
        for artifact_id in gone:
            try:
                transition_artifact(
                    session,
                    artifact_id,
                    {ArtifactState.AVAILABLE},
                    {
                        "state": ArtifactState.MISSING,
                        "failure_code": REFERENCED_FILE_MISSING,
                        "failure_detail": None,
                    },
                    storage_mode=StorageMode.REFERENCED,
                )
            except ArtifactStateError:
                continue  # settled by something else meanwhile
            marked.append(artifact_id)
        session.commit()
    return marked


def _matches(path: Path, size: int, recorded: StoredBytes | None) -> bool:
    """Whether the file at `path` is still the recorded content. The size check comes first so a
    changed multi-gigabyte video is not hashed just to learn it differs."""
    if recorded is None:
        return True
    return size == recorded.size_bytes and digest_path(path) == recorded


def _judge(path: Path, recorded: StoredBytes | None) -> tuple[ArtifactState, str | None]:
    """The state and failure code the file on disk implies.

    Only "there is nothing there" means missing, including a file that vanishes while it is read.
    `Path.is_file` would also report a denied or unreachable file as absent, so `stat` is used and
    every other `OSError` propagates: it is not evidence that the media is gone.
    """
    try:
        examined = path.stat()
        if not stat.S_ISREG(examined.st_mode):
            return ArtifactState.MISSING, REFERENCED_FILE_MISSING
        if _matches(path, examined.st_size, recorded):
            return ArtifactState.AVAILABLE, None
    except (FileNotFoundError, IsADirectoryError):
        return ArtifactState.MISSING, REFERENCED_FILE_MISSING
    return ArtifactState.MISSING, REFERENCED_CONTENT_CHANGED


def _referenced(artifact: Artifact | None, artifact_id: uuid.UUID) -> Artifact:
    if artifact is None or artifact.storage_mode != StorageMode.REFERENCED:
        where = "does not exist" if artifact is None else f"is {artifact.storage_mode}"
        raise ArtifactStateError(f"artifact {artifact_id} {where}; expected REFERENCED")
    return artifact


def reverify_referenced_artifact(
    session_factory: sessionmaker[Session], artifact_id: uuid.UUID, *, clock: Callable[[], datetime]
) -> str:
    """Compare a referenced original with the file on disk and record the result.

    A missing file makes the artifact MISSING (`REFERENCED_FILE_MISSING`); a file whose size or
    hash no longer matches also does (`REFERENCED_CONTENT_CHANGED`), since a different file is
    replacement, not the original. Only a file that matches the recorded fingerprint makes a
    MISSING artifact AVAILABLE again. A file that is present but cannot be read (locked, no
    permission) raises `OSError` and changes nothing: it is not evidence that the media is gone.
    Returns the resulting state. The file is read outside any transaction.
    """
    with session_factory() as session:
        artifact = _referenced(session.get(Artifact, artifact_id), artifact_id)
        if artifact.state not in {ArtifactState.AVAILABLE, ArtifactState.MISSING}:
            raise ArtifactStateError(
                f"artifact {artifact_id} is REFERENCED {artifact.state}; "
                "expected AVAILABLE or MISSING"
            )
        state, failure_code = artifact.state, artifact.failure_code
        path = Path(cast("str", artifact.external_path))
        recorded = (
            None
            if artifact.sha256 is None or artifact.size_bytes is None
            else StoredBytes(artifact.sha256, artifact.size_bytes)
        )

    new_state, new_code = _judge(path, recorded)
    if (new_state, new_code) == (state, failure_code):
        return str(state)

    with session_factory() as session:
        transition_artifact(
            session,
            artifact_id,
            {state},
            {"state": new_state, "failure_code": new_code, "failure_detail": None},
            storage_mode=StorageMode.REFERENCED,
        )
        session.commit()
    return str(new_state)


class RelinkMismatchError(ArtifactStorageError):
    """The candidate is not the recorded media: that is replacement, not relinking (§59)."""


def relink_referenced_artifact(
    session_factory: sessionmaker[Session],
    roots: StorageRoots,
    artifact_id: uuid.UUID,
    candidate: Path,
    *,
    clock: Callable[[], datetime],
) -> None:
    """Point a MISSING referenced original at the file the user selected ("Locate File").

    API and Contracts.md §59: relinking "must verify that the selected candidate represents the
    expected underlying media"; different media is replacement. The candidate must match the
    recorded size and SHA-256 exactly, so an artifact with no recorded fingerprint cannot be
    relinked (nothing to verify against). Only a MISSING artifact is relinked; V1 never searches
    a disk for it. The candidate is inspected outside any transaction and is never modified.
    """
    with session_factory() as session:
        artifact = _referenced(session.get(Artifact, artifact_id), artifact_id)
        if artifact.state != ArtifactState.MISSING:
            raise ArtifactStateError(
                f"artifact {artifact_id} is REFERENCED {artifact.state}; expected MISSING"
            )
        if artifact.sha256 is None or artifact.size_bytes is None:
            raise ArtifactStorageError(
                f"artifact {artifact_id} has no recorded fingerprint to verify a relink against"
            )
        recorded = StoredBytes(artifact.sha256, artifact.size_bytes)

    inspected = inspect_referenced_file(candidate, roots)
    if inspected.stored != recorded:
        raise RelinkMismatchError(
            f"{candidate.name!r} is not the media artifact {artifact_id} recorded"
        )

    with session_factory() as session:
        transition_artifact(
            session,
            artifact_id,
            {ArtifactState.MISSING},
            {
                "state": ArtifactState.AVAILABLE,
                "external_path": str(inspected.path),
                "failure_code": None,
                "failure_detail": None,
            },
            storage_mode=StorageMode.REFERENCED,
        )
        session.commit()
