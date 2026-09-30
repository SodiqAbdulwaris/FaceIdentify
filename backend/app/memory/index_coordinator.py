"""The IndexCoordinator: replays durable `IndexOperation`s into the per-space USearch indexes.

PERSISTENCE_IMPLEMENTATION.md §17 and §23. SQLite is authoritative; the index is derived. A use case
that makes a representation ANN-eligible (or not) writes an `IndexOperation` in the same transaction
(INDEX-01: "no code is allowed to mutate USearch first and hope that SQLite catches up"). The
coordinator is the normal sole writer to USearch. For each pending operation it re-reads the
representation, because the operation only says what was wanted and the row says what is true, then
applies it as a *desired state*, so replaying one is harmless:

* `ADD`: ensure the representation's vector is present under its `ann_key`, if it is still `ACTIVE`
  and eligible (its identity is `ACTIVE` too, persistence §6.2). A representation that is no longer
  eligible is left alone; the `REMOVE` that its loss of eligibility queued deals with it.
* `REMOVE`: ensure its key is absent, whatever the index currently holds. An *erased*
  representation has no key left (`ann_key` is cleared by erasure), so the only way to guarantee its
  vector is gone from the index is to rebuild the space's index from SQLite and confirm no older
  generation file, which would still hold the vector, remains (CONTEXT open question 25 is about
  ordering erasure so that this is not needed).

The index generation is persisted *before* any operation is marked `APPLIED`. A crash between the
two leaves the operations `PENDING`; replaying them finds the index already right and only marks
them applied. A failed operation is retried with a caller-supplied backoff until a caller-supplied
limit, then marked `FAILED`; neither number has a default, since choosing them would be an
unmeasured threshold.

Precondition: one process is the coordinator (§23) and it is the only writer of the index
directory, which lives in machine-local state under the desktop shell's single instance. Threads of
that process are serialized by a lock; a second coordinator in another process is not guarded
against (that is the library-lock question, CONTEXT 23). It does not decide identity truth; it
reads and writes only `index_operations`, and reads `representations`, `identities` and
`representation_spaces`.
"""

import threading
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, cast

import numpy as np
from numpy.typing import NDArray
from sqlalchemy import CursorResult, select, update
from sqlalchemy.orm import Session, sessionmaker

from backend.app.identities.models import Identity, IdentityState
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
    # valid vector for the space (wrong length, NaN or infinity): corrupt data, reported rather
    # than allowed to block the space.
    unindexable: list[uuid.UUID] = field(default_factory=list)
    # Spaces whose index was rebuilt to guarantee an erased representation's vector is gone.
    purged_spaces: list[uuid.UUID] = field(default_factory=list)


class _Effect(StrEnum):
    NONE = "NONE"
    CHANGED = "CHANGED"
    PURGE = "PURGE"  # the representation is erased: only a rebuild can guarantee it is gone


@dataclass(frozen=True)
class _Claimed:
    id: uuid.UUID
    representation_id: uuid.UUID
    space_id: uuid.UUID
    kind: str


