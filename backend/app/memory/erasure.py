"""Erasing representations: the two-step use case of PERSISTENCE_IMPLEMENTATION.md §6.2, §23, §25
(decisions 2026-10-01, CONTEXT open questions 25 and 30; GitHub issues 29 and 52).

A representation's vector is biometric data. Erasing it has to reach the SQLite row, the index files
and the write-ahead log, and a crash at any point must leave a state that startup can finish. The
order is the owner's:

1. *Queue and exclude* (one transaction, `queue`): each `ACTIVE`, `PENDING` or `SUPERSEDED`
   representation moves to `ERASING` and, if it has an `ann_key`, a `REMOVE` is queued. `ERASING` is
   excluded from retrieval, revalidation and every index build from the moment this commits.
2. *Apply the removal*: the coordinator applies the `REMOVE`s by rebuilding the space's index from
   SQLite (one rebuild per space for the whole batch), and refuses to mark one applied while an
   older generation file of the space remains.
3. *Retire and clear* (per space, under the coordinator's lock): once every needed `REMOVE` is
   `APPLIED`, no superseded generation file is left and the space's quarantined generations are
   deleted, the representations become `ERASED` (vector and key cleared) in a transaction that also
   sets the durable `wal_truncation_owed` marker.
4. *Truncate*: `truncate_wal`, outside any transaction. Only if it succeeds is the marker cleared. A
   `False` or an exception means cleanup is outstanding, and the erasure is never reported complete.
5. *Verify*: the cleared rows are read back (a cleared row has no key left, so it cannot be
   returned by candidate revalidation).

Every step is a guarded transition, so each can be repeated: `resume` (startup recovery) queues a
missing `REMOVE`, runs the same steps for everything still `ERASING`, and truncates the log if the
marker is set. A space whose cleanup cannot finish (a locked file) is reported and left `ERASING`
without stopping the other spaces.

"Erased" here means the vector is gone from SQLite, the index files and the log, as far as the
application can verify. It is not a claim of physical erasure from SSD storage, snapshots or
backups.
"""

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import Engine, delete, exists, func, select, update
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from backend.app.memory.index_coordinator import IndexCoordinator
from backend.app.memory.index_operation_repository import IndexOperationRepository, NewOperation
from backend.app.memory.models import (
    IndexOperation,
    IndexOperationKind,
    IndexOperationState,
    Representation,
    RepresentationState,
)
from backend.app.settings.app_state import WAL_TRUNCATION_OWED, AppStateRepository
from backend.infrastructure.db.engine import truncate_wal
from backend.infrastructure.db.unit_of_work import UnitOfWork
from backend.infrastructure.indexing.representation_index import (
    retire_quarantine,
    superseded_files,
)

# The states that hold a vector and may be erased. `ERASING` is already under way, `ERASED` is done
# and `DELETED` is not an erasure.
ERASABLE = (RepresentationState.ACTIVE, RepresentationState.PENDING, RepresentationState.SUPERSEDED)
CHUNK = 500  # bound parameters per statement, like the other repositories


def _chunks(ids: Sequence[uuid.UUID]) -> list[Sequence[uuid.UUID]]:
    return [ids[start : start + CHUNK] for start in range(0, len(ids), CHUNK)]


@dataclass
class ErasureReport:
    # Requested representations that are `ERASED` when the call returns (including ones that already
    # were), and those still `ERASING`. For `resume`, `erased` is what that call finished and
    # `pending` is every `ERASING` one.
    erased: list[uuid.UUID] = field(default_factory=list)
    pending: list[uuid.UUID] = field(default_factory=list)
    # Requested ids that are unknown or `DELETED`: nothing to erase.
    ignored: list[uuid.UUID] = field(default_factory=list)
    # Spaces whose cleanup could not finish, with why. Their representations stay `ERASING`.
    blocked: dict[uuid.UUID, str] = field(default_factory=dict)
    # Index operations that failed or are backing off in this call's coordinator pass, and a
    # truncation that raised.
    errors: list[str] = field(default_factory=list)
    # False when the truncating checkpoint is owed and did not succeed (it is retried later).
    wal_truncated: bool = True
    # True when an owed truncation was done in this call and its marker cleared.
    truncated: bool = False
    # Representations that were cleared but read back with a vector or key still set.
    unverified: list[uuid.UUID] = field(default_factory=list)

    @property
    def outstanding_cleanup(self) -> list[str]:
        """What is still owed, by name; empty exactly when the erasure is complete."""
        owed = [f"space {space}: {reason}" for space, reason in self.blocked.items()]
        owed += self.errors
        if self.pending:
            owed.append(f"{len(self.pending)} representations still erasing")
        if self.unverified:
            owed.append(f"{len(self.unverified)} cleared representations failed verification")
        if not self.wal_truncated:
            owed.append("the write-ahead log has not been truncated")
        return owed

    @property
    def complete(self) -> bool:
        return not self.outstanding_cleanup


