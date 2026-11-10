"""Execute one claimed processing job without making its output authoritative.

The scheduler has already made the short claim/start transition.  This module deliberately keeps
every expensive operation -- opening media, decoding, package verification and worker inference --
outside SQLite write transactions.  Each resulting detector/embedding result is settled in a short
transaction as private ``PENDING`` output.  A valid FINAL checkpoint is the hand-off to the
acceptance use case; it is *not* acceptance and creates neither ANN operations nor active rows.

A video (M6 steps 4 and 5) is decoded once, from where its run last stopped, through the pinned
ffmpeg, two frames a second by presentation time (D4), and taken in chunks; a chunk is a checkpoint
boundary (`video_chunks.py`). Within a chunk, detection and then representation go in batches of
frames, each batch ONE turn on the worker asked for inside `cancellable` (#242): a face search waits
at most one batch and a cancellation is seen at the next batch. The NumPy tracker links detections
into tracks (D6), selection keeps a few good observations per track and chunk, and only those are
embedded and recorded, in ONE transaction with the chunk's checkpoint. After the last chunk,
recognition and FINAL are as for an image, FINAL also carrying the run's tracks. A chunk holds its
frames' pixels in memory: `chunk_frames` frames, scaled to a longest side of `max_side` (about
120 MB at 1920 pixels).
"""

import math
import uuid
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager, closing
from dataclasses import dataclass, field, replace
from datetime import datetime
from itertools import batched
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.identities.models import Identity, IdentityState
from backend.app.identities.use_cases import create_pending_identity
from backend.app.jobs.models import Job, JobState
from backend.app.jobs.repository import JobRepository
from backend.app.memory.models import Observation, Representation, RepresentationSpace
from backend.app.processing.models import (
    CheckpointKind,
    ExecutionSegment,
    ExecutionSegmentState,
    ProcessingConfigurationSnapshot,
    ProcessingRun,
    ProcessingRunState,
)
from backend.app.processing.pending_output import (
    PendingOutputError,
    write_observation,
    write_representation,
)
from backend.app.processing.repository import CheckpointRepository, SegmentRepository
from backend.app.processing.run_repository import ProcessingRunRepository
from backend.app.processing.scheduler import StartedProcessingJob
from backend.app.processing.tracking import Candidate, Tracker, select_kept
from backend.app.processing.video_chunks import (
    VideoProcessing,
    agreed_identity,
    chunk_payload,
    frame_index,
    resume_point,
    video_tracks,
)
from backend.app.recognition.assessment import ObservationQuality, RecognitionService
from backend.app.recognition.reasoner import (
    DecisionPolicy,
    IdentityReasoner,
    Reason,
    RecognitionDecision,
    RecognitionOutcome,
)
from backend.app.recognition.retrieval import rebuild_run_local_index
from backend.app.runtime.package_store import RuntimePackageStore
from backend.app.runtime.perception_client import (
    Detected,
    PerceptionError,
    ProviderFallback,
    Represented,
)
from backend.app.runtime.worker_config import (
    PerceptionPlan,
    RuntimeUnavailableError,
    plan_perception,
)
from backend.app.sources.models import (
    Artifact,
    ArtifactState,
    Source,
    SourceKind,
    SourceState,
    StorageMode,
)
from backend.infrastructure.db.optimistic import optimistic_locked_update
from backend.infrastructure.db.unit_of_work import UnitOfWork
from backend.infrastructure.indexing.representation_index import RepresentationIndex
from backend.infrastructure.media.frames import Frame, frame_size, sampled_frames
from backend.infrastructure.media.image import ImageError, decode_image
from backend.infrastructure.media.video import MediaTools, MediaToolsMissingError, VideoError
from backend.infrastructure.storage.files import BytesMissingError, ManagedFileStore
from backend.ml.supervisor.lease import RequestCancelledError, cancellable
from backend.ml.supervisor.supervisor import WorkerFailedError

CHECKPOINT_SCHEMA_VERSION = 1
DEFAULT_VIDEO = VideoProcessing()


class ProcessingExecutionError(RuntimeError):
    """A claimed job cannot safely progress; its private output remains private."""


# Failures the executor settles itself (run and job `FAILED`) before re-raising them.
SETTLED_FAILURES: tuple[type[BaseException], ...] = (
    BytesMissingError,
    ImageError,
    PendingOutputError,
    PerceptionError,
    RuntimeUnavailableError,
    WorkerFailedError,
    ProcessingExecutionError,
    VideoError,
    MediaToolsMissingError,
    OSError,
)


class ProcessingCancelledError(RuntimeError):
    """A cancellation request was observed at a durable processing boundary."""


class ProcessingPausedError(RuntimeError):
    """A pause request was observed at a chunk boundary: the video run is `PAUSED` (M6 step 7)."""


class PerceptionPlanner(Protocol):
    """Turns a frozen selection into a plan: `plan_perception`, or the development profile's."""

    def __call__(
        self,
        session: Session,
        store: RuntimePackageStore,
        *,
        detector_component_version_id: uuid.UUID,
        representation_space_id: uuid.UUID,
        providers: Sequence[str],
        detector_model_export_id: uuid.UUID | None = None,
        embedder_model_export_id: uuid.UUID | None = None,
    ) -> PerceptionPlan: ...


class _Perception(Protocol):
    def detect(self, pixels: Any) -> Detected: ...

    def represent(self, pixels: Any, detections: tuple[Any, ...]) -> Represented: ...


@runtime_checkable
class _VideoPerception(_Perception, Protocol):
    def turn(self) -> AbstractContextManager[None]:
        """One worker turn for a batch of requests (#242)."""


@dataclass(frozen=True, slots=True)
class _Input:
    source_id: uuid.UUID
    run_id: uuid.UUID
    snapshot: dict[str, Any]
    storage_mode: str
    storage_key: str | None
    external_path: str | None
    supersedes_run_id: uuid.UUID | None = None  # the generation a reprocess run will replace
    kind: str = SourceKind.IMAGE
    width: int | None = None  # a video's size as shown, its frames' size
    height: int | None = None
    frame_rate: tuple[int, int] | None = field(default=None)
    duration_ms: int | None = None


