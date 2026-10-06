"""Partial failures across SQLite, the managed files and the USearch indexes are recoverable
(M2: TST-029; persistence §1, §23, §28; TESTING_STRATEGY.md INDEX-01 and INDEX-02).

There is no distributed transaction (architecture §19): the three stores are kept consistent by
ordering and by recovery. Each case here constructs the durable state a failure at one seam leaves,
proves with `library_problems` that it really is inconsistent, runs startup recovery, and proves the
library is then consistent and that a second run changes nothing.
"""

import io
import shutil
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.memory.erasure import RepresentationEraser
from backend.app.memory.index_coordinator import IndexCoordinator, RetryPolicy
from backend.app.memory.models import IndexOperation, Representation, RepresentationSpace
from backend.app.processing.accept_run import AcceptProcessingRunUseCase
from backend.app.recovery.startup import StartupReport, recover_on_startup
from backend.app.runtime.package_store import RuntimePackageStore
from backend.app.sources.artifact_storage import (
    MANAGED_FILE_MISSING,
    WRITE_NOT_COMPLETED,
    LibraryRootUnavailableError,
    mark_artifact_available,
    request_artifact_deletion,
    reserve_managed_artifact,
)
from backend.app.sources.models import Artifact
from backend.infrastructure.db.engine import create_session_factory
from backend.infrastructure.db.unit_of_work import TransactionRetry, UnitOfWork
from backend.infrastructure.indexing.representation_index import (
    IndexUnusableError,
    RepresentationIndex,
)
from backend.infrastructure.storage.files import ManagedFileStore
from backend.infrastructure.storage.layout import StorageRoots
from backend.infrastructure.storage.workspaces import WorkspaceManager
from tests.factories.models import ModelFactory, float32_vector
from tests.fixtures.consistency import library_problems
from tests.fixtures.persistence import AppDirs

NDIM = 4
DATA = b"the original bytes of one imported photo"


class SimulatedCrash(BaseException):
    """The process dying: no `except Exception` handler gets to tidy up after it."""


@dataclass
class Library:
    build: ModelFactory
    factory: sessionmaker[Session]
    store: ManagedFileStore
    workspaces: WorkspaceManager
    coordinator: IndexCoordinator
    space: RepresentationSpace
    engine: Engine
    roots: StorageRoots

    patch: pytest.MonkeyPatch

    def commit(self) -> None:
        self.build.session.commit()

    def problems(self, *, allow_orphans: bool = False) -> list[str]:
        self.commit()
        return library_problems(
            self.factory, self.store, self.coordinator, now=self.build.clock(),
            allow_orphans=allow_orphans,
        )  # fmt: skip

    def recover(self) -> StartupReport:
        self.commit()
        eraser = RepresentationEraser(
            self.factory, self.engine, self.coordinator, clock=self.build.clock,
            new_id=self.build.new_id, checkpoint_timeout_ms=0,
        )  # fmt: skip
        return recover_on_startup(
            self.factory, self.store, self.workspaces, self.coordinator, eraser,
            RuntimePackageStore(self.roots, new_id=self.build.new_id),
            AcceptProcessingRunUseCase(
                UnitOfWork(self.engine, retry=TransactionRetry(1, lambda _: 0)),
                new_id=self.build.new_id, clock=self.build.clock,
            ),
            clock=self.build.clock, index_batch=50, max_index_passes=5,
        )  # fmt: skip

    def artifact(self, artifact_id: uuid.UUID) -> Artifact:
        with self.factory() as session:
            row = session.get(Artifact, artifact_id)
            assert row is not None
            return row

    def operation(self, operation_id: uuid.UUID) -> IndexOperation:
        with self.factory() as session:
            row = session.get(IndexOperation, operation_id)
            assert row is not None
            return row


