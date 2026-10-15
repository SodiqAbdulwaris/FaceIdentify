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

from backend.app.sources.artifact_storage import ArtifactStateError, reverify_managed_artifact
from backend.app.sources.models import Artifact, ArtifactState, Source, StorageMode
from backend.app.sources.referenced_artifacts import reverify_referenced_artifact
from backend.infrastructure.storage.files import ManagedFileStore


class OriginalUnreadableError(Exception):
    """The file is there but could not be read (locked, no permission): nothing was changed."""


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

    Raises `LookupError` if the source does not exist and `OriginalUnreadableError` if the file is
    present but cannot be read. The file is read outside any transaction (the verifiers' rule).
    """
    with session_factory() as session:
        artifact = _original(session, source_id)
        if artifact is None:
            raise LookupError(f"source {source_id} does not exist")
        artifact_id, mode, before = artifact.id, artifact.storage_mode, artifact.state
    if before == ArtifactState.MISSING:
        try:
            if mode == StorageMode.MANAGED:
                reverify_managed_artifact(session_factory, store, artifact_id)
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
