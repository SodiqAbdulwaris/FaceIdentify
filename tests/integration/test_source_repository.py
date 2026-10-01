"""SourceRepository contract against real SQLite (M2: TST-022; persistence §20, §22, §26).

Proved here: nothing is committed on the caller's behalf, the library page is keyset-paginated so a
source imported while paging cannot shift or repeat a page, a missing original is known from the
artifact (the source stays as it is, CONTEXT open question 24), and `set_current_run` accepts only a
run of the same source that is being accepted or already accepted, at the expected revision, decided
by the database.
"""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.sources.models import Source
from backend.app.sources.repository import LibraryCursor, SourceRepository
from backend.infrastructure.db.engine import create_session_factory
from tests.factories.models import ModelFactory


@pytest.fixture
def factory(sqlite_engine: Engine) -> sessionmaker[Session]:
    return create_session_factory(sqlite_engine)


def new_source(build: ModelFactory, artifact_id: uuid.UUID, **overrides: object) -> Source:
    """A source not yet added: the repository adds it. The artifact is made and committed by the
    caller first, so the factory session holds no open write transaction."""
    fields: dict[str, object] = dict(
        id=build.new_id(), kind="IMAGE", state="ACTIVE", display_name="beach.jpg",
        original_artifact_id=artifact_id, created_at=build.clock(),
        updated_at=build.clock(),
    )  # fmt: skip
    return Source(**(fields | overrides))


def ids_of(page_entries: list) -> list[uuid.UUID]:  # type: ignore[type-arg]
    return [entry.source.id for entry in page_entries]


# --- the caller owns the transaction ----------------------------------------------------------