@pytest.fixture
def library(
    build: ModelFactory, sqlite_engine: Engine, file_store: ManagedFileStore,
    storage_roots: StorageRoots, app_dirs: AppDirs, monkeypatch: pytest.MonkeyPatch,
) -> Library:  # fmt: skip
    factory = create_session_factory(sqlite_engine)
    space = build.representation_space(dimension=NDIM)
    build.session.commit()
    return Library(
        build=build, factory=factory, store=file_store, workspaces=WorkspaceManager(storage_roots),
        coordinator=IndexCoordinator(
            factory,
            UnitOfWork(sqlite_engine, retry=TransactionRetry(1, lambda _: 0)),
            app_dirs.indexes,
            clock=build.clock, new_id=build.new_id,
            retry=RetryPolicy(max_attempts=3, backoff=lambda n: timedelta(minutes=n)),
        ),
        space=space, engine=sqlite_engine, roots=storage_roots, patch=monkeypatch,
    )  # fmt: skip


# --- durable states a failure at one seam leaves ---------------------------------------------


def import_original(library: Library, *, bytes_written: bool, available: bool) -> uuid.UUID:
    """The three-step managed import, stopped after the chosen step."""
    library.commit()
    with library.factory() as session:
        reserved = reserve_managed_artifact(
            session, "SOURCE_ORIGINAL", new_id=library.build.new_id, clock=library.build.clock
        )
        session.commit()
        artifact_id, key = reserved.id, reserved.storage_key
    assert key is not None
    if bytes_written:
        stored = library.store.store(key, io.BytesIO(DATA))
        if available:
            with library.factory() as session:
                mark_artifact_available(session, artifact_id, stored, clock=library.build.clock)
                session.commit()
    return artifact_id


def accept(library: Library, key: int, values: list[float] | None = None) -> IndexOperation:
    """What accepting a processed image commits at once: an available original, its Source, an
    ACTIVE representation, and the durable `IndexOperation` that says the index must follow."""
    artifact_id = import_original(library, bytes_written=True, available=True)
    build = library.build
    # One Source, one run and one observation, so the factories add no artifacts of their own.
    source = build.source(original_artifact_id=artifact_id)
    observation = build.observation(build.run(source_id=source.id))
    rep = build.representation(
        observation, representation_space_id=library.space.id, state="ACTIVE",
        identity_id=build.identity().id, ann_key=key,
        vector=float32_vector(values or [float(key), 1.0, 0.0, 0.0]),
    )  # fmt: skip
    operation = build.index_operation(rep, operation="ADD")
    library.commit()
    return operation


def open_index(library: Library) -> RepresentationIndex:
    return RepresentationIndex.open(
        library.coordinator.index_directory(library.space.id),
        representation_space_id=library.space.id, ndim=NDIM, metric="cos",
    )  # fmt: skip


@dataclass
class Case:
    """A named failure. `shows` is the phrase the consistency check must report before recovery
    (what is actually wrong); None only for states that are consistent by definition."""

    build: Callable[[Library], object]
    shows: str | None
    keeps_orphans: bool = False


def case_reserved_only(library: Library) -> uuid.UUID:
    return import_original(library, bytes_written=False, available=False)


def case_bytes_written_not_available(library: Library) -> uuid.UUID:
    return import_original(library, bytes_written=True, available=False)


def case_available_but_unreferenced(library: Library) -> uuid.UUID:
    return import_original(library, bytes_written=True, available=True)


def case_accepted_index_untouched(library: Library) -> IndexOperation:
    return accept(library, 1)


def case_index_persisted_but_not_settled(library: Library) -> IndexOperation:
    operation = accept(library, 1)

    def die(*_: object, **__: object) -> None:
        raise SimulatedCrash

    library.patch.setattr(library.coordinator, "_settle", die)
    with pytest.raises(SimulatedCrash):
        library.coordinator.apply_pending(limit=10)
    library.patch.undo()
    return operation