def _vector(blob: bytes, ndim: int) -> NDArray[np.float32]:
    """Canonical storage is contiguous little-endian float32 (§23): exactly `ndim` finite values."""
    if len(blob) != 4 * ndim:
        raise ValueError(f"a vector of {len(blob)} bytes is not {ndim} float32 values")
    vector = np.frombuffer(blob, dtype="<f4").astype(np.float32)
    if not np.isfinite(vector).all():
        raise ValueError("a vector must be finite (no NaN or infinity)")
    return vector


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
        self._lock = threading.Lock()

    def index_directory(self, space_id: uuid.UUID) -> Path:
        return self._root / space_id.hex

    # --- one pass -------------------------------------------------------------------------

    def apply_pending(self, *, limit: int) -> CoordinatorReport:
        """Apply up to `limit` due operations, oldest first, one space at a time. Passes are
        serialized: two threads calling this cannot both load, change and persist one index."""
        with self._lock:
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
            index = opened.index
            effects: dict[uuid.UUID, _Effect] = {}
            for operation in operations:
                try:
                    effects[operation.id] = self._apply_one(index, operation, ndim)
                    outcomes[operation.id] = None
                except Exception as error:  # noqa: BLE001 - one bad operation must not stop the rest
                    outcomes[operation.id] = f"{type(error).__name__}: {error}"
            if _Effect.PURGE in effects.values():
                self._purge(space_id, ndim, metric, operations, outcomes, report)
            elif _Effect.CHANGED in effects.values():
                # Persisted before anything is marked APPLIED (§17).
                index.persist(clock=self._clock, new_id=self._new_id)
        except Exception as error:  # noqa: BLE001 - the whole space's batch is retried
            message = f"{type(error).__name__}: {error}"
            outcomes = {operation.id: message for operation in operations}
        self._settle(outcomes, report)

    def _purge(
        self,
        space_id: uuid.UUID,
        ndim: int,
        metric: str,
        operations: list[_Claimed],
        outcomes: dict[uuid.UUID, str | None],
        report: CoordinatorReport,
    ) -> None:
        """Rebuild the space's index from SQLite so that nothing erased survives in it.

        Not quarantined (that would keep the old file, and the vector with it), and the old
        generation's file must actually be gone afterwards: if it is locked the pass fails and is
        retried, rather than reporting an erased vector absent while it is still on disk. The
        batch's operations are then applied again to the new index, because a `REMOVE` means
        absent even for a representation SQLite still calls active.
        """
        rebuilt = RepresentationIndex.build(
            self.index_directory(space_id),
            representation_space_id=space_id,
            ndim=ndim,
            metric=metric,
            entries=self._active_entries(space_id, ndim, report.unindexable),
            clock=self._clock,
            new_id=self._new_id,
        )
        changed = False
        for operation in operations:
            if outcomes[operation.id] is None:
                changed |= self._apply_one(rebuilt, operation, ndim) is _Effect.CHANGED
        if changed:
            rebuilt.persist(clock=self._clock, new_id=self._new_id)
        stale = rebuilt.stale_files()
        if stale:
            raise OSError(f"the superseded index file {stale[0].name} could not be removed")
        report.purged_spaces.append(space_id)

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
        """The space's eligible representations, streamed: what a rebuild is made of (§23). Eligible
        means ACTIVE with an ACTIVE identity. One whose stored vector is not `ndim` finite float32
        values is left out and recorded in `unindexable`."""
        with self._sessions() as session:
            rows = session.execute(
                select(Representation.id, Representation.ann_key, Representation.vector)
                .join(Identity, Identity.id == Representation.identity_id)
                .where(
                    Representation.representation_space_id == space_id,
                    Representation.state == RepresentationState.ACTIVE,
                    Identity.state == IdentityState.ACTIVE,
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

    def _apply_one(self, index: RepresentationIndex, operation: _Claimed, ndim: int) -> _Effect:
        """Re-read the representation and make the index match."""
        with self._sessions() as session:
            row = session.execute(
                select(
                    Representation.state,
                    Representation.ann_key,
                    Representation.vector,
                    Representation.representation_space_id,
                    Identity.state,
                )
                .outerjoin(Identity, Identity.id == Representation.identity_id)
                .where(Representation.id == operation.representation_id)
            ).one()  # RESTRICT foreign key: an operation's representation cannot vanish
        state, ann_key, blob, space_id, identity_state = row
        if space_id != operation.space_id:
            raise ValueError("the operation and its representation name different spaces")
        if operation.kind == IndexOperationKind.REMOVE:
            if ann_key is None:
                return _Effect.PURGE  # erased: no key left to remove by
            return _Effect.CHANGED if index.remove(ann_key) else _Effect.NONE
        if state != RepresentationState.ACTIVE or identity_state != IdentityState.ACTIVE:
            return _Effect.NONE  # no longer eligible; its REMOVE deals with it
        # The schema requires both for an ACTIVE representation (`active_eligible`, `erasure`).
        assert ann_key is not None
        assert blob is not None
        return _Effect.CHANGED if index.add(ann_key, _vector(blob, ndim)) else _Effect.NONE

    # --- settling -------------------------------------------------------------------------

    def _settle(self, outcomes: dict[uuid.UUID, str | None], report: CoordinatorReport) -> None:
        """Record each operation's outcome in one short write transaction.

        The attempt counts are read in their own transaction first, so no read precedes the writes
        in the transaction that commits them (a read-then-write in a deferred SQLite transaction
        can fail with `BUSY_SNAPSHOT` when another writer commits in between, CONTEXT open question
        20). Each UPDATE is guarded by the operation still being `PENDING`.
        """
        now = self._clock()
        with self._sessions() as session:
            seen = {
                row[0]: row[1]
                for row in session.execute(
                    select(IndexOperation.id, IndexOperation.attempt_count).where(
                        IndexOperation.id.in_(list(outcomes))
                    )
                )
            }
        with self._sessions() as session:
            for operation_id, error in outcomes.items():
                attempts = seen[operation_id]
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
