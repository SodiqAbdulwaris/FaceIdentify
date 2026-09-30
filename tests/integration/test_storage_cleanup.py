"""Conservative cleanup of unreferenced managed artifacts against a real database and real files
(M2: TST-025 "conservative cleanup"; API and Contracts.md §51; architecture §16.7).

Only an AVAILABLE managed artifact that no row references, past a grace period, is ever removed.
Everything else (the user's referenced files, anything in use, stray files on disk) is left alone.
"""

import io
import uuid
from collections.abc import Callable
from datetime import timedelta

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.runtime.models import (
    InstalledModelExport,
    ModelExport,
    RuntimePackage,
    RuntimePackageInstallation,
)
from backend.app.sources import storage_cleanup
from backend.app.sources.artifact_references import (
    artifact_reference_columns,
    unreferenced_artifacts,
)
from backend.app.sources.artifact_storage import (
    ArtifactStateError,
    create_managed_artifact,
    recover_artifacts,
    request_artifact_deletion,
    scan_storage,
)
from backend.app.sources.models import Artifact
from backend.app.sources.storage_cleanup import (
    cleanup_unreferenced_artifacts,
    find_unreferenced_artifacts,
)
from backend.infrastructure.db.engine import create_session_factory
from backend.infrastructure.storage.files import ManagedFileStore
from tests.factories.models import ModelFactory

DAY = timedelta(days=1)
SHA = b"\x11" * 32


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


def store_artifact(
    factory: sessionmaker[Session], store: ManagedFileStore, build: ModelFactory,
    kind: str = "SOURCE_ORIGINAL", data: bytes = b"some managed bytes",
) -> uuid.UUID:  # fmt: skip
    return create_managed_artifact(
        factory, store, kind, io.BytesIO(data), new_id=build.new_id, clock=build.clock
    )


def clean(
    factory: sessionmaker[Session], store: ManagedFileStore, build: ModelFactory,
    older_than_days: float = 1,
) -> storage_cleanup.CleanupReport:  # fmt: skip
    """Clean up as of a day after every artifact was stored (the frozen clock has not moved)."""
    return cleanup_unreferenced_artifacts(
        factory, store, older_than=build.clock() + DAY * older_than_days, clock=build.clock
    )


# --- what is removed -------------------------------------------------------------------------


def test_an_unreferenced_old_artifact_is_deleted_bytes_and_row(
    factory: sessionmaker[Session], file_store: ManagedFileStore, build: ModelFactory,
    load: Callable[[uuid.UUID], Artifact],
) -> None:  # fmt: skip
    artifact_id = store_artifact(factory, file_store, build)
    key = load(artifact_id).storage_key
    assert key is not None
    assert file_store.roots.path_for(key).is_file()

    report = clean(factory, file_store, build)

    assert (report.deleted, report.skipped, report.failed) == ([artifact_id], [], [])
    deleted = load(artifact_id)
    assert deleted.state == "DELETED"
    assert deleted.delete_requested_at is not None
    assert deleted.deleted_at is not None
    assert not file_store.roots.path_for(key).exists()
    with factory() as session:
        assert scan_storage(session, file_store).clean


def test_a_second_run_finds_nothing_to_do(
    factory: sessionmaker[Session], file_store: ManagedFileStore, build: ModelFactory
) -> None:
    store_artifact(factory, file_store, build)
    assert len(clean(factory, file_store, build).deleted) == 1

    again = clean(factory, file_store, build)

    assert (again.deleted, again.skipped, again.failed) == ([], [], [])


def test_oldest_artifacts_go_first(
    factory: sessionmaker[Session], file_store: ManagedFileStore, build: ModelFactory
) -> None:
    stored = []
    for n in range(6):  # enough that id order would not match age order by chance
        stored.append(store_artifact(factory, file_store, build, data=bytes([n])))
        build.clock.advance(hours=1)

    assert clean(factory, file_store, build).deleted == stored


# --- the grace period ------------------------------------------------------------------------