@dataclass(frozen=True, slots=True)
class _FrozenConfiguration:
    detector_component_version_id: uuid.UUID
    detector_export_id: uuid.UUID
    embedder_export_id: uuid.UUID
    representation_space_id: uuid.UUID
    dimension: int
    providers: tuple[str, ...]
    decision_policy: DecisionPolicy


@dataclass(frozen=True, slots=True)
class _Decision:
    observation_id: uuid.UUID
    representation_id: uuid.UUID
    decision: RecognitionDecision
    identity_id: uuid.UUID | None
    # A face of an unsettled video track (D7): `decision` is then its abstention and this is what
    # the reasoner proposed for the face alone, kept in its evidence.
    proposal: RecognitionDecision | None = None


@dataclass(frozen=True, slots=True)
class ExecutedProcessingJob:
    """The private output now protected by a FINAL checkpoint."""

    processing_run_id: uuid.UUID
    final_checkpoint_id: uuid.UUID
    observation_ids: tuple[uuid.UUID, ...]
    representation_ids: tuple[uuid.UUID, ...]


class ExecuteProcessingJob:
    """Run one image job through its private FINAL checkpoint.

    ``global_index_for`` is intentionally injected.  The index is derived state and this use case
    must not acquire the coordinator's writer lock or mutate USearch itself; it only reads the
    already-opened authoritative candidate index.
    """

    def __init__(
        self,
        uow: UnitOfWork,
        *,
        packages: RuntimePackageStore,
        files: ManagedFileStore,
        client_for: Callable[[PerceptionPlan], _Perception],
        global_index_for: Callable[[uuid.UUID], RepresentationIndex],
        new_id: Callable[[], uuid.UUID],
        clock: Callable[[], datetime],
        max_pixels: int,
        recognition_k: int,
        planner: PerceptionPlanner = plan_perception,
        video_tools: Callable[[], MediaTools] | None = None,
        video: VideoProcessing = DEFAULT_VIDEO,
    ) -> None:
        """`video_tools` finds the pinned FFmpeg when a video is processed; without it a video
        run fails (`ProcessingExecutionError`)."""
        if max_pixels < 1:
            raise ValueError("max_pixels must be positive")
        self._planner = planner
        self._uow = uow
        self._packages = packages
        self._files = files
        self._client_for = client_for
        self._global_index_for = global_index_for
        self._new_id = new_id
        self._clock = clock
        self._max_pixels = max_pixels
        self._recognition = RecognitionService(recognition_k)
        self._video_tools = video_tools
        self._video = video

    def execute(self, started: StartedProcessingJob) -> ExecutedProcessingJob:
        """Perform decode, perception, private recognition, and FINAL settlement.

        A failure is recorded after the failed external operation, then re-raised to the caller.
        It never becomes an implicit alternate model/provider attempt: that narrow policy is
        owned by :class:`PerceptionClient`.
        """
        try:
            self._cancel_if_requested(started)
            source = self._uow.read(lambda session: self._input(session, started))
            self._cancel_if_requested(started)
            frozen = _frozen(source.snapshot)
            plan = self._uow.read(lambda session: self._plan(session, frozen))

            # A cancellation requested while a request waits for the worker is seen at its turn,
            # so it never enters inference (#175); the cancellation is then settled as below.
            def cancelled() -> bool:
                return self._uow.read(lambda s: self._cancellation_requested(s, started))

            if source.kind == SourceKind.VIDEO:
                return self._execute_video(started, source, frozen, plan, cancelled)
            pixels = decode_image(self._read_original(source), max_pixels=self._max_pixels).pixels
            client = self._client_for(plan)

            with cancellable(cancelled):
                detected = client.detect(pixels)
            started = self._advance_after_fallbacks(source, started, detected.fallbacks)
            self._cancel_if_requested(started)
            observations = self._uow.write(
                lambda session: self._settle_detections(session, source, started, detected)
            )
            self._cancel_if_requested(started)
            with cancellable(cancelled):
                represented = client.represent(pixels, detected.detections)
            started = self._advance_after_fallbacks(source, started, represented.fallbacks)
            self._cancel_if_requested(started)
            representations = self._uow.write(
                lambda session: self._settle_representations(
                    session, source, started, frozen, detected, observations, represented
                )
            )
            self._checkpoint_private_output(source, started, observations, representations)
            self._cancel_if_requested(started)
            decisions = self._decide(source, frozen, representations)
            decisions = self._uow.write(
                lambda session: self._persist_decisions(session, source, started, decisions)
            )
            self._cancel_if_requested(started)
            checkpoint = self._uow.write(
                lambda session: self._finalize(session, source, started, observations, decisions)
            )
            return ExecutedProcessingJob(
                source.run_id,
                checkpoint,
                tuple(observations),
                tuple(decision.representation_id for decision in decisions),
            )
        except RequestCancelledError:
            self._uow.write(lambda session: self._cancel(session, started))
            raise ProcessingCancelledError("source processing was cancelled") from None
        except SETTLED_FAILURES as error:
            self._fail(started, type(error).__name__)
            raise

    def fail_claimed(self, started: StartedProcessingJob, code: str) -> None:
        """Settle claimed work `FAILED` after a failure this executor did not recognise (best
        effort, like the recognised ones); the caller re-raises the defect."""
        self._fail(started, code)

    def _cancel_if_requested(self, started: StartedProcessingJob) -> None:
        """Settle an already-requested cancellation between external work units.

        The request itself is written by the command boundary, not by this executor.  This method
        observes it only after an external operation has reached a safe boundary, so it never
        claims to cancel an in-flight worker call.  Private output already settled stays private.
        """
        requested = self._uow.read(lambda session: self._cancellation_requested(session, started))
        if requested:
            self._uow.write(lambda session: self._cancel(session, started))
            raise ProcessingCancelledError("source processing was cancelled")

    @staticmethod
    def _cancellation_requested(session: Session, started: StartedProcessingJob) -> bool:
        job = JobRepository(session).get(started.job.id)
        run = (
            ProcessingRunRepository(session).get(started.job.processing_run_id)
            if started.job.processing_run_id is not None
            else None
        )
        return (job is not None and job.state == JobState.CANCELLING) or (
            run is not None and run.state == ProcessingRunState.CANCELLING
        )

    def _cancel(self, session: Session, started: StartedProcessingJob) -> None:
        """Close the current interval and retain all private output for later inspection."""
        now = self._clock()
        settled = False
        if started.job.processing_run_id is not None:
            run = ProcessingRunRepository(session).lock(started.job.processing_run_id)
            job = JobRepository(session).get(started.job.id)
            if (
                run is not None
                and job is not None
                and job.processing_run_id == run.id
                and job.state in (JobState.RUNNING, JobState.CANCELLING)
            ):
                segment = SegmentRepository(session).get(started.execution_segment_id)
                closed = (
                    segment is not None
                    and segment.processing_run_id == run.id
                    and SegmentRepository(session).close(
                        segment.id,
                        ExecutionSegmentState.COMPLETED,
                        reason="CANCELLED",
                        now=now,
                    )
                )
                if closed and run.state in (
                    ProcessingRunState.RUNNING,
                    ProcessingRunState.CANCELLING,
                ):
                    settled = (
                        optimistic_locked_update(
                            session,
                            ProcessingRun,
                            run.id,
                            expected_revision=run.revision,
                            values={
                                "state": ProcessingRunState.CANCELLED,
                                "updated_at": now,
                            },
                            extra_where=(
                                ProcessingRun.state.in_(
                                    (ProcessingRunState.RUNNING, ProcessingRunState.CANCELLING)
                                ),
                            ),
                        )
                        == 1
                    )
        if settled:
            if not JobRepository(session).transition(
                started.job.id,
                (JobState.RUNNING, JobState.CANCELLING),
                JobState.CANCELLED,
                now=now,
            ):
                raise ProcessingExecutionError("the processing job changed while cancelling")

    def _input(
        self,
        session: Session,
        started: StartedProcessingJob,
        *,
        allow_cancelling: bool = False,
        allow_pausing: bool = False,
    ) -> _Input:
        if started.job.processing_run_id is None:
            raise ProcessingExecutionError("the claimed job has no processing run")
        actual = session.execute(
            select(ProcessingRun, ProcessingConfigurationSnapshot, Source, Artifact)
            .join(
                ProcessingConfigurationSnapshot,
                ProcessingConfigurationSnapshot.id == ProcessingRun.configuration_snapshot_id,
            )
            .join(Source, Source.id == ProcessingRun.source_id)
            .join(Artifact, Artifact.id == Source.original_artifact_id)
            .where(ProcessingRun.id == started.job.processing_run_id)
        ).one_or_none()
        if actual is None:
            raise ProcessingExecutionError("the processing run/source/original is missing")
        run, snapshot, source, artifact = actual
        if run.state not in (
            (ProcessingRunState.RUNNING,)
            + ((ProcessingRunState.CANCELLING,) if allow_cancelling else ())
            + ((ProcessingRunState.PAUSING,) if allow_pausing else ())
        ):
            raise ProcessingExecutionError(f"the processing run is {run.state}, not RUNNING")
        if (
            source.kind not in (SourceKind.IMAGE, SourceKind.VIDEO)
            or source.state != SourceState.ACTIVE
        ):
            raise ProcessingExecutionError("the source is no longer an active image or video")
        if artifact.state != ArtifactState.AVAILABLE:
            raise ProcessingExecutionError("the source original is not available")
        return _Input(
            run.source_id,
            run.id,
            snapshot.canonical_json,
            artifact.storage_mode,
            artifact.storage_key,
            artifact.external_path,
            run.supersedes_run_id,
            source.kind,
            source.width,
            source.height,
            None
            if source.frame_rate_num is None or source.frame_rate_den is None
            else (source.frame_rate_num, source.frame_rate_den),
            source.media_duration_ms,
        )

    def _revalidate_settlement_context(
        self,
        session: Session,
        source: _Input,
        started: StartedProcessingJob,
        *,
        allow_cancelling: bool = False,
        allow_pausing: bool = False,
    ) -> tuple[ProcessingRun, ExecutionSegment, Job]:
        """Reload every mutable owner immediately before a private-output mutation.

        Compute runs outside a transaction, so its source/artifact may be recycled or become
        unavailable and its claim may be cancelled or reassigned while the worker is running.  A
        write UnitOfWork already owns SQLite's writer lock; the fresh reads below are therefore the
        state that the following settlement mutation protects, not cached pre-compute state.
        """
        current = self._input(
            session, started, allow_cancelling=allow_cancelling, allow_pausing=allow_pausing
        )
        run = ProcessingRunRepository(session).lock(current.run_id)
        assert run is not None  # _input just reloaded the same run in this write transaction
        segment = SegmentRepository(session).get(started.execution_segment_id)
        if (
            segment is None
            or segment.processing_run_id != current.run_id
            or segment.state != ExecutionSegmentState.RUNNING
        ):
            raise ProcessingExecutionError("the execution segment is no longer running")
        job = JobRepository(session).get(started.job.id)
        if (
            job is None
            or job.processing_run_id != current.run_id
            or job.state
            not in (
                (JobState.RUNNING,)
                + ((JobState.CANCELLING,) if allow_cancelling else ())
                + ((JobState.PAUSING,) if allow_pausing else ())
            )
        ):
            raise ProcessingExecutionError("the processing job is no longer running")
        return run, segment, job

    def _plan(self, session: Session, frozen: _FrozenConfiguration) -> PerceptionPlan:
        return self._planner(
            session,
            self._packages,
            detector_component_version_id=frozen.detector_component_version_id,
            detector_model_export_id=frozen.detector_export_id,
            embedder_model_export_id=frozen.embedder_export_id,
            representation_space_id=frozen.representation_space_id,
            providers=frozen.providers,
        )

    def _read_original(self, source: _Input) -> bytes:
        if source.storage_mode == StorageMode.MANAGED:
            if source.storage_key is None:
                raise ProcessingExecutionError("a managed original has no storage key")
            with self._files.open(source.storage_key) as stream:
                return stream.read()
        if source.storage_mode == StorageMode.REFERENCED:
            if source.external_path is None:
                raise ProcessingExecutionError("a referenced original has no path")
            return Path(source.external_path).read_bytes()
        raise ProcessingExecutionError(f"unknown source storage mode {source.storage_mode!r}")

    def _advance_after_fallbacks(
        self,
        source: _Input,
        started: StartedProcessingJob,
        fallbacks: tuple[ProviderFallback, ...],
    ) -> StartedProcessingJob:
        """Close an actual provider attempt and continue under the variant that ran.

        A detector-to-embedder transition alone stays within an interval.  The client emits these
        records only after its narrow provider-unavailable policy has moved to a later variant, so
        every new segment describes a real execution-environment change rather than pipeline
        progress.
        """
        if not fallbacks:
            return started
        segment_id = self._uow.write(
            lambda session: self._record_provider_fallbacks(session, source, started, fallbacks)
        )
        return replace(started, execution_segment_id=segment_id)

    def _record_provider_fallbacks(
        self,
        session: Session,
        source: _Input,
        started: StartedProcessingJob,
        fallbacks: tuple[ProviderFallback, ...],
    ) -> uuid.UUID:
        run, segment, _job = self._revalidate_settlement_context(
            session, source, started, allow_cancelling=True, allow_pausing=True
        )
        repository = SegmentRepository(session)
        current = segment
        for fallback in fallbacks:
            if not repository.close(
                current.id,
                ExecutionSegmentState.COMPLETED,
                reason="FALLBACK",
                now=self._clock(),
            ):
                raise ProcessingExecutionError("the execution segment could not close for fallback")
            current = repository.append(
                run.id,
                segment_id=self._new_id(),
                runtime_variant_id=fallback.selected.runtime_variant_id,
                runtime_details={
                    "schema_version": 1,
                    "transition": "PROVIDER_FALLBACK",
                    "failed_attempts": [
                        {
                            "variant_id": str(attempt.variant.runtime_variant_id),
                            "provider": attempt.variant.provider,
                            "error_code": attempt.code.value,
                            "error_message": attempt.message,
                        }
                        for attempt in fallback.failed
                    ],
                    "selected_variant_id": str(fallback.selected.runtime_variant_id),
                    "selected_provider": fallback.selected.provider,
                },
                now=self._clock(),
            )
        return current.id

    def _settle_detections(
        self,
        session: Session,
        source: _Input,
        started: StartedProcessingJob,
        detected: Detected,
    ) -> list[uuid.UUID]:
        self._revalidate_settlement_context(session, source, started)
        ids: list[uuid.UUID] = []
        for sequence, detection in enumerate(detected.detections):
            ids.append(
                write_observation(
                    session,
                    source_id=source.source_id,
                    processing_run_id=source.run_id,
                    execution_segment_id=started.execution_segment_id,
                    sequence_in_run=sequence,
                    detection=detection,
                    detector=detected.ran,
                    new_id=self._new_id,
                    now=self._clock(),
                ).observation_id
            )
        return ids

    def _settle_representations(
        self,
        session: Session,
        source: _Input,
        started: StartedProcessingJob,
        frozen: _FrozenConfiguration,
        detected: Detected,
        observations: list[uuid.UUID],
        represented: Represented,
    ) -> list[uuid.UUID]:
        if not detected.detections:
            if represented.vectors or represented.ran is not None:
                raise ProcessingExecutionError("a no-face result was unexpectedly represented")
            self._revalidate_settlement_context(session, source, started)
            return []
        if represented.ran is None or len(represented.vectors) != len(observations):
            raise ProcessingExecutionError("the embedder did not settle every detected face")
        self._revalidate_settlement_context(session, source, started)
        ids: list[uuid.UUID] = []
        for detection, observation_id, vector in zip(
            detected.detections, observations, represented.vectors, strict=True
        ):
            ids.append(
                write_representation(
                    session,
                    observation_id=observation_id,
                    execution_segment_id=started.execution_segment_id,
                    detection_index=detection.detection_index,
                    vector=vector,
                    embedder=represented.ran,
                    representation_space_id=frozen.representation_space_id,
                    new_id=self._new_id,
                    now=self._clock(),
                ).representation_id
            )
        return ids

    def _checkpoint_private_output(
        self,
        source: _Input,
        started: StartedProcessingJob,
        observations: list[uuid.UUID],
        representations: list[uuid.UUID],
    ) -> uuid.UUID:
        """Record the durable, private perception boundary before identity reasoning."""
        return self._uow.write(
            lambda session: self._append_private_output_checkpoint(
                session, source, started, observations, representations
            )
        )

    def _append_private_output_checkpoint(
        self,
        session: Session,
        source: _Input,
        started: StartedProcessingJob,
        observations: list[uuid.UUID],
        representations: list[uuid.UUID],
    ) -> uuid.UUID:
        run, segment, _job = self._revalidate_settlement_context(session, source, started)
        checkpoint = CheckpointRepository(session).append(
            run.id,
            checkpoint_id=self._new_id(),
            segment_id=segment.id,
            kind=CheckpointKind.INTERMEDIATE,
            payload_schema_version=CHECKPOINT_SCHEMA_VERSION,
            payload={
                "schema_version": CHECKPOINT_SCHEMA_VERSION,
                "observations": [str(identifier) for identifier in observations],
                "representations": [str(identifier) for identifier in representations],
            },
            now=self._clock(),
        )
        self._point_run_at(session, run, checkpoint.id)
        return checkpoint.id

    def _point_run_at(self, session: Session, run: ProcessingRun, checkpoint_id: uuid.UUID) -> None:
        changed = optimistic_locked_update(
            session,
            ProcessingRun,
            run.id,
            expected_revision=run.revision,
            values={"current_checkpoint_id": checkpoint_id, "updated_at": self._clock()},
            extra_where=(
                ProcessingRun.state.in_((ProcessingRunState.RUNNING, ProcessingRunState.PAUSING)),
            ),
        )
        if changed != 1:
            raise ProcessingExecutionError("the processing run changed while checkpointing")

    # --- video (M6 steps 4 and 5) -------------------------------------------------------------

    def _execute_video(
        self,
        started: StartedProcessingJob,
        source: _Input,
        frozen: "_FrozenConfiguration",
        plan: PerceptionPlan,
        cancelled: Callable[[], bool],
    ) -> ExecutedProcessingJob:
        if self._video_tools is None or source.width is None or source.height is None:
            raise ProcessingExecutionError("video processing is not configured or has no size")
        width, height = frame_size(source.width, source.height, self._video.max_side)
        if width * height > self._max_pixels:
            raise ProcessingExecutionError("the video's frames have more pixels than allowed")
        client = self._client_for(plan)
        if not isinstance(client, _VideoPerception):
            raise ProcessingExecutionError("this perception cannot process a video")
        resume = self._uow.read(lambda session: resume_point(session, source.run_id))
        tracker = Tracker(state=resume.tracker)
        frames = sampled_frames(
            self._video_tools(),
            self._original_path(source),
            width=source.width,
            height=source.height,
            rate=self._video.rate,
            after_slot=resume.slot,
            max_side=self._video.max_side,
        )
        sequence = resume.sequence
        with closing(frames):
            for chunk in batched(frames, self._video.chunk_frames):
                started, sequence, tracker = self._video_chunk(
                    started, source, frozen, client, cancelled, tracker, chunk, sequence
                )
        self._pause_if_requested(started)  # (a pause asked after the last chunk: none to finish)
        observations, representations = self._uow.read(
            lambda session: _run_output(session, source.run_id)
        )
        tracks = self._uow.read(lambda session: video_tracks(session, source.run_id))
        decisions = _settle_tracks(self._decide(source, frozen, representations), tracks)
        decisions = self._uow.write(
            lambda session: self._persist_decisions(session, source, started, decisions)
        )
        self._cancel_if_requested(started)
        checkpoint = self._uow.write(
            lambda session: self._finalize(
                session, source, started, observations, decisions, tracks=tracks
            )
        )
        return ExecutedProcessingJob(
            source.run_id,
            checkpoint,
            tuple(observations),
            tuple(decision.representation_id for decision in decisions),
        )

    def _original_path(self, source: _Input) -> Path:
        # (one location form per storage mode: the artifacts table's `location` constraint)
        path = (
            self._files.roots.path_for(str(source.storage_key))
            if source.storage_mode == StorageMode.MANAGED
            else Path(str(source.external_path))
        )
        if not path.is_file():
            raise BytesMissingError(f"the original of {source.source_id} is missing")
        return path

    def _video_chunk(
        self,
        started: StartedProcessingJob,
        source: _Input,
        frozen: "_FrozenConfiguration",
        client: _VideoPerception,
        cancelled: Callable[[], bool],
        tracker: Tracker,
        chunk: tuple[Frame, ...],
        sequence: int,
    ) -> tuple[StartedProcessingJob, int, Tracker]:
        """Detect, track, select, embed and settle one chunk. Returns the claim (advanced past any
        provider fallback), the next observation's sequence and the tracker after the chunk.

        A provider that falls back part way through a chunk starts a new execution segment; the
        chunk is then done again from its first frame under the variant that now runs (with the
        tracker as it was before the chunk), so every row it settles names the segment that
        produced it. A fallback is rare and a chunk is ten seconds of video."""
        before = tracker.state()
        while True:
            segment = started.execution_segment_id
            started, found = self._chunk_work(
                started, source, frozen, client, cancelled, tracker, chunk
            )
            if started.execution_segment_id == segment:
                break
            tracker = Tracker(state=before)
        current = started
        sequence = self._uow.write(
            lambda session: self._settle_chunk(
                session, source, current, frozen, chunk, found, sequence, tracker
            )
        )
        self._cancel_if_requested(started)
        self._pause_if_requested(started)
        return started, sequence, tracker

    def _chunk_work(
        self,
        started: StartedProcessingJob,
        source: _Input,
        frozen: "_FrozenConfiguration",
        client: _VideoPerception,
        cancelled: Callable[[], bool],
        tracker: Tracker,
        chunk: tuple[Frame, ...],
    ) -> tuple[StartedProcessingJob, Any]:
        detected: list[Detected] = []
        for batch in batched(chunk, self._video.frames_per_turn):
            with cancellable(cancelled), client.turn():
                results = [client.detect(frame.pixels) for frame in batch]
            for result in results:
                started = self._advance_after_fallbacks(source, started, result.fallbacks)
            detected.extend(results)
            self._cancel_if_requested(started)
        spans: dict[int, list[int]] = {}
        candidates: list[Candidate] = []
        for position, (frame, result) in enumerate(zip(chunk, detected, strict=True)):
            index = frame_index(frame.timestamp_ms, frame.slot, source.frame_rate)
            boxes = [detection.box for detection in result.detections]
            points = [detection.landmarks for detection in result.detections]
            for detection, track in zip(
                result.detections, tracker.update(frame.slot, boxes, points), strict=True
            ):
                span = spans.setdefault(track, [frame.timestamp_ms, 0, index, 0])
                span[1], span[3] = frame.timestamp_ms, index
                candidates.append(
                    Candidate(
                        track,
                        detection.score,
                        detection.box,
                        (position, detection),
                        detection.landmarks,
                        frame.slot,
                    )
                )
        kept = select_kept(
            candidates,
            keep=self._video.keep_per_track,
            min_score=frozen.decision_policy.min_detection_score,
            room=lambda track: tracker.room(track, self._video.max_per_track),
        )
        for candidate in kept:
            tracker.kept(candidate.track)
        faces: dict[int, list[tuple[int, Any]]] = {}
        for candidate in sorted(kept, key=lambda c: (c.key[0], c.key[1].detection_index)):
            faces.setdefault(candidate.key[0], []).append((candidate.track, candidate.key[1]))
        represented: dict[int, Represented] = {}
        for pairs in batched(faces.items(), self._video.frames_per_turn):
            with cancellable(cancelled), client.turn():
                embedded = [
                    client.represent(chunk[position].pixels, tuple(d for _t, d in found))
                    for position, found in pairs
                ]
            for (position, _found), vectors in zip(pairs, embedded, strict=True):
                started = self._advance_after_fallbacks(source, started, vectors.fallbacks)
                represented[position] = vectors
            self._cancel_if_requested(started)
        return started, (detected, faces, represented, spans)

    def _pause_if_requested(self, started: StartedProcessingJob) -> None:
        """At a chunk boundary (its checkpoint written): settle a requested pause `PAUSED`."""
        if self._uow.write(lambda session: self._pause(session, started)):
            raise ProcessingPausedError("the video run was paused")

    def _pause(self, session: Session, started: StartedProcessingJob) -> bool:
        run = ProcessingRunRepository(session).lock(started.job.processing_run_id)  # type: ignore[arg-type]
        job = JobRepository(session).get(started.job.id)
        if run is None or job is None or run.state != ProcessingRunState.PAUSING:
            return False
        now = self._clock()
        if job.state != JobState.PAUSING or not SegmentRepository(session).close(
            # (a pause ends the segment normally, at a checkpoint; the run says it is PAUSED)
            started.execution_segment_id,
            ExecutionSegmentState.COMPLETED,
            reason="NORMAL",
            now=now,
        ):
            raise ProcessingExecutionError("the paused job or its segment changed")
        optimistic_locked_update(
            session,
            ProcessingRun,
            run.id,
            expected_revision=run.revision,
            values={"state": ProcessingRunState.PAUSED, "updated_at": now},
        )
        JobRepository(session).transition(job.id, (JobState.PAUSING,), JobState.PAUSED, now=now)
        return True

    def _settle_chunk(
        self,
        session: Session,
        source: _Input,
        started: StartedProcessingJob,
        frozen: "_FrozenConfiguration",
        chunk: tuple[Frame, ...],
        found: tuple[
            list[Detected], dict[int, list[tuple[int, Any]]], dict[int, Represented],
            dict[int, list[int]],
        ],
        sequence: int,
        tracker: Tracker,
    ) -> int:  # fmt: skip
        detected, faces, represented, spans = found
        run, segment, _job = self._revalidate_settlement_context(
            session, source, started, allow_pausing=True
        )
        kept: list[tuple[uuid.UUID, int]] = []
        for position, pairs in faces.items():
            frame, result = chunk[position], represented[position]
            if result.ran is None or len(result.vectors) != len(pairs):
                raise ProcessingExecutionError("the embedder did not settle every selected face")
            index = frame_index(frame.timestamp_ms, frame.slot, source.frame_rate)
            for (track, detection), vector in zip(pairs, result.vectors, strict=True):
                observation_id = write_observation(
                    session,
                    source_id=source.source_id,
                    processing_run_id=source.run_id,
                    execution_segment_id=started.execution_segment_id,
                    sequence_in_run=sequence,
                    detection=detection,
                    detector=detected[position].ran,
                    new_id=self._new_id,
                    now=self._clock(),
                    frame_index=index,
                    timestamp_ms=frame.timestamp_ms,
                ).observation_id
                write_representation(
                    session,
                    observation_id=observation_id,
                    execution_segment_id=started.execution_segment_id,
                    detection_index=detection.detection_index,
                    vector=vector,
                    embedder=result.ran,
                    representation_space_id=frozen.representation_space_id,
                    new_id=self._new_id,
                    now=self._clock(),
                )
                kept.append((observation_id, track))
                sequence += 1
        checkpoint = CheckpointRepository(session).append(
            run.id,
            checkpoint_id=self._new_id(),
            segment_id=segment.id,
            kind=CheckpointKind.INTERMEDIATE,
            payload_schema_version=CHECKPOINT_SCHEMA_VERSION,
            payload=chunk_payload(
                slot=chunk[-1].slot,
                sequence=sequence,
                tracker=tracker.state(),
                spans=spans,
                observations=kept,
            ),
            now=self._clock(),
        )
        self._point_run_at(session, run, checkpoint.id)
        # Progress in sampled slots of the whole video (API 17), for the screen's bar and ETA.
        done = chunk[-1].slot + 1
        total = math.ceil((source.duration_ms or 0) / 1000 * self._video.rate)
        JobRepository(session).set_progress(
            started.job.id, completed=done, total=max(done, total), now=self._clock()
        )
        return sequence

    def _decide(
        self, source: _Input, frozen: _FrozenConfiguration, representations: list[uuid.UUID]
    ) -> list[_Decision]:
        if not representations:
            return []
        global_index = self._global_index_for(frozen.representation_space_id)

        def decide(session: Session) -> list[_Decision]:
            space = session.get(RepresentationSpace, frozen.representation_space_id)
            if space is None or space.dimension != frozen.dimension:
                raise ProcessingExecutionError("the frozen representation space is no longer valid")
            run_local = rebuild_run_local_index(
                session,
                processing_run_id=source.run_id,
                representation_space_id=space.id,
                dimension=space.dimension,
                metric="cos",
            )
            rows = session.execute(
                select(Representation, Observation)
                .join(Observation, Observation.id == Representation.observation_id)
                .where(Representation.id.in_(representations))
                .order_by(Observation.sequence_in_run)
            ).all()
            if len(rows) != len(representations):
                raise ProcessingExecutionError(
                    "a settled representation disappeared before recognition"
                )
            # A generation is never evidence for its successor (persistence 12.1 item 3): the faces
            # of the generation a reprocess run replaces are left out of its candidates.
            predecessor = (
                []
                if source.supersedes_run_id is None
                else list(
                    session.scalars(
                        select(Representation.id).where(
                            Representation.processing_run_id == source.supersedes_run_id,
                            Representation.representation_space_id == space.id,
                        )
                    )
                )
            )
            result: list[_Decision] = []
            for representation, observation in rows:
                assert representation.vector is not None  # PENDING rows retain their vector
                vector = np.frombuffer(representation.vector, dtype="<f4")
                assessment = self._recognition.assess(
                    session,
                    representation_space_id=space.id,
                    dimension=space.dimension,
                    vector=vector,
                    quality=ObservationQuality(observation.quality_json["detection_score"]),
                    global_index=global_index,
                    processing_run_id=source.run_id,
                    run_local=run_local,
                    exclude=[*representations, *predecessor],
                )
                result.append(
                    _Decision(
                        observation.id,
                        representation.id,
                        IdentityReasoner(frozen.decision_policy).decide(assessment),
                        None,
                    )
                )
            return result

        return self._uow.read(decide)

    def _persist_decisions(
        self,
        session: Session,
        source: _Input,
        started: StartedProcessingJob,
        decisions: list[_Decision],
    ) -> list[_Decision]:
        self._revalidate_settlement_context(session, source, started)
        persisted: list[_Decision] = []
        for entry in decisions:
            representation = session.get(Representation, entry.representation_id)
            if representation is None or representation.processing_run_id != source.run_id:
                raise ProcessingExecutionError("a decision representation is no longer this run's")
            if representation.state != "PENDING":
                raise ProcessingExecutionError("a decision representation is no longer private")
            if entry.decision.outcome is RecognitionOutcome.CREATE_NEW:
                created_identity = create_pending_identity(
                    session,
                    new_id=self._new_id,
                    clock=self._clock,
                    created_by_processing_run_id=source.run_id,
                    representative_observation_id=entry.observation_id,
                )
                representation.identity_id = created_identity.id
                persisted.append(
                    _Decision(
                        entry.observation_id,
                        entry.representation_id,
                        entry.decision,
                        created_identity.id,
                    )
                )
            elif entry.decision.outcome is RecognitionOutcome.MATCH_EXISTING:
                identity_id = entry.decision.identity_id
                identity: Identity | None = (
                    session.get(Identity, identity_id) if identity_id is not None else None
                )
                if identity is None or identity.state != IdentityState.ACTIVE:
                    raise ProcessingExecutionError("the matched identity is no longer ACTIVE")
                representation.identity_id = identity.id
                persisted.append(
                    _Decision(
                        entry.observation_id, entry.representation_id, entry.decision, identity.id
                    )
                )
            else:
                persisted.append(entry)
        return persisted

    def _finalize(
        self,
        session: Session,
        source: _Input,
        started: StartedProcessingJob,
        observations: list[uuid.UUID],
        decisions: list[_Decision],
        *,
        tracks: list[dict[str, Any]] | None = None,
    ) -> uuid.UUID:
        run, segment, _job = self._revalidate_settlement_context(session, source, started)
        payload: dict[str, Any] = {
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "observations": [str(identifier) for identifier in observations],
            "decisions": [
                {
                    "observation_id": str(entry.observation_id),
                    "representation_id": str(entry.representation_id),
                    "outcome": entry.decision.outcome.value,
                    "reason": entry.decision.reason.value,
                    "identity_id": None if entry.identity_id is None else str(entry.identity_id),
                    # CREATE_NEW receives its durable pending identity only after reasoning.
                    # FINAL evidence must record that resolved result, not the proposal's null id.
                    "evidence": {
                        **entry.decision.evidence_payload(),
                        "identity_id": None
                        if entry.identity_id is None
                        else str(entry.identity_id),
                        **_proposal(entry),
                    },
                }
                for entry in decisions
            ],
        }
        if tracks is not None:  # a video's tracks, for its occurrences over time (step 6)
            payload["tracks"] = tracks
        checkpoint = CheckpointRepository(session).append(
            run.id,
            checkpoint_id=self._new_id(),
            segment_id=segment.id,
            kind=CheckpointKind.FINAL,
            payload_schema_version=CHECKPOINT_SCHEMA_VERSION,
            payload=payload,
            now=self._clock(),
        )
        if not SegmentRepository(session).close(
            segment.id, "COMPLETED", reason="NORMAL", now=self._clock()
        ):
            raise ProcessingExecutionError("the execution segment could not close")
        changed = optimistic_locked_update(
            session,
            ProcessingRun,
            run.id,
            expected_revision=run.revision,
            values={
                "state": ProcessingRunState.FINALIZING,
                "current_checkpoint_id": checkpoint.id,
                "updated_at": self._clock(),
            },
            extra_where=(ProcessingRun.state == ProcessingRunState.RUNNING,),
        )
        if changed != 1:
            raise ProcessingExecutionError("the processing run changed while finalizing")
        return checkpoint.id

    def _fail(self, started: StartedProcessingJob, code: str) -> None:
        """Best-effort durable failure after a known external failure; never hides the cause."""

        def settle(session: Session) -> None:
            now = self._clock()
            settled = False
            if started.job.processing_run_id is not None:
                run = ProcessingRunRepository(session).lock(started.job.processing_run_id)
                job = JobRepository(session).get(started.job.id)
                if (
                    run is not None
                    and job is not None
                    and job.processing_run_id == run.id
                    and job.state == JobState.RUNNING
                ):
                    segment = SegmentRepository(session).get(started.execution_segment_id)
                    closed = (
                        segment is not None
                        and segment.processing_run_id == run.id
                        and SegmentRepository(session).close(
                            segment.id, "FAILED", reason=None, now=now
                        )
                    )
                    if closed and run.state == ProcessingRunState.RUNNING:
                        settled = (
                            optimistic_locked_update(
                                session,
                                ProcessingRun,
                                run.id,
                                expected_revision=run.revision,
                                values={
                                    "state": ProcessingRunState.FAILED,
                                    "failed_at": now,
                                    "updated_at": now,
                                    "failure_code": code,
                                    "failure_detail": "source processing failed",
                                },
                                extra_where=(ProcessingRun.state == ProcessingRunState.RUNNING,),
                            )
                            == 1
                        )
            if settled:
                if not JobRepository(session).transition(
                    started.job.id,
                    (JobState.RUNNING,),
                    JobState.FAILED,
                    now=now,
                    failure_code=code,
                    failure_detail="source processing failed",
                ):
                    raise ProcessingExecutionError("the processing job changed while failing")

        try:
            self._uow.write(settle)
        except ProcessingExecutionError:
            # A failed post-lock transition rolls back the entire short settlement. The original
            # external error remains the caller's failure; startup recovery owns this live claim.
            return


