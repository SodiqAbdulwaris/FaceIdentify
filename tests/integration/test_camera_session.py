"""A live camera session on the real pipeline (M7 step 4; plan C2 to C8; TST-071, TST-072,
TST-075, TST-076 live half).

Planted perception (painted squares, no model) and scripted frames (no camera): a known person's
visit becomes one TRACK occurrence on the camera from its first to its last moment, accepted while
the session runs; an unknown person's faces stay unplaced and create nothing; at most three faces
per encounter are kept, each as a face crop; a gap in the stream closes every encounter; the
session ends COMPLETED on a stop and FAILED with the camera's reason when it does not come back.
"""

import uuid
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select

from backend.app.cameras.capture import Gap
from backend.app.cameras.session import (
    CameraBusyError,
    CameraNotConfiguredError,
    CameraSettings,
    running_session,
)
from backend.app.identities.models import Evidence, EvidenceKind, Identity
from backend.app.jobs.models import Job, JobState, JobType
from backend.app.memory.models import (
    Observation,
    ObservationState,
    Occurrence,
    OccurrenceKind,
    Representation,
    RepresentationState,
)
from backend.app.processing.accept_run import AcceptanceError, AcceptProcessingRunUseCase
from backend.app.processing.execute_job import ProcessingExecutionError
from backend.app.processing.models import ExecutionSegment, ProcessingRun
from backend.app.sources.models import Artifact, ArtifactKind, ArtifactState, Source
from backend.infrastructure.media.camera import CameraError, LiveFrame
from backend.ml.supervisor.supervisor import WorkerFailedError
from tests.fixtures.camera_pipeline import Camera, empty, frames, picture, visit
from tests.fixtures.pipeline import Pipeline
from tests.integration.test_video_occurrences import enrol_red

EPOCH_MS = 1_793_000_000_000  # some UTC moment in 2026


def wall_clock() -> Any:
    """UTC that moves 200 ms per reading, like frames at 5 per second."""
    ticks = iter(range(10_000))
    return lambda: (
        datetime.fromtimestamp(EPOCH_MS / 1000, UTC) + timedelta(milliseconds=200 * next(ticks))
    )


@pytest.fixture
def red(pipeline: Pipeline) -> uuid.UUID:
    return enrol_red(pipeline)


@pytest.fixture
def camera(pipeline: Pipeline) -> Camera:
    return Camera(pipeline)


def rows(pipeline: Pipeline, model: Any, *where: Any) -> list[Any]:
    with pipeline.lib.session_factory() as session:
        return list(session.scalars(select(model).where(*where)).all())


def test_a_known_person_s_visit_is_one_occurrence_accepted_while_the_session_runs(
    pipeline: Pipeline, red: uuid.UUID, camera: Camera
) -> None:
    started = camera.start()
    run_id = started.job.processing_run_id
    seen_during: list[int] = []

    def stream() -> Iterator[LiveFrame | Gap]:
        yield from frames(*visit("red", 0, 2), *empty(2, 1.6))
        # (the encounter closed above, before the session ends)
        seen_during.append(len(rows(pipeline, Occurrence, Occurrence.processing_run_id == run_id)))
        with pipeline.lib.session_factory() as session:
            seen_during.append(len(session.scalars(select(ProcessingRun)).all()))

    assert camera.executor(utc_ms=wall_clock()).run(started, stream()) == "STOPPED"

    assert seen_during[0] == 1  # visible while the run was still RUNNING
    (occurrence,) = rows(pipeline, Occurrence, Occurrence.processing_run_id == run_id)
    assert (occurrence.source_id, occurrence.identity_id) == (camera.id, red)
    assert occurrence.kind == OccurrenceKind.TRACK
    assert occurrence.start_timestamp_ms >= EPOCH_MS
    assert occurrence.end_timestamp_ms - occurrence.start_timestamp_ms == 9 * 200  # 10 frames
    faces = rows(pipeline, Observation, Observation.processing_run_id == run_id)
    assert 1 <= len(faces) <= 3  # at most three per encounter (C3)
    assert all(face.state == ObservationState.ACTIVE for face in faces)
    crops = rows(pipeline, Artifact, Artifact.id.in_([f.face_crop_artifact_id for f in faces]))
    assert len(crops) == len(faces)
    assert {(c.kind, c.state, c.mime_type) for c in crops} == {
        (ArtifactKind.FACE_CROP, ArtifactState.AVAILABLE, "image/jpeg")
    }
    for crop in crops:
        assert pipeline.lib.store.digest(crop.storage_key) is not None  # the bytes exist
    assert len(rows(pipeline, Identity)) == 1  # nothing new
    (run,) = rows(pipeline, ProcessingRun, ProcessingRun.id == run_id)
    (job,) = rows(pipeline, Job, Job.id == started.job.id)
    assert (run.state, job.state) == ("COMPLETED", "COMPLETED")
    assert camera.perception.classes  # every request was in the live class
    assert set(camera.perception.classes) == {"detect:LIVE", "represent:LIVE"}