class RepresentationEraser:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        engine: Engine,
        coordinator: IndexCoordinator,
        *,
        unit_of_work: UnitOfWork,
        clock: Callable[[], datetime],
        new_id: Callable[[], uuid.UUID],
        checkpoint_timeout_ms: int = 5000,
    ) -> None:
        self._sessions = session_factory  # reads; every write goes through the unit of work
        self._uow = unit_of_work
        self._engine = engine
        self._coordinator = coordinator
        self._clock = clock
        self._new_id = new_id
        self._checkpoint_timeout_ms = checkpoint_timeout_ms  # how long a reader may block the log

    def erase(self, representation_ids: Sequence[uuid.UUID]) -> ErasureReport:
        """Erase one or many representations. Bulk is one queueing transaction and one rebuild per
        space, never one per representation. Safe to repeat: an `ERASING` or `ERASED` one is left
        as it is and the remaining steps are run again."""
        ids = list(dict.fromkeys(representation_ids))
        self.queue(ids)
        return self._drive(ids)

    def resume(self) -> ErasureReport:
        """Startup recovery (§28): queue a missing `REMOVE` for every `ERASING` representation and
        run the remaining steps for all of them, then truncate the log if that is owed."""
        try:
            self.queue([])
            return self._drive(None)
        except Exception as error:  # noqa: BLE001 - recovery reports it; startup must go on
            report = ErasureReport()
            report.errors.append(f"{type(error).__name__}: {error}")
            return report

    # --- step one -------------------------------------------------------------------------

    def queue(self, representation_ids: Sequence[uuid.UUID]) -> None:
        """Move the erasable ones among `representation_ids` to `ERASING` and queue their `REMOVE`s
        in one transaction; then make sure every `ERASING` representation with a key has one."""
        now = self._clock()
        ids = list(representation_ids)
        self._uow.write(lambda session: self._queue(session, ids, now))

    def queue_in(self, session: Session, representation_ids: Sequence[uuid.UUID]) -> None:
        """`queue`, inside the caller's transaction: for a use case that must exclude the vectors
        from retrieval in the same commit as its own change (permanent Source deletion)."""
        self._queue(session, list(representation_ids), self._clock())

    def settle_log(self) -> list[str]:
        """Truncate the write-ahead log if a truncation is owed; what is still owed, by name (empty
        when the log is clean). For a use case that deleted rows holding biometric payload."""
        report = ErasureReport()
        self._truncate(report)
        return report.outstanding_cleanup

    def _queue(self, session: Session, ids: list[uuid.UUID], now: datetime) -> None:
        operations: list[NewOperation] = []
        for chunk in _chunks(ids):
            moved = session.execute(
                update(Representation)
                .where(Representation.id.in_(chunk), Representation.state.in_(ERASABLE))
                .values(state=RepresentationState.ERASING)
                .returning(
                    Representation.id,
                    Representation.representation_space_id,
                    Representation.ann_key,
                )
                .execution_options(synchronize_session=False)
            ).all()
            keyed = [
                NewOperation(rep_id, space_id, IndexOperationKind.REMOVE)
                for rep_id, space_id, ann_key in moved
                if ann_key is not None
            ]
            operations += keyed
            # An ordinary REMOVE may be in flight (claimed, applied in place, not yet settled):
            # its in-place removal leaves the vector's bytes in the live file, and the unique
            # pending REMOVE would make this erasure skip its own. Delete it so a fresh REMOVE
            # (applied by a rebuild) takes its place; its late settlement is then skipped. A
            # `FAILED` one goes too: it would keep this erasure from finishing until the next
            # call requeued it. Only this chunk's ids are bound, so a huge bulk stays under
            # SQLite's parameter limit.
            session.execute(
                delete(IndexOperation).where(
                    IndexOperation.representation_id.in_([op.representation_id for op in keyed]),
                    IndexOperation.operation == IndexOperationKind.REMOVE,
                    IndexOperation.state.in_(
                        (IndexOperationState.PENDING, IndexOperationState.FAILED)
                    ),
                )
            )
        repository = IndexOperationRepository(session)
        repository.append_batch(operations, now=now, new_id=self._new_id)
        repository.append_batch(self._missing_removes(session), now=now, new_id=self._new_id)
        for failed in self._failed_removes(session):
            repository.requeue(failed, now=now)  # out of attempts earlier: a fresh set

    @staticmethod
    def _missing_removes(session: Session) -> list[NewOperation]:
        """An `ERASING` representation with a key and no `REMOVE` in any state (the transaction that
        moved it was not ours, or its row was lost): it needs one."""
        any_remove = exists().where(
            IndexOperation.representation_id == Representation.id,
            IndexOperation.operation == IndexOperationKind.REMOVE,
        )
        rows = session.execute(
            select(Representation.id, Representation.representation_space_id).where(
                Representation.state == RepresentationState.ERASING,
                Representation.ann_key.is_not(None),
                ~any_remove,
            )
        ).all()
        return [
            NewOperation(rep_id, space_id, IndexOperationKind.REMOVE) for rep_id, space_id in rows
        ]

    @staticmethod
    def _failed_removes(session: Session) -> list[uuid.UUID]:
        """`FAILED` `REMOVE`s of `ERASING` representations: the erasure is not finished, so they
        get another set of attempts instead of waiting for the next start."""
        return list(
            session.scalars(
                select(IndexOperation.id)
                .join(Representation, Representation.id == IndexOperation.representation_id)
                .where(
                    IndexOperation.operation == IndexOperationKind.REMOVE,
                    IndexOperation.state == IndexOperationState.FAILED,
                    Representation.state == RepresentationState.ERASING,
                )
            )
        )

    # --- steps two to five ----------------------------------------------------------------

    def _drive(self, scope: Sequence[uuid.UUID] | None) -> ErasureReport:
        report = ErasureReport()
        with self._sessions() as session:
            spaces = list(
                session.scalars(
                    select(Representation.representation_space_id)
                    .where(Representation.state == RepresentationState.ERASING)
                    .distinct()
                )
            )
            due = session.scalar(
                select(func.count())
                .select_from(IndexOperation)
                .where(IndexOperation.state == IndexOperationState.PENDING)
            )
        if spaces and due:
            applied = self._coordinator.apply_pending(limit=due)
            ours = self._erasing_operations()
            report.errors += [
                f"{op}: {error}" for op, error in applied.retrying + applied.failed if op in ours
            ]
        cleared: list[uuid.UUID] = []
        for space_id in spaces:
            try:
                done, reason = self._finalize_space(space_id)
            except Exception as error:  # noqa: BLE001 - one space must not stop the others
                report.blocked[space_id] = f"{type(error).__name__}: {error}"
                continue
            cleared += done
            if reason is not None:
                report.blocked[space_id] = reason
        # The states are read before the marker: an erasure another caller finished meanwhile
        # sets its marker in the same transaction that makes it `ERASED`, so a representation seen
        # `ERASED` here has its marker visible to the truncation below.
        self._summarize(scope, cleared, report)
        self._truncate(report)
        self._verify(cleared, report)
        return report

    def _erasing_operations(self) -> set[uuid.UUID]:
        with self._sessions() as session:
            return set(
                session.scalars(
                    select(IndexOperation.id)
                    .join(Representation, Representation.id == IndexOperation.representation_id)
                    .where(Representation.state == RepresentationState.ERASING)
                )
            )

    def _finalize_space(self, space_id: uuid.UUID) -> tuple[list[uuid.UUID], str | None]:
        """Clear every `ERASING` representation of the space whose removal is done. Returns them,
        and why the others (if any) must wait for a retry."""
        directory = self._coordinator.index_directory(space_id)
        with self._coordinator.exclusive():
            with self._sessions() as session:
                rows = session.execute(
                    select(Representation.id, Representation.ann_key).where(
                        Representation.representation_space_id == space_id,
                        Representation.state == RepresentationState.ERASING,
                    )
                ).all()
                removed = self._removal_done(session, space_id)
            ready = [rep for rep, key in rows if key is None or rep in removed]
            reason = None
            if any(key is not None for rep, key in rows if rep in removed):
                # (Keyed ones only: a keyless representation was never in an index.)
                # A fresh listing, not the in-memory index: the old generations must be gone.
                left = superseded_files(directory) + retire_quarantine(directory)
                if left:
                    reason = f"{left[0].name} could not be removed"
                    ready = [rep for rep, key in rows if key is None]
            if not ready:
                return [], reason
            now = self._clock()
            return self._uow.write(lambda session: self._clear(session, ready, now)), reason

    def _clear(self, session: Session, ready: list[uuid.UUID], now: datetime) -> list[uuid.UUID]:
        cleared: list[uuid.UUID] = []
        # A value of its own for every clearing commit, whatever `new_id` is: a checkpoint
        # that ran before this commit must not clear the marker this commit sets.
        AppStateRepository(session).set(WAL_TRUNCATION_OWED, uuid.uuid4().hex, now=now)
        for chunk in _chunks(ready):
            cleared += session.scalars(
                update(Representation)
                .where(
                    Representation.id.in_(chunk),
                    Representation.state == RepresentationState.ERASING,
                )
                .values(
                    state=RepresentationState.ERASED,
                    vector=None,
                    ann_key=None,
                    erased_at=now,
                )
                .returning(Representation.id)
                .execution_options(synchronize_session=False)
            ).all()
        return cleared

    @staticmethod
    def _removal_done(session: Session, space_id: uuid.UUID) -> set[uuid.UUID]:
        """Keyed `ERASING` representations of the space with a `REMOVE` applied and none open."""

        def remove(*states: IndexOperationState) -> ColumnElement[bool]:
            return exists().where(
                IndexOperation.representation_id == Representation.id,
                IndexOperation.operation == IndexOperationKind.REMOVE,
                IndexOperation.state.in_(states),
            )

        return set(
            session.scalars(
                select(Representation.id).where(
                    Representation.representation_space_id == space_id,
                    Representation.state == RepresentationState.ERASING,
                    Representation.ann_key.is_not(None),
                    remove(IndexOperationState.APPLIED),
                    ~remove(IndexOperationState.PENDING, IndexOperationState.FAILED),
                )
            )
        )

    def _truncate(self, report: ErasureReport) -> None:
        """Truncate the log if the marker says it is owed; clear the marker only on success, and
        only if it still holds the value read before the checkpoint (a later erasure set it again).
        """
        with self._sessions() as session:
            owed = AppStateRepository(session).get(WAL_TRUNCATION_OWED)
        if owed is None:
            return
        try:
            done = truncate_wal(self._engine, busy_timeout_ms=self._checkpoint_timeout_ms)
        except Exception as error:  # noqa: BLE001 - a database error means the same: still owed
            report.errors.append(f"truncate_wal: {type(error).__name__}: {error}")
            done = False
        if not done:
            report.wal_truncated = False
            return
        self._uow.write(
            lambda session: AppStateRepository(session).clear(WAL_TRUNCATION_OWED, value=owed)
        )
        report.truncated = True

    def _verify(self, cleared: Sequence[uuid.UUID], report: ErasureReport) -> None:
        with self._sessions() as session:
            for chunk in _chunks(list(cleared)):
                report.unverified += session.scalars(
                    select(Representation.id).where(
                        Representation.id.in_(chunk),
                        (Representation.state != RepresentationState.ERASED)
                        | Representation.vector.is_not(None)
                        | Representation.ann_key.is_not(None),
                    )
                ).all()

    def _summarize(
        self, scope: Sequence[uuid.UUID] | None, cleared: Sequence[uuid.UUID], report: ErasureReport
    ) -> None:
        with self._sessions() as session:
            if scope is None:
                report.erased = list(cleared)  # recovery reports what it finished
                report.pending = list(
                    session.scalars(
                        select(Representation.id).where(
                            Representation.state == RepresentationState.ERASING
                        )
                    )
                )
                return
            states: dict[uuid.UUID, str] = {}
            for chunk in _chunks(list(scope)):
                states |= {
                    rep_id: state
                    for rep_id, state in session.execute(
                        select(Representation.id, Representation.state).where(
                            Representation.id.in_(chunk)
                        )
                    )
                }
        for rep_id in scope:
            state = states.get(rep_id)
            if state == RepresentationState.ERASED:
                report.erased.append(rep_id)
            elif state == RepresentationState.ERASING:
                report.pending.append(rep_id)
            else:
                report.ignored.append(rep_id)