def test_nothing_newer_than_the_cutoff_is_collected(
    factory: sessionmaker[Session], file_store: ManagedFileStore, build: ModelFactory,
    load: Callable[[uuid.UUID], Artifact],
) -> None:  # fmt: skip
    """A just-stored artifact's Source may be about to commit; that is what the cutoff protects."""
    artifact_id = store_artifact(factory, file_store, build)
    stored_at = build.clock()

    for cutoff in (stored_at - DAY, stored_at):  # before it, and exactly when it became available
        report = cleanup_unreferenced_artifacts(
            factory, file_store, older_than=cutoff, clock=build.clock
        )
        assert report.deleted == []
        assert load(artifact_id).state == "AVAILABLE"

    just_after = cleanup_unreferenced_artifacts(
        factory, file_store, older_than=stored_at + timedelta(seconds=1), clock=build.clock
    )
    assert just_after.deleted == [artifact_id]


def test_the_age_is_measured_from_when_the_artifact_became_available(
    factory: sessionmaker[Session], file_store: ManagedFileStore, db_session: Session,
    build: ModelFactory,
) -> None:  # fmt: skip
    """A long write must not make a finished artifact look old (created_at is the reservation)."""
    artifact = build.artifact()
    artifact.created_at = build.clock() - 10 * DAY
    artifact.available_at = build.clock()
    db_session.commit()

    with factory() as session:
        assert find_unreferenced_artifacts(session, older_than=build.clock()) == []
        assert find_unreferenced_artifacts(session, older_than=build.clock() + DAY) == [artifact.id]


def test_an_artifact_with_no_availability_time_falls_back_to_its_creation_time(
    factory: sessionmaker[Session], db_session: Session, build: ModelFactory
) -> None:
    artifact = build.artifact()  # the factory leaves available_at unset
    db_session.commit()

    with factory() as session:
        assert find_unreferenced_artifacts(session, older_than=build.clock()) == []
        assert find_unreferenced_artifacts(session, older_than=build.clock() + DAY) == [artifact.id]


# --- what is never removed -------------------------------------------------------------------


def reference_by_source_original(build: ModelFactory, artifact: Artifact) -> None:
    build.source(original_artifact_id=artifact.id)


def reference_by_source_thumbnail(build: ModelFactory, artifact: Artifact) -> None:
    build.source(thumbnail_artifact_id=artifact.id)


def reference_by_recycled_source(build: ModelFactory, artifact: Artifact) -> None:
    build.source(state="RECYCLED", original_artifact_id=artifact.id)


def reference_by_observation_crop(build: ModelFactory, artifact: Artifact) -> None:
    build.observation(face_crop_artifact_id=artifact.id)


def reference_by_model_export(build: ModelFactory, artifact: Artifact) -> None:
    build.add(
        ModelExport(
            id=build.new_id(), component_version_id=build.component_version().id,
            format="ONNX", precision="FP16", artifact_id=artifact.id, sha256=SHA,
            input_contract_json={}, created_at=build.clock(),
        )
    )  # fmt: skip


def reference_by_installed_model_export(build: ModelFactory, artifact: Artifact) -> None:
    export = build.add(
        ModelExport(
            id=build.new_id(), component_version_id=build.component_version().id,
            format="ONNX", precision="FP16", artifact_id=build.artifact().id, sha256=SHA,
            input_contract_json={}, created_at=build.clock(),
        )
    )  # fmt: skip
    build.add(
        InstalledModelExport(
            id=build.new_id(), model_export_id=export.id, artifact_id=artifact.id,
            state="INSTALLED",
        )
    )  # fmt: skip


def reference_by_runtime_package_installation(build: ModelFactory, artifact: Artifact) -> None:
    package = build.add(
        RuntimePackage(
            id=build.new_id(), key=f"runtime-{build.new_id()}", manifest_schema_version=1,
            manifest_json={}, state="ACTIVE", created_at=build.clock(),
        )
    )  # fmt: skip
    build.add(
        RuntimePackageInstallation(
            id=build.new_id(), runtime_package_id=package.id, artifact_id=artifact.id,
            state="INSTALLED",
        )
    )  # fmt: skip


