"""Managed artifacts whose files are gone become MISSING at startup (M2: TST-029 and TST-030;
IMPLEMENTATION_ARCHITECTURE.md §16.4: recovery reconciles "missing available files").

Existence only: nothing is hashed, the row keeps its fingerprint and references, and only an
AVAILABLE managed artifact is ever moved.
"""

import io
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, update
from sqlalchemy.orm import Session, sessionmaker

from backend.app.sources import artifact_storage
from backend.app.sources.artifact_storage import (
    MANAGED_FILE_MISSING,
    create_managed_artifact,
    mark_missing_managed_files,
)
from backend.app.sources.models import Artifact
from backend.infrastructure.db.engine import create_session_factory
from backend.infrastructure.storage.files import ManagedFileStore
from tests.factories.models import ModelFactory


@pytest.fixture
def factory(sqlite_engine: Engine) -> sessionmaker[Session]:
    return create_session_factory(sqlite_engine)


def stored(
    factory: sessionmaker[Session], store: ManagedFileStore, build: ModelFactory
) -> tuple[uuid.UUID, Path]:
    artifact_id = create_managed_artifact(
        factory, store, "SOURCE_ORIGINAL", io.BytesIO(b"bytes"),
        new_id=build.new_id, clock=build.clock,
    )  # fmt: skip
    with factory() as session:
        row = session.get(Artifact, artifact_id)
        assert row is not None
        key = row.storage_key
    assert key is not None
    return artifact_id, store.roots.path_for(key)


def state_of(factory: sessionmaker[Session], artifact_id: uuid.UUID) -> str:
    with factory() as session:
        artifact = session.get(Artifact, artifact_id)
        assert artifact is not None
        return artifact.state


def test_only_the_artifact_whose_file_is_gone_is_marked(
    factory: sessionmaker[Session], file_store: ManagedFileStore, build: ModelFactory
) -> None:
    kept, _ = stored(factory, file_store, build)
    lost, lost_path = stored(factory, file_store, build)
    lost_path.unlink()

    assert mark_missing_managed_files(factory, file_store) == [lost]

    assert (state_of(factory, kept), state_of(factory, lost)) == ("AVAILABLE", "MISSING")
    with factory() as session:
        row = session.get(Artifact, lost)
        assert row is not None
        assert (row.failure_code, row.sha256 is not None, row.size_bytes) == (
            MANAGED_FILE_MISSING, True, 5,
        )  # fmt: skip
    assert mark_missing_managed_files(factory, file_store) == []  # idempotent


@pytest.mark.parametrize("state", ["PENDING", "MISSING", "DELETING", "DELETE_FAILED", "DELETED"])
def test_an_artifact_in_another_state_is_never_touched(
    factory: sessionmaker[Session], file_store: ManagedFileStore, build: ModelFactory, state: str
) -> None:
    artifact_id, path = stored(factory, file_store, build)
    path.unlink()
    with factory() as session:
        session.execute(update(Artifact).where(Artifact.id == artifact_id).values(state=state))
        session.commit()

    assert mark_missing_managed_files(factory, file_store) == []
    assert state_of(factory, artifact_id) == state


def test_a_referenced_original_is_not_a_managed_file(
    factory: sessionmaker[Session], file_store: ManagedFileStore, build: ModelFactory,
    tmp_path: Path,
) -> None:  # fmt: skip
    artifact = build.artifact(
        storage_mode="REFERENCED", storage_key=None, external_path=str(tmp_path / "gone.jpg")
    )
    build.session.commit()

    assert mark_missing_managed_files(factory, file_store) == []
    assert state_of(factory, artifact.id) == "AVAILABLE"


def test_a_key_that_is_not_a_valid_managed_key_is_left_for_the_scan_to_report(
    factory: sessionmaker[Session], file_store: ManagedFileStore, build: ModelFactory
) -> None:
    artifact = build.artifact(storage_key="originals/../../database/library.db")
    build.session.commit()

    assert mark_missing_managed_files(factory, file_store) == []
    assert state_of(factory, artifact.id) == "AVAILABLE"


def test_a_file_that_cannot_be_examined_is_not_marked_missing(
    factory: sessionmaker[Session], file_store: ManagedFileStore, build: ModelFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    artifact_id, path = stored(factory, file_store, build)
    real_stat = Path.stat

    def denied(self: Path, **kwargs: bool) -> Any:
        if self == path:
            raise PermissionError("access is denied")
        return real_stat(self, **kwargs)

    monkeypatch.setattr(Path, "stat", denied)

    assert mark_missing_managed_files(factory, file_store) == []
    assert state_of(factory, artifact_id) == "AVAILABLE"


def test_a_directory_where_the_file_was_counts_as_missing(
    factory: sessionmaker[Session], file_store: ManagedFileStore, build: ModelFactory
) -> None:
    artifact_id, path = stored(factory, file_store, build)
    path.unlink()
    path.mkdir()

    assert mark_missing_managed_files(factory, file_store) == [artifact_id]


def test_an_artifact_settled_while_the_scan_ran_is_not_overwritten(
    factory: sessionmaker[Session], file_store: ManagedFileStore, build: ModelFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    artifact_id, path = stored(factory, file_store, build)
    path.unlink()
    real = artifact_storage.transition_artifact

    def settled_first(session: Session, target: uuid.UUID, *args: Any, **kwargs: Any) -> None:
        with factory() as other:
            other.execute(update(Artifact).where(Artifact.id == target).values(state="DELETING"))
            other.commit()
        real(session, target, *args, **kwargs)

    monkeypatch.setattr(artifact_storage, "transition_artifact", settled_first)

    assert mark_missing_managed_files(factory, file_store) == []
    assert state_of(factory, artifact_id) == "DELETING"