def snapshot_runnable(
    packages: RuntimePackageStore, planner: PerceptionPlanner
) -> Callable[[Session, ProcessingRun], bool]:
    """Whether a run's frozen snapshot can still be planned with what is installed (M6 D10: a
    video run is resumed only then)."""

    def runnable(session: Session, run: ProcessingRun) -> bool:
        snapshot = session.get(ProcessingConfigurationSnapshot, run.configuration_snapshot_id)
        try:
            frozen = _frozen(None if snapshot is None else snapshot.canonical_json)
            planner(
                session,
                packages,
                detector_component_version_id=frozen.detector_component_version_id,
                detector_model_export_id=frozen.detector_export_id,
                embedder_model_export_id=frozen.embedder_export_id,
                representation_space_id=frozen.representation_space_id,
                providers=frozen.providers,
            )
        except (ProcessingExecutionError, RuntimeUnavailableError):
            return False
        return True

    return runnable


def _settle_tracks(decisions: list[_Decision], tracks: list[dict[str, Any]]) -> list[_Decision]:
    """M6 D7: a track's faces keep their matches only when every one matched the same identity;
    otherwise each abstains (`TRACK_UNSETTLED`), its own proposal kept. A video never creates an
    identity automatically: an unknown track is left for the person to name."""
    by_observation = {str(entry.observation_id): entry for entry in decisions}
    unsettled: set[str] = set()
    for track in tracks:
        faces = [by_observation[observation] for observation in track["observations"]]
        if agreed_identity([(f.decision.outcome, f.decision.identity_id) for f in faces]) is None:
            unsettled.update(track["observations"])
    return [
        replace(
            entry,
            decision=replace(
                entry.decision,
                outcome=RecognitionOutcome.ABSTAIN,
                reason=Reason.TRACK_UNSETTLED,
                identity_id=None,
            ),
            proposal=entry.decision,
        )
        if str(entry.observation_id) in unsettled
        else entry
        for entry in decisions
    ]


