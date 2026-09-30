"""Referenced (external, user-owned) originals against a real database and real files (M2: TST-025;
API and Contracts.md §52, §57, §60; IMPLEMENTATION_ARCHITECTURE.md §23.5).

The application records a verified reference, keeps the Source when the file goes missing, and
never modifies, moves or deletes the external file.
"""

import hashlib
import os
import uuid
from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy import Engine, event, update
from sqlalchemy.orm import Session, sessionmaker

from backend.app.sources import referenced_artifacts
from backend.app.sources.artifact_storage import ArtifactStateError, ArtifactStorageError
from backend.app.sources.models import Artifact, Source
from backend.app.sources.referenced_artifacts import (
    REFERENCED_CONTENT_CHANGED,
    REFERENCED_FILE_MISSING,
    RelinkMismatchError,
    add_referenced_artifact,
    relink_referenced_artifact,
    reverify_referenced_artifact,
)
from backend.infrastructure.db.engine import create_session_factory
from backend.infrastructure.storage import referenced as referenced_module
from backend.infrastructure.storage.files import StoredBytes, digest_path
from backend.infrastructure.storage.layout import StorageRoots
from backend.infrastructure.storage.referenced import ReferencedFileError, inspect_referenced_file
from tests.factories.models import ModelFactory
from tests.fixtures.links import link_directory

PHOTO = b"\xff\xd8 the user's own photo"


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


@pytest.fixture
def photo(tmp_path: Path) -> Path:
    path = tmp_path / "user photos" / "holiday.jpg"
    path.parent.mkdir()
    path.write_bytes(PHOTO)
    return path


def import_file(
    factory: sessionmaker[Session], roots: StorageRoots, build: ModelFactory, path: Path
) -> uuid.UUID:
    referenced = inspect_referenced_file(path, roots)
    with factory() as session:
        artifact = add_referenced_artifact(
            session, referenced, new_id=build.new_id, clock=build.clock, mime_type="image/jpeg"
        )
        session.commit()
        return artifact.id


def reverify(factory: sessionmaker[Session], build: ModelFactory, artifact_id: uuid.UUID) -> str:
    return reverify_referenced_artifact(factory, artifact_id, clock=build.clock)


# --- inspecting a file -----------------------------------------------------------------------


def test_inspecting_a_file_fingerprints_it_and_leaves_it_alone(
    storage_roots: StorageRoots, photo: Path
) -> None:
    before = photo.stat().st_mtime_ns

    inspected = inspect_referenced_file(photo, storage_roots)

    assert inspected.path == photo.resolve()
    assert inspected.stored.sha256 == hashlib.sha256(PHOTO).digest()
    assert inspected.stored.size_bytes == len(PHOTO)
    assert (photo.read_bytes(), photo.stat().st_mtime_ns) == (PHOTO, before)


def test_the_recorded_location_is_the_real_file_behind_a_link(
    storage_roots: StorageRoots, photo: Path, tmp_path: Path
) -> None:
    link = tmp_path / "shortcut"
    link_directory(link, photo.parent)

    assert inspect_referenced_file(link / photo.name, storage_roots).path == photo.resolve()


def test_a_relative_path_is_refused(storage_roots: StorageRoots) -> None:
    with pytest.raises(ReferencedFileError, match="absolute"):
        inspect_referenced_file(Path("holiday.jpg"), storage_roots)


def test_a_missing_file_is_refused(storage_roots: StorageRoots, tmp_path: Path) -> None:
    with pytest.raises(ReferencedFileError, match="cannot read"):
        inspect_referenced_file(tmp_path / "nothing.jpg", storage_roots)


def test_a_directory_is_refused(storage_roots: StorageRoots, photo: Path) -> None:
    with pytest.raises(ReferencedFileError, match="not a file"):
        inspect_referenced_file(photo.parent, storage_roots)


def test_a_file_in_the_library_or_local_state_is_refused(storage_roots: StorageRoots) -> None:
    """Such a file would be a managed orphan, and `cache/` and `temp/` are disposable."""
    for inside in (
        storage_roots.library_root / "originals" / uuid.uuid4().hex,
        storage_roots.library_root / "database" / "library.db",
        storage_roots.local_state_root / "cache" / "thumb.jpg",
    ):
        inside.write_bytes(b"x")
        with pytest.raises(ReferencedFileError, match="own storage"):
            inspect_referenced_file(inside, storage_roots)


