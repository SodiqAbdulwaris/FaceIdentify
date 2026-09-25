"""Managed artifact lifecycle: the `artifacts` table kept consistent with bytes on disk.

PERSISTENCE_IMPLEMENTATION.md §4.1: "Managed creation is a three-step protocol: commit a `PENDING`
row; write to a temporary file, hash/verify, then atomically rename; commit `AVAILABLE` plus the
final key/hash/size... Deletion is symmetrical: commit deletion intent, remove the managed bytes,
then finalize the row. A referenced file is never physically deleted by this application."

The primitives (`reserve_managed_artifact`, `mark_artifact_available`, `request_artifact_deletion`,
`finalize_artifact_deletion`) flush but never commit, so a caller such as source import can put
`AVAILABLE` and its new Source in one transaction (API and Contracts.md §56). The orchestrators
(`create_managed_artifact`, `delete_managed_artifact`, `recover_artifacts`) own their commits
because filesystem work must happen *between* transactions, never inside one (§1 rule 3).
"""

import uuid
from collections.abc import Callable, Collection
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO, cast

from sqlalchemy import CursorResult, select, update
from sqlalchemy.orm import Session, sessionmaker

from backend.app.sources.models import Artifact, ArtifactKind, ArtifactState, StorageMode
from backend.infrastructure.storage.files import ManagedFileStore, StoredBytes
from backend.infrastructure.storage.layout import UnsafeStorageKeyError

KIND_DIRECTORIES = {
    ArtifactKind.SOURCE_ORIGINAL: "originals",
    ArtifactKind.FACE_CROP: "crops",
    ArtifactKind.THUMBNAIL: "thumbnails",
    ArtifactKind.MODEL_EXPORT: "models",
}

# Recorded on a reservation whose bytes never reached their final key (the write failed, or the
# process died before the rename). The Artifact enum has no FAILED state; MISSING is the state for
# "a verified failure to resolve bytes" (§4.1), and nothing references such a row.
WRITE_NOT_COMPLETED = "WRITE_NOT_COMPLETED"
DELETE_ERROR = "DELETE_ERROR"


class ArtifactStorageError(Exception):
    """A managed-artifact operation that is not valid for the artifact's current state."""


class ArtifactStateError(ArtifactStorageError):
    """The artifact is missing, not managed, or not in a state this transition starts from."""


def storage_key_for(kind: str, artifact_id: uuid.UUID) -> str:
    """ID-oriented managed key (IMPLEMENTATION_ARCHITECTURE.md §16.3: never name-oriented)."""
    if kind == ArtifactKind.RUNTIME_PACKAGE:
        # API and Contracts.md §54: "Runtime/model artifacts remain under the specialized runtime
        # package layer"; runtime packages are machine-specific and live in machine-local state.
        raise ArtifactStorageError("runtime packages are not stored in the library")
    # ponytail: one flat directory per kind; shard by id prefix if one grows past ~100k files.
    return f"{KIND_DIRECTORIES[ArtifactKind(kind)]}/{artifact_id.hex}"


def _transition(
    session: Session,
    artifact_id: uuid.UUID,
    from_states: Collection[str],
    values: dict[str, Any],
) -> None:
    """Move one managed artifact between states, guarded by its current state in the database."""
    result = cast(
        "CursorResult[Any]",
        session.execute(
            update(Artifact)
            .where(
                Artifact.id == artifact_id,
                Artifact.storage_mode == StorageMode.MANAGED,
                Artifact.state.in_(from_states),
            )
            .values(**values),
            execution_options={"synchronize_session": False},
        ),
    )
    if result.rowcount == 0:
        current = session.get(Artifact, artifact_id, populate_existing=True)
        where = (
            "does not exist" if current is None else f"is {current.storage_mode} {current.state}"
        )
        raise ArtifactStateError(
            f"artifact {artifact_id} {where}; expected MANAGED in {sorted(from_states)}"
        )