def case_index_deleted(library: Library) -> IndexOperation:
    operation = accept(library, 1)
    library.coordinator.apply_pending(limit=10)
    for path in library.coordinator.index_directory(library.space.id).iterdir():
        path.unlink()
    return operation


def case_index_manifest_corrupt(library: Library) -> IndexOperation:
    operation = accept(library, 1)
    library.coordinator.apply_pending(limit=10)
    (library.coordinator.index_directory(library.space.id) / "manifest.json").write_text("{x")
    return operation


def case_index_has_a_key_sqlite_no_longer_stands_behind(library: Library) -> IndexOperation:
    """A database restored from another moment: the index still holds what SQLite dropped."""
    operation = accept(library, 1)
    library.coordinator.apply_pending(limit=10)
    with library.factory() as session:
        row = session.get(Representation, operation.representation_id)
        assert row is not None
        row.state = "SUPERSEDED"
        session.commit()
    return operation


def case_index_lacks_a_key_sqlite_has(library: Library) -> IndexOperation:
    """The opposite: SQLite has an ACTIVE representation whose operation was applied, but the index
    file is from before it."""
    first = accept(library, 1)
    library.coordinator.apply_pending(limit=10)
    second = accept(library, 2)
    library.coordinator.apply_pending(limit=10)
    index = open_index(library)
    index.remove(2)
    index.persist(clock=library.build.clock, new_id=library.build.new_id)
    assert first.id != second.id
    return second


def case_index_holds_a_different_key_with_the_same_count(library: Library) -> IndexOperation:
    """Counts agree, so only the keys themselves can show the index is not SQLite's."""
    operation = accept(library, 1)
    library.coordinator.apply_pending(limit=10)
    index = open_index(library)
    index.remove(1)
    index.add(99, np.array([9.0, 9.0, 0.0, 0.0], dtype=np.float32))  # a key nothing has
    index.persist(clock=library.build.clock, new_id=library.build.new_id)
    return operation


def case_superseded_index_file_left_behind(library: Library) -> Path:
    """A generation the live manifest no longer names, still holding every vector it was built
    with: what an interrupted persist or a rebuild whose cleanup failed leaves."""
    accept(library, 1)
    library.coordinator.apply_pending(limit=10)
    directory = library.coordinator.index_directory(library.space.id)
    live = open_index(library).manifest
    assert live is not None
    stale = directory / f"index.{uuid.uuid4().hex}.usearch"
    shutil.copyfile(directory / live.index_file, stale)
    return stale


def case_managed_file_deleted_behind_our_back(library: Library) -> uuid.UUID:
    artifact_id = import_original(library, bytes_written=True, available=True)
    key = library.artifact(artifact_id).storage_key
    assert key is not None
    library.store.roots.path_for(key).unlink()
    return artifact_id


def case_staging_file_of_a_settled_artifact(library: Library) -> uuid.UUID:
    artifact_id = import_original(library, bytes_written=True, available=True)
    key = library.artifact(artifact_id).storage_key
    assert key is not None
    library.store.staging_path(key).write_bytes(b"a torn write that was never renamed")
    return artifact_id


def case_orphan_file_no_row_owns(library: Library) -> Path:
    stray = library.roots.library_root / "originals" / uuid.uuid4().hex
    stray.write_bytes(b"possibly the only copy, its row lost in a restore")
    return stray


def case_deletion_intent_committed_bytes_still_there(library: Library) -> uuid.UUID:
    artifact_id = import_original(library, bytes_written=True, available=True)
    with library.factory() as session:
        request_artifact_deletion(session, artifact_id, clock=library.build.clock)
        session.commit()
    return artifact_id


def case_disk_full_while_persisting_the_index(library: Library) -> IndexOperation:
    operation = accept(library, 1)

    def full_disk(*_: object, **__: object) -> None:
        raise OSError("no space left on device")

    library.patch.setattr(RepresentationIndex, "persist", full_disk)
    report = library.coordinator.apply_pending(limit=10)
    library.patch.undo()
    assert [op for op, _ in report.retrying] == [operation.id]
    return operation


