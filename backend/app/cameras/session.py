"""A live camera session: start it, run it, end it (M7 step 4; plan C2 to C8).

**Start** (`start_camera_session`) is one short transaction: the camera must be an active `CAMERA`
Source and no other session may be running (`CameraBusyError`, one at a time, C2); the processing
request is resolved and frozen into a configuration snapshot with the camera settings beside it,
and a `PROCESS_CAMERA_SESSION` job is created and claimed at once with its run `RUNNING` and its
first execution segment, exactly as the scheduler claims source work (the scheduler itself never
claims a camera job).

**Running** (`CameraSessionExecutor.run`) reads the session's frames (`LiveCamera`): each frame is
detected in the worker's **live** class (one request outstanding at a time, so the live queue is
never longer than one; `lease.live()`), tracked into encounters (`encounters.py`), and an encounter
that closes is recorded at once:

1. its chosen sightings (at most `keep`, C3) are embedded, still in the live class;
2. one transaction writes their face crops (managed `FACE_CROP` artifacts, reserved and written
   before it), observations and representations as the run's private `PENDING` output;
3. each face is decided as a video's are (`_decide`: the frozen policy over the global
   index), the track rule D7 settles the encounter (`_settle_tracks`: one identity for all its
   faces, else every one abstains as `TRACK_UNSETTLED`, so a camera never creates an identity, C5),
   and one transaction accepts it through the run acceptance's own validation
   (`accept_encounter`): matched faces join their identity and become one `TRACK` occurrence from
   the encounter's first to its last UTC millisecond; an unknown person's faces become
   identity-less active representations with abstention evidence (the unplaced-faces list), and
   no occurrence.

A crash between 2 and 3 leaves that encounter's rows private (`PENDING`) in a run that startup
recovery marks `INTERRUPTED`; encounters already accepted stay. Frames are never written.

**End**: a stop closes the stream; the open encounters are recorded, then the segment, run and job
are completed. A camera that does not come back (`CameraError`) or a failing worker records what it
can and ends the session `FAILED` with the reason's code. Sessions are never resumed or retried.
"""

import io
import math
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
from numpy.typing import NDArray
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.cameras.capture import Gap
from backend.app.cameras.encounters import Encounter, Encounters, Sighting
from backend.app.jobs.models import Job, JobPriority, JobState, JobType, ProgressMode
from backend.app.jobs.repository import JobRepository
from backend.app.memory.models import Observation
from backend.app.processing.accept_run import AcceptProcessingRunUseCase
from backend.app.processing.configuration import (
    ProcessingConfigurationError,
    ProcessingRequestV1,
    resolve,
)
from backend.app.processing.execute_job import (
    ExecuteProcessingJob,
    ProcessingExecutionError,
    _Decision,
    _frozen,
    _FrozenConfiguration,
    _Input,
    _proposal,
    _settle_tracks,
)
from backend.app.processing.models import (
    ExecutionSegmentState,
    ProcessingConfigurationSnapshot,
    ProcessingRun,
    ProcessingRunState,
)
from backend.app.processing.pending_output import write_observation, write_representation
from backend.app.processing.repository import SegmentRepository
from backend.app.processing.run_repository import ProcessingRunRepository, SnapshotRepository
from backend.app.processing.scheduler import StartedProcessingJob
from backend.app.runtime.perception_client import Detected, Represented
from backend.app.sources.artifact_storage import (
    mark_artifact_available,
    mark_write_not_completed,
    reserve_managed_artifact,
)
from backend.app.sources.models import ArtifactKind, Source, SourceKind, SourceState
from backend.infrastructure.db.optimistic import optimistic_locked_update
from backend.infrastructure.media.camera import CameraError, LiveFrame
from backend.infrastructure.storage.files import StoredBytes
from backend.ml.supervisor.lease import live

CAMERA_OWNER = "camera"
LEASE_FOR_SECONDS = 365 * 24 * 3600  # a session's claim lasts as long as the session (no expiry)
CROP_QUALITY = 90


class CameraSessionError(Exception):
    code = "CAMERA_NOT_FOUND"


class CameraNotConfiguredError(CameraSessionError):
    """No active camera with that id."""


class CameraBusyError(CameraSessionError):
    code = "CAMERA_BUSY"


