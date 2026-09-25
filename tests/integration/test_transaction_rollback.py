"""A use case that fails part-way leaves nothing behind (M2: TST-023; TESTING_STRATEGY.md PER-01:
"Multi-record authoritative domain operations must commit atomically").

Use cases flush but never commit: the caller owns the transaction (PERSISTENCE_IMPLEMENTATION.md
§26). So the guarantee to prove is that a failure at *any* point, followed by the caller's
rollback, leaves the database exactly as it was, even though by then the use case may already have
flushed inserts and run bulk `UPDATE`s with `synchronize_session=False`.

Rather than hand-picking failure points, each case first counts every SQL statement its use case
sends, then is re-run once per statement with a fault injected at exactly that statement.
"""

import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, event
from sqlalchemy.orm import Session

from backend.app.identities.models import EvidenceKind
from backend.app.identities.use_cases import (
    StaleRevisionError,
    activate_identity,
    assign_representation_to_identity,
    merge_identities,
    split_identity,
)
from backend.app.people.use_cases import (
    assign_identity_to_person,
    remove_identity_from_person,
    rename_person,
)
from backend.infrastructure.db.engine import create_session_factory
from tests.factories.models import ModelFactory

Operation = Callable[[Session], object]


class InjectedFault(Exception):
    """Raised in place of a real SQL statement; never raised by production code."""


def database_path(engine: Engine) -> Path:
    assert engine.url.database is not None
    return Path(engine.url.database)


