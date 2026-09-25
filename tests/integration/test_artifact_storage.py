"""Managed artifact lifecycle against a real database and real directories (M2: TST-025; TST-026
"Pending and available states are correct"; PERSISTENCE_IMPLEMENTATION.md §4.1 and §28).

Every crash window of the three-step create protocol and the symmetric delete protocol is
reproduced, then settled by `recover_artifacts`, the startup recovery step.
"""

import hashlib
import io
import uuid
from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.sources import artifact_storage
from backend.app.sources.artifact_storage import (
    DELETE_ERROR,
    WRITE_NOT_COMPLETED,
    ArtifactStateError,
    ArtifactStorageError,
    RecoveryReport,
    create_managed_artifact,
    delete_managed_artifact,
    mark_artifact_available,
    recover_artifacts,
    request_artifact_deletion,
    reserve_managed_artifact,
    scan_storage,
    storage_key_for,
    verify_artifact,
)
from backend.app.sources.models import Artifact, Source
from backend.infrastructure.db.engine import create_session_factory
from backend.infrastructure.storage.files import ManagedFileStore, StoredBytes
from tests.factories.models import ModelFactory

DATA = b"\x89PNG not really, but bytes all the same"


class SimulatedCrash(BaseException):
    """The process dying: no `except Exception` handler gets to tidy up after it."""


@pytest.fixture
def factory(sqlite_engine: Engine) -> sessionmaker[Session]:
    return create_session_factory(sqlite_engine)


@pytest.fixture
def load(factory: sessionmaker[Session]) -> Callable[[uuid.UUID], Artifact]:
    def get(artifact_id: uuid.UUID) -> Artifact:
        with factory() as session:
            artifact = session.get(Artifact, artifact_id)
            assert artifact is not None
            return artifact

    return get


def create(
    factory: sessionmaker[Session], store: ManagedFileStore, build: ModelFactory
) -> uuid.UUID:
    return create_managed_artifact(
        factory, store, "SOURCE_ORIGINAL", io.BytesIO(DATA),
        new_id=build.new_id, clock=build.clock, mime_type="image/png",
        original_filename="beach.png",
    )  # fmt: skip


def recover(
    factory: sessionmaker[Session], store: ManagedFileStore, build: ModelFactory
) -> RecoveryReport:
    return recover_artifacts(factory, store, clock=build.clock)


# --- keys ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "directory"),
    [
        ("SOURCE_ORIGINAL", "originals"),
        ("FACE_CROP", "crops"),
        ("THUMBNAIL", "thumbnails"),
        ("MODEL_EXPORT", "models"),
    ],
)
def test_storage_keys_are_id_oriented(kind: str, directory: str) -> None:
    artifact_id = uuid.uuid4()
    assert storage_key_for(kind, artifact_id) == f"{directory}/{artifact_id.hex}"


def test_runtime_packages_are_not_stored_in_the_library() -> None:
    with pytest.raises(ArtifactStorageError, match="runtime"):
        storage_key_for("RUNTIME_PACKAGE", uuid.uuid4())


# --- creation ------------------------------------------------------------------------------------


def test_create_commits_an_available_artifact_matching_its_bytes(
    factory: sessionmaker[Session], file_store: ManagedFileStore, build: ModelFactory,
    load: Callable[[uuid.UUID], Artifact],
) -> None:  # fmt: skip
    artifact = load(create(factory, file_store, build))

    assert artifact.state == "AVAILABLE"
    assert artifact.storage_mode == "MANAGED"
    assert artifact.storage_key == f"originals/{artifact.id.hex}"
    assert artifact.sha256 == hashlib.sha256(DATA).digest()
    assert artifact.size_bytes == len(DATA)
    assert artifact.available_at is not None
    assert (artifact.mime_type, artifact.original_filename) == ("image/png", "beach.png")
    assert file_store.roots.path_for(artifact.storage_key).read_bytes() == DATA
    assert verify_artifact(file_store, artifact)
    assert file_store.staging_files() == []