def test_an_unknown_person_creates_nothing_and_stays_unplaced(
    pipeline: Pipeline, red: uuid.UUID, camera: Camera
) -> None:
    camera.run(*visit("green", 0, 1), *empty(1, 1.6))

    assert camera.closed == [None]
    assert len(rows(pipeline, Identity)) == 1
    assert rows(pipeline, Occurrence, Occurrence.source_id == camera.id) == []
    faces = rows(pipeline, Representation, Representation.identity_id.is_(None))
    assert faces
    assert {face.state for face in faces} == {RepresentationState.ACTIVE}
    abstained = rows(pipeline, Evidence, Evidence.kind == EvidenceKind.RECOGNITION_ABSTAINED)
    assert len(abstained) == len(faces)
    assert {e.payload_json["reason"] for e in abstained} == {"TRACK_UNSETTLED"}


def test_two_people_at_once_are_two_encounters(
    pipeline: Pipeline, red: uuid.UUID, camera: Camera
) -> None:
    both = [(n / 5, picture(("red", 10, 40), ("green", 110, 40))) for n in range(5)]
    camera.run(*both, *empty(1, 1.6))

    assert len(camera.closed) == 2
    assert camera.closed.count(None) == 1  # the green one stays unplaced
    occurrences = rows(pipeline, Occurrence, Occurrence.source_id == camera.id)
    assert [o.identity_id for o in occurrences] == [red]


def test_a_gap_in_the_stream_ends_every_encounter(
    pipeline: Pipeline, red: uuid.UUID, camera: Camera
) -> None:
    camera.run(*visit("red", 0, 1), (1.2, None), *visit("red", 1.4, 1))

    assert len(rows(pipeline, Occurrence, Occurrence.source_id == camera.id)) == 2


def test_the_session_ends_with_its_open_encounters_recorded(
    pipeline: Pipeline, red: uuid.UUID, camera: Camera
) -> None:
    camera.run(*visit("red", 0, 1))  # stopped while the person is still there

    assert len(rows(pipeline, Occurrence, Occurrence.source_id == camera.id)) == 1


def test_a_camera_that_does_not_come_back_ends_the_session_failed(
    pipeline: Pipeline, red: uuid.UUID, camera: Camera
) -> None:
    def stream() -> Iterator[LiveFrame | Gap]:
        yield from frames(*visit("red", 0, 1))
        raise CameraError("the camera did not come back within 30 seconds")

    started = camera.start()
    with pytest.raises(CameraError):
        camera.executor().run(started, stream())

    assert len(rows(pipeline, Occurrence, Occurrence.source_id == camera.id)) == 1  # kept
    (job,) = rows(pipeline, Job, Job.id == started.job.id)
    assert (job.state, job.failure_code) == (JobState.FAILED, "CAMERA_DISCONNECTED")


def test_a_worker_failure_ends_the_session_failed(
    pipeline: Pipeline, red: uuid.UUID, camera: Camera
) -> None:
    camera.perception.fail_represent = WorkerFailedError("the worker died")
    started = camera.start()
    with pytest.raises(WorkerFailedError):
        camera.executor().run(started, frames(*visit("red", 0, 1), *empty(1, 1.6)))

    (job,) = rows(pipeline, Job, Job.id == started.job.id)
    assert (job.state, job.failure_code) == (JobState.FAILED, "WorkerFailedError")
    assert rows(pipeline, Observation, Observation.source_id == camera.id) == []


def test_only_one_session_runs_at_a_time(pipeline: Pipeline, camera: Camera) -> None:
    other = Camera(pipeline)
    camera.start()

    with pytest.raises(CameraBusyError) as busy:
        other.start()

    assert busy.value.code == "CAMERA_BUSY"
    with pipeline.lib.session_factory() as session:
        assert running_session(session) == camera.id