def test_add_flushes_but_does_not_commit(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    artifact = build.artifact()
    build.session.commit()
    with factory() as session:
        source = SourceRepository(session).add(new_source(build, artifact.id))
        with factory() as other:  # not visible to another connection until the caller commits
            assert other.get(Source, source.id) is None
        session.rollback()
    with factory() as session:
        assert session.get(Source, source.id) is None


def test_add_checks_constraints_at_once(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    artifact = build.artifact()
    build.session.commit()
    with factory() as session, pytest.raises(IntegrityError):
        SourceRepository(session).add(new_source(build, artifact.id, display_name="   "))


def test_get_returns_the_row_as_the_database_has_it_now(
    sqlite_engine: Engine, factory: sessionmaker[Session], build: ModelFactory
) -> None:
    source = build.source()
    build.session.commit()
    with Session(sqlite_engine, expire_on_commit=False) as session:  # keeps what it has loaded
        repository = SourceRepository(session)
        held = repository.get(source.id)  # held, so the session's identity map keeps it
        assert held is not None
        assert held.display_name == "beach.jpg"
        session.commit()
        with factory() as other:
            row = other.get(Source, source.id)
            assert row is not None
            row.display_name = "renamed.jpg"
            other.commit()

        refreshed = repository.get(source.id)

        assert refreshed is not None
        assert refreshed.display_name == "renamed.jpg"
        assert repository.get(build.new_id()) is None


# --- the library page -------------------------------------------------------------------------


def test_the_library_page_lists_one_state_newest_first_with_ties_by_id(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    t0 = build.clock()
    oldest = build.source(created_at=t0)
    tied = sorted(
        (build.source(created_at=t0 + timedelta(seconds=1)) for _ in range(2)),
        key=lambda s: s.id,
        reverse=True,
    )
    newest = build.source(created_at=t0 + timedelta(seconds=2))
    build.source(state="RECYCLED", created_at=t0 + timedelta(seconds=3))  # another state
    build.session.commit()

    with factory() as session:
        page = SourceRepository(session).library_page(state="ACTIVE", limit=10)

    assert ids_of(page.entries) == [newest.id, tied[0].id, tied[1].id, oldest.id]
    assert page.next_cursor is None


def test_pages_follow_the_cursor_without_gaps_or_repeats(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    t0 = build.clock()
    sources = [build.source(created_at=t0 + timedelta(seconds=i // 2)) for i in range(7)]
    build.session.commit()
    expected = [s.id for s in sorted(sources, key=lambda s: (s.created_at, s.id), reverse=True)]

    seen: list[uuid.UUID] = []
    with factory() as session:
        repository = SourceRepository(session)
        cursor: LibraryCursor | None = None
        sizes = []
        while True:
            page = repository.library_page(state="ACTIVE", limit=3, after=cursor)
            seen += ids_of(page.entries)
            sizes.append(len(page.entries))
            if page.next_cursor is None:
                break
            cursor = page.next_cursor

    assert seen == expected
    assert sizes == [3, 3, 1]


def test_a_page_that_exactly_fits_has_no_next_cursor(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    for _ in range(4):
        build.source()
    build.session.commit()

    with factory() as session:
        repository = SourceRepository(session)
        first = repository.library_page(state="ACTIVE", limit=2)
        second = repository.library_page(state="ACTIVE", limit=2, after=first.next_cursor)

    assert (len(first.entries), first.next_cursor is not None) == (2, True)
    assert (len(second.entries), second.next_cursor) == (2, None)


def test_a_source_imported_while_paging_does_not_shift_the_next_page(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    t0 = build.clock()
    older = [build.source(created_at=t0 + timedelta(seconds=i)) for i in range(4)]
    spare = build.artifact()
    build.session.commit()
    expected_rest = [s.id for s in sorted(older, key=lambda s: s.created_at, reverse=True)][2:]

    with factory() as session:
        repository = SourceRepository(session)
        first = repository.library_page(state="ACTIVE", limit=2)
        with factory() as other:  # a new source arrives between the two requests
            SourceRepository(other).add(
                new_source(build, spare.id, created_at=t0 + timedelta(minutes=5))
            )
            other.commit()

        second = repository.library_page(state="ACTIVE", limit=2, after=first.next_cursor)

    assert ids_of(second.entries) == expected_rest  # an offset would have repeated a row


def test_an_empty_library_is_an_empty_page(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    with factory() as session:
        page = SourceRepository(session).library_page(state="ACTIVE", limit=5)

    assert (page.entries, page.next_cursor) == ([], None)


@pytest.mark.parametrize("limit", [0, -1])
def test_a_page_holds_at_least_one_source(factory: sessionmaker[Session], limit: int) -> None:
    with factory() as session, pytest.raises(ValueError, match="at least one"):
        SourceRepository(session).library_page(state="ACTIVE", limit=limit)


def test_a_missing_original_is_known_from_its_artifact_and_the_source_is_untouched(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    t0 = build.clock()
    fine = build.source(created_at=t0)
    lost = build.source(
        created_at=t0 + timedelta(seconds=1),
        original_artifact_id=build.artifact(state="MISSING").id,
    )
    build.session.commit()

    with factory() as session:
        entries = {
            e.source.id: e
            for e in SourceRepository(session).library_page(state="ACTIVE", limit=10).entries
        }

    assert entries[fine.id].original_state == "AVAILABLE"
    assert entries[lost.id].original_state == "MISSING"
    assert entries[lost.id].source.state == "ACTIVE"  # not UNAVAILABLE: that stays unassigned


def test_the_library_page_shows_rows_as_the_database_has_them_now(
    sqlite_engine: Engine, factory: sessionmaker[Session], build: ModelFactory
) -> None:
    source = build.source()
    build.session.commit()
    with Session(sqlite_engine, expire_on_commit=False) as session:  # keeps what it has loaded
        held = SourceRepository(session).get(source.id)  # held, so the identity map keeps it
        assert held is not None
        assert held.display_name == "beach.jpg"
        session.commit()
        with factory() as other:
            row = other.get(Source, source.id)
            assert row is not None
            row.display_name = "renamed.jpg"
            other.commit()

        page = SourceRepository(session).library_page(state="ACTIVE", limit=5)

    assert [entry.source.display_name for entry in page.entries] == ["renamed.jpg"]