@dataclass(frozen=True, slots=True)
class CameraSettings:
    """A session's camera settings (plan C2, C3, C7, C8), frozen into its snapshot."""

    sample_fps: float = 5.0
    reconnect_timeout_seconds: float = 30.0
    encounter_gap_seconds: float = 5.0
    keep_per_encounter: int = 3
    pool_per_encounter: int = 8
    max_side: int = 1920

    def frozen(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "sample_fps": self.sample_fps,
            "reconnect_timeout_seconds": self.reconnect_timeout_seconds,
            "encounter_gap_seconds": self.encounter_gap_seconds,
            "keep_per_encounter": self.keep_per_encounter,
            "pool_per_encounter": self.pool_per_encounter,
            "max_side": self.max_side,
        }

    @classmethod
    def from_frozen(cls, value: object) -> "CameraSettings":
        if not isinstance(value, dict) or value.get("schema_version") != 1:
            raise ProcessingExecutionError("the session's camera settings are malformed")
        try:
            return cls(
                float(value["sample_fps"]),
                float(value["reconnect_timeout_seconds"]),
                float(value["encounter_gap_seconds"]),
                int(value["keep_per_encounter"]),
                int(value["pool_per_encounter"]),
                int(value["max_side"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ProcessingExecutionError("the session's camera settings are malformed") from error


RUNNING_SESSION = (JobState.QUEUED, JobState.RUNNING, JobState.CANCELLING)


def running_session(session: Session) -> uuid.UUID | None:
    """The camera Source whose session is running, if any."""
    return session.scalar(
        select(ProcessingRun.source_id)
        .join(Job, Job.processing_run_id == ProcessingRun.id)
        .where(Job.type == JobType.PROCESS_CAMERA_SESSION, Job.state.in_(RUNNING_SESSION))
        .limit(1)
    )


def start_camera_session(
    session: Session,
    camera_id: uuid.UUID,
    *,
    processing_request: dict[str, Any],
    settings: CameraSettings,
    new_id: Callable[[], uuid.UUID],
    now: datetime,
) -> StartedProcessingJob:
    """Create and claim one camera session (see the module docstring). Joins the caller's
    transaction."""
    source = session.get(Source, camera_id)
    if source is None or source.kind != SourceKind.CAMERA or source.state != SourceState.ACTIVE:
        raise CameraNotConfiguredError(f"no active camera {camera_id}")
    if running_session(session) is not None:
        raise CameraBusyError("a camera session is already running")
    try:
        configuration = resolve(session, ProcessingRequestV1.parse(processing_request))
    except ProcessingConfigurationError as error:
        raise ProcessingExecutionError(str(error)) from None
    snapshot = SnapshotRepository(session).create(
        snapshot_id=new_id(),
        schema_version=1,
        canonical_json={**configuration, "camera": settings.frozen()},
        now=now,
        created_by_user_action="camera.start",
    )
    run = ProcessingRunRepository(session).add(
        ProcessingRun(
            id=new_id(),
            source_id=camera_id,
            configuration_snapshot_id=snapshot.id,
            state=ProcessingRunState.PENDING,
            requested_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    repository = JobRepository(session)
    job = repository.add(
        Job(
            id=new_id(),
            type=JobType.PROCESS_CAMERA_SESSION,
            processing_run_id=run.id,
            state=JobState.QUEUED,
            priority=JobPriority.HIGH,
            payload_schema_version=1,
            payload_json=None,
            progress_mode=ProgressMode.INDETERMINATE,
            created_at=now,
            updated_at=now,
        )
    )
    claimed = repository.claim_next(
        owner=CAMERA_OWNER,
        now=now,
        lease_for=timedelta(seconds=LEASE_FOR_SECONDS),
        types=(JobType.PROCESS_CAMERA_SESSION,),
        where=(Job.id == job.id,),
    )
    assert claimed is not None  # (just created, in this transaction)
    optimistic_locked_update(
        session,
        ProcessingRun,
        run.id,
        expected_revision=run.revision,
        values={"state": ProcessingRunState.RUNNING, "started_at": now, "updated_at": now},
    )
    segment = SegmentRepository(session).append(
        run.id,
        segment_id=new_id(),
        runtime_variant_id=None,
        runtime_details={"schema_version": 1},
        now=now,
    )
    return StartedProcessingJob(claimed, segment.id)


@dataclass(frozen=True, slots=True)
class Seen:
    """What one frame showed, for the preview and the status."""

    frame: LiveFrame
    detected: Detected
    open_encounters: int


class CameraSessionExecutor(ExecuteProcessingJob):
    """Runs one started camera session to its end (see the module docstring)."""

    def __init__(
        self,
        *args: Any,
        accept: AcceptProcessingRunUseCase,
        wake_index: Callable[[], None] = lambda: None,
        utc_now: Callable[[], datetime] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._accept = accept
        self._wake_index = wake_index
        self._utc_now = utc_now or self._clock

    def run(
        self,
        started: StartedProcessingJob,
        frames: Iterable[LiveFrame | Gap],
        *,
        seen: Callable[[Seen], None] = lambda _seen: None,
        closed: Callable[[uuid.UUID | None], None] = lambda _occurrence: None,
    ) -> str:
        """Run the session until `frames` ends. Returns how it ended: `STOPPED`, or the failure
        code it was settled `FAILED` with (then the error is re-raised)."""
        state = _State(started)
        try:
            source = self._uow.read(lambda session: self._input(session, started))
            frozen = _frozen(source.snapshot)
            settings = CameraSettings.from_frozen(source.snapshot.get("camera"))
            plan = self._uow.read(lambda session: self._plan(session, frozen))
            client = self._client_for(plan)
            encounters = Encounters(
                fps=settings.sample_fps,
                gap_seconds=settings.encounter_gap_seconds,
                pool=settings.pool_per_encounter,
            )
            began: float | None = None
            try:
                for item in frames:
                    if isinstance(item, Gap):
                        for encounter in encounters.close_all():
                            closed(self._record(state, source, frozen, settings, client, encounter))
                        continue
                    began = item.received_at if began is None else began
                    with live(), client.turn():  # type: ignore[attr-defined]
                        detected = client.detect(item.pixels)
                    state.started = self._advance_after_fallbacks(
                        source, state.started, detected.fallbacks
                    )
                    for encounter in encounters.see(
                        elapsed=item.received_at - began,
                        sequence=item.sequence,
                        at_ms=self._epoch_ms(),
                        pixels=item.pixels,
                        detections=detected.detections,
                        detector=detected.ran,
                    ):
                        closed(self._record(state, source, frozen, settings, client, encounter))
                    seen(Seen(item, detected, encounters.open))
            except CameraError:
                for encounter in encounters.close_all():
                    closed(self._record(state, source, frozen, settings, client, encounter))
                raise
            for encounter in encounters.close_all():
                closed(self._record(state, source, frozen, settings, client, encounter))
            self._uow.write(lambda session: self._complete(session, source, state.started))
            return "STOPPED"
        except CameraError as error:
            self._fail(state.started, error.code)
            raise
        except Exception as error:
            self._fail(state.started, type(error).__name__)
            raise

    def _epoch_ms(self) -> int:
        return math.floor(self._utc_now().astimezone(UTC).timestamp() * 1000)

    def _input(
        self,
        session: Session,
        started: StartedProcessingJob,
        *,
        allow_cancelling: bool = False,
        allow_pausing: bool = False,
    ) -> _Input:
        """The camera's session: a camera has no original to read (the parent joins one)."""
        actual = session.execute(
            select(ProcessingRun, ProcessingConfigurationSnapshot, Source)
            .join(
                ProcessingConfigurationSnapshot,
                ProcessingConfigurationSnapshot.id == ProcessingRun.configuration_snapshot_id,
            )
            .join(Source, Source.id == ProcessingRun.source_id)
            .where(ProcessingRun.id == started.job.processing_run_id)
        ).one_or_none()
        if actual is None:
            raise ProcessingExecutionError("the camera session's run is missing")
        run, snapshot, source = actual
        if run.state != ProcessingRunState.RUNNING:
            raise ProcessingExecutionError(f"the camera session is {run.state}, not RUNNING")
        if source.kind != SourceKind.CAMERA or source.state != SourceState.ACTIVE:
            raise ProcessingExecutionError("the camera is no longer an active camera")
        return _Input(
            run.source_id, run.id, snapshot.canonical_json, "", None, None, kind=SourceKind.CAMERA
        )

    def _record(
        self,
        state: "_State",
        source: _Input,
        frozen: _FrozenConfiguration,
        settings: CameraSettings,
        client: Any,
        encounter: Encounter,
    ) -> uuid.UUID | None:
        """Embed, write and accept one closed encounter. Returns its occurrence, if it has one."""
        sightings = encounter.chosen(
            keep=settings.keep_per_encounter,
            min_score=frozen.decision_policy.min_detection_score,
        )
        if not sightings:
            return None
        with live(), client.turn():
            represented: list[Represented] = [
                client.represent(sighting.crop, (sighting.detection,)) for sighting in sightings
            ]
        for result in represented:
            state.started = self._advance_after_fallbacks(source, state.started, result.fallbacks)
        crops = self._store_crops(sightings)
        observations, representations = self._uow.write(
            lambda session: self._write_private(
                session, state, source, frozen, sightings, represented, crops
            )
        )
        track = {
            "track": encounter.track,
            "observations": [str(o) for o in observations],
            "start_ms": encounter.start_ms,
            "end_ms": encounter.end_ms,
            "start_frame": encounter.start_sequence,
            "end_frame": encounter.end_sequence,
        }
        decisions = _settle_tracks(self._decide(source, frozen, representations), [track])
        occurrence = self._uow.write(
            lambda session: self._accept_encounter(session, source, state, decisions, track)
        )
        self._wake_index()
        return occurrence

    def _store_crops(self, sightings: list[Sighting]) -> list[tuple[uuid.UUID, StoredBytes]]:
        """Each sighting's crop as a managed JPEG (reserved, written, then recorded AVAILABLE in the
        encounter's transaction; a crash in between leaves a reservation recovery settles)."""
        reserved = self._uow.write(
            lambda session: [
                (artifact.id, artifact.storage_key)
                for artifact in (
                    reserve_managed_artifact(
                        session,
                        ArtifactKind.FACE_CROP,
                        new_id=self._new_id,
                        clock=self._clock,
                        mime_type="image/jpeg",
                    )
                    for _ in sightings
                )
            ]
        )
        stored = []
        for (artifact_id, key), sighting in zip(reserved, sightings, strict=True):
            assert key is not None
            try:
                stored.append(self._files.store(key, io.BytesIO(_jpeg(sighting.crop))))
            except Exception as error:

                def unwritten(
                    session: Session,
                    artifact_id: uuid.UUID = artifact_id,
                    detail: str = f"{type(error).__name__}: {error}",
                ) -> None:
                    mark_write_not_completed(session, artifact_id, detail)

                self._uow.write(unwritten)
                raise
        return [
            (artifact_id, bytes_)
            for (artifact_id, _k), bytes_ in zip(reserved, stored, strict=True)
        ]

    def _write_private(
        self,
        session: Session,
        state: "_State",
        source: _Input,
        frozen: _FrozenConfiguration,
        sightings: list[Sighting],
        represented: list[Represented],
        crops: list[tuple[uuid.UUID, StoredBytes]],
    ) -> tuple[list[uuid.UUID], list[uuid.UUID]]:
        self._revalidate_settlement_context(session, source, state.started)
        observations: list[uuid.UUID] = []
        representations: list[uuid.UUID] = []
        for sighting, result, (crop, stored) in zip(sightings, represented, crops, strict=True):
            if result.ran is None or len(result.vectors) != 1:
                raise ProcessingExecutionError("the embedder did not settle a chosen face")
            mark_artifact_available(session, crop, stored, clock=self._clock)
            observation_id = write_observation(
                session,
                source_id=source.source_id,
                processing_run_id=source.run_id,
                execution_segment_id=state.started.execution_segment_id,
                sequence_in_run=state.sequence,
                detection=sighting.detection,
                detector=sighting.detector,
                new_id=self._new_id,
                now=self._clock(),
                frame_index=sighting.sequence,
                timestamp_ms=sighting.at_ms,
            ).observation_id
            observation = session.get(Observation, observation_id)
            assert observation is not None
            observation.face_crop_artifact_id = crop
            representations.append(
                write_representation(
                    session,
                    observation_id=observation_id,
                    execution_segment_id=state.started.execution_segment_id,
                    detection_index=0,
                    vector=result.vectors[0],
                    embedder=result.ran,
                    representation_space_id=frozen.representation_space_id,
                    new_id=self._new_id,
                    now=self._clock(),
                ).representation_id
            )
            observations.append(observation_id)
            state.sequence += 1
        return observations, representations

    def _accept_encounter(
        self,
        session: Session,
        source: _Input,
        state: "_State",
        decisions: list[_Decision],
        track: dict[str, Any],
    ) -> uuid.UUID | None:
        persisted = self._persist_decisions(session, source, state.started, decisions)
        payload = [
            {
                "observation_id": str(entry.observation_id),
                "representation_id": str(entry.representation_id),
                "outcome": entry.decision.outcome.value,
                "reason": entry.decision.reason.value,
                "identity_id": None if entry.identity_id is None else str(entry.identity_id),
                "evidence": {
                    **entry.decision.evidence_payload(),
                    "identity_id": None if entry.identity_id is None else str(entry.identity_id),
                    **_proposal(entry),
                },
            }
            for entry in persisted
        ]
        return self._accept.accept_encounter(session, source.run_id, payload, track)

    def _complete(self, session: Session, source: _Input, started: StartedProcessingJob) -> None:
        run, segment, _job = self._revalidate_settlement_context(session, source, started)
        now = self._clock()
        # (the segment and the job were just found RUNNING under this write lock: both moves hold)
        closed = SegmentRepository(session).close(
            segment.id, ExecutionSegmentState.COMPLETED, reason="NORMAL", now=now
        )
        assert closed
        optimistic_locked_update(
            session,
            ProcessingRun,
            run.id,
            expected_revision=run.revision,
            values={"state": ProcessingRunState.COMPLETED, "completed_at": now, "updated_at": now},
        )
        ended = JobRepository(session).transition(
            started.job.id, (JobState.RUNNING,), JobState.COMPLETED, now=now
        )
        assert ended


class _State:
    def __init__(self, started: StartedProcessingJob) -> None:
        self.started = started
        self.sequence = 0


def _jpeg(pixels: NDArray[np.uint8]) -> bytes:
    buffer = io.BytesIO()
    Image.fromarray(pixels, "RGB").save(buffer, format="JPEG", quality=CROP_QUALITY)
    return buffer.getvalue()
