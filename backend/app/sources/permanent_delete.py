"""Permanent deletion of a Source (identity-and-memory-model-v1.md §40-§45, §57; API and
Contracts.md §5.7 and §60; PERSISTENCE_IMPLEMENTATION.md §4.2; CONTEXT questions 29 and 30).

"Delete Media removes media and evidence-bearing biometric material; it does not remove the people
the user named." The order is the one the specs ask for, durable intent first:

1. *Intent* (one transaction): the Source moves `RECYCLED` -> `DELETING`, and every managed artifact
   it owns (the original, the thumbnail and each face crop) gets its deletion intent. A referenced
   original is only marked `DELETED`: the user's file is never touched.
2. *Bytes*: each artifact's bytes are removed and its row finalized (`DELETE_FAILED` is retried at
   the next start).
3. *Representations*: every face vector of the Source goes through `RepresentationEraser`, which
   reaches the SQLite row, the index files and the write-ahead log.
4. *Finalization* (one transaction, only once 2 and 3 are done): the Source's occurrences,
   observations, representations, index operations, processing runs and then their now-unreferenced
   configuration snapshots are deleted; Evidence that cited them is kept but loses the links to the
   deleted representations and the run (it keeps ids, kinds, scores and the Source's tombstone, no
   biometric payload); an unnamed identity left with nothing becomes `DELETED`; the Source row stays
   as a tombstone (`DELETED`, no name, no media facts) so retained Evidence still resolves it.

Each step can be repeated, so `resume` (startup) finishes whatever a crash interrupted. The user
cannot resurrect anything: the bytes, the vectors, the observations and the runs no longer exist.

Functions in the finalization are pure functions of the session: the unit of work may run them
again after a busy database.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import CompoundSelect, Select, delete, exists, select, union, update
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql import Executable

from backend.app.identities.models import (
    Evidence,
    EvidenceCandidate,
    EvidenceRepresentation,
    Identity,
    IdentityState,
)
from backend.app.jobs.models import Job
from backend.app.memory.erasure import CHUNK, RepresentationEraser
from backend.app.memory.models import (
    IndexOperation,
    IndexOperationKind,
    Observation,
    ObservationState,
    Occurrence,
    OccurrenceState,
    Representation,
    RepresentationState,
)
from backend.app.people.models import AssociationState, IdentityPersonAssociation
from backend.app.processing.models import (
    ExecutionSegment,
    ProcessingCheckpoint,
    ProcessingConfigurationSnapshot,
    ProcessingRun,
)
from backend.app.settings.app_state import WAL_TRUNCATION_OWED, AppStateRepository
from backend.app.sources.artifact_storage import (
    DELETABLE_STATES,
    complete_artifact_deletion,
    request_artifact_deletion,
    transition_artifact,
)
from backend.app.sources.lifecycle import IN_FLIGHT, SourceBusyError, SourceLifecycleError
from backend.app.sources.models import Artifact, ArtifactState, Source, SourceState, StorageMode
from backend.infrastructure.db.optimistic import optimistic_locked_update
from backend.infrastructure.db.unit_of_work import UnitOfWork
from backend.infrastructure.storage.files import ManagedFileStore
from backend.infrastructure.storage.layout import UnsafeStorageKeyError

# What a tombstoned Source is called: its filename was source metadata, which is removed (§40).
DELETED_DISPLAY_NAME = "Deleted image"

# Representations that still hold a vector in some form. Finalization refuses while one is left.
_HOLDS_VECTOR = (
    RepresentationState.DELETED,  # (a DELETED row keeps its vector; intent moves it to ERASING)
    RepresentationState.ACTIVE,
    RepresentationState.PENDING,
    RepresentationState.SUPERSEDED,
    RepresentationState.ERASING,
)


class SourceNotRecycledError(SourceLifecycleError):
    """Only a Source in the Recycle Bin can be deleted permanently (identity model §39)."""


class SourceMissingError(SourceLifecycleError):
    """No such Source."""


class ErasureIncompleteError(SourceLifecycleError):
    """Finalization was asked for while a face vector of the Source still exists."""


@dataclass
class DeletionReport:
    source_id: uuid.UUID
    # True when the Source is `DELETED`: nothing of it is left but its tombstone.
    complete: bool
    # What is still owed (a locked file, an erasure that could not finish); startup retries it.
    outstanding: list[str] = field(default_factory=list)
    # True when this call changed the Source (began its deletion, or finalized it): a repeat that
    # only found it stuck, or already done, has nothing to announce.
    changed: bool = False


def _chunks(ids: list[uuid.UUID]) -> list[list[uuid.UUID]]:
    """Bound parameters per statement stay under the database limit however long the history."""
    return [ids[start : start + CHUNK] for start in range(0, len(ids), CHUNK)]


class PermanentSourceDeletion:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        unit_of_work: UnitOfWork,
        eraser: RepresentationEraser,
        store: ManagedFileStore,
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self._sessions = session_factory
        self._uow = unit_of_work
        self._eraser = eraser
        self._store = store
        self._clock = clock

    def delete(self, source_id: uuid.UUID) -> DeletionReport:
        """Delete a recycled Source for good. Safe to repeat: a `DELETING` one is carried on, a
        `DELETED` one is reported complete."""
        now = self._clock()
        before = self._uow.write(lambda session: self._begin(session, source_id, now))
        report = self._carry_on(source_id)
        # A repeat that changed nothing (already gone, or still stuck the same way) is not news.
        report.changed = report.changed or before == SourceState.RECYCLED
        return report

    def resume(self) -> list[DeletionReport]:
        """Startup recovery: carry on every Source whose deletion a crash interrupted. One that
        cannot finish is reported and left `DELETING` for the next start."""
        with self._sessions() as session:
            pending = list(
                session.scalars(select(Source.id).where(Source.state == SourceState.DELETING))
            )
        reports = []
        for source_id in pending:
            try:
                reports.append(self._carry_on(source_id))
            except Exception as error:  # noqa: BLE001 - one Source must not stop startup or the rest
                reports.append(
                    DeletionReport(source_id, False, [f"{type(error).__name__}: {error}"])
                )
        return reports

    # --- step one: intent -----------------------------------------------------------------

    def _begin(self, session: Session, source_id: uuid.UUID, now: datetime) -> str:
        """Record the intent; returns the state the Source was in."""
        source = session.get(Source, source_id, populate_existing=True)
        if source is None:
            raise SourceMissingError(f"source {source_id} does not exist")
        if source.state in (SourceState.DELETING, SourceState.DELETED):
            return source.state  # a repeat
        if source.state != SourceState.RECYCLED:
            raise SourceNotRecycledError(
                f"source {source_id} is {source.state}; move it to the Recycle Bin first"
            )
        if session.scalar(
            select(ProcessingRun.id)
            .where(ProcessingRun.source_id == source_id, ProcessingRun.state.in_(IN_FLIGHT))
            .limit(1)
        ):
            raise SourceBusyError(f"source {source_id} has processing in flight")
        # (One `BEGIN IMMEDIATE` write: no other writer can slip between the read and this.)
        optimistic_locked_update(
            session,
            Source,
            source_id,
            expected_revision=source.revision,
            values={"state": SourceState.DELETING, "updated_at": now},
        )
        for artifact in session.scalars(
            select(Artifact).where(Artifact.id.in_(self._artifact_ids(source_id)))
        ):
            if artifact.storage_mode == StorageMode.REFERENCED:
                # The user's file is theirs: only this application's record of it ends.
                transition_artifact(
                    session,
                    artifact.id,
                    set(ArtifactState),
                    {"state": ArtifactState.DELETED, "deleted_at": now},
                    storage_mode=StorageMode.REFERENCED,
                )
            elif artifact.state == ArtifactState.PENDING:
                # A write that never finished: its bytes (final or staged) still have to go.
                transition_artifact(
                    session,
                    artifact.id,
                    {ArtifactState.PENDING},
                    {"state": ArtifactState.DELETING, "delete_requested_at": now},
                )
            elif artifact.state in DELETABLE_STATES:
                request_artifact_deletion(session, artifact.id, clock=lambda: now)
        # The faces leave recognition, search and every reader in this same commit: the vectors
        # are queued for erasure (a DELETED row, which the eraser ignores, is made erasable first),
        # and the occurrences and observations stop being authoritative.
        observations = select(Observation.id).where(Observation.source_id == source_id)
        no_sync = {"synchronize_session": False}
        # A DELETED row keeps its vector and may carry an ordinary REMOVE that only took the key
        # out of the live index (the file keeps the bytes): forget every REMOVE it had, so erasure
        # queues its own, which is applied by a rebuild.
        deleted_vectors = select(Representation.id).where(
            Representation.observation_id.in_(observations),
            Representation.state == RepresentationState.DELETED,
        )
        session.execute(
            delete(IndexOperation).where(
                IndexOperation.representation_id.in_(deleted_vectors),
                IndexOperation.operation == IndexOperationKind.REMOVE,
            ),
            execution_options=no_sync,
        )
        session.execute(
            update(Representation)
            .where(Representation.id.in_(deleted_vectors))
            .values(state=RepresentationState.ERASING),
            execution_options=no_sync,
        )
        self._eraser.queue_in(session, list(session.scalars(self._representation_ids(source_id))))
        session.execute(
            update(Occurrence)
            .where(Occurrence.source_id == source_id)
            .values(state=OccurrenceState.DELETED),
            execution_options=no_sync,
        )
        session.execute(
            update(Observation)
            .where(Observation.source_id == source_id)
            .values(state=ObservationState.DELETED),
            execution_options=no_sync,
        )
        return SourceState.RECYCLED

    @staticmethod
    def _artifact_ids(source_id: uuid.UUID) -> CompoundSelect[tuple[uuid.UUID | None]]:
        """A subquery: the original, the thumbnail and every face crop of the Source."""
        owned = (
            select(Source.original_artifact_id.label("id")).where(Source.id == source_id),
            select(Source.thumbnail_artifact_id).where(
                Source.id == source_id, Source.thumbnail_artifact_id.is_not(None)
            ),
            select(Observation.face_crop_artifact_id).where(
                Observation.source_id == source_id, Observation.face_crop_artifact_id.is_not(None)
            ),
        )
        return union(*owned)

    # --- steps two to four ----------------------------------------------------------------

    def _carry_on(self, source_id: uuid.UUID) -> DeletionReport:
        with self._sessions() as session:
            source = session.get(Source, source_id)
            if source is None:
                raise SourceMissingError(f"source {source_id} does not exist")
            state = source.state
        if state == SourceState.DELETED:
            owed = self._eraser.settle_log()  # (still owed from the first try?) after the read ends
            return DeletionReport(source_id, not owed, owed)
        if state != SourceState.DELETING:
            raise SourceNotRecycledError(f"source {source_id} is {state}")
        with self._sessions() as session:
            owed_bytes = list(
                session.scalars(
                    select(Artifact.id).where(
                        Artifact.id.in_(self._artifact_ids(source_id)),
                        Artifact.storage_mode == StorageMode.MANAGED,
                        Artifact.state.in_((ArtifactState.DELETING, ArtifactState.DELETE_FAILED)),
                    )
                )
            )
            vectors = list(session.scalars(self._representation_ids(source_id)))
            staged_keys = list(
                key
                for key in session.scalars(
                    select(Artifact.storage_key).where(
                        Artifact.id.in_(self._artifact_ids(source_id)),
                        Artifact.storage_mode == StorageMode.MANAGED,
                    )
                )
                if key is not None
            )
            unfinished = list(
                session.scalars(
                    select(Artifact.id).where(
                        Artifact.id.in_(self._artifact_ids(source_id)),
                        Artifact.state != ArtifactState.DELETED,
                    )
                )
            )

        outstanding: list[str] = []
        for artifact_id in owed_bytes:
            try:
                complete_artifact_deletion(
                    self._sessions, self._store, artifact_id, clock=self._clock
                )
            except (OSError, UnsafeStorageKeyError) as error:
                outstanding.append(f"artifact {artifact_id}: {type(error).__name__}: {error}")
        for key in staged_keys:  # a half-written file belongs to the artifact, whatever its state
            staged = self._store.staging_path(key)
            try:
                staged.unlink(missing_ok=True)
            except OSError as error:
                outstanding.append(f"staged file of {key}: {type(error).__name__}: {error}")
        # Whatever owns bytes must be gone before the rows that name it are: an artifact that is
        # neither deleted nor being deleted (a state nobody handles) blocks.
        outstanding += [
            f"artifact {artifact_id} is not deleted"
            for artifact_id in unfinished
            if artifact_id not in owed_bytes
        ]
        if vectors:
            outstanding += self._eraser.erase(vectors).outstanding_cleanup
        if outstanding:
            return DeletionReport(source_id, False, outstanding)
        now = self._clock()
        finalized = self._uow.write(lambda session: self._finalize(session, source_id, now))
        # The rows that held landmarks, quality data and payloads were just deleted: the log may
        # still hold their earlier pages, so it is truncated before this is reported done.
        owed = self._eraser.settle_log()
        return DeletionReport(source_id, not owed, owed, changed=finalized)

    @staticmethod
    def _representation_ids(source_id: uuid.UUID) -> Select[tuple[uuid.UUID]]:
        return select(Representation.id).where(
            Representation.observation_id.in_(
                select(Observation.id).where(Observation.source_id == source_id)
            )
        )

    # --- step four: finalization ----------------------------------------------------------

    def _finalize(self, session: Session, source_id: uuid.UUID, now: datetime) -> bool:
        """Delete what is left; True if this call did it (False: another request already had)."""
        source = session.get(Source, source_id, populate_existing=True)
        if source is None:
            raise SourceMissingError(f"source {source_id} does not exist")
        if source.state == SourceState.DELETED:
            return False  # another request finished it
        if source.state != SourceState.DELETING:
            raise SourceLifecycleError(f"source {source_id} is {source.state}, not DELETING")
        observations = select(Observation.id).where(Observation.source_id == source_id)
        representations = select(Representation.id).where(
            Representation.observation_id.in_(observations)
        )
        if session.scalar(
            select(Representation.id)
            .where(
                Representation.observation_id.in_(observations),
                Representation.state.in_(_HOLDS_VECTOR),
            )
            .limit(1)
        ):
            raise ErasureIncompleteError(f"source {source_id} still has a face vector")

        # The log will hold the earlier pages of what is deleted below: owe a truncation, durably.
        AppStateRepository(session).set(WAL_TRUNCATION_OWED, uuid.uuid4().hex, now=now)
        owned = [i for i in session.scalars(select(self._artifact_ids(source_id).subquery())) if i]

        # The identities that lose something, read before the rows go.
        affected: set[uuid.UUID] = set(
            session.scalars(select(Occurrence.identity_id).where(Occurrence.source_id == source_id))
        )
        affected.update(
            identity_id
            for identity_id in session.scalars(
                select(Representation.identity_id).where(Representation.id.in_(representations))
            )
            if identity_id is not None
        )

        def run(statement: Executable) -> None:
            session.execute(statement, execution_options={"synchronize_session": False})

        # Evidence stays; what it pointed at goes. A candidate keeps its identity and score.
        run(
            delete(EvidenceRepresentation).where(
                EvidenceRepresentation.representation_id.in_(representations)
            )
        )
        run(
            update(EvidenceCandidate)
            .where(EvidenceCandidate.representation_id.in_(representations))
            .values(representation_id=None)
        )
        run(delete(IndexOperation).where(IndexOperation.representation_id.in_(representations)))
        run(delete(Occurrence).where(Occurrence.source_id == source_id))  # membership cascades
        # The observations own their representations: deleting them deletes those rows too.
        run(delete(Observation).where(Observation.source_id == source_id))

        runs = select(ProcessingRun.id).where(ProcessingRun.source_id == source_id)
        snapshots = list(
            session.scalars(
                select(ProcessingRun.configuration_snapshot_id).where(
                    ProcessingRun.source_id == source_id
                )
            )
        )
        run(
            update(Evidence)
            .where(Evidence.processing_run_id.in_(runs))
            .values(processing_run_id=None)
        )
        run(
            update(Identity)
            .where(Identity.created_by_processing_run_id.in_(runs))
            .values(created_by_processing_run_id=None)
        )
        run(delete(ProcessingCheckpoint).where(ProcessingCheckpoint.processing_run_id.in_(runs)))
        run(delete(ExecutionSegment).where(ExecutionSegment.processing_run_id.in_(runs)))
        run(update(Job).where(Job.processing_run_id.in_(runs)).values(previous_job_id=None))
        run(delete(Job).where(Job.processing_run_id.in_(runs)))
        run(
            update(ProcessingRun)
            .where(ProcessingRun.source_id == source_id)
            .values(parent_run_id=None)
        )
        run(update(Source).where(Source.id == source_id).values(current_processing_run_id=None))
        run(delete(ProcessingRun).where(ProcessingRun.source_id == source_id))
        for chunk in _chunks(snapshots):
            run(
                delete(ProcessingConfigurationSnapshot).where(
                    ProcessingConfigurationSnapshot.id.in_(chunk)
                )
            )
        # What describes the deleted files goes with them (the id and storage key stay).
        for chunk in _chunks(owned):
            run(
                update(Artifact)
                .where(Artifact.id.in_(chunk))
                .values(original_filename=None, mime_type=None, sha256=None, size_bytes=None)
            )

        # An identity that keeps other faces needs a face to show; the deleted one cannot be it.
        survivor = (
            select(Occurrence.representative_observation_id)
            .where(
                Occurrence.identity_id == Identity.id,
                Occurrence.state == OccurrenceState.ACTIVE,
                Occurrence.representative_observation_id.is_not(None),
            )
            .order_by(Occurrence.created_at, Occurrence.id)
            .limit(1)
            .scalar_subquery()
        )
        for chunk in _chunks(list(affected)):
            run(
                update(Identity)
                .where(
                    Identity.id.in_(chunk),
                    Identity.state == IdentityState.ACTIVE,
                    Identity.representative_observation_id.is_(None),
                    survivor.is_not(None),
                )
                .values(
                    representative_observation_id=survivor,
                    revision=Identity.revision + 1,
                    updated_at=now,
                )
            )

        # An unnamed identity with nothing left has no reason to exist; a named one stays.
        for chunk in _chunks(list(affected)):
            run(
                update(Identity)
                .where(
                    Identity.id.in_(chunk),
                    Identity.state == IdentityState.ACTIVE,
                    ~exists().where(
                        Occurrence.identity_id == Identity.id,
                        Occurrence.state.in_((OccurrenceState.ACTIVE, OccurrenceState.PENDING)),
                    ),
                    ~exists().where(
                        IdentityPersonAssociation.identity_id == Identity.id,
                        IdentityPersonAssociation.state == AssociationState.ACTIVE,
                    ),
                )
                .values(state=IdentityState.DELETED, revision=Identity.revision + 1, updated_at=now)
            )

        optimistic_locked_update(
            session,
            Source,
            source_id,
            expected_revision=source.revision,
            values={
                "state": SourceState.DELETED,
                "display_name": DELETED_DISPLAY_NAME,
                "thumbnail_artifact_id": None,
                "captured_at": None,
                "media_duration_ms": None,
                "width": None,
                "height": None,
                "frame_rate_num": None,
                "frame_rate_den": None,
                "updated_at": now,
            },
        )
        return True