CASES: dict[str, Case] = {
    "reserved only": Case(case_reserved_only, "is still PENDING"),
    "bytes written, never made available": Case(
        case_bytes_written_not_available, "is still PENDING"
    ),
    "available but unreferenced": Case(case_available_but_unreferenced, None),
    "accepted, index untouched": Case(case_accepted_index_untouched, "pending and due"),
    "index persisted, operation not settled": Case(
        case_index_persisted_but_not_settled, "pending and due"
    ),
    "index deleted": Case(case_index_deleted, "no usable index"),
    "index manifest corrupt": Case(case_index_manifest_corrupt, "no usable index"),
    "index holds a key sqlite dropped": Case(
        case_index_has_a_key_sqlite_no_longer_stands_behind, "index holds"
    ),
    "index lacks a key sqlite has": Case(case_index_lacks_a_key_sqlite_has, "index lacks keys"),
    "index holds a different key, same count": Case(
        case_index_holds_a_different_key_with_the_same_count, "index lacks keys"
    ),
    "superseded index file left behind": Case(
        case_superseded_index_file_left_behind, "superseded index files"
    ),
    "managed file deleted": Case(case_managed_file_deleted_behind_our_back, "bytes are not"),
    "staging file left behind": Case(
        case_staging_file_of_a_settled_artifact, "staging files remain"
    ),
    "orphan file": Case(case_orphan_file_no_row_owns, "files no row owns", keeps_orphans=True),
    "deletion intent, bytes still there": Case(
        case_deletion_intent_committed_bytes_still_there, "is still DELETING"
    ),
    "disk full while persisting the index": Case(
        case_disk_full_while_persisting_the_index, "no usable index"
    ),
}


# --- the matrix --------------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(CASES))
def test_a_partial_failure_is_recoverable_and_recovery_is_idempotent(
    library: Library, name: str
) -> None:
    case = CASES[name]
    case.build(library)

    before = library.problems()
    if case.shows is None:
        assert before == []
    else:
        assert any(case.shows in problem for problem in before), f"{name}: found {before}"

    library.recover()

    assert library.problems(allow_orphans=case.keeps_orphans) == []
    again = library.recover()
    assert again.repaired_nothing, f"{name}: a second recovery still repaired {again}"
    assert library.problems(allow_orphans=case.keeps_orphans) == []


# --- what recovery decides in each case -------------------------------------------------------


def test_a_reservation_whose_bytes_never_arrived_is_marked_missing_not_available(
    library: Library,
) -> None:
    artifact_id = case_reserved_only(library)

    library.recover()

    artifact = library.artifact(artifact_id)
    assert (artifact.state, artifact.failure_code) == ("MISSING", WRITE_NOT_COMPLETED)


def test_bytes_that_were_renamed_into_place_are_made_available(library: Library) -> None:
    artifact_id = case_bytes_written_not_available(library)

    library.recover()

    artifact = library.artifact(artifact_id)
    assert (artifact.state, artifact.size_bytes) == ("AVAILABLE", len(DATA))


def test_an_available_artifact_whose_file_vanished_becomes_missing_and_keeps_its_fingerprint(
    library: Library,
) -> None:
    artifact_id = case_managed_file_deleted_behind_our_back(library)
    before = library.artifact(artifact_id)

    report = library.recover()

    after = library.artifact(artifact_id)
    assert (after.state, after.failure_code) == ("MISSING", MANAGED_FILE_MISSING)
    assert (after.sha256, after.size_bytes) == (before.sha256, before.size_bytes)
    assert report.missing_managed == [artifact_id]


def test_the_orphan_file_is_reported_and_kept_never_deleted(library: Library) -> None:
    stray = case_orphan_file_no_row_owns(library)

    library.recover()

    assert stray.read_bytes().startswith(b"possibly the only copy")


