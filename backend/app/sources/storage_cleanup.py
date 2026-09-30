"""Conservative cleanup of managed artifacts that nothing references.

IMPLEMENTATION_ARCHITECTURE.md §16.7 and API and Contracts.md §51 ("conservative cleanup"). This is
the narrowest useful case: an AVAILABLE managed artifact that no row anywhere points at, past a
grace period. Such an artifact appears when an import's bytes were stored and its final commit then
failed (startup recovery finishes the artifact, and nothing references it: artifact_storage review
M2), or when a Source was deleted and its artifacts were not.

What this never touches, by design:

* a REFERENCED artifact: the file is the user's (§52);
* an artifact in any state but AVAILABLE, or any row something references (the references are read
  from the schema, see `artifact_references`), including a recycled Source's files;
* files on disk that no row owns. `scan_storage` reports them. They are not deleted because the row
  that owned one may simply have been lost (a database restored from an older backup), and then the
  file is the only copy: the cost of keeping a stray file is disk space, of deleting it is the data.

Deletion goes through the crash-safe protocol (intent, bytes, finalize), and the "nothing
references it" test is part of the intent's UPDATE, so an artifact that gets referenced after it was
chosen is skipped instead of deleted.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.sources.artifact_references import unreferenced_artifacts
from backend.app.sources.artifact_storage import ArtifactStateError, delete_managed_artifact
from backend.app.sources.models import Artifact, ArtifactState, StorageMode
from backend.infrastructure.storage.files import ManagedFileStore


@dataclass
class CleanupReport:
    deleted: list[uuid.UUID] = field(default_factory=list)
    # Chosen, then found referenced or changed by the time the intent was recorded: left alone.
    skipped: list[uuid.UUID] = field(default_factory=list)
    # The bytes could not be removed; the artifact is DELETE_FAILED and startup recovery retries it.
    failed: list[tuple[uuid.UUID, str]] = field(default_factory=list)


def find_unreferenced_artifacts(session: Session, *, older_than: datetime) -> list[uuid.UUID]:
    """AVAILABLE managed artifacts no row references, whose availability is older than the cutoff.

    `older_than` has no default: it is the grace period that keeps a just-stored artifact, whose
    Source is about to be committed, from being collected, and the caller knows its own windows.
    """
    available_since = func.coalesce(Artifact.available_at, Artifact.created_at)
    return list(
        session.scalars(
            select(Artifact.id)
            .where(
                Artifact.storage_mode == StorageMode.MANAGED,
                Artifact.state == ArtifactState.AVAILABLE,
                available_since < older_than,
                unreferenced_artifacts(),
            )
            .order_by(available_since, Artifact.id)
        )
    )


def cleanup_unreferenced_artifacts(
    session_factory: sessionmaker[Session],
    store: ManagedFileStore,
    *,
    older_than: datetime,
    clock: Callable[[], datetime],
) -> CleanupReport:
    """Delete every unreferenced managed artifact older than the cutoff. Tolerant: one that cannot
    be deleted is reported and does not stop the rest."""
    with session_factory() as session:
        candidates = find_unreferenced_artifacts(session, older_than=older_than)

    report = CleanupReport()
    for artifact_id in candidates:
        try:
            delete_managed_artifact(
                session_factory, store, artifact_id, clock=clock, only_if_unreferenced=True
            )
        except ArtifactStateError:
            report.skipped.append(artifact_id)
        except OSError as error:
            report.failed.append((artifact_id, f"{type(error).__name__}: {error}"))
        else:
            report.deleted.append(artifact_id)
    return report