def test_a_link_into_the_library_does_not_smuggle_a_file_past_the_check(
    storage_roots: StorageRoots, tmp_path: Path
) -> None:
    (storage_roots.library_root / "database" / "library.db").write_bytes(b"x")
    link = tmp_path / "shortcut"
    link_directory(link, storage_roots.library_root / "database")

    with pytest.raises(ReferencedFileError, match="own storage"):
        inspect_referenced_file(link / "library.db", storage_roots)


def test_a_link_loop_is_a_refusal_not_a_crash(storage_roots: StorageRoots, tmp_path: Path) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    second.mkdir()
    link_directory(first, second)
    second.rmdir()
    link_directory(second, first)

    with pytest.raises(ReferencedFileError, match="cannot read"):
        inspect_referenced_file(first / "holiday.jpg", storage_roots)


@pytest.mark.parametrize("change", ["size-only", "mtime-only"])
def test_a_file_that_changes_while_it_is_hashed_is_refused(
    storage_roots: StorageRoots, photo: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    """A fingerprint of a half-written file would later make the real file look "changed"."""

    def changes_while_read(path: Path) -> StoredBytes:
        stored = digest_path(path)
        before = path.stat()
        if change == "size-only":
            with path.open("ab") as out:
                out.write(b"a download still in progress")
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))  # only the size differs
        else:
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 10**9))
        return stored

    monkeypatch.setattr(referenced_module, "digest_path", changes_while_read)
    with pytest.raises(ReferencedFileError, match="changed while it was being read"):
        inspect_referenced_file(photo, storage_roots)


def test_two_artifacts_may_reference_the_same_file(
    factory: sessionmaker[Session], storage_roots: StorageRoots, build: ModelFactory,
    photo: Path, load: Callable[[uuid.UUID], Artifact],
) -> None:  # fmt: skip
    """The same photo imported twice is two Sources; nothing forbids duplicate references."""
    first = import_file(factory, storage_roots, build, photo)
    second = import_file(factory, storage_roots, build, photo)

    assert first != second
    assert load(first).external_path == load(second).external_path