REFERENCES = {
    "sources.original_artifact_id": reference_by_source_original,
    "sources.thumbnail_artifact_id": reference_by_source_thumbnail,
    "a recycled source": reference_by_recycled_source,
    "observations.face_crop_artifact_id": reference_by_observation_crop,
    "model_exports.artifact_id": reference_by_model_export,
    "installed_model_exports.artifact_id": reference_by_installed_model_export,
    "runtime_package_installations.artifact_id": reference_by_runtime_package_installation,
}


def test_the_references_are_read_from_the_schema_and_each_has_a_test() -> None:
    """A new table pointing at `artifacts` makes this fail: add its case to REFERENCES below."""
    found = {f"{column.table.name}.{column.name}" for column in artifact_reference_columns()}

    assert found == {
        "sources.original_artifact_id",
        "sources.thumbnail_artifact_id",
        "observations.face_crop_artifact_id",
        "model_exports.artifact_id",
        "installed_model_exports.artifact_id",
        "runtime_package_installations.artifact_id",
    }
    assert found <= set(REFERENCES)


@pytest.mark.parametrize("reference", sorted(REFERENCES))
def test_an_artifact_anything_references_is_never_collected(
    factory: sessionmaker[Session], file_store: ManagedFileStore, db_session: Session,
    build: ModelFactory, load: Callable[[uuid.UUID], Artifact], reference: str,
) -> None:  # fmt: skip
    artifact_id = store_artifact(factory, file_store, build)
    REFERENCES[reference](build, load(artifact_id))
    db_session.commit()
    key = load(artifact_id).storage_key
    assert key is not None

    report = clean(factory, file_store, build, older_than_days=365)

    # never even chosen: not merely saved by the deletion-time check
    assert (report.deleted, report.skipped, report.failed) == ([], [], [])
    assert load(artifact_id).state == "AVAILABLE"
    assert file_store.roots.path_for(key).is_file()


@pytest.mark.parametrize("state", ["PENDING", "MISSING", "DELETING", "DELETE_FAILED", "DELETED"])
def test_only_available_artifacts_are_candidates(
    factory: sessionmaker[Session], db_session: Session, build: ModelFactory, state: str
) -> None:
    build.artifact(state=state)
    db_session.commit()

    with factory() as session:
        assert find_unreferenced_artifacts(session, older_than=build.clock() + 365 * DAY) == []


def test_a_referenced_original_is_never_a_candidate_however_unused(
    factory: sessionmaker[Session], db_session: Session, build: ModelFactory
) -> None:
    """The file is the user's (§52): not ours to delete, referenced by a Source or not."""
    build.artifact(
        storage_mode="REFERENCED", storage_key=None, external_path="D:/movies/a.mkv",
        size_bytes=4_000_000,
    )  # fmt: skip
    db_session.commit()

    with factory() as session:
        assert find_unreferenced_artifacts(session, older_than=build.clock() + 365 * DAY) == []


def test_a_file_no_row_owns_is_reported_and_kept(
    factory: sessionmaker[Session], file_store: ManagedFileStore, build: ModelFactory
) -> None:
    """The row may just have been lost (an older backup restored): the file may be the only copy."""
    stray = file_store.roots.library_root / "originals" / uuid.uuid4().hex
    stray.write_bytes(b"perhaps the only copy")
    store_artifact(factory, file_store, build)

    report = clean(factory, file_store, build)

    assert len(report.deleted) == 1
    assert stray.read_bytes() == b"perhaps the only copy"
    with factory() as session:
        assert scan_storage(session, file_store).orphans == [f"originals/{stray.name}"]


# --- races and failures ----------------------------------------------------------------------