# --- creation ---------------------------------------------------------------------------------


def reserve_managed_artifact(
    session: Session,
    kind: str,
    *,
    new_id: Callable[[], uuid.UUID],
    clock: Callable[[], datetime],
    mime_type: str | None = None,
    original_filename: str | None = None,
) -> Artifact:
    """Step 1: a PENDING row that owns its final storage key before any byte is written."""
    artifact_id = new_id()
    artifact = Artifact(
        id=artifact_id,
        kind=kind,
        storage_mode=StorageMode.MANAGED,
        state=ArtifactState.PENDING,
        storage_key=storage_key_for(kind, artifact_id),
        mime_type=mime_type,
        original_filename=original_filename,
        created_at=clock(),
    )
    session.add(artifact)
    session.flush()
    return artifact


def mark_artifact_available(
    session: Session,
    artifact_id: uuid.UUID,
    stored: StoredBytes,
    *,
    clock: Callable[[], datetime],
) -> None:
    """Step 3: record the verified hash and size and make the artifact AVAILABLE."""
    _transition(
        session,
        artifact_id,
        {ArtifactState.PENDING},
        {
            "state": ArtifactState.AVAILABLE,
            "sha256": stored.sha256,
            "size_bytes": stored.size_bytes,
            "available_at": clock(),
            "failure_code": None,
            "failure_detail": None,
        },
    )


def _mark_write_not_completed(session: Session, artifact_id: uuid.UUID, detail: str) -> None:
    _transition(
        session,
        artifact_id,
        {ArtifactState.PENDING},
        {
            "state": ArtifactState.MISSING,
            "failure_code": WRITE_NOT_COMPLETED,
            "failure_detail": detail[:500],
        },
    )


def create_managed_artifact(
    session_factory: sessionmaker[Session],
    store: ManagedFileStore,
    kind: str,
    source: BinaryIO,
    *,
    new_id: Callable[[], uuid.UUID],
    clock: Callable[[], datetime],
    mime_type: str | None = None,
    original_filename: str | None = None,
) -> uuid.UUID:
    """All three steps, each transaction short and none held open across the file write."""
    with session_factory() as session:
        artifact = reserve_managed_artifact(
            session, kind, new_id=new_id, clock=clock,
            mime_type=mime_type, original_filename=original_filename,
        )  # fmt: skip
        artifact_id, storage_key = artifact.id, artifact.storage_key
        session.commit()
    assert storage_key is not None  # set by reserve_managed_artifact

    try:
        stored = store.store(storage_key, source)
    except Exception as error:
        with session_factory() as session:
            _mark_write_not_completed(session, artifact_id, f"{type(error).__name__}: {error}")
            session.commit()
        raise

    with session_factory() as session:
        mark_artifact_available(session, artifact_id, stored, clock=clock)
        session.commit()
    return artifact_id


# --- deletion ---------------------------------------------------------------------------------

DELETABLE_STATES = {ArtifactState.AVAILABLE, ArtifactState.MISSING, ArtifactState.DELETE_FAILED}


def request_artifact_deletion(
    session: Session, artifact_id: uuid.UUID, *, clock: Callable[[], datetime]
) -> None:
    """Step 1 of deletion: durable intent. Refuses REFERENCED artifacts: their bytes are the
    user's, and this application never deletes them (API and Contracts.md §52)."""
    _transition(
        session,
        artifact_id,
        DELETABLE_STATES,
        {"state": ArtifactState.DELETING, "delete_requested_at": clock()},
    )


def finalize_artifact_deletion(
    session: Session, artifact_id: uuid.UUID, *, clock: Callable[[], datetime]
) -> None:
    """Step 3 of deletion, once the bytes are verified gone."""
    _transition(
        session,
        artifact_id,
        {ArtifactState.DELETING, ArtifactState.DELETE_FAILED},
        {"state": ArtifactState.DELETED, "deleted_at": clock(), "failure_code": None,
         "failure_detail": None},
    )  # fmt: skip


