"""Logical Source recycle and restore against a real database and real managed bytes (M2: TST-025
"recycle/restore"; API and Contracts.md §5.5-§5.6 and §60; processing-architecture-v1.md §30).

Recycling is database state: no byte moves, no other row changes, and restoring avoids
reprocessing because nothing about the Source's processing history was touched.
"""

import io
import uuid
from typing import Any

import pytest
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session, sessionmaker

from backend.app.sources.artifact_storage import create_managed_artifact
from backend.app.sources.lifecycle import (
    SourceLifecycleError,
    StaleSourceRevisionError,
    recycle_source,
    restore_source,
)
from backend.app.sources.models import Artifact, Source
from backend.infrastructure.db.engine import Base, create_session_factory
from backend.infrastructure.storage.files import ManagedFileStore
from tests.factories.models import ModelFactory

PHOTO = b"\xff\xd8 bytes that recycling must never move"


@pytest.fixture
def factory(sqlite_engine: Engine) -> sessionmaker[Session]:
    return create_session_factory(sqlite_engine)


def other_tables(session: Session) -> dict[str, list[tuple[Any, ...]]]:
    """Every row of every table except `sources`: what recycling must leave exactly as it is."""
    return {
        table.name: sorted(map(tuple, session.execute(select(table)).all()), key=repr)
        for table in Base.metadata.sorted_tables
        if table.name != "sources"
    }


def reload(factory: sessionmaker[Session], source_id: uuid.UUID) -> Source:
    with factory() as session:
        source = session.get(Source, source_id)
        assert source is not None
        return source


# --- recycle and restore ---------------------------------------------------------------------


def test_recycling_moves_an_active_source_to_the_bin(
    db_session: Session, build: ModelFactory
) -> None:
    source = build.source()
    db_session.commit()
    before = source.updated_at
    build.clock.advance(minutes=5)

    recycled = recycle_source(db_session, source.id, expected_revision=1, clock=build.clock)

    assert recycled.state == "RECYCLED"
    assert recycled.recycled_at is not None
    assert recycled.updated_at == recycled.recycled_at > before
    assert recycled.revision == 2


def test_restoring_brings_it_back_and_clears_the_recycle_time(
    db_session: Session, build: ModelFactory
) -> None:
    source = build.source()
    db_session.commit()
    build.clock.advance(minutes=5)
    recycled_at = recycle_source(
        db_session, source.id, expected_revision=1, clock=build.clock
    ).updated_at
    build.clock.advance(minutes=5)

    restored = restore_source(db_session, source.id, expected_revision=2, clock=build.clock)

    assert (restored.state, restored.recycled_at, restored.revision) == ("ACTIVE", None, 3)
    assert restored.updated_at > recycled_at
    assert restored.created_at == source.created_at


def test_the_caller_owns_the_transaction(
    factory: sessionmaker[Session], db_session: Session, build: ModelFactory
) -> None:
    source = build.source()
    db_session.commit()
    source_id = source.id

    with factory() as session:
        recycle_source(session, source_id, expected_revision=1, clock=build.clock)
        session.rollback()

    assert reload(factory, source_id).state == "ACTIVE"


def test_recycling_and_restoring_move_no_bytes_and_change_nothing_else(
    factory: sessionmaker[Session], db_session: Session, file_store: ManagedFileStore,
    build: ModelFactory,
) -> None:  # fmt: skip
    artifact_id = create_managed_artifact(
        factory, file_store, "SOURCE_ORIGINAL", io.BytesIO(PHOTO),
        new_id=build.new_id, clock=build.clock,
    )  # fmt: skip
    source = build.source(original_artifact_id=artifact_id)
    # A finished run: recycling is refused while one is still working (SourceBusyError).
    source.current_processing_run_id = build.run(source_id=source.id, state="COMPLETED").id
    db_session.commit()
    source_id = source.id
    key = f"originals/{artifact_id.hex}"
    path = file_store.roots.path_for(key)
    stat_before = path.stat()
    with factory() as session:
        others_before = other_tables(session)

    with factory() as session:
        recycle_source(session, source_id, expected_revision=1, clock=build.clock)
        session.commit()
    with factory() as session:
        assert other_tables(session) == others_before
    assert path.read_bytes() == PHOTO
    assert path.stat().st_mtime_ns == stat_before.st_mtime_ns
    assert file_store.staging_files() == []
    assert reload(factory, source_id).current_processing_run_id is not None

    with factory() as session:
        restore_source(session, source_id, expected_revision=2, clock=build.clock)
        session.commit()
    with factory() as session:
        assert other_tables(session) == others_before
    assert path.read_bytes() == PHOTO
    assert reload(factory, source_id).current_processing_run_id is not None


# --- what cannot be recycled or restored -----------------------------------------------------


@pytest.mark.parametrize("state", ["RECYCLED", "DELETING", "DELETED", "UNAVAILABLE"])
def test_only_an_active_source_is_recycled(
    db_session: Session, build: ModelFactory, state: str
) -> None:
    source = build.source(state=state)
    db_session.commit()

    with pytest.raises(SourceLifecycleError, match=f"is {state}"):
        recycle_source(db_session, source.id, expected_revision=1, clock=build.clock)
    db_session.rollback()
    assert reload_state(db_session, source.id) == state


