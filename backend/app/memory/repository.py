"""Repositories for `observations` and `representations`
(PERSISTENCE_IMPLEMENTATION.md §26: "batch add, explicit pages/streams, candidate lookup by ann
keys, ann-key allocation, lifecycle transition").

Like the other repositories they join the caller's transaction and never commit, and every change is
one statement decided by the database. Pages are keyset-paginated (§22: "large/growing collection ->
explicit cursor-paginated query"), so rows added while someone is paging cannot shift or repeat a
page. Representation reads are *projections* (`RepresentationSummary`): a vector is a few kilobytes
and a caller that needs it asks for the row.

Two rules live in the repository because the schema cannot say them:

* `RepresentationRepository.transition` never moves a representation into or out of `ERASING` or
  `ERASED`. Erasure is the two-step `RepresentationEraser` (§6.2), whose guarded transitions and
  index work a plain state change would bypass.
* `allocate_ann_key` is the one place a key is allocated. A permanent key is handed out when a
  representation becomes ANN-eligible, unique within its space; a key allocated in a transaction
  that rolls back is handed out again, which is harmless because only committed keys are indexed
  (CONTEXT open question 21, finalised 2026-10-01: run-local indexes use their own labels, never
  these keys).
"""

import uuid
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, and_, insert, or_, select, update
from sqlalchemy.orm import Session

from backend.app.memory.models import (
    AnnKeySequence,
    Observation,
    Representation,
    RepresentationState,
)

_KEYS_PER_QUERY = 500  # bound parameters per statement
_ERASURE_STATES = (RepresentationState.ERASING, RepresentationState.ERASED)


def _execute(session: Session, statement: Any) -> "CursorResult[Any]":
    # A DML statement returns a CursorResult (it has `rowcount`); SQLAlchemy types it loosely.
    return cast("CursorResult[Any]", session.execute(statement))


class ObservationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add_batch(self, observations: Sequence[Observation]) -> list[Observation]:
        """Stage the observations and flush once, so their constraints are checked now. One
        flush, not one statement per call: a processing run records its faces in batches."""
        self._session.add_all(observations)
        self._session.flush()
        return list(observations)

    def get(self, observation_id: uuid.UUID) -> Observation | None:
        """The row as the database has it now, not as this session last saw it."""
        return self._session.get(Observation, observation_id, populate_existing=True)

    def page_for_run(
        self, run_id: uuid.UUID, *, limit: int, after_sequence: int | None = None
    ) -> list[Observation]:
        """Up to `limit` observations of a run in the order they were recorded
        (`sequence_in_run`, unique per run), starting after `after_sequence`. Fewer than `limit`
        means the last page. `limit` must be at least 1."""
        if limit < 1:
            raise ValueError("a page holds at least one observation")
        query = select(Observation).where(Observation.processing_run_id == run_id)
        if after_sequence is not None:
            query = query.where(Observation.sequence_in_run > after_sequence)
        return list(
            self._session.scalars(
                query.order_by(Observation.sequence_in_run)
                .limit(limit)
                .execution_options(populate_existing=True)
            )
        )

    def transition(
        self,
        observation_id: uuid.UUID,
        *,
        from_states: Collection[str],
        to_state: str,
        superseded_by_run_id: uuid.UUID | None = None,
    ) -> bool:
        """Move the observation to `to_state` only if it is in one of `from_states` now: one
        guarded `UPDATE`. `superseded_by_run_id` is recorded when given. False if it was not."""
        values: dict[str, Any] = {"state": to_state}
        if superseded_by_run_id is not None:
            values["superseded_by_run_id"] = superseded_by_run_id
        result = _execute(
            self._session,
            update(Observation)
            .where(Observation.id == observation_id, Observation.state.in_(list(from_states)))
            .values(**values)
            .execution_options(synchronize_session=False),
        )
        return bool(result.rowcount)


@dataclass(frozen=True)
class RepresentationSummary:
    """A representation without its vector."""

    id: uuid.UUID
    observation_id: uuid.UUID
    identity_id: uuid.UUID | None
    representation_space_id: uuid.UUID
    state: str
    ann_key: int | None
    created_at: datetime


@dataclass(frozen=True)
class RepresentationCursor:
    """Where the next page starts: after the row with this `created_at` and `id`."""

    created_at: datetime
    id: uuid.UUID


_SUMMARY_COLUMNS = (
    Representation.id,
    Representation.observation_id,
    Representation.identity_id,
    Representation.representation_space_id,
    Representation.state,
    Representation.ann_key,
    Representation.created_at,
)


class RepresentationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add_batch(self, representations: Sequence[Representation]) -> list[Representation]:
        """Stage the representations and flush once, so their constraints are checked now."""
        self._session.add_all(representations)
        self._session.flush()
        return list(representations)

    def get(self, representation_id: uuid.UUID) -> Representation | None:
        """The row as the database has it now, not as this session last saw it."""
        return self._session.get(Representation, representation_id, populate_existing=True)

    def page_for_run(
        self,
        run_id: uuid.UUID,
        *,
        limit: int,
        after: RepresentationCursor | None = None,
        states: Collection[str] | None = None,
    ) -> tuple[list[RepresentationSummary], RepresentationCursor | None]:
        """Up to `limit` representations of a run, oldest first (ties by id), in `states` if given,
        starting after the cursor, with the cursor of the next page (None on the last). `limit` must
        be at least 1."""
        if limit < 1:
            raise ValueError("a page holds at least one representation")
        query = select(*_SUMMARY_COLUMNS).where(Representation.processing_run_id == run_id)
        if states is not None:
            query = query.where(Representation.state.in_(list(states)))
        if after is not None:
            query = query.where(
                or_(
                    Representation.created_at > after.created_at,
                    and_(
                        Representation.created_at == after.created_at, Representation.id > after.id
                    ),
                )
            )
        rows = self._session.execute(
            query.order_by(Representation.created_at, Representation.id).limit(limit + 1)
        ).all()  # one more than asked: whether there is a next page
        page = [RepresentationSummary(*row) for row in rows[:limit]]
        more = len(rows) > limit
        last = page[-1] if more else None
        return page, RepresentationCursor(last.created_at, last.id) if last else None

    def by_ann_keys(
        self, representation_space_id: uuid.UUID, ann_keys: Sequence[int]
    ) -> dict[int, RepresentationSummary]:
        """The representations holding these keys in this space, by key, whatever their state: an
        index returns candidate keys only and the caller decides what is still eligible (§23). A key
        no row holds is absent. Keys are read `_KEYS_PER_QUERY` at a time."""
        unique = list(dict.fromkeys(ann_keys))
        found: dict[int, RepresentationSummary] = {}
        for start in range(0, len(unique), _KEYS_PER_QUERY):
            rows = self._session.execute(
                select(*_SUMMARY_COLUMNS).where(
                    Representation.representation_space_id == representation_space_id,
                    Representation.ann_key.in_(unique[start : start + _KEYS_PER_QUERY]),
                )
            ).all()
            for row in rows:
                summary = RepresentationSummary(*row)
                assert summary.ann_key is not None  # selected by key
                found[summary.ann_key] = summary
        return found

    def transition(
        self,
        representation_id: uuid.UUID,
        *,
        from_states: Collection[str],
        to_state: str,
        now: datetime,
    ) -> bool:
        """Move the representation to `to_state` only if it is in one of `from_states` now: one
        guarded `UPDATE`; `activated_at` is set when it becomes `ACTIVE`. False if it was not.

        `ERASING` and `ERASED` are refused on either side (`ValueError`): erasure is
        `RepresentationEraser`, not a state change. Moving to `ACTIVE` still needs an identity and
        a key, which the schema enforces (`active_eligible`)."""
        if to_state in _ERASURE_STATES or any(state in _ERASURE_STATES for state in from_states):
            raise ValueError("erasure is not a plain state change: use RepresentationEraser")
        values: dict[str, Any] = {"state": to_state}
        if to_state == RepresentationState.ACTIVE:
            values["activated_at"] = now
        result = _execute(
            self._session,
            update(Representation)
            .where(
                Representation.id == representation_id,
                Representation.state.in_(list(from_states)),
            )
            .values(**values)
            .execution_options(synchronize_session=False),
        )
        return bool(result.rowcount)

    def allocate_ann_key(self, representation_space_id: uuid.UUID) -> int:
        """Allocate the next positive ANN key for a space (§6.3). Guarded and race-safe.

        Allocation happens inside the caller's transaction, so a committed key is never handed out
        again, but a rolled-back allocation is. The sequence row is created lazily on first
        allocation (nothing else creates it)."""
        self._session.execute(
            insert(AnnKeySequence)
            .prefix_with("OR IGNORE")
            .values(representation_space_id=representation_space_id, next_ann_key=1)
        )
        # scalar_one() is intentional: nothing deletes ann_key_sequences rows and its FK to
        # representation_spaces is RESTRICT, so the row this UPDATE targets (just INSERT-OR-IGNORE'd
        # above) cannot be missing. If that stops being true this fails loudly.
        return self._session.execute(
            update(AnnKeySequence)
            .where(AnnKeySequence.representation_space_id == representation_space_id)
            .values(next_ann_key=AnnKeySequence.next_ann_key + 1)
            .returning(AnnKeySequence.next_ann_key - 1)
        ).scalar_one()