def test_an_index_ahead_of_sqlite_is_rebuilt_without_the_key_it_should_not_have(
    library: Library,
) -> None:
    case_index_has_a_key_sqlite_no_longer_stands_behind(library)
    assert open_index(library).contains(1)

    report = library.recover()

    assert library.space.id in report.indexes_rebuilt
    assert not open_index(library).contains(1)


def test_an_index_behind_sqlite_is_caught_up_even_when_nothing_is_pending(
    library: Library,
) -> None:
    case_index_lacks_a_key_sqlite_has(library)
    assert not open_index(library).contains(2)
    with library.factory() as session:  # no operation is pending: only the drift check can notice
        assert not session.scalars(
            select(IndexOperation.id).where(IndexOperation.state == "PENDING")
        ).all()

    report = library.recover()

    assert library.space.id in report.indexes_rebuilt
    assert open_index(library).contains(2)


def test_an_index_that_is_already_right_is_left_alone(library: Library) -> None:
    accept(library, 1)
    library.coordinator.apply_pending(limit=10)
    manifest = open_index(library).manifest

    report = library.recover()

    assert report.indexes_rebuilt == []
    assert open_index(library).manifest == manifest


def test_a_failed_persist_leaves_the_operation_pending_and_nothing_half_written(
    library: Library,
) -> None:
    operation = case_disk_full_while_persisting_the_index(library)

    pending = library.operation(operation.id)
    assert (pending.state, pending.attempt_count, pending.failure_code) == (
        "PENDING", 1, "APPLY_ERROR",
    )  # fmt: skip
    # No index existed yet, and the failed build left nothing half-written for a reader to find.
    with pytest.raises(IndexUnusableError, match="no manifest"):
        open_index(library)


def lock_index_files(library: Library) -> None:
    """Make every index file refuse deletion, as an open handle does on Windows."""
    real_unlink = Path.unlink

    def locked(self: Path, *args: bool, **kwargs: bool) -> None:
        if self.suffix == ".usearch":
            raise PermissionError("the file is in use")
        real_unlink(self, *args, **kwargs)

    library.patch.setattr(Path, "unlink", locked)


def test_a_drift_rebuild_that_cannot_remove_the_old_generation_is_not_reported_clean(
    library: Library,
) -> None:
    """The old file still holds every vector it was built with, SQLite's say-so notwithstanding."""
    case_index_has_a_key_sqlite_no_longer_stands_behind(library)
    lock_index_files(library)

    report = library.recover()

    assert library.space.id in report.indexes_rebuilt
    assert len(report.index_operations.leftover_files) == 1
    assert "1 superseded index files not removed" in report.unresolved
    assert not report.clean
    assert any("superseded index files" in problem for problem in library.problems())

    library.patch.undo()  # the lock is released: the next start finishes the cleanup
    again = library.recover()

    assert again.clean
    assert library.problems() == []


def test_a_non_finite_vector_is_reported_every_start_not_silently_skipped(
    library: Library,
) -> None:
    accept(library, 1)
    accept(library, 2, [float("nan"), 1.0, 0.0, 0.0])

    first = library.recover()
    second = library.recover()

    for report in (first, second):
        assert "1 representations that cannot be indexed" in report.unresolved
    assert not second.clean  # a key SQLite has can never be in the index, so it stays unresolved


def test_a_library_root_that_is_not_there_recovers_nothing(library: Library) -> None:
    artifact_id = case_reserved_only(library)
    library.commit()
    root = library.roots.library_root
    real_is_dir = Path.is_dir
    library.patch.setattr(Path, "is_dir", lambda self: False if self == root else real_is_dir(self))

    with pytest.raises(LibraryRootUnavailableError):
        library.recover()

    assert (
        library.artifact(artifact_id).state == "PENDING"
    )  # not read as "the write never finished"
