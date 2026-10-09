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

import stat
import uuid
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO, cast

from sqlalchemy import ColumnElement, CursorResult, select, update
from sqlalchemy.orm import Session, sessionmaker

from backend.app.sources.artifact_references import unreferenced_artifacts
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
# An AVAILABLE managed artifact whose file is no longer where its key says (removed behind the
# application's back, or a database restored from a newer state than the files).
MANAGED_FILE_MISSING = "MANAGED_FILE_MISSING"


class ArtifactStorageError(Exception):
    """A managed-artifact operation that is not valid for the artifact's current state."""


class LibraryRootUnavailableError(ArtifactStorageError):
    """The library root is not there (an unmounted drive, a moved folder). Nothing can be concluded
    about any managed file, so nothing may be marked missing or recovered from its absence."""


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


def transition_artifact(
    session: Session,
    artifact_id: uuid.UUID,
    from_states: Collection[str],
    values: dict[str, Any],
    *,
    storage_mode: str = StorageMode.MANAGED,
    extra_where: Sequence[ColumnElement[bool]] = (),
) -> None:
    """Move one artifact between states, guarded by its current state in the database (and by
    `extra_where`, evaluated there too)."""
    result = cast(
        "CursorResult[Any]",
        session.execute(
            update(Artifact)
            .where(
                Artifact.id == artifact_id,
                Artifact.storage_mode == storage_mode,
                Artifact.state.in_(from_states),
                *extra_where,
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
            f"artifact {artifact_id} {where}; expected {storage_mode} in {sorted(from_states)}"
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
    transition_artifact(
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


def mark_write_not_completed(session: Session, artifact_id: uuid.UUID, detail: str) -> None:
    """A reservation whose bytes never reached their key: MISSING, with the reason. For a caller
    that does the three steps itself (the primitives above) and whose write failed."""
    transition_artifact(
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
            mark_write_not_completed(session, artifact_id, f"{type(error).__name__}: {error}")
            session.commit()
        raise

    with session_factory() as session:
        mark_artifact_available(session, artifact_id, stored, clock=clock)
        session.commit()
    return artifact_id


# --- deletion ---------------------------------------------------------------------------------

DELETABLE_STATES = {ArtifactState.AVAILABLE, ArtifactState.MISSING, ArtifactState.DELETE_FAILED}


def request_artifact_deletion(
    session: Session,
    artifact_id: uuid.UUID,
    *,
    clock: Callable[[], datetime],
    only_if_unreferenced: bool = False,
) -> None:
    """Step 1 of deletion: durable intent. Refuses REFERENCED artifacts: their bytes are the
    user's, and this application never deletes them (API and Contracts.md §52).

    `only_if_unreferenced` also requires, in the same UPDATE, that no row anywhere points at the
    artifact, so one that became referenced after it was chosen for cleanup is left alone."""
    transition_artifact(
        session,
        artifact_id,
        DELETABLE_STATES,
        {"state": ArtifactState.DELETING, "delete_requested_at": clock()},
        extra_where=[unreferenced_artifacts()] if only_if_unreferenced else (),
    )


def finalize_artifact_deletion(
    session: Session, artifact_id: uuid.UUID, *, clock: Callable[[], datetime]
) -> None:
    """Step 3 of deletion, once the bytes are verified gone."""
    transition_artifact(
        session,
        artifact_id,
        {ArtifactState.DELETING, ArtifactState.DELETE_FAILED},
        {"state": ArtifactState.DELETED, "deleted_at": clock(), "failure_code": None,
         "failure_detail": None},
    )  # fmt: skip


def _record_delete_failure(session: Session, artifact_id: uuid.UUID, detail: str) -> None:
    transition_artifact(
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
    only_if_unreferenced: bool = False,
) -> None:
    """Intent, then bytes, then finalization. A filesystem failure leaves DELETE_FAILED (which
    recovery retries) and re-raises. Whether the artifact *should* be deleted is the caller's
    decision (API and Contracts.md §51)."""
    with session_factory() as session:
        request_artifact_deletion(
            session, artifact_id, clock=clock, only_if_unreferenced=only_if_unreferenced
        )
        storage_key = _storage_key(session, artifact_id)
        # Before the intent is committed: a key that can never be resolved would otherwise leave
        # the artifact DELETING with no way to finish.
        store.roots.path_for(storage_key)
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


def complete_artifact_deletion(
    session_factory: sessionmaker[Session],
    store: ManagedFileStore,
    artifact_id: uuid.UUID,
    *,
    clock: Callable[[], datetime],
) -> None:
    """Steps 2 and 3 for an artifact whose intent is already recorded (`DELETING`, or
    `DELETE_FAILED` from an earlier try): remove the bytes (and a write that never finished), then
    finalize. A filesystem failure leaves `DELETE_FAILED` (which recovery retries) and re-raises.
    Safe to repeat, and to run twice at once: an artifact someone else finished is left alone."""
    with session_factory() as session:
        artifact = session.get(Artifact, artifact_id)
        if artifact is not None and artifact.state == ArtifactState.DELETED:
            return
        if (
            artifact is None
            or artifact.storage_mode != StorageMode.MANAGED
            or artifact.state not in {ArtifactState.DELETING, ArtifactState.DELETE_FAILED}
            or artifact.storage_key is None
        ):
            raise ArtifactStateError(f"artifact {artifact_id} has no deletion intent to complete")
        storage_key = artifact.storage_key
    try:
        store.delete(storage_key)
        store.staging_path(storage_key).unlink(missing_ok=True)
    except OSError as error:
        with session_factory() as session:
            _record_delete_failure(session, artifact_id, f"{type(error).__name__}: {error}")
            session.commit()
        raise
    with session_factory() as session:
        current = session.get(Artifact, artifact_id, populate_existing=True)
        if current is not None and current.state != ArtifactState.DELETED:
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


def _settled_staging_owners(
    session_factory: sessionmaker[Session], staging_files: list[Path]
) -> set[Path]:
    """The staging files named after a managed artifact whose write is settled (not PENDING)."""
    by_id: dict[uuid.UUID, Path] = {}
    for path in staging_files:
        try:
            by_id[uuid.UUID(hex=path.stem)] = path
        except ValueError:
            continue  # not named by this application: never ours to delete
    if not by_id:
        return set()
    with session_factory() as session:
        settled = session.scalars(
            select(Artifact.id).where(
                Artifact.id.in_(by_id),
                Artifact.storage_mode == StorageMode.MANAGED,
                Artifact.state != ArtifactState.PENDING,
            )
        ).all()
    return {by_id[artifact_id] for artifact_id in settled}


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
    for the next start instead of aborting recovery. A staging file is removed only when it belongs
    to a managed artifact that is no longer PENDING ("clean owned temp data", §28): its write is
    settled and its id is never reused. Any other staging file is reported, not deleted.
    """
    report = RecoveryReport()
    with session_factory() as session:
        pending = _managed_in(session, {ArtifactState.PENDING})
        deleting = _managed_in(session, {ArtifactState.DELETING, ArtifactState.DELETE_FAILED})

    for artifact_id, storage_key in pending:
        # A file at the final key is complete by construction: only a finished, fsynced write is
        # ever renamed there. The lost step was the AVAILABLE commit, so hash it and finish it.
        try:
            stored = store.digest(storage_key)
        except (OSError, UnsafeStorageKeyError) as error:
            report.skipped.append((artifact_id, _describe(error)))
            continue
        with session_factory() as session:
            if stored is not None:
                mark_artifact_available(session, artifact_id, stored, clock=clock)
                report.finalized.append(artifact_id)
            else:
                mark_write_not_completed(session, artifact_id, "interrupted before finalization")
                report.write_not_completed.append(artifact_id)
            session.commit()

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

    settled = _settled_staging_owners(session_factory, store.staging_files())
    for staged in store.staging_files():
        if staged not in settled:
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


def require_library_root(store: ManagedFileStore) -> None:
    """Raise `LibraryRootUnavailableError` unless the library root is a directory, before any
    recovery step reads "the file is not there" as "the file is gone"."""
    if not store.roots.library_root.is_dir():
        raise LibraryRootUnavailableError(f"{store.roots.library_root} is not a directory")


def reverify_managed_artifact(
    session_factory: sessionmaker[Session], store: ManagedFileStore, artifact_id: uuid.UUID
) -> str:
    """Bring a `MISSING` managed artifact back to AVAILABLE if its file is there again and matches
    the recorded size and SHA-256 exactly; a file that differs is not the original and leaves it
    `MISSING`. Returns the resulting state. A file that cannot be read raises `OSError` and changes
    nothing. The file is read outside any transaction.
    """
    with session_factory() as session:
        artifact = session.get(Artifact, artifact_id)
        if (
            artifact is None
            or artifact.storage_mode != StorageMode.MANAGED
            or artifact.state != ArtifactState.MISSING
            or artifact.storage_key is None
        ):
            raise ArtifactStateError(f"artifact {artifact_id} is not a MISSING managed artifact")
        key = artifact.storage_key
        recorded = StoredBytes(cast("bytes", artifact.sha256), cast("int", artifact.size_bytes))
    if store.digest(key) != recorded:
        return str(ArtifactState.MISSING)
    with session_factory() as session:
        transition_artifact(
            session,
            artifact_id,
            {ArtifactState.MISSING},
            {"state": ArtifactState.AVAILABLE, "failure_code": None, "failure_detail": None},
            storage_mode=StorageMode.MANAGED,
        )
        session.commit()
    return str(ArtifactState.AVAILABLE)


def mark_missing_managed_files(
    session_factory: sessionmaker[Session], store: ManagedFileStore
) -> list[uuid.UUID]:
    """Mark every AVAILABLE managed artifact whose file is gone `MISSING`, by existence alone.

    IMPLEMENTATION_ARCHITECTURE.md §16.4: startup recovery "reconciles pending records, staging/temp
    files, missing available files, and managed orphans". `MISSING` is "a verified failure to
    resolve bytes" (persistence §4.1) and nothing else changes: the row, its hash and its references
    stay, so a file that is restored can be verified and brought back. Reads no file, only its
    status. A file that is present but cannot be examined, or a key that is not a valid managed key,
    is left as it is (the consistency scan reports the latter). Returns the artifacts marked.
    `reverify_managed_artifact` brings one back. Raises `LibraryRootUnavailableError`, before
    marking anything, if the library root itself is not there: an unmounted drive says nothing about
    any single file.
    """
    require_library_root(store)
    with session_factory() as session:
        candidates = _managed_in(session, {ArtifactState.AVAILABLE})
    gone: list[uuid.UUID] = []
    for artifact_id, storage_key in candidates:
        try:
            path = store.roots.path_for(storage_key)
        except UnsafeStorageKeyError:
            continue
        try:
            present = stat.S_ISREG(path.stat().st_mode)
        except FileNotFoundError:
            present = False
        except OSError:
            continue
        if not present:
            gone.append(artifact_id)
    if not gone:
        return []
    marked: list[uuid.UUID] = []
    with session_factory() as session:
        for artifact_id in gone:
            try:
                transition_artifact(
                    session,
                    artifact_id,
                    {ArtifactState.AVAILABLE},
                    {
                        "state": ArtifactState.MISSING,
                        "failure_code": MANAGED_FILE_MISSING,
                        "failure_detail": None,
                    },
                )
            except ArtifactStateError:
                continue  # settled by something else meanwhile
            marked.append(artifact_id)
        session.commit()
    return marked


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