def test_a_write_error_settles_the_reservation_at_once(
    factory: sessionmaker[Session], file_store: ManagedFileStore, build: ModelFactory,
    load: Callable[[uuid.UUID], Artifact], monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    def disk_full(*_: object, **__: object) -> StoredBytes:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(file_store, "store", disk_full)
    with pytest.raises(OSError, match="No space left"):
        create(factory, file_store, build)

    with factory() as session:
        artifact = session.query(Artifact).one()
    assert artifact.state == "MISSING"
    assert artifact.failure_code == WRITE_NOT_COMPLETED
    assert artifact.failure_detail is not None
    assert "No space left" in artifact.failure_detail
    assert artifact.sha256 is None


def test_the_primitives_let_a_caller_commit_available_and_its_source_together(
    factory: sessionmaker[Session], file_store: ManagedFileStore, build: ModelFactory,
    load: Callable[[uuid.UUID], Artifact],
) -> None:  # fmt: skip
    """API and Contracts.md §56: the Source appears in the same commit that makes its original
    AVAILABLE, never before."""
    with factory() as session:
        reserved = reserve_managed_artifact(
            session, "SOURCE_ORIGINAL", new_id=build.new_id, clock=build.clock
        )
        artifact_id, key = reserved.id, reserved.storage_key
        session.commit()
    assert key is not None
    stored = file_store.store(key, io.BytesIO(DATA), staging_name=artifact_id.hex)

    with factory() as session:
        mark_artifact_available(session, artifact_id, stored, clock=build.clock)
        source = Source(
            id=build.new_id(), kind="IMAGE", state="ACTIVE", display_name="beach.png",
            original_artifact_id=artifact_id, created_at=build.clock(), updated_at=build.clock(),
        )  # fmt: skip
        session.add(source)
        session.commit()

    assert load(artifact_id).state == "AVAILABLE"


@pytest.mark.parametrize("state", ["AVAILABLE", "MISSING", "DELETING", "DELETED"])
def test_only_a_pending_artifact_can_become_available(
    factory: sessionmaker[Session], db_session: Session, build: ModelFactory, state: str
) -> None:
    artifact = build.artifact(state=state)
    db_session.commit()
    with factory() as session, pytest.raises(ArtifactStateError, match=state):
        mark_artifact_available(
            session, artifact.id, StoredBytes(b"\x00" * 32, 1), clock=build.clock
        )


def test_an_unknown_artifact_cannot_become_available(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    with factory() as session, pytest.raises(ArtifactStateError, match="does not exist"):
        mark_artifact_available(
            session, uuid.uuid4(), StoredBytes(b"\x00" * 32, 1), clock=build.clock
        )


# --- crash windows during creation, then startup recovery ---------------------------------------


def test_crash_after_reserving_before_any_byte_is_written(
    factory: sessionmaker[Session], file_store: ManagedFileStore, build: ModelFactory,
    load: Callable[[uuid.UUID], Artifact], monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    def die(*_: object, **__: object) -> StoredBytes:
        raise SimulatedCrash

    monkeypatch.setattr(file_store, "store", die)
    with pytest.raises(SimulatedCrash):
        create(factory, file_store, build)
    monkeypatch.undo()

    with factory() as session:
        artifact_id = session.query(Artifact).one().id
    assert load(artifact_id).state == "PENDING"  # the crash left the reservation behind

    report = recover(factory, file_store, build)

    assert report.write_not_completed == [artifact_id]
    settled = load(artifact_id)
    assert (settled.state, settled.failure_code) == ("MISSING", WRITE_NOT_COMPLETED)


def test_crash_mid_write_leaves_a_staging_file_that_recovery_removes(
    factory: sessionmaker[Session], file_store: ManagedFileStore, db_session: Session,
    build: ModelFactory, load: Callable[[uuid.UUID], Artifact],
) -> None:  # fmt: skip
    """A killed process runs no cleanup, so its torn `.part` file really is left behind."""
    reserved = reserve_managed_artifact(
        db_session, "SOURCE_ORIGINAL", new_id=build.new_id, clock=build.clock
    )
    db_session.commit()
    file_store.staging_path(reserved.id.hex).write_bytes(DATA[:10])

    report = recover(factory, file_store, build)

    assert report.write_not_completed == [reserved.id]
    assert report.staging_removed == [f"{reserved.id.hex}.part"]
    assert load(reserved.id).state == "MISSING"
    assert file_store.staging_files() == []


def test_crash_after_the_rename_before_the_available_commit_is_finished_by_recovery(
    factory: sessionmaker[Session], file_store: ManagedFileStore, build: ModelFactory,
    load: Callable[[uuid.UUID], Artifact], monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    """§4.1: "If the second commit is lost, recovery verifies the expected final key and
    completes... the row." The bytes are complete by construction, so nothing is lost."""

    def die(*_: object, **__: object) -> None:
        raise SimulatedCrash

    monkeypatch.setattr(artifact_storage, "mark_artifact_available", die)
    with pytest.raises(SimulatedCrash):
        create(factory, file_store, build)
    monkeypatch.undo()

    with factory() as session:
        artifact_id = session.query(Artifact).one().id
    assert load(artifact_id).state == "PENDING"

    report = recover(factory, file_store, build)

    assert report.finalized == [artifact_id]
    artifact = load(artifact_id)
    assert artifact.state == "AVAILABLE"
    assert artifact.sha256 == hashlib.sha256(DATA).digest()
    assert artifact.size_bytes == len(DATA)
    assert verify_artifact(file_store, artifact)


# --- deletion -------------------------------------------------------------------------------------


def test_delete_removes_the_bytes_and_finalizes_the_row(
    factory: sessionmaker[Session], file_store: ManagedFileStore, build: ModelFactory,
    load: Callable[[uuid.UUID], Artifact],
) -> None:  # fmt: skip
    artifact_id = create(factory, file_store, build)
    key = load(artifact_id).storage_key
    assert key is not None

    delete_managed_artifact(factory, file_store, artifact_id, clock=build.clock)

    deleted = load(artifact_id)
    assert deleted.state == "DELETED"
    assert deleted.delete_requested_at is not None
    assert deleted.deleted_at is not None
    assert not file_store.roots.path_for(key).exists()


def test_a_referenced_original_is_never_deleted(
    factory: sessionmaker[Session], file_store: ManagedFileStore, db_session: Session,
    build: ModelFactory, tmp_path: Path, load: Callable[[uuid.UUID], Artifact],
) -> None:  # fmt: skip
    """API and Contracts.md §52: "The application never deletes REFERENCED originals"."""
    external = tmp_path / "user photos" / "holiday.jpg"
    external.parent.mkdir()
    external.write_bytes(b"the user's own file")
    artifact = build.artifact(storage_mode="REFERENCED", storage_key=None,
                              external_path=str(external))  # fmt: skip
    db_session.commit()

    with pytest.raises(ArtifactStateError, match="REFERENCED"):
        delete_managed_artifact(factory, file_store, artifact.id, clock=build.clock)

    assert external.read_bytes() == b"the user's own file"
    assert load(artifact.id).state == "AVAILABLE"


def test_a_pending_artifact_cannot_be_deleted(
    factory: sessionmaker[Session], db_session: Session, build: ModelFactory
) -> None:
    artifact = build.artifact(state="PENDING")
    db_session.commit()
    with factory() as session, pytest.raises(ArtifactStateError, match="PENDING"):
        request_artifact_deletion(session, artifact.id, clock=build.clock)


def test_a_delete_error_leaves_a_retryable_failure_that_recovery_retries(
    factory: sessionmaker[Session], file_store: ManagedFileStore, build: ModelFactory,
    load: Callable[[uuid.UUID], Artifact], monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    artifact_id = create(factory, file_store, build)
    key = load(artifact_id).storage_key
    assert key is not None

    def locked(_key: str) -> None:
        raise PermissionError("file is open in another program")

    monkeypatch.setattr(file_store, "delete", locked)
    with pytest.raises(PermissionError):
        delete_managed_artifact(factory, file_store, artifact_id, clock=build.clock)
    failed = load(artifact_id)
    assert (failed.state, failed.failure_code) == ("DELETE_FAILED", DELETE_ERROR)
    assert file_store.roots.path_for(key).exists()

    report = recover(factory, file_store, build)  # still locked: stays a retryable failure
    assert report.delete_failed == [artifact_id]
    assert load(artifact_id).state == "DELETE_FAILED"

    monkeypatch.undo()  # the other program closed the file
    report = recover(factory, file_store, build)
    assert report.deleted == [artifact_id]
    finished = load(artifact_id)
    assert (finished.state, finished.failure_code) == ("DELETED", None)
    assert not file_store.roots.path_for(key).exists()


def test_crash_after_the_deletion_intent_is_finished_by_recovery(
    factory: sessionmaker[Session], file_store: ManagedFileStore, build: ModelFactory,
    load: Callable[[uuid.UUID], Artifact], monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    artifact_id = create(factory, file_store, build)
    key = load(artifact_id).storage_key
    assert key is not None

    def die(_key: str) -> None:
        raise SimulatedCrash

    monkeypatch.setattr(file_store, "delete", die)
    with pytest.raises(SimulatedCrash):
        delete_managed_artifact(factory, file_store, artifact_id, clock=build.clock)
    monkeypatch.undo()
    assert load(artifact_id).state == "DELETING"

    report = recover(factory, file_store, build)

    assert report.deleted == [artifact_id]
    assert load(artifact_id).state == "DELETED"
    assert not file_store.roots.path_for(key).exists()


def test_crash_after_the_bytes_are_gone_before_finalizing_is_finished_by_recovery(
    factory: sessionmaker[Session], file_store: ManagedFileStore, build: ModelFactory,
    load: Callable[[uuid.UUID], Artifact], monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    artifact_id = create(factory, file_store, build)

    def die(*_: object, **__: object) -> None:
        raise SimulatedCrash

    monkeypatch.setattr(artifact_storage, "finalize_artifact_deletion", die)
    with pytest.raises(SimulatedCrash):
        delete_managed_artifact(factory, file_store, artifact_id, clock=build.clock)
    monkeypatch.undo()
    assert load(artifact_id).state == "DELETING"

    report = recover(factory, file_store, build)  # the file is already gone: deleting is a no-op

    assert report.deleted == [artifact_id]
    assert load(artifact_id).state == "DELETED"


# --- recovery as a whole --------------------------------------------------------------------------


def test_recovery_is_idempotent_and_leaves_settled_artifacts_alone(
    factory: sessionmaker[Session], file_store: ManagedFileStore, db_session: Session,
    build: ModelFactory, load: Callable[[uuid.UUID], Artifact],
) -> None:  # fmt: skip
    available = create(factory, file_store, build)
    pending = reserve_managed_artifact(
        db_session, "THUMBNAIL", new_id=build.new_id, clock=build.clock
    )
    db_session.commit()
    file_store.staging_path("unrelated").write_bytes(b"left by a dead process")
    before_available = load(available)

    first = recover(factory, file_store, build)
    second = recover(factory, file_store, build)

    assert first.write_not_completed == [pending.id]
    assert first.staging_removed == ["unrelated.part"]
    assert second == RecoveryReport()  # nothing left to do
    after = load(available)
    assert (after.state, after.sha256, after.available_at) == (
        before_available.state, before_available.sha256, before_available.available_at,
    )  # fmt: skip


# --- integrity and the consistency scan ----------------------------------------------------------


def test_verify_detects_tampered_and_missing_bytes(
    factory: sessionmaker[Session], file_store: ManagedFileStore, build: ModelFactory,
    load: Callable[[uuid.UUID], Artifact],
) -> None:  # fmt: skip
    artifact = load(create(factory, file_store, build))
    assert artifact.storage_key is not None
    path = file_store.roots.path_for(artifact.storage_key)

    path.write_bytes(DATA[:-1] + b"!")  # same size, different content
    assert not verify_artifact(file_store, artifact)
    path.write_bytes(DATA + b"extra")
    assert not verify_artifact(file_store, artifact)
    path.unlink()
    assert not verify_artifact(file_store, artifact)


def test_verify_refuses_an_artifact_that_is_not_available_and_managed(
    db_session: Session, file_store: ManagedFileStore, build: ModelFactory
) -> None:
    with pytest.raises(ArtifactStateError):
        verify_artifact(file_store, build.artifact(state="PENDING"))


def test_scan_of_a_consistent_library_is_clean(
    factory: sessionmaker[Session], file_store: ManagedFileStore, db_session: Session,
    build: ModelFactory,
) -> None:  # fmt: skip
    """Rows that legitimately have no file (deleted, a write that never completed, a write still
    in flight) are not reported: only an AVAILABLE artifact without bytes is a new problem."""
    create(factory, file_store, build)
    deleted = create(factory, file_store, build)
    delete_managed_artifact(factory, file_store, deleted, clock=build.clock)
    reserve_managed_artifact(db_session, "THUMBNAIL", new_id=build.new_id, clock=build.clock)
    db_session.commit()
    recover(factory, file_store, build)  # that reservation becomes MISSING / WRITE_NOT_COMPLETED
    reserve_managed_artifact(db_session, "FACE_CROP", new_id=build.new_id, clock=build.clock)
    db_session.commit()  # and this one is still PENDING

    with factory() as session:
        assert scan_storage(session, file_store).clean


def test_scan_reports_missing_orphan_and_stray_files_and_changes_nothing(
    factory: sessionmaker[Session], file_store: ManagedFileStore, build: ModelFactory,
    load: Callable[[uuid.UUID], Artifact],
) -> None:  # fmt: skip
    kept = create(factory, file_store, build)
    lost = create(factory, file_store, build)
    lost_key = load(lost).storage_key
    assert lost_key is not None
    file_store.roots.path_for(lost_key).unlink()  # deleted behind the application's back
    orphan = file_store.roots.library_root / "crops" / "stray-crop"
    orphan.write_bytes(b"no artifact row owns this")
    file_store.staging_path("half-written").write_bytes(b"x")

    with factory() as session:
        scan = scan_storage(session, file_store)

    assert scan.missing == [lost]
    assert scan.orphans == ["crops/stray-crop"]
    assert scan.stray_staging == ["half-written.part"]
    assert not scan.clean
    # Report only: the row, the orphan and the staging file are all untouched.
    assert load(lost).state == "AVAILABLE"
    assert load(kept).state == "AVAILABLE"
    assert orphan.exists()
    assert file_store.staging_files() != []