def test_only_an_active_camera_can_start(pipeline: Pipeline, camera: Camera) -> None:
    image = pipeline.import_image()
    for not_a_camera in (image, uuid.uuid4()):
        with pytest.raises(CameraNotConfiguredError) as refused:
            camera.start(not_a_camera)
        assert refused.value.code == "CAMERA_NOT_FOUND"
    assert rows(pipeline, Job, Job.type == JobType.PROCESS_CAMERA_SESSION) == []


def test_a_malformed_request_starts_nothing(pipeline: Pipeline, camera: Camera) -> None:
    pipeline.request = {"schema_version": 99}
    with pytest.raises(ProcessingExecutionError):
        camera.start()
    assert rows(pipeline, Job, Job.type == JobType.PROCESS_CAMERA_SESSION) == []


@pytest.mark.parametrize(
    "value",
    [None, {"schema_version": 2}, {"schema_version": 1, "sample_fps": "fast"}],
)
def test_malformed_camera_settings_are_refused(value: object) -> None:
    with pytest.raises(ProcessingExecutionError, match="camera settings"):
        CameraSettings.from_frozen(value)


def test_the_settings_round_trip_through_the_snapshot() -> None:
    settings = CameraSettings(sample_fps=2.5, encounter_gap_seconds=4)
    assert CameraSettings.from_frozen(settings.frozen()) == settings


def test_an_encounter_whose_session_was_stopped_from_outside_is_refused(
    pipeline: Pipeline, red: uuid.UUID, camera: Camera
) -> None:
    started = camera.start()

    def stream() -> Iterator[LiveFrame | Gap]:
        yield from frames(*visit("red", 0, 1))
        with pipeline.lib.session_factory() as session:  # the run ends behind the session's back
            session.get(ProcessingRun, started.job.processing_run_id).state = "FAILED"  # type: ignore[union-attr]
            session.commit()

    with pytest.raises(ProcessingExecutionError):
        camera.executor().run(started, stream())

    assert rows(pipeline, Occurrence, Occurrence.source_id == camera.id) == []


def test_accepting_an_encounter_checks_the_session(
    pipeline: Pipeline, red: uuid.UUID, camera: Camera
) -> None:
    started = camera.start()
    run_id = started.job.processing_run_id
    assert run_id is not None
    accept = AcceptProcessingRunUseCase(
        pipeline.lib.unit_of_work, new_id=pipeline.new_id, clock=pipeline.clock
    )
    track = {"track": 0, "observations": [str(uuid.uuid4())], "start_ms": 0, "end_ms": 0,
             "start_frame": 0, "end_frame": 0}  # fmt: skip

    with pytest.raises(AcceptanceError, match="exactly its faces"):
        pipeline.lib.unit_of_work.write(
            lambda session: accept.accept_encounter(session, run_id, [], track)
        )
    with pytest.raises(AcceptanceError, match="not running"):
        pipeline.lib.unit_of_work.write(
            lambda session: accept.accept_encounter(session, uuid.uuid4(), [], track)
        )
    with pipeline.lib.session_factory() as session:
        session.get(Job, started.job.id).state = JobState.CANCELLING  # type: ignore[union-attr]
        session.commit()
    with pytest.raises(AcceptanceError, match="no longer valid"):
        pipeline.lib.unit_of_work.write(
            lambda session: accept.accept_encounter(session, run_id, [], track)
        )


def test_a_provider_fallback_during_a_session_starts_a_new_segment(
    pipeline: Pipeline, red: uuid.UUID, camera: Camera
) -> None:
    """TST-075 (live half): the CPU takes over mid-session and the session goes on."""
    from backend.app.runtime.perception_client import ProviderFallback, ProviderUnavailable
    from backend.ml.contracts.protocol import MLErrorCode

    failed = ProviderUnavailable(
        pipeline.perception.detector, MLErrorCode.RUNTIME_INITIALIZATION_FAILED, "gone"
    )
    camera.perception.fallbacks = [ProviderFallback((failed,), pipeline.perception.detector)]
    started = camera.start()
    camera.executor().run(started, frames(*visit("red", 0, 1), *empty(1, 1.6)))

    segments = rows(
        pipeline, ExecutionSegment,
        ExecutionSegment.processing_run_id == started.job.processing_run_id,
    )  # fmt: skip
    assert [s.ended_reason for s in segments] == ["FALLBACK", "NORMAL"]
    assert len(rows(pipeline, Occurrence, Occurrence.source_id == camera.id)) == 1
    with pipeline.lib.session_factory() as session:
        faces = session.scalar(
            select(func.count())
            .select_from(Observation)
            .where(Observation.execution_segment_id == segments[1].id)
        )
    assert faces  # the faces after the fallback name the segment that produced them