def committed_state(engine: Engine) -> dict[str, list[tuple[Any, ...]]]:
    """Every row of every table, as committed, read over a connection outside SQLAlchemy."""
    with closing(sqlite3.connect(database_path(engine))) as connection:
        tables = [
            name
            for (name,) in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        return {
            table: sorted(connection.execute(f'SELECT * FROM "{table}"').fetchall(), key=repr)
            for table in tables
        }


@contextmanager
def statement_counter(engine: Engine, fail_at: int | None = None) -> Iterator[list[str]]:
    """Record every statement sent to SQLite; raise `InjectedFault` instead of the `fail_at`-th."""
    seen: list[str] = []

    def before(_conn: Any, _cursor: Any, statement: str, *_: Any) -> None:
        seen.append(statement)
        if fail_at is not None and len(seen) == fail_at:
            raise InjectedFault(statement)

    event.listen(engine, "before_cursor_execute", before)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", before)


@dataclass(frozen=True)
class Case:
    name: str
    arrange: Callable[[ModelFactory], Operation]


# --- the use cases, each set up with enough data to reach its every write ---------------------


def assign_created(build: ModelFactory) -> Operation:
    """First assignment to a new identity: also reads for existing IDENTITY_CREATED evidence."""
    identity = build.identity()
    pending = build.representation(state="PENDING")
    return lambda s: assign_representation_to_identity(
        s, pending.id, identity.id, new_id=build.new_id, clock=build.clock,
        evidence_kind=EvidenceKind.IDENTITY_CREATED,
    )  # fmt: skip


def assign_matched(build: ModelFactory) -> Operation:
    identity = build.identity()
    pending = build.representation(state="PENDING")
    return lambda s: assign_representation_to_identity(
        s, pending.id, identity.id, new_id=build.new_id, clock=build.clock,
        evidence_kind=EvidenceKind.IDENTITY_MATCHED,
    )  # fmt: skip


def activate(build: ModelFactory) -> Operation:
    identity = build.identity(state="PENDING")
    return lambda s: activate_identity(s, identity.id, expected_revision=1, clock=build.clock)


def merge(build: ModelFactory) -> Operation:
    survivor = build.identity()
    loser = build.identity()
    space = build.representation_space()
    for key in (1, 2):
        build.representation(representation_space_id=space.id, identity_id=loser.id,
                             state="ACTIVE", ann_key=key)  # fmt: skip
    build.association(identity_id=loser.id, person_id=build.person().id)  # carry-over path
    return lambda s: merge_identities(
        s, loser.id, survivor.id, expected_revision=1, new_id=build.new_id, clock=build.clock
    )


def split(build: ModelFactory) -> Operation:
    source = build.identity()
    space = build.representation_space()
    moved = [
        build.representation(
            representation_space_id=space.id, identity_id=source.id, state="ACTIVE", ann_key=key
        ).id  # fmt: skip
        for key in (1, 2, 3)
    ][:2]
    return lambda s: split_identity(s, source.id, moved, new_id=build.new_id, clock=build.clock)


def correct_person_link(build: ModelFactory) -> Operation:
    """Reassignment is the correction path: supersede the old link, add Evidence and a new link."""
    identity = build.identity()
    build.association(identity_id=identity.id, person_id=build.person().id)
    other = build.person(display_name="Bob", normalized_name="bob")
    return lambda s: assign_identity_to_person(
        s, identity.id, other.id, new_id=build.new_id, clock=build.clock
    )


def remove_person_link(build: ModelFactory) -> Operation:
    identity = build.identity()
    build.association(identity_id=identity.id, person_id=build.person().id)
    return lambda s: remove_identity_from_person(
        s, identity.id, new_id=build.new_id, clock=build.clock
    )


def rename(build: ModelFactory) -> Operation:
    person = build.person()
    return lambda s: rename_person(s, person.id, "Alicia", expected_revision=1, clock=build.clock)


CASES = [
    Case("assign_created", assign_created),
    Case("assign_matched", assign_matched),
    Case("activate", activate),
    Case("merge", merge),
    Case("split", split),
    Case("correct_person_link", correct_person_link),
    Case("remove_person_link", remove_person_link),
    Case("rename", rename),
]


def arranged(
    case: Case, build: ModelFactory, db_session: Session, sqlite_engine: Engine
) -> tuple[Operation, dict[str, list[tuple[Any, ...]]]]:
    operation = case.arrange(build)
    db_session.commit()
    db_session.close()
    return operation, committed_state(sqlite_engine)


# --- tests -------------------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_a_fault_at_any_statement_then_rollback_leaves_the_database_unchanged(
    case: Case, sqlite_engine: Engine, db_session: Session, build: ModelFactory
) -> None:
    operation, before = arranged(case, build, db_session, sqlite_engine)
    factory = create_session_factory(sqlite_engine)

    # Dry run: how many statements does the use case send? Undo it the same way a caller would.
    with factory() as session, statement_counter(sqlite_engine) as statements:
        operation(session)
        session.rollback()
    writes = [s for s in statements if s.lstrip().upper().startswith(("INSERT", "UPDATE"))]
    assert writes, "the use case wrote nothing, so this case proves nothing"
    assert committed_state(sqlite_engine) == before

    for fail_at in range(1, len(statements) + 1):
        with factory() as session:
            with statement_counter(sqlite_engine, fail_at), pytest.raises(InjectedFault):
                operation(session)
            session.rollback()
            # The caller carries on and commits: nothing of the failed use case may go with it.
            session.commit()
        assert committed_state(sqlite_engine) == before, f"fault at statement {fail_at}"

    # And the faults were injected into a path that really does succeed, and that sends exactly
    # the statements the loop covered (a longer path would leave its extra statements untested).
    with factory() as session, statement_counter(sqlite_engine) as final_statements:
        operation(session)
        session.commit()
    assert final_statements == statements  # COMMIT is a DBAPI call, not a cursor statement
    assert committed_state(sqlite_engine) != before


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_closing_the_session_without_committing_discards_everything(
    case: Case, sqlite_engine: Engine, db_session: Session, build: ModelFactory
) -> None:
    """A caller that swallows the error and just leaves the session block must not leak writes:
    closing a session with an open transaction rolls it back."""
    operation, before = arranged(case, build, db_session, sqlite_engine)
    factory = create_session_factory(sqlite_engine)

    with factory() as session:
        operation(session)  # succeeds, flushes everything
        # no commit, no rollback: the `with` block closes the session

    assert committed_state(sqlite_engine) == before


def test_a_stale_merge_that_flushed_before_failing_commits_nothing_after_rollback(
    sqlite_engine: Engine, db_session: Session, build: ModelFactory
) -> None:
    """`merge_identities` checks the loser's revision last, after it has already moved
    representations, reconciled the Person link and inserted Evidence and lineage (see its
    implementation entry). The caller's rollback must discard all of that."""
    survivor = build.identity()
    loser = build.identity()
    space = build.representation_space()
    build.representation(representation_space_id=space.id, identity_id=loser.id,
                         state="ACTIVE", ann_key=1)  # fmt: skip
    build.association(identity_id=loser.id, person_id=build.person().id)
    db_session.commit()
    db_session.close()
    before = committed_state(sqlite_engine)

    with (
        create_session_factory(sqlite_engine)() as session,
        statement_counter(sqlite_engine) as statements,
    ):
        with pytest.raises(StaleRevisionError):
            merge_identities(
                session, loser.id, survivor.id,
                expected_revision=99, new_id=build.new_id, clock=build.clock,
            )  # fmt: skip
        assert any(s.lstrip().upper().startswith("INSERT") for s in statements)  # it did write
        session.rollback()
        session.commit()

    assert committed_state(sqlite_engine) == before