def _record_delete_failure(session: Session, artifact_id: uuid.UUID, detail: str) -> None:
    _transition(
        session,
        artifact_id,
        {ArtifactState.DELETING, ArtifactState.DELETE_FAILED},
        {
            "state": ArtifactState.DELETE_FAILED,
            "failure_code": DELETE_ERROR,
            "failure_detail": detail[:500],
        },
    )


def _storage_key(session: Session, artifact_id: uuid.UUID) -> str:
    """Only called after a guarded transition proved the row exists and is MANAGED, and the
    `location` CHECK constraint requires every MANAGED row to carry a key."""
    artifact = session.get(Artifact, artifact_id, populate_existing=True)
    assert artifact is not None
    assert artifact.storage_key is not None
    return artifact.storage_key


def delete_managed_artifact(
    session_factory: sessionmaker[Session],
    store: ManagedFileStore,
    artifact_id: uuid.UUID,
    *,
    clock: Callable[[], datetime],
) -> None:
    """Intent, then bytes, then finalization. A filesystem failure leaves DELETE_FAILED (which
    recovery retries) and re-raises. Whether the artifact *should* be deleted is the caller's
    decision (API and Contracts.md §51)."""
    with session_factory() as session:
        request_artifact_deletion(session, artifact_id, clock=clock)
        storage_key = _storage_key(session, artifact_id)
        session.commit()

    try:
        store.delete(storage_key)
    except OSError as error:
        with session_factory() as session:
            _record_delete_failure(session, artifact_id, f"{type(error).__name__}: {error}")
            session.commit()
        raise

    with session_factory() as session:
        finalize_artifact_deletion(session, artifact_id, clock=clock)
        session.commit()


# --- integrity --------------------------------------------------------------------------------


def verify_artifact(store: ManagedFileStore, artifact: Artifact) -> bool:
    """True when an AVAILABLE managed artifact's bytes exist and match its recorded hash/size."""
    if (
        artifact.storage_mode != StorageMode.MANAGED
        or artifact.state != ArtifactState.AVAILABLE
        or artifact.storage_key is None
    ):
        raise ArtifactStateError(f"artifact {artifact.id} is not an AVAILABLE managed artifact")
    return store.digest(artifact.storage_key) == StoredBytes(
        cast("bytes", artifact.sha256), cast("int", artifact.size_bytes)
    )


# --- startup recovery and consistency scan ----------------------------------------------------


@dataclass
class RecoveryReport:
    finalized: list[uuid.UUID] = field(default_factory=list)
    write_not_completed: list[uuid.UUID] = field(default_factory=list)
    deleted: list[uuid.UUID] = field(default_factory=list)
    delete_failed: list[uuid.UUID] = field(default_factory=list)
    staging_removed: list[str] = field(default_factory=list)
    # Rows left untouched because a file could not be read or a key is unusable; retried next start.
    skipped: list[tuple[uuid.UUID, str]] = field(default_factory=list)
    # Staging files recovery does not own (no PENDING artifact of its own), or could not remove.
    staging_left: list[str] = field(default_factory=list)


def _managed_in(session: Session, states: Collection[str]) -> list[tuple[uuid.UUID, str]]:
    rows = session.execute(
        select(Artifact.id, Artifact.storage_key)
        .where(Artifact.storage_mode == StorageMode.MANAGED, Artifact.state.in_(states))
        .order_by(Artifact.created_at, Artifact.id)
    ).all()
    return [(row.id, cast("str", row.storage_key)) for row in rows]


def _describe(error: BaseException) -> str:
    return f"{type(error).__name__}: {error}"


