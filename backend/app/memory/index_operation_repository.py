"""IndexOperationRepository: the persistence mechanics of `index_operations`
(PERSISTENCE_IMPLEMENTATION.md §17, §26: "append batch, pending/failed batch,
attempt/applied/failed transition").

Two kinds of caller use it. A use case that makes a representation ANN-eligible (or not) calls
`append_batch` in the same transaction as that change (INDEX-01: SQLite precedes the index). The
IndexCoordinator reads what is due and records outcomes. Either way it joins the caller's
transaction and never commits, and every change is one statement decided by the database.

Duplicates are not errors: the schema allows one `PENDING` operation per `(representation,
operation)`, because two would say the same thing, so `append_batch` skips an operation that is
already pending.

An *opposite* pending operation is superseded, as §17 requires ("creating an opposite operation must
supersede/coalesce the obsolete desired state in the use case"). It has to be: `REMOVE` means absent
whatever SQLite says, so a pending `REMOVE` left in the queue would run after, and undo, a later
`ADD` that was skipped as a duplicate of an earlier one. There is no `SUPERSEDED` state, and a
`FAILED` one would be requeued at startup, so the obsolete operation's row is deleted: it was never
applied and records nothing that happened. (That choice is CONTEXT open question 27.)
"""

import uuid
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, delete, exists, select, text, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, aliased

from backend.app.memory.models import IndexOperation, IndexOperationKind, IndexOperationState

_OPPOSITE: dict[str, str] = {
    IndexOperationKind.ADD.value: IndexOperationKind.REMOVE.value,
    IndexOperationKind.REMOVE.value: IndexOperationKind.ADD.value,
}


@dataclass(frozen=True)
class NewOperation:
    """A desired index change to record: `kind` is `ADD` or `REMOVE`. `space_id` must be the
    representation's own space; the coordinator refuses an operation whose space differs."""

    representation_id: uuid.UUID
    space_id: uuid.UUID
    kind: str


@dataclass(frozen=True)
class DueOperation:
    id: uuid.UUID
    representation_id: uuid.UUID
    space_id: uuid.UUID
    kind: str


ATTEMPT_COUNT_CHUNK = 500


class IndexOperationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def append_batch(
        self,
        operations: Sequence[NewOperation],
        *,
        now: datetime,
        new_id: Callable[[], uuid.UUID],
    ) -> list[uuid.UUID]:
        """Record each operation as `PENDING`, due now, in the order given, and return the ids of
        those recorded. Skipped ones are omitted, so the result cannot be matched to the input by
        position.

        For each: a pending operation of the *opposite* kind for the same representation is deleted
        (it is obsolete, see the module docstring), then this one is inserted unless one of its own
        kind is already pending (it says the same thing). A later operation in the batch therefore
        supersedes an earlier one for the same representation. Two statements per operation, so
        there is no limit on the batch size from SQLite's bound-variable ceiling. An unknown `kind`
        is a `ValueError`; a representation or space that does not exist is the database's
        `IntegrityError`. `new_id` supplies each id and is called for every operation, including
        those skipped (no default: callers inject it so tests are deterministic).
        """
        recorded: list[uuid.UUID] = []
        for op in operations:
            try:
                opposite = _OPPOSITE[op.kind]
            except KeyError:
                raise ValueError(f"{op.kind!r} is not an index operation") from None
            self._session.execute(
                delete(IndexOperation).where(
                    IndexOperation.representation_id == op.representation_id,
                    IndexOperation.operation == opposite,
                    IndexOperation.state == IndexOperationState.PENDING,
                )
            )
            inserted = self._session.execute(
                sqlite_insert(IndexOperation)
                .values(
                    id=new_id(),
                    representation_id=op.representation_id,
                    representation_space_id=op.space_id,
                    operation=op.kind,
                    state=IndexOperationState.PENDING,
                    attempt_count=0,
                    not_before_at=now,
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_nothing(
                    index_elements=["representation_id", "operation"],
                    index_where=text("state = 'PENDING'"),
                )
                .returning(IndexOperation.id)
            ).scalar_one_or_none()
            if inserted is not None:
                recorded.append(inserted)
        return recorded

    def due(self, *, now: datetime, limit: int) -> list[DueOperation]:
        """Up to `limit` `PENDING` operations whose time has come, oldest due first."""
        rows = self._session.execute(
            select(
                IndexOperation.id,
                IndexOperation.representation_id,
                IndexOperation.representation_space_id,
                IndexOperation.operation,
            )
            .where(
                IndexOperation.state == IndexOperationState.PENDING,
                IndexOperation.not_before_at <= now,
            )
            .order_by(IndexOperation.not_before_at, IndexOperation.created_at, IndexOperation.id)
            .limit(limit)
        ).all()
        return [DueOperation(*row) for row in rows]

    def failed_ids(self) -> list[uuid.UUID]:
        """Every `FAILED` operation, newest first."""
        return list(
            self._session.scalars(
                select(IndexOperation.id)
                .where(IndexOperation.state == IndexOperationState.FAILED)
                .order_by(IndexOperation.created_at.desc(), IndexOperation.id)
            )
        )

    def attempt_counts(self, operation_ids: Collection[uuid.UUID]) -> dict[uuid.UUID, int]:
        ids = list(operation_ids)
        counts: dict[uuid.UUID, int] = {}
        for start in range(0, len(ids), ATTEMPT_COUNT_CHUNK):  # (bound parameters per statement)
            counts |= {
                row[0]: row[1]
                for row in self._session.execute(
                    select(IndexOperation.id, IndexOperation.attempt_count).where(
                        IndexOperation.id.in_(ids[start : start + ATTEMPT_COUNT_CHUNK])
                    )
                )
            }
        return counts

    def requeue(self, operation_id: uuid.UUID, *, now: datetime) -> bool:
        """Put a `FAILED` operation back to `PENDING`, due now, with a fresh attempt count; its
        failure code and detail stay until the next outcome replaces them. False if it is not
        `FAILED`, or if a `PENDING` operation for the same representation and kind exists (it
        already says the same thing, and the schema allows only one)."""
        other = aliased(IndexOperation)
        result = self._execute(
            update(IndexOperation)
            .where(
                IndexOperation.id == operation_id,
                IndexOperation.state == IndexOperationState.FAILED,
                ~exists().where(
                    other.state == IndexOperationState.PENDING,
                    other.representation_id == IndexOperation.representation_id,
                    other.operation == IndexOperation.operation,
                ),
            )
            .values(
                state=IndexOperationState.PENDING,
                attempt_count=0,
                not_before_at=now,
                updated_at=now,
            )
        )
        return bool(result.rowcount)

    def settle(
        self,
        operation_id: uuid.UUID,
        *,
        attempts: int,
        now: datetime,
        values: dict[str, Any],
    ) -> bool:
        """Record one attempt's outcome on a `PENDING` operation: `attempts` is the new count and
        `values` the outcome's own columns (state, retry time, failure code and detail, applied
        time). False if it was no longer `PENDING`: someone else settled it meanwhile."""
        result = self._execute(
            update(IndexOperation)
            .where(
                IndexOperation.id == operation_id,
                IndexOperation.state == IndexOperationState.PENDING,
            )
            .values(attempt_count=attempts, last_attempt_at=now, updated_at=now, **values)
        )
        return bool(result.rowcount)

    def _execute(self, statement: Any) -> "CursorResult[Any]":
        # A DML statement returns a CursorResult (it has `rowcount`); SQLAlchemy types it loosely.
        return cast("CursorResult[Any]", self._session.execute(statement))
