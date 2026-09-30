"""The IndexCoordinator: replays durable `IndexOperation`s into the per-space USearch indexes.

PERSISTENCE_IMPLEMENTATION.md §17 and §23. SQLite is authoritative; the index is derived. A use case
that makes a representation ANN-eligible (or not) writes an `IndexOperation` in the same transaction
(INDEX-01: "no code is allowed to mutate USearch first and hope that SQLite catches up"). The
coordinator is the normal sole writer to USearch. For each pending operation it re-reads the
representation, because the operation only says what was wanted and the row says what is true, then
applies it as a *desired state*, so replaying one is harmless:

* `ADD`: ensure the representation's vector is present under its `ann_key`, if it is still `ACTIVE`
  and eligible. A representation that is no longer eligible is left alone; the `REMOVE` that its
  loss of eligibility queued deals with it.
* `REMOVE`: ensure its key is absent, whatever the index currently holds.

The index generation is persisted *before* any operation is marked `APPLIED`. A crash between the
two leaves the operations `PENDING`; replaying them finds the index already right and only marks
them applied. A failed operation is retried with a caller-supplied backoff until a caller-supplied
limit, then marked `FAILED`; neither number has a default, since choosing them would be an
unmeasured threshold.

Precondition: one process, one thread, is the coordinator (§23), and it is the only writer of the
index directory. It does not decide identity truth or what is eligible beyond the representation's
own state; it reads and writes only `index_operations`, and reads `representations` and
`representation_spaces`.
"""

import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast

import numpy as np
from numpy.typing import NDArray
from sqlalchemy import CursorResult, select, update
from sqlalchemy.orm import Session, sessionmaker

from backend.app.memory.models import (
    IndexOperation,
    IndexOperationKind,
    IndexOperationState,
    Representation,
    RepresentationSpace,
    RepresentationState,
)
from backend.infrastructure.indexing.representation_index import (
    RepresentationIndex,
    open_or_rebuild,
)

# RepresentationSpace.metric (persistence §6) to USearch's metric name.
USEARCH_METRICS = {"COSINE": "cos"}

APPLY_ERROR = "APPLY_ERROR"


@dataclass(frozen=True)
class RetryPolicy:
    """`backoff(attempts_made)` is how long to wait before the next try."""

    max_attempts: int
    backoff: Callable[[int], timedelta]


@dataclass
class CoordinatorReport:
    applied: list[uuid.UUID] = field(default_factory=list)
    # Failed this time; will be tried again after the backoff.
    retrying: list[tuple[uuid.UUID, str]] = field(default_factory=list)
    # Out of attempts: marked FAILED.
    failed: list[tuple[uuid.UUID, str]] = field(default_factory=list)
    # Spaces whose persisted index was unusable and was rebuilt from SQLite.
    rebuilt_spaces: list[uuid.UUID] = field(default_factory=list)
    # ACTIVE representations a rebuild had to leave out because their stored vector is not a
    # valid vector for the space: corrupt data, reported rather than allowed to block the space.
    unindexable: list[uuid.UUID] = field(default_factory=list)


@dataclass(frozen=True)
class _Claimed:
    id: uuid.UUID
    representation_id: uuid.UUID
    space_id: uuid.UUID
    kind: str


def _vector(blob: bytes, ndim: int) -> NDArray[np.float32]:
    """Canonical storage is contiguous little-endian float32 (§23)."""
    if len(blob) != 4 * ndim:
        raise ValueError(f"a vector of {len(blob)} bytes is not {ndim} float32 values")
    return np.frombuffer(blob, dtype="<f4").astype(np.float32)