def test_an_artifact_referenced_after_it_was_chosen_is_skipped_not_deleted(
    factory: sessionmaker[Session], file_store: ManagedFileStore, db_session: Session,
    build: ModelFactory, load: Callable[[uuid.UUID], Artifact], monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    artifact_id = store_artifact(factory, file_store, build)
    key = load(artifact_id).storage_key
    assert key is not None
    chosen = find_unreferenced_artifacts_once(factory, build)
    assert chosen == [artifact_id]
    build.source(original_artifact_id=artifact_id)  # the import's Source commits in the window
    db_session.commit()
    monkeypatch.setattr(storage_cleanup, "find_unreferenced_artifacts", lambda *_, **__: chosen)

    report = clean(factory, file_store, build)

    assert (report.deleted, report.skipped) == ([], [artifact_id])
    assert load(artifact_id).state == "AVAILABLE"
    assert file_store.roots.path_for(key).is_file()


def find_unreferenced_artifacts_once(
    factory: sessionmaker[Session], build: ModelFactory
) -> list[uuid.UUID]:
    with factory() as session:
        return find_unreferenced_artifacts(session, older_than=build.clock() + DAY)


def test_the_unreferenced_guard_is_what_stops_a_plain_deletion_request(
    factory: sessionmaker[Session], file_store: ManagedFileStore, db_session: Session,
    build: ModelFactory, load: Callable[[uuid.UUID], Artifact],
) -> None:  # fmt: skip
    referenced = store_artifact(factory, file_store, build)
    build.source(original_artifact_id=referenced)
    db_session.commit()

    with factory() as session, pytest.raises(ArtifactStateError):
        request_artifact_deletion(session, referenced, clock=build.clock, only_if_unreferenced=True)
    with factory() as session:  # without the guard the caller decides, as before
        request_artifact_deletion(session, referenced, clock=build.clock)
        session.commit()
    assert load(referenced).state == "DELETING"


def test_the_unreferenced_condition_matches_exactly_the_unreferenced_rows(
    db_session: Session, build: ModelFactory
) -> None:
    free = build.artifact()
    used = build.artifact()
    build.source(original_artifact_id=used.id)
    db_session.commit()

    chosen = db_session.scalars(select(Artifact.id).where(unreferenced_artifacts())).all()

    assert free.id in chosen
    assert used.id not in chosen


def test_one_artifact_that_cannot_be_deleted_does_not_stop_the_rest(
    factory: sessionmaker[Session], file_store: ManagedFileStore, build: ModelFactory,
    load: Callable[[uuid.UUID], Artifact], monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    stuck = store_artifact(factory, file_store, build, data=b"locked")
    build.clock.advance(hours=1)
    fine = store_artifact(factory, file_store, build, data=b"fine")
    stuck_key = load(stuck).storage_key
    real_delete = file_store.delete

    def delete(key: str) -> None:
        if key == stuck_key:
            raise PermissionError("file is open in another program")
        real_delete(key)

    monkeypatch.setattr(file_store, "delete", delete)

    report = clean(factory, file_store, build)

    assert report.deleted == [fine]
    assert [artifact_id for artifact_id, _ in report.failed] == [stuck]
    assert "PermissionError" in report.failed[0][1]
    assert load(stuck).state == "DELETE_FAILED"

    monkeypatch.undo()  # the program lets go; startup recovery finishes the job
    assert recover_artifacts(factory, file_store, clock=build.clock).deleted == [stuck]
    assert load(stuck).state == "DELETED"


def test_a_recycled_sources_files_are_kept(
    factory: sessionmaker[Session], file_store: ManagedFileStore, db_session: Session,
    build: ModelFactory, load: Callable[[uuid.UUID], Artifact],
) -> None:  # fmt: skip
    """The Recycle Bin keeps the original and its thumbnail so a restore needs no reprocessing."""
    original = store_artifact(factory, file_store, build)
    thumbnail = store_artifact(factory, file_store, build, kind="THUMBNAIL", data=b"thumb")
    build.source(state="RECYCLED", original_artifact_id=original, thumbnail_artifact_id=thumbnail)
    db_session.commit()

    assert clean(factory, file_store, build, older_than_days=365).deleted == []
    assert (load(original).state, load(thumbnail).state) == ("AVAILABLE", "AVAILABLE")