@pytest.mark.parametrize("state", ["ACTIVE", "DELETING", "DELETED", "UNAVAILABLE"])
def test_only_a_recycled_source_is_restored(
    db_session: Session, build: ModelFactory, state: str
) -> None:
    source = build.source(state=state)
    db_session.commit()

    with pytest.raises(SourceLifecycleError, match=f"is {state}"):
        restore_source(db_session, source.id, expected_revision=1, clock=build.clock)
    db_session.rollback()
    assert reload_state(db_session, source.id) == state


def reload_state(session: Session, source_id: uuid.UUID) -> str:
    source = session.get(Source, source_id, populate_existing=True)
    assert source is not None
    return source.state


def test_an_unknown_source_is_refused(db_session: Session, build: ModelFactory) -> None:
    for operation in (recycle_source, restore_source):
        with pytest.raises(SourceLifecycleError, match="does not exist"):
            operation(db_session, uuid.uuid4(), expected_revision=1, clock=build.clock)


def test_a_stale_revision_changes_nothing(
    factory: sessionmaker[Session], db_session: Session, build: ModelFactory
) -> None:
    source = build.source()
    db_session.commit()
    source_id = source.id

    with factory() as first, factory() as second:
        recycle_source(first, source_id, expected_revision=1, clock=build.clock)
        first.commit()
        with pytest.raises(StaleSourceRevisionError, match="revision 2, expected 1"):
            recycle_source(second, source_id, expected_revision=1, clock=build.clock)

    assert reload(factory, source_id).revision == 2


def test_a_stale_revision_is_reported_even_when_the_state_is_also_wrong(
    db_session: Session, build: ModelFactory
) -> None:
    """The caller's view is out of date, which is the more useful thing to tell it."""
    source = build.source(state="RECYCLED")
    db_session.commit()

    with pytest.raises(StaleSourceRevisionError):
        recycle_source(db_session, source.id, expected_revision=7, clock=build.clock)


# --- restoring "where possible" --------------------------------------------------------------


@pytest.mark.parametrize("original_state", ["DELETING", "DELETE_FAILED", "DELETED"])
def test_a_source_whose_original_bytes_are_gone_is_not_restored(
    db_session: Session, build: ModelFactory, original_state: str
) -> None:
    source = build.source(
        state="RECYCLED", original_artifact_id=build.artifact(state=original_state).id
    )
    db_session.commit()

    with pytest.raises(SourceLifecycleError, match=f"its original is {original_state}"):
        restore_source(db_session, source.id, expected_revision=1, clock=build.clock)
    db_session.rollback()
    assert reload_state(db_session, source.id) == "RECYCLED"


def test_the_state_is_reported_before_the_original(
    db_session: Session, build: ModelFactory
) -> None:
    """An ACTIVE source is refused for being ACTIVE, whatever has happened to its original."""
    source = build.source(state="ACTIVE", original_artifact_id=build.artifact(state="DELETED").id)
    db_session.commit()

    with pytest.raises(SourceLifecycleError, match="is ACTIVE; expected RECYCLED"):
        restore_source(db_session, source.id, expected_revision=1, clock=build.clock)


def test_a_deletion_begun_in_another_session_is_seen_despite_a_cached_original(
    factory: sessionmaker[Session], db_session: Session, build: ModelFactory
) -> None:
    """Sessions keep loaded objects after a commit, so the database must evaluate the guard."""
    original = build.artifact(state="AVAILABLE")
    source = build.source(state="RECYCLED", original_artifact_id=original.id)
    db_session.commit()
    source_id, original_id = source.id, original.id

    with factory() as restoring:
        cached = restoring.get(Artifact, original_id)
        assert cached is not None
        assert cached.state == "AVAILABLE"
        restoring.commit()  # the cached object outlives the transaction

        with factory() as deleting:
            deleting.execute(
                update(Artifact).where(Artifact.id == original_id).values(state="DELETING")
            )
            deleting.commit()

        assert cached.state == "AVAILABLE"  # stale, exactly as the reviewer described
        with pytest.raises(SourceLifecycleError, match="its original is DELETING"):
            restore_source(restoring, source_id, expected_revision=1, clock=build.clock)
        restoring.rollback()

    assert reload(factory, source_id).state == "RECYCLED"


@pytest.mark.parametrize("original_state", ["DELETING", "DELETE_FAILED", "DELETED"])
def test_a_source_whose_original_is_being_deleted_is_not_recycled(
    db_session: Session, build: ModelFactory, original_state: str
) -> None:
    source = build.source(original_artifact_id=build.artifact(state=original_state).id)
    db_session.commit()

    with pytest.raises(SourceLifecycleError, match=f"its original is {original_state}"):
        recycle_source(db_session, source.id, expected_revision=1, clock=build.clock)
    db_session.rollback()
    assert reload_state(db_session, source.id) == "ACTIVE"


@pytest.mark.parametrize("original_state", ["AVAILABLE", "MISSING"])
def test_a_source_is_restored_while_its_original_can_still_come_back(
    db_session: Session, build: ModelFactory, original_state: str
) -> None:
    """A MISSING referenced original keeps its Source (§23.5): the user can still Locate File."""
    source = build.source(
        state="RECYCLED", original_artifact_id=build.artifact(state=original_state).id
    )
    db_session.commit()

    restored = restore_source(db_session, source.id, expected_revision=1, clock=build.clock)

    assert restored.state == "ACTIVE"
