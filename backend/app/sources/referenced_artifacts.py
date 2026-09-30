"""REFERENCED artifacts: external, user-owned originals the application never modifies or deletes.

API and Contracts.md §57: a referenced import inspects the external file first
(`backend.infrastructure.storage.referenced`), then one short transaction records
`Artifact(REFERENCED, AVAILABLE)` and its Source. `add_referenced_artifact` flushes but never
commits, for the same reason the managed primitives do.

The external file may later go missing, and that "is handled by availability state rather than
corrupting Source history" (§57). `reverify_referenced_artifact` moves an artifact between
AVAILABLE and MISSING; it never touches the Source row or the file. Relinking a moved file is
`relink_referenced_artifact`.
"""

import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import cast

from sqlalchemy.orm import Session, sessionmaker

from backend.app.sources.artifact_storage import ArtifactStateError, transition_artifact
from backend.app.sources.models import Artifact, ArtifactKind, ArtifactState, StorageMode
from backend.infrastructure.storage.files import StoredBytes, digest_path
from backend.infrastructure.storage.referenced import ReferencedFile

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


def _matches(path: Path, recorded: StoredBytes | None) -> bool:
    """Whether the file at `path` is still the recorded content. The size check comes first so a
    changed multi-gigabyte video is not hashed just to learn it differs."""
    if recorded is None:
        return True
    return path.stat().st_size == recorded.size_bytes and digest_path(path) == recorded


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

    if not path.is_file():
        new_state, new_code = ArtifactState.MISSING, REFERENCED_FILE_MISSING
    elif _matches(path, recorded):
        new_state, new_code = ArtifactState.AVAILABLE, None
    else:
        new_state, new_code = ArtifactState.MISSING, REFERENCED_CONTENT_CHANGED
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