def recover_artifacts(
    session_factory: sessionmaker[Session],
    store: ManagedFileStore,
    *,
    clock: Callable[[], datetime],
) -> RecoveryReport:
    """Settle every interrupted managed write and deletion (PERSISTENCE_IMPLEMENTATION.md §28).

    Precondition: runs at startup, before this process writes managed bytes, and with no other
    process using the library (single-instance is the desktop shell's job, tech-stack.md §2; a
    library shared between machines is CONTEXT open question 23). Under it, every PENDING artifact
    belongs to a process that no longer exists.

    Idempotent, and tolerant: one unreadable file or unusable key is reported in `skipped` and left
    for the next start instead of aborting recovery. Only the staging files of the PENDING artifacts
    it settles are removed ("clean owned temp data", §28); any other is reported, not deleted.
    """
    report = RecoveryReport()
    with session_factory() as session:
        pending = _managed_in(session, {ArtifactState.PENDING})
        deleting = _managed_in(session, {ArtifactState.DELETING, ArtifactState.DELETE_FAILED})

    owned_staging: set[Path] = set()
    for artifact_id, storage_key in pending:
        # A file at the final key is complete by construction: only a finished, fsynced write is
        # ever renamed there. The lost step was the AVAILABLE commit, so hash it and finish it.
        try:
            stored = store.digest(storage_key)
            staged = store.staging_path(storage_key)
        except (OSError, UnsafeStorageKeyError) as error:
            report.skipped.append((artifact_id, _describe(error)))
            continue
        with session_factory() as session:
            if stored is not None:
                mark_artifact_available(session, artifact_id, stored, clock=clock)
                report.finalized.append(artifact_id)
            else:
                _mark_write_not_completed(session, artifact_id, "interrupted before finalization")
                report.write_not_completed.append(artifact_id)
            session.commit()
        owned_staging.add(staged)

    for artifact_id, storage_key in deleting:
        try:
            store.delete(storage_key)
        except UnsafeStorageKeyError as error:
            report.skipped.append((artifact_id, _describe(error)))
            continue
        except OSError as error:
            with session_factory() as session:
                _record_delete_failure(session, artifact_id, _describe(error))
                session.commit()
            report.delete_failed.append(artifact_id)
            continue
        with session_factory() as session:
            finalize_artifact_deletion(session, artifact_id, clock=clock)
            session.commit()
        report.deleted.append(artifact_id)

    for staged in store.staging_files():
        if staged not in owned_staging:
            report.staging_left.append(staged.name)
            continue
        try:
            staged.unlink(missing_ok=True)
        except OSError:
            report.staging_left.append(staged.name)
            continue
        report.staging_removed.append(staged.name)
    return report


@dataclass(frozen=True)
class StorageScan:
    """Inconsistencies between `artifacts` and the managed directories. Reported, never repaired."""

    missing: list[uuid.UUID]
    orphans: list[str]
    stray_staging: list[str]
    unsafe_keys: list[uuid.UUID]

    @property
    def clean(self) -> bool:
        return not (self.missing or self.orphans or self.stray_staging or self.unsafe_keys)


def scan_storage(session: Session, store: ManagedFileStore) -> StorageScan:
    """AVAILABLE managed artifacts with no file, files no live artifact owns, leftover staging
    files, and rows whose key is unusable (processing-architecture-v1.md §19). Existence only;
    `verify_artifact` hashes."""
    rows = session.execute(
        select(Artifact.id, Artifact.state, Artifact.storage_key).where(
            Artifact.storage_mode == StorageMode.MANAGED,
            Artifact.state != ArtifactState.DELETED,
        )
    ).all()
    owned = {cast("str", row.storage_key) for row in rows}
    missing: list[uuid.UUID] = []
    unsafe: list[uuid.UUID] = []
    for row in rows:
        try:
            path = store.roots.path_for(cast("str", row.storage_key))
        except UnsafeStorageKeyError:
            unsafe.append(row.id)
            continue
        if row.state == ArtifactState.AVAILABLE and not path.is_file():
            missing.append(row.id)
    orphans = [key for key in store.managed_files() if key not in owned]
    stray = [path.name for path in store.staging_files()]
    return StorageScan(sorted(missing), orphans, stray, sorted(unsafe))
