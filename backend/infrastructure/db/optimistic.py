"""Shared optimistic-locking update helper (PERSISTENCE_IMPLEMENTATION.md §2).

Every mutable, user-visible aggregate has a `revision INTEGER NOT NULL DEFAULT 1` column;
updates that can race use `WHERE id = :id AND revision = :expected_revision`, then increment
`revision`. This gives every feature one correct implementation of that pattern, instead of each
re-deriving the session-sync subtlety found while building `Identity` activation: the default
`synchronize_session="auto"` strategy cannot safely evaluate an expression-based SET value
(`revision + 1`) against an already-loaded Python object, so callers must not trust any
in-memory copy of the row after this call and should re-fetch with `populate_existing=True`.
"""

from collections.abc import Sequence
from typing import Any, cast

from sqlalchemy import ColumnElement, CursorResult
from sqlalchemy import update as sa_update
from sqlalchemy.orm import Session


def optimistic_locked_update(
    session: Session,
    model: type[Any],
    row_id: Any,
    *,
    expected_revision: int,
    values: dict[str, Any],
    extra_where: Sequence[ColumnElement[bool]] = (),
) -> int:
    """Update one row of `model` by primary key `id`, if its `revision` matches.

    `extra_where` adds further required conditions (e.g. a required current state), evaluated
    against the database, never against a cached object. Returns the number of rows updated (0
    or 1); the caller decides what a 0 means (row missing, stale revision, or an `extra_where`
    condition that did not hold) and how to report it.
    """
    result = cast(
        "CursorResult[Any]",
        session.execute(
            sa_update(model)
            .where(model.id == row_id, model.revision == expected_revision, *extra_where)
            .values(**values, revision=model.revision + 1),
            execution_options={"synchronize_session": False},
        ),
    )
    return result.rowcount