class IndexCoordinator:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        index_root: Path,
        *,
        clock: Callable[[], datetime],
        new_id: Callable[[], uuid.UUID],
        retry: RetryPolicy,
    ) -> None:
        self._sessions = session_factory
        self._root = index_root
        self._clock = clock
        self._new_id = new_id
        self._retry = retry

    def index_directory(self, space_id: uuid.UUID) -> Path:
        return self._root / space_id.hex

    # --- one pass -------------------------------------------------------------------------

    def apply_pending(self, *, limit: int) -> CoordinatorReport:
        """Apply up to `limit` due operations, oldest first, one space at a time."""
        report = CoordinatorReport()
        by_space: dict[uuid.UUID, list[_Claimed]] = {}
        for claimed in self._claim(limit):
            by_space.setdefault(claimed.space_id, []).append(claimed)
        for space_id, operations in by_space.items():
            self._apply_space(space_id, operations, report)
        return report

    def _claim(self, limit: int) -> list[_Claimed]:
        with self._sessions() as session:
            rows = session.execute(
                select(
                    IndexOperation.id,
                    IndexOperation.representation_id,
                    IndexOperation.representation_space_id,
                    IndexOperation.operation,
                )
                .where(
                    IndexOperation.state == IndexOperationState.PENDING,
                    IndexOperation.not_before_at <= self._clock(),
                )
                .order_by(
                    IndexOperation.not_before_at, IndexOperation.created_at, IndexOperation.id
                )
                .limit(limit)
            ).all()
        return [_Claimed(row[0], row[1], row[2], row[3]) for row in rows]

    def _apply_space(
        self, space_id: uuid.UUID, operations: list[_Claimed], report: CoordinatorReport
    ) -> None:
        outcomes: dict[uuid.UUID, str | None] = {}  # operation id -> error, or None if applied
        try:
            ndim, metric = self._space(space_id)
            opened = open_or_rebuild(
                self.index_directory(space_id),
                representation_space_id=space_id,
                ndim=ndim,
                metric=metric,
                entries=lambda: self._active_entries(space_id, ndim, report.unindexable),
                clock=self._clock,
                new_id=self._new_id,
            )
            if opened.rebuilt:
                report.rebuilt_spaces.append(space_id)
            changed = False
            for operation in operations:
                try:
                    changed |= self._apply_one(opened.index, operation, ndim)
                    outcomes[operation.id] = None
                except Exception as error:  # noqa: BLE001 - one bad operation must not stop the rest
                    outcomes[operation.id] = f"{type(error).__name__}: {error}"
            if changed:
                # Persisted before anything is marked APPLIED (§17).
                opened.index.persist(clock=self._clock, new_id=self._new_id)
        except Exception as error:  # noqa: BLE001 - the whole space's batch is retried
            message = f"{type(error).__name__}: {error}"
            outcomes = {operation.id: message for operation in operations}
        self._settle(outcomes, report)

    def _space(self, space_id: uuid.UUID) -> tuple[int, str]:
        with self._sessions() as session:
            space = session.get(RepresentationSpace, space_id)
            assert space is not None  # RESTRICT foreign key: an operation's space cannot vanish
            # The schema allows only COSINE today; a metric added later without a USearch name here
            # fails its space's operations (they are retried and then FAILED), not the others.
            return space.dimension, USEARCH_METRICS[space.metric]

    def _active_entries(
        self, space_id: uuid.UUID, ndim: int, unindexable: list[uuid.UUID]
    ) -> Iterator[tuple[int, NDArray[np.float32]]]:
        """The space's active representations, streamed: what a rebuild is made of (§23). One whose
        stored vector is not `ndim` float32 values is left out and recorded in `unindexable`."""
        with self._sessions() as session:
            rows = session.execute(
                select(Representation.id, Representation.ann_key, Representation.vector)
                .where(
                    Representation.representation_space_id == space_id,
                    Representation.state == RepresentationState.ACTIVE,
                )
                .order_by(Representation.ann_key)
                .execution_options(yield_per=1000)
            )
            for representation_id, ann_key, blob in rows:
                try:
                    vector = _vector(blob, ndim)
                except ValueError:
                    unindexable.append(representation_id)
                    continue
                yield ann_key, vector

    def _apply_one(self, index: RepresentationIndex, operation: _Claimed, ndim: int) -> bool:
        """Re-read the representation and make the index match. True if the index changed."""
        with self._sessions() as session:
            row = session.execute(
                select(
                    Representation.state,
                    Representation.ann_key,
                    Representation.vector,
                    Representation.representation_space_id,
                ).where(Representation.id == operation.representation_id)
            ).one()  # RESTRICT foreign key: an operation's representation cannot vanish
        state, ann_key, blob, space_id = row
        if space_id != operation.space_id:
            raise ValueError("the operation and its representation name different spaces")
        if operation.kind == IndexOperationKind.REMOVE:
            # An erased representation has no key left to remove (open question 25).
            return ann_key is not None and index.remove(ann_key)
        if state != RepresentationState.ACTIVE:
            return False  # no longer eligible; its REMOVE deals with it
        # The schema requires both for an ACTIVE representation (`active_eligible`, `erasure`).
        assert ann_key is not None
        assert blob is not None
        return index.add(ann_key, _vector(blob, ndim))

    # --- settling -------------------------------------------------------------------------

    def _settle(self, outcomes: dict[uuid.UUID, str | None], report: CoordinatorReport) -> None:
        now = self._clock()
        with self._sessions() as session:
            for operation_id, error in outcomes.items():
                attempts = session.scalar(
                    select(IndexOperation.attempt_count).where(IndexOperation.id == operation_id)
                )
                assert attempts is not None  # operations are never deleted
                if error is None:
                    values: dict[str, object] = {
                        "state": IndexOperationState.APPLIED,
                        "applied_at": now,
                        "failure_code": None,
                        "failure_detail": None,
                    }
                elif attempts + 1 >= self._retry.max_attempts:
                    values = {
                        "state": IndexOperationState.FAILED,
                        "failure_code": APPLY_ERROR,
                        "failure_detail": error[:500],
                    }
                else:
                    values = {
                        "not_before_at": now + self._retry.backoff(attempts + 1),
                        "failure_code": APPLY_ERROR,
                        "failure_detail": error[:500],
                    }
                result = cast(
                    "CursorResult[Any]",
                    session.execute(
                        update(IndexOperation)
                        .where(
                            IndexOperation.id == operation_id,
                            IndexOperation.state == IndexOperationState.PENDING,
                        )
                        .values(
                            attempt_count=attempts + 1,
                            last_attempt_at=now,
                            updated_at=now,
                            **values,
                        )
                    ),
                )
                if result.rowcount == 0:
                    continue  # settled by someone else meanwhile
                if error is None:
                    report.applied.append(operation_id)
                elif values.get("state") == IndexOperationState.FAILED:
                    report.failed.append((operation_id, error))
                else:
                    report.retrying.append((operation_id, error))
            session.commit()
