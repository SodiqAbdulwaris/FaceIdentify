"""Bring a missing original back: on-access verification and manual recovery (issue #179).

Owner decision 2026-10-14 (locked): when a source whose original is `MISSING` is opened or used,
its original is verified again before it is treated as available; "Recheck File" does the same on
request, and "Locate Original" relinks a referenced original (`relink_referenced_artifact`). There
is no startup scan and no periodic recheck. A recheck only ever moves `MISSING` to `AVAILABLE`
through the existing verifiers, which compare the file with the recorded size and SHA-256: a file
that differs is not the original, and the source stays missing. It never touches the Source row,
its faces or its history, and a repeat is harmless.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.sources.artifact_storage import (
    MANAGED_FILE_MISSING,
    ArtifactStateError,
    reverify_managed_artifact,
    transition_artifact,
)
from backend.app.sources.models import Artifact, ArtifactState, Source, StorageMode
from backend.app.sources.referenced_artifacts import reverify_referenced_artifact
from backend.infrastructure.storage.files import ManagedFileStore

# A managed original's file is back in its place but is not the recorded bytes (the managed twin of
# `REFERENCED_CONTENT_CHANGED`): the user is told it changed, not to put a file back that is there.
MANAGED_CONTENT_CHANGED = "MANAGED_CONTENT_CHANGED"


class OriginalUnreadableError(Exception):
    """The file is there but could not be read (locked, no permission): nothing was changed."""


class OriginalUnverifiableError(Exception):
    """The original has no recorded fingerprint, so a file in its place cannot be shown to be it:
    it stays missing (a file's mere presence is never proof)."""


@dataclass(frozen=True, slots=True)
class Recheck:
    state: str  # the original's availability afterwards
    reason: str | None  # why it is still not available (the artifact's failure code)
    recovered: bool  # it was MISSING and is AVAILABLE now


def _original(session: Session, source_id: uuid.UUID) -> Artifact | None:
    return session.execute(
        select(Artifact)
        .join(Source, Source.original_artifact_id == Artifact.id)
        .where(Source.id == source_id)
    ).scalar_one_or_none()


def recheck_original(
    session_factory: sessionmaker[Session],
    store: ManagedFileStore,
    source_id: uuid.UUID,
    *,
    clock: Callable[[], datetime],
) -> Recheck:
    """Verify a `MISSING` original again; an original in any other state is left as it is.

    Raises `LookupError` if the source does not exist, `OriginalUnreadableError` if the file is
    present but cannot be read, and `OriginalUnverifiableError` for a referenced original with no
    recorded size and SHA-256 (nothing to verify a file against; the referenced verifier would
    otherwise accept any file by its presence). The file is read outside any transaction.
    """
    with session_factory() as session:
        artifact = _original(session, source_id)
        if artifact is None:
            raise LookupError(f"source {source_id} does not exist")
        artifact_id, mode, before = artifact.id, artifact.storage_mode, artifact.state
        key, fingerprinted = (
            artifact.storage_key,
            None not in (artifact.sha256, artifact.size_bytes),
        )
    if before == ArtifactState.MISSING:
        if not fingerprinted:
            raise OriginalUnverifiableError(f"artifact {artifact_id} has no recorded fingerprint")
        try:
            if mode == StorageMode.MANAGED:
                assert key is not None  # a MANAGED artifact always has a key (CHECK)
                if reverify_managed_artifact(session_factory, store, artifact_id) != "AVAILABLE":
                    _say_why_managed_is_missing(session_factory, store, artifact_id, key)
            else:
                reverify_referenced_artifact(session_factory, artifact_id, clock=clock)
        except ArtifactStateError:
            pass  # settled by a concurrent recheck or relink: the state read below is the answer
        except OSError as error:
            raise OriginalUnreadableError(str(error)) from error
    with session_factory() as session:
        after = session.get(Artifact, artifact_id)
        assert after is not None  # artifact rows are never deleted (a deleted one is DELETED)
        reason = None if after.state == ArtifactState.AVAILABLE else after.failure_code
        return Recheck(
            str(after.state),
            reason,
            before == ArtifactState.MISSING and after.state == ArtifactState.AVAILABLE,
        )


def _say_why_managed_is_missing(
    session_factory: sessionmaker[Session],
    store: ManagedFileStore,
    artifact_id: uuid.UUID,
    key: str,
) -> None:
    """Record whether a still-missing managed original is absent or there but different."""
    code = MANAGED_CONTENT_CHANGED if store.roots.path_for(key).is_file() else MANAGED_FILE_MISSING
    with session_factory() as session:
        transition_artifact(
            session,
            artifact_id,
            {ArtifactState.MISSING},
            {"failure_code": code},
        )
        session.commit()
