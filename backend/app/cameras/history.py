"""Deleting part of a camera's history (M7 step 5; product spec 9; plan C9; SEC-006 camera half).

The user can delete one encounter, a selection of them, or everything a camera saw in a UTC time
range (a day is a range). Deletion is permanent and immediate, with no Recycle bin (C9), and
follows the order of a Source's permanent deletion (M5 step 4c, `permanent_delete.py`), durable
intent first:

1. *Intent* (one transaction): the chosen faces (observations), and every encounter they belong to,
   become `DELETED`; their vectors are queued for erasure (out of recognition and search from this
   commit on); their face crops get their deletion intent; the identities that lose a face are
   bumped, so a merge or split prepared against them is refused.
2. *Bytes and vectors*: the crops' bytes are removed and the vectors erased (row, index files and
   write-ahead log, `RepresentationEraser`).
3. *Finalization* (one transaction, only once 2 is done): the deleted encounters and faces are
   removed with their index operations; Evidence that cited them stays, detached from them (ids,
   kinds and scores, no biometric payload), as M5 step 4b leaves it; the write-ahead log is
   truncated.

Anything 2 or 3 could not finish (a locked file) is reported; a repeat, or the next deletion on the
same camera, carries it on: faces already `DELETED` are included again. Startup recovery finishes
erasures and crop deletions on its own.

Deleting the whole camera with all its history is the existing permanent deletion of its Source.
"""

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from backend.app.identities.models import (
    EvidenceCandidate,
    EvidenceRepresentation,
    Identity,
    IdentityState,
)
from backend.app.memory.erasure import CHUNK, RepresentationEraser
from backend.app.memory.models import (
    IndexOperation,
    Observation,
    ObservationState,
    Occurrence,
    OccurrenceObservation,
    OccurrenceState,
    Representation,
    RepresentationState,
)
from backend.app.settings.app_state import WAL_TRUNCATION_OWED, AppStateRepository
from backend.app.sources.artifact_storage import (
    DELETABLE_STATES,
    complete_artifact_deletion,
    request_artifact_deletion,
)
from backend.app.sources.models import Artifact, ArtifactState, Source, SourceKind, SourceState
from backend.infrastructure.db.unit_of_work import UnitOfWork
from backend.infrastructure.storage.files import ManagedFileStore
from backend.infrastructure.storage.layout import UnsafeStorageKeyError

_LIVE = (ObservationState.ACTIVE, ObservationState.PENDING)
_HOLDS_VECTOR = (
    RepresentationState.ACTIVE,
    RepresentationState.PENDING,
    RepresentationState.SUPERSEDED,
    RepresentationState.ERASING,
)


class CameraHistoryError(Exception):
    pass


class CameraNotFoundError(CameraHistoryError):
    code = "CAMERA_NOT_FOUND"


class CameraBusyError(CameraHistoryError):
    """A session is running: what it is writing cannot be deleted under it."""

    code = "CAMERA_BUSY"


@dataclass(frozen=True, slots=True)
class HistorySelection:
    """What to delete: these encounters, and every face seen in `[start_ms, end_ms]` (UTC
    milliseconds, inclusive). Nothing given is everything."""

    occurrence_ids: tuple[uuid.UUID, ...] = ()
    start_ms: int | None = None
    end_ms: int | None = None

    @property
    def everything(self) -> bool:
        return not self.occurrence_ids and self.start_ms is None and self.end_ms is None


@dataclass
class HistoryDeletion:
    camera_id: uuid.UUID
    faces: int  # faces whose deletion this call began
    encounters: int  # encounters whose deletion this call began
    complete: bool
    outstanding: list[str] = field(default_factory=list)


def _chunks(ids: Sequence[uuid.UUID]) -> list[Sequence[uuid.UUID]]:
    return [ids[start : start + CHUNK] for start in range(0, len(ids), CHUNK)]