def _proposal(entry: _Decision) -> dict[str, Any]:
    if entry.proposal is None:
        return {}
    proposed = entry.proposal
    return {
        "proposal": {
            "outcome": proposed.outcome.value,
            "reason": proposed.reason.value,
            "identity_id": None if proposed.identity_id is None else str(proposed.identity_id),
        }
    }


def _run_output(session: Session, run_id: uuid.UUID) -> tuple[list[uuid.UUID], list[uuid.UUID]]:
    """A video run's observations and their representations, in sequence order."""
    rows = session.execute(
        select(Observation.id, Representation.id)
        .join(Representation, Representation.observation_id == Observation.id)
        .where(Observation.processing_run_id == run_id)
        .order_by(Observation.sequence_in_run)
    ).all()
    return [row[0] for row in rows], [row[1] for row in rows]


def _frozen(value: object) -> _FrozenConfiguration:
    """Read only the exact snapshot shape execution needs; corrupt historical JSON fails closed."""
    try:
        root = _object(value, "snapshot")
        if root["schema_version"] != 1:
            raise ProcessingExecutionError("the snapshot schema is unsupported")
        detector = _object(root["detector"], "snapshot.detector")
        embedder = _object(root["embedder"], "snapshot.embedder")
        space = _object(root["representation_space"], "snapshot.representation_space")
        policy = _object(root["runtime_policy"], "snapshot.runtime_policy")
        decision = _object(root["decision_policy"], "snapshot.decision_policy")
        providers = policy["providers"]
        if (
            not isinstance(providers, list)
            or not providers
            or any(not isinstance(p, str) for p in providers)
        ):
            raise ProcessingExecutionError("the snapshot runtime providers are invalid")
        return _FrozenConfiguration(
            _uuid(
                _object(detector["component_version"], "snapshot.detector.component_version")["id"]
            ),
            _uuid(_object(detector["export"], "snapshot.detector.export")["id"]),
            _uuid(_object(embedder["export"], "snapshot.embedder.export")["id"]),
            _uuid(space["id"]),
            _int(space["dimension"], "snapshot.representation_space.dimension"),
            tuple(providers),
            DecisionPolicy(
                _string(decision["version"]),
                _number(decision["min_detection_score"]),
                _number(decision["match_threshold"]),
                _number(decision["margin"]),
                _number(decision["new_identity_ceiling"]),
            ),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ProcessingExecutionError("the frozen processing snapshot is malformed") from error


def _object(value: object, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProcessingExecutionError(f"{path} is not an object")
    return value


def _uuid(value: object) -> uuid.UUID:
    if not isinstance(value, str):
        raise ProcessingExecutionError("a frozen id is not a UUID string")
    try:
        return uuid.UUID(value)
    except ValueError as error:
        raise ProcessingExecutionError("a frozen id is not a UUID string") from error


def _int(value: object, path: str) -> int:
    if type(value) is not int or value < 1:
        raise ProcessingExecutionError(f"{path} is not positive")
    return value


def _string(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ProcessingExecutionError("a frozen string is blank")
    return value


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProcessingExecutionError("a frozen number is invalid")
    return float(value)