def test_keeping_no_face_records_nothing(pipeline: Pipeline, red: uuid.UUID) -> None:
    camera = Camera(
        pipeline,
        settings=CameraSettings(sample_fps=5, encounter_gap_seconds=1, keep_per_encounter=0),
    )
    camera.run(*visit("red", 0, 1), *empty(1, 1.6))

    assert camera.closed == [None]
    assert rows(pipeline, Observation, Observation.source_id == camera.id) == []


def test_a_face_the_embedder_did_not_settle_fails_the_session(
    pipeline: Pipeline, red: uuid.UUID, camera: Camera
) -> None:
    camera.perception.drop_vector = True
    started = camera.start()
    with pytest.raises(ProcessingExecutionError, match="did not settle"):
        camera.executor().run(started, frames(*visit("red", 0, 1)))

    (job,) = rows(pipeline, Job, Job.id == started.job.id)
    assert (job.state, job.failure_code) == (JobState.FAILED, "ProcessingExecutionError")


def test_a_session_whose_camera_went_away_fails(pipeline: Pipeline, camera: Camera) -> None:
    started = camera.start()
    with pipeline.lib.session_factory() as session:
        session.get(Source, camera.id).state = "RECYCLED"  # type: ignore[union-attr]
        session.commit()

    with pytest.raises(ProcessingExecutionError, match="no longer an active camera"):
        camera.executor().run(started, frames(*visit("red", 0, 1)))


def test_a_session_without_its_run_fails(pipeline: Pipeline, camera: Camera) -> None:
    started = camera.start()
    lost = replace(started, job=replace(started.job, processing_run_id=uuid.uuid4()))

    with pytest.raises(ProcessingExecutionError, match="run is missing"):
        camera.executor().run(lost, frames())


def test_a_crop_that_cannot_be_written_fails_the_session_and_is_recorded_missing(
    pipeline: Pipeline, red: uuid.UUID, camera: Camera, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = pipeline.lib.store.store
    written: list[str] = []

    def full(key: str, source: Any) -> Any:
        if written:  # the first crop is written, the second is not
            raise OSError("the disk is full")
        written.append(key)
        return real(key, source)

    monkeypatch.setattr(pipeline.lib.store, "store", full)
    started = camera.start()
    with pytest.raises(OSError, match="disk is full"):
        camera.executor().run(started, frames(*visit("red", 0, 1), *empty(1, 1.6)))

    crops = rows(pipeline, Artifact, Artifact.kind == ArtifactKind.FACE_CROP)
    assert len(crops) >= 2
    assert {(c.state, c.failure_code) for c in crops} == {("MISSING", "WRITE_NOT_COMPLETED")}
    assert pipeline.lib.store.digest(written[0]) is None  # the crop already written is gone
    assert rows(pipeline, Observation, Observation.source_id == camera.id) == []


def test_a_fallback_while_embedding_embeds_the_encounter_again_under_the_new_provider(
    pipeline: Pipeline, red: uuid.UUID, camera: Camera
) -> None:
    """TST-075 (live half): every face of the encounter names the segment that produced it."""
    from backend.app.runtime.perception_client import ProviderFallback, ProviderUnavailable
    from backend.ml.contracts.protocol import MLErrorCode

    failed = ProviderUnavailable(
        pipeline.perception.embedder, MLErrorCode.RUNTIME_INITIALIZATION_FAILED, "gone"
    )
    camera.perception.represent_fallbacks = [
        ProviderFallback((failed,), pipeline.perception.embedder)
    ]
    started = camera.start()
    camera.executor().run(started, frames(*visit("red", 0, 2), *empty(2, 1.6)))

    segments = rows(
        pipeline, ExecutionSegment,
        ExecutionSegment.processing_run_id == started.job.processing_run_id,
    )  # fmt: skip
    assert [s.ended_reason for s in segments] == ["FALLBACK", "NORMAL"]
    faces = rows(pipeline, Observation, Observation.source_id == camera.id)
    assert faces
    assert {face.execution_segment_id for face in faces} == {segments[1].id}
    reps = rows(pipeline, Representation, Representation.observation_id.in_([f.id for f in faces]))
    assert {r.execution_segment_id for r in reps} == {segments[1].id}
    assert camera.perception.represented == 2 * len(faces)  # embedded twice: before and after