class DeleteCameraHistory:
    def __init__(
        self,
        unit_of_work: UnitOfWork,
        eraser: RepresentationEraser,
        store: ManagedFileStore,
        *,
        clock: Callable[[], datetime],
        is_running: Callable[[Session, uuid.UUID], bool],
    ) -> None:
        self._uow = unit_of_work
        self._eraser = eraser
        self._store = store
        self._clock = clock
        self._is_running = is_running

    def delete(self, camera_id: uuid.UUID, selection: HistorySelection) -> HistoryDeletion:
        now = self._clock()
        faces, encounters = self._uow.write(
            lambda session: self._intent(session, camera_id, selection, now)
        )
        outstanding = self._carry_on(camera_id)
        return HistoryDeletion(camera_id, faces, encounters, not outstanding, outstanding)

    # --- step one ---------------------------------------------------------------------------

    def _intent(
        self, session: Session, camera_id: uuid.UUID, selection: HistorySelection, now: datetime
    ) -> tuple[int, int]:
        source = session.get(Source, camera_id)
        if (
            source is None
            or source.kind != SourceKind.CAMERA
            or source.state in (SourceState.DELETING, SourceState.DELETED)
        ):
            raise CameraNotFoundError(f"no camera {camera_id}")
        if self._is_running(session, camera_id):
            raise CameraBusyError("stop the camera's session before deleting its history")
        chosen = select(Observation.id).where(
            Observation.source_id == camera_id, Observation.state.in_(_LIVE)
        )
        if not selection.everything:
            conditions = []
            if selection.occurrence_ids:
                conditions.append(
                    Observation.id.in_(
                        select(OccurrenceObservation.observation_id)
                        .join(Occurrence, Occurrence.id == OccurrenceObservation.occurrence_id)
                        .where(
                            Occurrence.id.in_(selection.occurrence_ids),
                            Occurrence.source_id == camera_id,
                        )
                    )
                )
            if selection.start_ms is not None or selection.end_ms is not None:
                low = selection.start_ms if selection.start_ms is not None else 0
                high = selection.end_ms if selection.end_ms is not None else 2**62
                conditions.append(Observation.timestamp_ms.between(low, high))
            chosen = chosen.where(or_(*conditions))
        faces = list(session.scalars(chosen))
        encounters = set(
            session.scalars(
                select(OccurrenceObservation.occurrence_id)
                .join(Occurrence, Occurrence.id == OccurrenceObservation.occurrence_id)
                .where(
                    OccurrenceObservation.observation_id.in_(chosen),
                    Occurrence.state == OccurrenceState.ACTIVE,
                )
            )
        )
        encounters.update(
            session.scalars(
                select(Occurrence.id).where(
                    Occurrence.id.in_(selection.occurrence_ids),
                    Occurrence.source_id == camera_id,
                    Occurrence.state == OccurrenceState.ACTIVE,
                )
            )
        )
        no_sync = {"synchronize_session": False}
        for chunk in _chunks(faces):
            self._eraser.queue_in(
                session,
                list(
                    session.scalars(
                        select(Representation.id).where(Representation.observation_id.in_(chunk))
                    )
                ),
            )
            # (a face names its crop only once the crop is written: never a PENDING one)
            for artifact_id in session.scalars(
                select(Artifact.id)
                .join(Observation, Observation.face_crop_artifact_id == Artifact.id)
                .where(Observation.id.in_(chunk), Artifact.state.in_(DELETABLE_STATES))
            ):
                request_artifact_deletion(session, artifact_id, clock=lambda: now)
            session.execute(
                update(Observation)
                .where(Observation.id.in_(chunk))
                .values(state=ObservationState.DELETED),
                execution_options=no_sync,
            )
        for chunk in _chunks(list(encounters)):
            session.execute(
                update(Identity)
                .where(
                    Identity.id.in_(select(Occurrence.identity_id).where(Occurrence.id.in_(chunk))),
                    Identity.state == IdentityState.ACTIVE,
                )
                .values(revision=Identity.revision + 1, updated_at=now),
                execution_options=no_sync,
            )
            session.execute(
                update(Occurrence)
                .where(Occurrence.id.in_(chunk))
                .values(state=OccurrenceState.DELETED),
                execution_options=no_sync,
            )
        return len(faces), len(encounters)

    # --- steps two and three ----------------------------------------------------------------

    def _carry_on(self, camera_id: uuid.UUID) -> list[str]:
        deleted = select(Observation.id).where(
            Observation.source_id == camera_id, Observation.state == ObservationState.DELETED
        )

        def owed(session: Session) -> tuple[list[tuple[uuid.UUID, str | None]], list[uuid.UUID]]:
            crops = list(
                session.execute(
                    select(Artifact.id, Artifact.storage_key)
                    .join(Observation, Observation.face_crop_artifact_id == Artifact.id)
                    .where(
                        Observation.id.in_(deleted),
                        Artifact.state.in_((ArtifactState.DELETING, ArtifactState.DELETE_FAILED)),
                    )
                ).tuples()
            )
            vectors = list(
                session.scalars(
                    select(Representation.id).where(
                        Representation.observation_id.in_(deleted),
                        Representation.state.in_(_HOLDS_VECTOR),
                    )
                )
            )
            return crops, vectors

        crops, vectors = self._uow.read(owed)
        outstanding: list[str] = []
        for artifact_id, key in crops:
            try:
                complete_artifact_deletion(self._uow, self._store, artifact_id, clock=self._clock)
                assert key is not None  # (a managed crop always has its key)
                self._store.staging_path(key).unlink(missing_ok=True)
            except (OSError, UnsafeStorageKeyError) as error:
                outstanding.append(f"crop {artifact_id}: {type(error).__name__}: {error}")
        if vectors:
            outstanding += self._eraser.erase(vectors).outstanding_cleanup
        if outstanding:
            return outstanding
        now = self._clock()
        self._uow.write(lambda session: self._finalize(session, camera_id, now))
        return self._eraser.settle_log()

    @staticmethod
    def _finalize(session: Session, camera_id: uuid.UUID, now: datetime) -> None:
        faces = list(
            session.scalars(
                select(Observation.id).where(
                    Observation.source_id == camera_id,
                    Observation.state == ObservationState.DELETED,
                    ~Observation.id.in_(
                        select(Representation.observation_id).where(
                            Representation.state.in_(_HOLDS_VECTOR)
                        )
                    ),
                )
            )
        )
        if not faces:
            return
        # The log will hold the earlier pages of what is deleted below: owe a truncation, durably.
        AppStateRepository(session).set(WAL_TRUNCATION_OWED, uuid.uuid4().hex, now=now)
        no_sync = {"synchronize_session": False}
        session.execute(
            delete(Occurrence).where(
                Occurrence.source_id == camera_id, Occurrence.state == OccurrenceState.DELETED
            ),
            execution_options=no_sync,
        )  # (membership cascades)
        for chunk in _chunks(faces):
            representations = select(Representation.id).where(
                Representation.observation_id.in_(chunk)
            )
            session.execute(
                delete(EvidenceRepresentation).where(
                    EvidenceRepresentation.representation_id.in_(representations)
                ),
                execution_options=no_sync,
            )
            session.execute(
                update(EvidenceCandidate)
                .where(EvidenceCandidate.representation_id.in_(representations))
                .values(representation_id=None),
                execution_options=no_sync,
            )
            session.execute(
                delete(IndexOperation).where(IndexOperation.representation_id.in_(representations)),
                execution_options=no_sync,
            )
            # (an occurrence of another camera's history never names these faces; any other
            # occurrence that showed one of them loses it as its representative face)
            session.execute(
                update(Occurrence)
                .where(Occurrence.representative_observation_id.in_(chunk))
                .values(representative_observation_id=None),
                execution_options=no_sync,
            )
            session.execute(
                delete(Observation).where(Observation.id.in_(chunk)), execution_options=no_sync
            )  # (their representations go with them)