def test_a_file_that_cannot_be_read_is_a_refusal(
    storage_roots: StorageRoots, photo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def locked(_path: Path) -> None:
        raise PermissionError("file is open in another program")

    monkeypatch.setattr(referenced_module, "digest_path", locked)
    with pytest.raises(ReferencedFileError, match="open in another program"):
        inspect_referenced_file(photo, storage_roots)


# --- recording an import ---------------------------------------------------------------------


def test_an_import_records_a_referenced_available_artifact(
    factory: sessionmaker[Session], storage_roots: StorageRoots, build: ModelFactory,
    photo: Path, load: Callable[[uuid.UUID], Artifact],
) -> None:  # fmt: skip
    artifact = load(import_file(factory, storage_roots, build, photo))

    assert (artifact.kind, artifact.storage_mode, artifact.state) == (
        "SOURCE_ORIGINAL", "REFERENCED", "AVAILABLE",
    )  # fmt: skip
    assert artifact.external_path == str(photo.resolve())
    assert artifact.storage_key is None
    assert artifact.sha256 == hashlib.sha256(PHOTO).digest()
    assert artifact.size_bytes == len(PHOTO)
    assert (artifact.mime_type, artifact.original_filename) == ("image/jpeg", "holiday.jpg")
    assert artifact.available_at == artifact.created_at
    assert photo.read_bytes() == PHOTO


def test_the_artifact_and_its_source_commit_in_one_transaction(
    factory: sessionmaker[Session], storage_roots: StorageRoots, build: ModelFactory,
    photo: Path,
) -> None:  # fmt: skip
    """API and Contracts.md §57: "short transaction → Artifact(REFERENCED, AVAILABLE) → Source"."""
    referenced = inspect_referenced_file(photo, storage_roots)
    with factory() as session:
        artifact = add_referenced_artifact(
            session, referenced, new_id=build.new_id, clock=build.clock
        )
        session.add(
            Source(
                id=build.new_id(), kind="IMAGE", state="ACTIVE", display_name="holiday.jpg",
                original_artifact_id=artifact.id, created_at=build.clock(),
                updated_at=build.clock(),
            )
        )  # fmt: skip
        session.rollback()

    with factory() as session:
        assert session.query(Artifact).count() == 0
        assert session.query(Source).count() == 0


# --- availability ----------------------------------------------------------------------------


def test_an_unchanged_file_stays_available(
    factory: sessionmaker[Session], storage_roots: StorageRoots, build: ModelFactory,
    photo: Path, load: Callable[[uuid.UUID], Artifact],
) -> None:  # fmt: skip
    artifact_id = import_file(factory, storage_roots, build, photo)
    before = load(artifact_id)

    assert reverify(factory, build, artifact_id) == "AVAILABLE"

    after = load(artifact_id)
    assert (after.state, after.failure_code, after.available_at) == (
        "AVAILABLE", None, before.available_at,
    )  # fmt: skip


def test_rechecking_an_unchanged_file_writes_nothing(
    factory: sessionmaker[Session], sqlite_engine: Engine, storage_roots: StorageRoots,
    build: ModelFactory, photo: Path,
) -> None:  # fmt: skip
    """A startup pass over many references must not turn into a write per reference."""
    artifact_id = import_file(factory, storage_roots, build, photo)
    writes: list[str] = []

    def record(_conn: object, _cursor: object, statement: str, *_rest: object) -> None:
        if statement.lstrip().upper().startswith(("UPDATE", "INSERT", "DELETE")):
            writes.append(statement)

    event.listen(sqlite_engine, "before_cursor_execute", record)
    try:
        reverify(factory, build, artifact_id)
        photo.unlink()
        reverify(factory, build, artifact_id)  # a change: one write
        assert len(writes) == 1
        reverify(factory, build, artifact_id)  # still missing for the same reason
        assert len(writes) == 1
    finally:
        event.remove(sqlite_engine, "before_cursor_execute", record)


def test_a_missing_file_makes_the_artifact_missing_and_keeps_the_source(
    factory: sessionmaker[Session], storage_roots: StorageRoots, build: ModelFactory,
    photo: Path, load: Callable[[uuid.UUID], Artifact],
) -> None:  # fmt: skip
    """IMPLEMENTATION_ARCHITECTURE.md §23.5: keep the Source record, mark availability MISSING."""
    referenced = inspect_referenced_file(photo, storage_roots)
    with factory() as session:
        artifact = add_referenced_artifact(
            session, referenced, new_id=build.new_id, clock=build.clock
        )
        source = Source(
            id=build.new_id(), kind="IMAGE", state="ACTIVE", display_name="holiday.jpg",
            original_artifact_id=artifact.id, created_at=build.clock(), updated_at=build.clock(),
        )  # fmt: skip
        session.add(source)
        session.commit()
        artifact_id, source_id = artifact.id, source.id
    photo.unlink()

    assert reverify(factory, build, artifact_id) == "MISSING"

    missing = load(artifact_id)
    assert (missing.state, missing.failure_code) == ("MISSING", REFERENCED_FILE_MISSING)
    assert missing.sha256 == hashlib.sha256(PHOTO).digest()  # the fingerprint survives
    with factory() as session:
        kept = session.get(Source, source_id)
        assert kept is not None
        assert (kept.state, kept.revision, kept.original_artifact_id) == ("ACTIVE", 1, artifact_id)


def test_the_same_file_coming_back_makes_the_artifact_available_again(
    factory: sessionmaker[Session], storage_roots: StorageRoots, build: ModelFactory,
    photo: Path, load: Callable[[uuid.UUID], Artifact],
) -> None:  # fmt: skip
    artifact_id = import_file(factory, storage_roots, build, photo)
    photo.unlink()
    reverify(factory, build, artifact_id)
    photo.write_bytes(PHOTO)

    assert reverify(factory, build, artifact_id) == "AVAILABLE"

    restored = load(artifact_id)
    assert (restored.state, restored.failure_code, restored.failure_detail) == (
        "AVAILABLE", None, None,
    )  # fmt: skip


@pytest.mark.parametrize("changed", [b"a different photo!!", b"\xff\xd8 the user's own phot0"])
def test_a_different_file_at_the_same_place_is_not_the_original(
    factory: sessionmaker[Session], storage_roots: StorageRoots, build: ModelFactory,
    photo: Path, load: Callable[[uuid.UUID], Artifact], changed: bytes,
) -> None:  # fmt: skip
    """Different size or same size: either way it is replacement, not the original (§59)."""
    artifact_id = import_file(factory, storage_roots, build, photo)
    photo.write_bytes(changed)

    assert reverify(factory, build, artifact_id) == "MISSING"

    assert load(artifact_id).failure_code == REFERENCED_CONTENT_CHANGED
    assert photo.read_bytes() == changed  # never "fixed" by the application

    photo.write_bytes(PHOTO)
    assert reverify(factory, build, artifact_id) == "AVAILABLE"


def test_a_file_that_changed_size_is_not_hashed(
    factory: sessionmaker[Session], storage_roots: StorageRoots, build: ModelFactory,
    photo: Path, load: Callable[[uuid.UUID], Artifact], monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    artifact_id = import_file(factory, storage_roots, build, photo)
    photo.write_bytes(PHOTO + b"more")

    def forbidden(_path: Path) -> None:
        raise AssertionError("a file whose size differs must not be read to learn it differs")

    monkeypatch.setattr(referenced_artifacts, "digest_path", forbidden)
    assert reverify(factory, build, artifact_id) == "MISSING"
    assert load(artifact_id).failure_code == REFERENCED_CONTENT_CHANGED


def test_the_reason_changes_when_a_missing_file_returns_altered(
    factory: sessionmaker[Session], storage_roots: StorageRoots, build: ModelFactory,
    photo: Path, load: Callable[[uuid.UUID], Artifact],
) -> None:  # fmt: skip
    artifact_id = import_file(factory, storage_roots, build, photo)
    photo.unlink()
    reverify(factory, build, artifact_id)
    assert load(artifact_id).failure_code == REFERENCED_FILE_MISSING

    photo.write_bytes(b"something else entirely")
    assert reverify(factory, build, artifact_id) == "MISSING"
    assert load(artifact_id).failure_code == REFERENCED_CONTENT_CHANGED


def test_a_file_that_cannot_be_read_is_not_evidence_that_it_is_gone(
    factory: sessionmaker[Session], storage_roots: StorageRoots, build: ModelFactory,
    photo: Path, load: Callable[[uuid.UUID], Artifact], monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    artifact_id = import_file(factory, storage_roots, build, photo)

    def locked(_path: Path) -> None:
        raise PermissionError("file is open in another program")

    monkeypatch.setattr(referenced_artifacts, "digest_path", locked)
    with pytest.raises(PermissionError):
        reverify(factory, build, artifact_id)
    assert load(artifact_id).state == "AVAILABLE"


@pytest.mark.parametrize(
    "error",
    [
        PermissionError("access is denied"),
        # winerror 21: an unplugged or unreachable drive. `Path.is_file` reports this one as False.
        OSError(0, "the device is not ready", None, 21),
    ],
    ids=["access-denied", "device-not-ready"],
)
def test_a_file_that_cannot_be_examined_is_not_evidence_that_it_is_gone(
    factory: sessionmaker[Session], storage_roots: StorageRoots, build: ModelFactory,
    photo: Path, load: Callable[[uuid.UUID], Artifact], monkeypatch: pytest.MonkeyPatch,
    error: OSError,
) -> None:  # fmt: skip
    artifact_id = import_file(factory, storage_roots, build, photo)
    real_stat = Path.stat
    target = photo.resolve()  # computed first: resolving calls stat

    def unreachable(self: Path, **kwargs: bool) -> object:
        if self == target:
            raise error
        return real_stat(self, **kwargs)

    monkeypatch.setattr(Path, "stat", unreachable)
    with pytest.raises(OSError, match=str(error)[-12:]):
        reverify(factory, build, artifact_id)
    assert load(artifact_id).state == "AVAILABLE"


def test_a_file_deleted_while_it_is_being_read_is_missing(
    factory: sessionmaker[Session], storage_roots: StorageRoots, build: ModelFactory,
    photo: Path, load: Callable[[uuid.UUID], Artifact], monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    artifact_id = import_file(factory, storage_roots, build, photo)

    def vanishes(path: Path) -> object:
        path.unlink()
        return digest_path(path)  # now raises FileNotFoundError

    monkeypatch.setattr(referenced_artifacts, "digest_path", vanishes)
    assert reverify(factory, build, artifact_id) == "MISSING"
    assert load(artifact_id).failure_code == REFERENCED_FILE_MISSING


def test_a_file_in_the_place_of_the_folder_is_missing(
    factory: sessionmaker[Session], storage_roots: StorageRoots, build: ModelFactory,
    photo: Path, load: Callable[[uuid.UUID], Artifact],
) -> None:  # fmt: skip
    artifact_id = import_file(factory, storage_roots, build, photo)
    photo.unlink()
    photo.parent.rmdir()
    photo.parent.write_bytes(b"now a plain file")

    assert reverify(factory, build, artifact_id) == "MISSING"
    assert load(artifact_id).failure_code == REFERENCED_FILE_MISSING


def test_a_file_that_becomes_a_directory_while_being_read_is_missing(
    factory: sessionmaker[Session], storage_roots: StorageRoots, build: ModelFactory,
    photo: Path, load: Callable[[uuid.UUID], Artifact], monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    artifact_id = import_file(factory, storage_roots, build, photo)

    def swapped(_path: Path) -> object:
        raise IsADirectoryError("is a directory")

    monkeypatch.setattr(referenced_artifacts, "digest_path", swapped)
    assert reverify(factory, build, artifact_id) == "MISSING"
    assert load(artifact_id).failure_code == REFERENCED_FILE_MISSING


def test_a_directory_in_the_place_of_the_file_is_missing(
    factory: sessionmaker[Session], storage_roots: StorageRoots, build: ModelFactory,
    photo: Path, load: Callable[[uuid.UUID], Artifact],
) -> None:  # fmt: skip
    artifact_id = import_file(factory, storage_roots, build, photo)
    photo.unlink()
    photo.mkdir()

    assert reverify(factory, build, artifact_id) == "MISSING"
    assert load(artifact_id).failure_code == REFERENCED_FILE_MISSING


def test_an_artifact_without_a_fingerprint_is_checked_for_existence_only(
    factory: sessionmaker[Session], db_session: Session, build: ModelFactory, photo: Path,
    load: Callable[[uuid.UUID], Artifact],
) -> None:  # fmt: skip
    """Hashing very large media may be deferred (IMPLEMENTATION_ARCHITECTURE.md §16.2)."""
    artifact = build.artifact(
        storage_mode="REFERENCED", storage_key=None, external_path=str(photo),
        sha256=None, size_bytes=None,
    )  # fmt: skip
    db_session.commit()

    assert reverify(factory, build, artifact.id) == "AVAILABLE"
    photo.unlink()
    assert reverify(factory, build, artifact.id) == "MISSING"
    photo.write_bytes(b"anything")
    assert reverify(factory, build, artifact.id) == "AVAILABLE"
    assert load(artifact.id).failure_code is None


def test_a_concurrent_state_change_is_not_overwritten(
    factory: sessionmaker[Session], storage_roots: StorageRoots, build: ModelFactory,
    photo: Path, load: Callable[[uuid.UUID], Artifact], monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    """The write is guarded by the state that was read, so it cannot resurrect a settled row."""
    artifact_id = import_file(factory, storage_roots, build, photo)

    def row_settles_while_the_file_is_read(_path: Path, _size: int, _recorded: object) -> bool:
        with factory() as other:
            other.execute(
                update(Artifact).where(Artifact.id == artifact_id).values(state="DELETED")
            )
            other.commit()
        return False  # the file no longer matches, so a write is due

    monkeypatch.setattr(referenced_artifacts, "_matches", row_settles_while_the_file_is_read)
    with pytest.raises(ArtifactStateError, match="DELETED"):
        reverify(factory, build, artifact_id)
    assert load(artifact_id).state == "DELETED"


# --- what may be reverified ------------------------------------------------------------------


def test_a_managed_artifact_is_not_reverified_here(
    factory: sessionmaker[Session], db_session: Session, build: ModelFactory
) -> None:
    artifact = build.artifact()
    db_session.commit()
    with pytest.raises(ArtifactStateError, match="expected REFERENCED"):
        reverify(factory, build, artifact.id)


def test_an_unknown_artifact_is_refused(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    with pytest.raises(ArtifactStateError, match="does not exist"):
        reverify(factory, build, uuid.uuid4())


@pytest.mark.parametrize("state", ["PENDING", "DELETING", "DELETE_FAILED", "DELETED"])
def test_only_an_available_or_missing_reference_is_reverified(
    factory: sessionmaker[Session], db_session: Session, build: ModelFactory, photo: Path,
    state: str,
) -> None:  # fmt: skip
    artifact = build.artifact(
        storage_mode="REFERENCED", storage_key=None, external_path=str(photo), state=state
    )
    db_session.commit()
    with pytest.raises(ArtifactStateError, match=f"REFERENCED {state}"):
        reverify(factory, build, artifact.id)


# --- relinking -------------------------------------------------------------------------------


def relink(
    factory: sessionmaker[Session], roots: StorageRoots, build: ModelFactory,
    artifact_id: uuid.UUID, candidate: Path,
) -> None:  # fmt: skip
    relink_referenced_artifact(factory, roots, artifact_id, candidate, clock=build.clock)


def missing_artifact(
    factory: sessionmaker[Session], roots: StorageRoots, build: ModelFactory, photo: Path
) -> uuid.UUID:
    """An imported photo that was then moved away, so its artifact is MISSING."""
    artifact_id = import_file(factory, roots, build, photo)
    photo.unlink()
    assert reverify(factory, build, artifact_id) == "MISSING"
    return artifact_id


def test_the_moved_file_relinks_and_the_artifact_is_available_again(
    factory: sessionmaker[Session], storage_roots: StorageRoots, build: ModelFactory,
    photo: Path, tmp_path: Path, load: Callable[[uuid.UUID], Artifact],
) -> None:  # fmt: skip
    artifact_id = missing_artifact(factory, storage_roots, build, photo)
    moved = tmp_path / "somewhere else" / "renamed.jpg"
    moved.parent.mkdir()
    moved.write_bytes(PHOTO)

    relink(factory, storage_roots, build, artifact_id, moved)

    artifact = load(artifact_id)
    assert (artifact.state, artifact.failure_code, artifact.failure_detail) == (
        "AVAILABLE", None, None,
    )  # fmt: skip
    assert artifact.external_path == str(moved.resolve())
    assert artifact.original_filename == "holiday.jpg"  # provenance: what was imported
    assert artifact.sha256 == hashlib.sha256(PHOTO).digest()
    assert moved.read_bytes() == PHOTO
    assert reverify(factory, build, artifact_id) == "AVAILABLE"


def test_a_relink_records_the_real_file_behind_a_link(
    factory: sessionmaker[Session], storage_roots: StorageRoots, build: ModelFactory,
    photo: Path, tmp_path: Path, load: Callable[[uuid.UUID], Artifact],
) -> None:  # fmt: skip
    artifact_id = missing_artifact(factory, storage_roots, build, photo)
    real_folder = tmp_path / "real folder"
    real_folder.mkdir()
    (real_folder / "moved.jpg").write_bytes(PHOTO)
    link = tmp_path / "shortcut"
    link_directory(link, real_folder)

    relink(factory, storage_roots, build, artifact_id, link / "moved.jpg")

    assert load(artifact_id).external_path == str((real_folder / "moved.jpg").resolve())


@pytest.mark.parametrize("other", [b"a different photo!!", PHOTO[:-1] + b"0"])
def test_different_media_is_replacement_not_relinking(
    factory: sessionmaker[Session], storage_roots: StorageRoots, build: ModelFactory,
    photo: Path, tmp_path: Path, load: Callable[[uuid.UUID], Artifact], other: bytes,
) -> None:  # fmt: skip
    """§59: different size or the same size with other content: nothing changes."""
    artifact_id = missing_artifact(factory, storage_roots, build, photo)
    before = load(artifact_id)
    candidate = tmp_path / "candidate.jpg"
    candidate.write_bytes(other)

    with pytest.raises(RelinkMismatchError, match="not the media"):
        relink(factory, storage_roots, build, artifact_id, candidate)

    after = load(artifact_id)
    assert (after.state, after.external_path, after.failure_code) == (
        "MISSING", before.external_path, REFERENCED_FILE_MISSING,
    )  # fmt: skip
    assert candidate.read_bytes() == other


def test_a_candidate_inside_the_application_or_unreadable_is_refused(
    factory: sessionmaker[Session], storage_roots: StorageRoots, build: ModelFactory,
    photo: Path,
) -> None:  # fmt: skip
    artifact_id = missing_artifact(factory, storage_roots, build, photo)
    inside = storage_roots.library_root / "originals" / uuid.uuid4().hex
    inside.write_bytes(PHOTO)

    with pytest.raises(ReferencedFileError, match="own storage"):
        relink(factory, storage_roots, build, artifact_id, inside)
    with pytest.raises(ReferencedFileError, match="cannot read"):
        relink(factory, storage_roots, build, artifact_id, photo)  # the old, vanished place


@pytest.mark.parametrize("state", ["AVAILABLE", "PENDING", "DELETING", "DELETE_FAILED", "DELETED"])
def test_only_a_missing_reference_is_relinked(
    factory: sessionmaker[Session], storage_roots: StorageRoots, db_session: Session,
    build: ModelFactory, photo: Path, state: str,
) -> None:  # fmt: skip
    artifact = build.artifact(
        storage_mode="REFERENCED", storage_key=None, external_path=str(photo), state=state
    )
    db_session.commit()
    with pytest.raises(ArtifactStateError, match=f"REFERENCED {state}"):
        relink(factory, storage_roots, build, artifact.id, photo)


def test_a_managed_or_unknown_artifact_is_not_relinked(
    factory: sessionmaker[Session], storage_roots: StorageRoots, db_session: Session,
    build: ModelFactory, photo: Path,
) -> None:  # fmt: skip
    managed = build.artifact(state="MISSING")
    db_session.commit()
    with pytest.raises(ArtifactStateError, match="expected REFERENCED"):
        relink(factory, storage_roots, build, managed.id, photo)
    with pytest.raises(ArtifactStateError, match="does not exist"):
        relink(factory, storage_roots, build, uuid.uuid4(), photo)


def test_nothing_can_be_relinked_without_a_recorded_fingerprint(
    factory: sessionmaker[Session], storage_roots: StorageRoots, db_session: Session,
    build: ModelFactory, photo: Path, load: Callable[[uuid.UUID], Artifact],
) -> None:  # fmt: skip
    artifact = build.artifact(
        storage_mode="REFERENCED", storage_key=None, external_path=str(photo / "gone"),
        state="MISSING", sha256=None, size_bytes=None,
    )  # fmt: skip
    db_session.commit()
    with pytest.raises(ArtifactStorageError, match="no recorded fingerprint"):
        relink(factory, storage_roots, build, artifact.id, photo)
    assert load(artifact.id).state == "MISSING"


def test_a_relink_that_loses_a_race_does_not_overwrite(
    factory: sessionmaker[Session], storage_roots: StorageRoots, build: ModelFactory,
    photo: Path, tmp_path: Path, load: Callable[[uuid.UUID], Artifact],
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    artifact_id = missing_artifact(factory, storage_roots, build, photo)
    candidate = tmp_path / "candidate.jpg"
    candidate.write_bytes(PHOTO)
    real = inspect_referenced_file

    def another_relink_wins_first(path: Path, roots: StorageRoots) -> object:
        with factory() as other:
            other.execute(
                update(Artifact).where(Artifact.id == artifact_id)
                .values(state="AVAILABLE", external_path="C:/elsewhere.jpg")
            )  # fmt: skip
            other.commit()
        return real(path, roots)

    monkeypatch.setattr(referenced_artifacts, "inspect_referenced_file", another_relink_wins_first)
    with pytest.raises(ArtifactStateError, match="AVAILABLE"):
        relink(factory, storage_roots, build, artifact_id, candidate)
    assert load(artifact_id).external_path == "C:/elsewhere.jpg"
