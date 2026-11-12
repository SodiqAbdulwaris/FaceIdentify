"""A video job: decode, detect in batches, track, select, embed, checkpoint each chunk (M6 steps
4 and 5; #242; TST-063, TST-065, TST-067, TST-069).

The real executor, lease, decoder and database on a clip of painted squares
(`tests/fixtures/video_pipeline.py`); only perception is painted.
"""

import threading
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select, update

from backend.app.jobs.models import Job, JobState
from backend.app.memory.models import Observation, Representation
from backend.app.processing.accept_run import AcceptProcessingRunUseCase
from backend.app.processing.cancel import (
    CancelError,
    CancelOutcome,
    CancelProcessingUseCase,
    RunNotFoundError,
)
from backend.app.processing.execute_job import (
    ProcessingCancelledError,
    ProcessingExecutionError,
    ProcessingPausedError,
    snapshot_runnable,
)
from backend.app.processing.models import (
    CheckpointKind,
    ProcessingCheckpoint,
    ProcessingRun,
    ProcessingRunState,
)
from backend.app.processing.pause import PauseError, PauseOutcome, PauseProcessingUseCase
from backend.app.processing.repository import SegmentRepository
from backend.app.processing.retry import RetryProcessingUseCase
from backend.app.processing.runner import ProcessingRunner, RunOutcomeKind
from backend.app.processing.scheduler import ProcessingScheduler, StartedProcessingJob
from backend.app.runtime.package_store import RuntimePackageStore
from backend.app.runtime.perception_client import Detected, ProviderFallback, ProviderUnavailable
from backend.app.runtime.worker_config import RuntimeUnavailableError
from backend.app.sources.models import Source
from backend.infrastructure.media.video import CorruptVideoError
from backend.infrastructure.storage.files import BytesMissingError
from backend.ml.contracts.protocol import MLErrorCode
from backend.ml.supervisor.lease import interactive
from tests.fixtures.pipeline import Pipeline
from tests.fixtures.video_pipeline import (
    PaintedPerception,
    import_video,
    painted_clip,
    video_executor,
    video_perception,
)


class Crash(BaseException):
    """The process was killed here."""


@pytest.fixture
def perception(pipeline: Pipeline) -> PaintedPerception:
    return video_perception(pipeline)


@pytest.fixture
def video(pipeline: Pipeline, tmp_path: Path) -> uuid.UUID:
    return import_video(pipeline, painted_clip(tmp_path / "squares.mp4"))


def claim(pipeline: Pipeline, source_id: uuid.UUID) -> StartedProcessingJob:
    pipeline.enqueue(source_id)
    started = pipeline.scheduler().claim_source_job("worker")
    assert started is not None
    return started


def checkpoints(pipeline: Pipeline, run_id: uuid.UUID) -> list[ProcessingCheckpoint]:
    with pipeline.lib.session_factory() as session:
        return list(
            session.scalars(
                select(ProcessingCheckpoint)
                .where(ProcessingCheckpoint.processing_run_id == run_id)
                .order_by(ProcessingCheckpoint.ordinal)
            )
        )


def observations(pipeline: Pipeline, run_id: uuid.UUID) -> list[Observation]:
    with pipeline.lib.session_factory() as session:
        return list(
            session.scalars(
                select(Observation)
                .where(Observation.processing_run_id == run_id)
                .order_by(Observation.sequence_in_run)
            )
        )


def run_state(pipeline: Pipeline, run_id: uuid.UUID) -> str:
    with pipeline.lib.session_factory() as session:
        run = session.get(ProcessingRun, run_id)
        assert run is not None
        return run.state


def test_a_video_is_processed_chunk_by_chunk_into_tracks(
    pipeline: Pipeline, perception: PaintedPerception, video: uuid.UUID
) -> None:
    started = claim(pipeline, video)

    executed = video_executor(pipeline).execute(started)

    run_id = executed.processing_run_id
    assert run_state(pipeline, run_id) == ProcessingRunState.FINALIZING
    # 3 s at two frames a second: 6 frames, chunks of 4, so two chunk checkpoints and FINAL
    kinds = [c.kind for c in checkpoints(pipeline, run_id)]
    assert kinds == [CheckpointKind.INTERMEDIATE] * 2 + [CheckpointKind.FINAL]
    assert perception.log.count("detect") == 6  # every sampled frame once
    with pipeline.lib.session_factory() as session:
        job = session.get(Job, started.job.id)
        assert job is not None
        assert (job.progress_completed, job.progress_total) == (6, 6)  # slots of the whole video
    final = checkpoints(pipeline, run_id)[-1].payload_json
    tracks = {t["track"]: t for t in final["tracks"]}
    red, green = tracks[0], tracks[1]
    assert (red["start_ms"], red["end_ms"]) == (0, 2520)  # the whole clip, 25 fps frame times
    assert (green["start_ms"], green["end_ms"]) == (1000, 2520)  # from one second on
    assert (red["start_frame"], red["end_frame"]) == (0, 63)
    # at most three kept per track and chunk, recorded with frame and time; only those embedded
    kept = observations(pipeline, run_id)
    assert (
        len(kept)
        == len(red["observations"]) + len(green["observations"])
        == len(executed.representation_ids)
    )
    assert all(o.frame_index is not None and o.timestamp_ms is not None for o in kept)
    assert len(red["observations"]) <= 6
    assert len(green["observations"]) <= 6
    assert {str(o.id) for o in kept} == set(red["observations"]) | set(green["observations"])


def test_a_video_never_builds_a_run_local_index(
    pipeline: Pipeline, perception: PaintedPerception, video: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    """Every face of the video is excluded from its own candidates, so a run-local index could
    only ever hold excluded faces; building one per face made a long video quadratic (D8)."""
    built: list[object] = []
    monkeypatch.setattr(
        "backend.app.processing.execute_job.rebuild_run_local_index",
        lambda *args, **kwargs: built.append(args),
    )

    executed = video_executor(pipeline).execute(claim(pipeline, video))

    assert run_state(pipeline, executed.processing_run_id) == ProcessingRunState.FINALIZING
    assert executed.representation_ids  # faces were recognised...
    assert built == []  # ...without one


def test_each_batch_of_frames_takes_one_turn_on_the_worker(
    pipeline: Pipeline, perception: PaintedPerception, video: uuid.UUID
) -> None:
    video_executor(pipeline, chunk_frames=4, frames_per_turn=2).execute(claim(pipeline, video))

    detect_turns = [
        perception.log[i + 1 : i + 3]
        for i, entry in enumerate(perception.log)
        if entry == "turn" and perception.log[i + 1] == "detect"
    ]
    assert len(detect_turns) == 3  # frames 1-2, 3-4 (chunk one) and 5-6 (chunk two)
    assert all(turn == ["detect", "detect"] for turn in detect_turns)


def test_a_search_waits_for_at_most_one_batch(
    pipeline: Pipeline, perception: PaintedPerception, video: uuid.UUID
) -> None:
    started = claim(pipeline, video)
    inside_first_batch = threading.Event()
    order: list[str] = []

    def on_detect(number: int) -> None:
        order.append(f"frame {number}")
        if number == 1:  # hold the first batch until the search is queued behind it
            inside_first_batch.set()
            waited = threading.Event()
            for _ in range(1000):
                if perception.lease.queued(True) == 1:
                    break
                waited.wait(0.01)  # (polls a condition; the outcome never depends on timing)
            assert perception.lease.queued(True) == 1

    perception.on_detect = on_detect

    def search() -> None:
        assert inside_first_batch.wait(10)
        with interactive(), perception.lease.held():
            order.append("search")

    thread = threading.Thread(target=search)
    thread.start()
    video_executor(pipeline, frames_per_turn=2).execute(started)
    thread.join()

    assert order.index("search") == order.index("frame 2") + 1  # after the batch, not the run


def test_a_cancellation_is_seen_at_the_next_batch(
    pipeline: Pipeline, perception: PaintedPerception, video: uuid.UUID
) -> None:
    started = claim(pipeline, video)

    def cancel_at(number: int) -> None:
        if number == 3:  # the first frame of chunk one's second batch: cancel while it runs
            with pipeline.lib.session_factory() as session:
                session.execute(
                    update(Job).where(Job.id == started.job.id).values(state=JobState.CANCELLING)
                )
                session.commit()

    perception.on_detect = cancel_at

    with pytest.raises(ProcessingCancelledError):
        video_executor(pipeline, frames_per_turn=2).execute(started)

    run_id = started.job.processing_run_id
    assert run_id is not None
    assert run_state(pipeline, run_id) == ProcessingRunState.CANCELLED
    assert perception.log.count("detect") == 4  # the running batch ended; no batch after it
    assert observations(pipeline, run_id) == []  # chunk one never settled: nothing half-written


def test_a_run_resumed_after_a_crash_does_no_frame_twice(
    pipeline: Pipeline, perception: PaintedPerception, video: uuid.UUID
) -> None:
    started = claim(pipeline, video)
    uninterrupted_detects = 6

    def crash_at(number: int) -> None:
        if number == 5:  # inside chunk two, after chunk one's checkpoint
            raise Crash

    perception.on_detect = crash_at
    with pytest.raises(Crash):
        video_executor(pipeline).execute(started)
    run_id = started.job.processing_run_id
    assert run_id is not None
    first_chunk = observations(pipeline, run_id)
    assert first_chunk
    assert len(checkpoints(pipeline, run_id)) == 1

    perception.on_detect = None
    executed = video_executor(pipeline).execute(started)  # the same claim, resumed

    assert perception.log.count("detect") == uninterrupted_detects + 1  # frame 5 twice only
    resumed = observations(pipeline, run_id)
    assert [o.id for o in resumed[: len(first_chunk)]] == [o.id for o in first_chunk]
    assert len({(o.timestamp_ms, o.bbox_x) for o in resumed}) == len(resumed)  # none twice
    final = checkpoints(pipeline, run_id)[-1].payload_json
    assert {t["track"] for t in final["tracks"]} == {0, 1}  # the tracks crossed the restart
    assert len(executed.representation_ids) == len(resumed)


@pytest.mark.parametrize(
    ("problem", "error"),
    [
        ("no tools", ProcessingExecutionError),
        ("too many pixels", ProcessingExecutionError),
        ("no turn", ProcessingExecutionError),
        ("missing original", BytesMissingError),
        ("damaged original", CorruptVideoError),
        ("a face not embedded", ProcessingExecutionError),
    ],
)
def test_a_video_that_cannot_be_processed_fails_its_run(
    pipeline: Pipeline,
    perception: PaintedPerception,
    video: uuid.UUID,
    problem: str,
    error: type[Exception],
) -> None:
    started = claim(pipeline, video)
    options: dict[str, Any] = {}
    if problem == "no tools":
        options["tools"] = False
    if problem == "too many pixels":
        options["max_pixels"] = 160 * 120 - 1
    if problem == "no turn":
        pipeline.perception = object()  # type: ignore[assignment]
    if problem in ("missing original", "damaged original"):
        with pipeline.lib.session_factory() as session:
            source = session.get(Source, video)
            assert source is not None
            assert source.original_artifact_id is not None
            path = pipeline.lib.store.roots.path_for(f"originals/{source.original_artifact_id.hex}")
        if problem == "missing original":
            path.unlink()
        else:
            path.write_bytes(path.read_bytes()[:3000])
    if problem == "a face not embedded":
        perception.drop_vector = True

    with pytest.raises(error):
        video_executor(pipeline, **options).execute(started)

    assert started.job.processing_run_id is not None
    assert run_state(pipeline, started.job.processing_run_id) == ProcessingRunState.FAILED


def test_a_referenced_video_without_faces_finishes_with_no_tracks(
    pipeline: Pipeline, perception: PaintedPerception, tmp_path: Path
) -> None:
    from tests.fixtures.media import make_clip

    plain = import_video(
        pipeline,
        make_clip(tmp_path / "plain.mp4", seconds=1, source="color=c=gray"),
        referenced=True,
    )

    executed = video_executor(pipeline).execute(claim(pipeline, plain))

    final = checkpoints(pipeline, executed.processing_run_id)[-1].payload_json
    assert final["tracks"] == []
    assert final["decisions"] == []
    with pipeline.lib.session_factory() as session:
        assert session.scalars(select(Representation)).all() == []


# --- pause and resume (M6 step 7; TST-066) ----------------------------------------------------


def pauser(pipeline: Pipeline) -> PauseProcessingUseCase:
    return PauseProcessingUseCase(pipeline.lib.unit_of_work, clock=pipeline.clock)


def segments(pipeline: Pipeline, run_id: uuid.UUID) -> list[Any]:
    with pipeline.lib.session_factory() as session:
        return SegmentRepository(session).list_for_run(run_id)


def job_state(pipeline: Pipeline, job_id: uuid.UUID) -> str:
    with pipeline.lib.session_factory() as session:
        job = session.get(Job, job_id)
        assert job is not None
        return job.state


def test_a_paused_run_stops_at_its_chunk_and_resumes_after_it(
    pipeline: Pipeline, perception: PaintedPerception, video: uuid.UUID
) -> None:
    started = claim(pipeline, video)
    run_id = started.job.processing_run_id
    assert run_id is not None

    def pause_at(number: int) -> None:
        if number == 2:
            pauser(pipeline).pause(run_id)

    perception.on_detect = pause_at

    with pytest.raises(ProcessingPausedError):
        video_executor(pipeline).execute(started)

    assert run_state(pipeline, run_id) == ProcessingRunState.PAUSED
    assert job_state(pipeline, started.job.id) == JobState.PAUSED
    assert len(checkpoints(pipeline, run_id)) == 1  # the chunk in hand was finished first
    assert [s.ended_reason for s in segments(pipeline, run_id)] == ["NORMAL"]
    first_chunk = observations(pipeline, run_id)
    assert pauser(pipeline).pause(run_id) == PauseOutcome.ALREADY

    assert pauser(pipeline).resume(run_id) == PauseOutcome.RESUMED
    assert pauser(pipeline).resume(run_id) == PauseOutcome.ALREADY  # (queued: a repeat)
    perception.on_detect = None
    again = pipeline.scheduler().claim_source_job("worker")
    assert again is not None
    executed = video_executor(pipeline).execute(again)

    assert executed.processing_run_id == run_id
    assert perception.log.count("detect") == 6  # every frame once, across the pause
    assert [o.id for o in observations(pipeline, run_id)][: len(first_chunk)] == [
        o.id for o in first_chunk
    ]
    assert len(segments(pipeline, run_id)) == 2  # a new segment after the resume


def test_a_pause_asked_after_the_last_chunk_pauses_before_recognition(
    pipeline: Pipeline, perception: PaintedPerception, video: uuid.UUID
) -> None:
    started = claim(pipeline, video)
    run_id = started.job.processing_run_id
    assert run_id is not None

    def pause_at(number: int) -> None:
        if number == 6:
            pauser(pipeline).pause(run_id)

    perception.on_detect = pause_at

    with pytest.raises(ProcessingPausedError):
        video_executor(pipeline).execute(started)

    assert len(checkpoints(pipeline, run_id)) == 2  # every chunk done; nothing left but FINAL
    pauser(pipeline).resume(run_id)
    perception.on_detect = None
    again = pipeline.scheduler().claim_source_job("worker")
    assert again is not None
    video_executor(pipeline).execute(again)
    assert run_state(pipeline, run_id) == ProcessingRunState.FINALIZING
    assert perception.log.count("detect") == 6


def test_only_a_running_video_run_is_paused_and_only_a_paused_one_resumed(
    pipeline: Pipeline, perception: PaintedPerception, video: uuid.UUID
) -> None:
    pipeline.enqueue(video)
    with pipeline.lib.session_factory() as session:
        run_id = session.scalars(select(ProcessingRun.id)).one()
    image_run = pipeline.execute(pipeline.import_image())

    with pytest.raises(PauseError, match="PENDING"):
        pauser(pipeline).pause(run_id)  # queued, not running
    with pytest.raises(PauseError, match="not a video"):
        pauser(pipeline).pause(image_run)
    with pytest.raises(PauseError, match="cannot be resumed"):
        pauser(pipeline).resume(image_run)
    with pytest.raises(RunNotFoundError):
        pauser(pipeline).pause(uuid.uuid4())


def test_a_settlement_that_finds_the_paused_job_changed_fails_safely(
    pipeline: Pipeline, perception: PaintedPerception, video: uuid.UUID
) -> None:
    started = claim(pipeline, video)
    run_id = started.job.processing_run_id
    assert run_id is not None

    def pause_run_only(number: int) -> None:
        if number == 2:  # the run is PAUSING but its job is not: not ours to settle
            with pipeline.lib.session_factory() as session:
                session.execute(
                    update(ProcessingRun)
                    .where(ProcessingRun.id == run_id)
                    .values(state=ProcessingRunState.PAUSING)
                )
                session.commit()

    perception.on_detect = pause_run_only

    with pytest.raises(ProcessingExecutionError, match="paused job or its segment changed"):
        video_executor(pipeline).execute(started)


def test_the_runner_reports_a_paused_run(
    pipeline: Pipeline, perception: PaintedPerception, video: uuid.UUID
) -> None:
    pipeline.enqueue(video)
    uow = pipeline.lib.unit_of_work
    runner = ProcessingRunner(
        uow,
        pipeline.scheduler(),
        video_executor(pipeline),
        AcceptProcessingRunUseCase(uow, new_id=pipeline.new_id, clock=pipeline.clock),
        owner="runner",
        clock=pipeline.clock,
    )

    def pause_at(number: int) -> None:
        if number == 1:
            with pipeline.lib.session_factory() as session:
                run_id = session.scalars(select(ProcessingRun.id)).one()
            pauser(pipeline).pause(run_id)

    perception.on_detect = pause_at

    outcome = runner.run_once()

    assert outcome.kind == RunOutcomeKind.PAUSED
    assert runner.run_once().kind == RunOutcomeKind.IDLE  # a paused job is not claimed again


# --- retry of a video run (M6 step 7, D10; TST-064 video half) --------------------------------


def retrier(pipeline: Pipeline, runnable: bool = True) -> RetryProcessingUseCase:
    return RetryProcessingUseCase(
        pipeline.lib.unit_of_work,
        new_id=pipeline.new_id,
        clock=pipeline.clock,
        wake_scheduler=lambda: None,
        runnable=lambda _session, _run: runnable,
    )


def fail_at(perception: PaintedPerception, frame: int) -> None:
    def broken(number: int) -> None:
        if number == frame:
            raise OSError("the disk went away")

    perception.on_detect = broken


def test_a_failed_video_run_is_retried_from_its_last_chunk(
    pipeline: Pipeline, perception: PaintedPerception, video: uuid.UUID
) -> None:
    started = claim(pipeline, video)
    run_id = started.job.processing_run_id
    assert run_id is not None
    fail_at(perception, 5)  # inside chunk two
    with pytest.raises(OSError, match="disk went away"):
        video_executor(pipeline).execute(started)
    first_chunk = observations(pipeline, run_id)

    scheduled = retrier(pipeline).retry(started.job.id)

    assert scheduled.processing_run_id == run_id  # the same run continues
    assert scheduled.job_id != started.job.id
    perception.on_detect = None
    again = pipeline.scheduler().claim_source_job("worker")
    assert again is not None
    assert again.job.id == scheduled.job_id
    video_executor(pipeline).execute(again)
    assert perception.log.count("detect") == 7  # frames 1-5, then 5 and 6 again: none of chunk one
    resumed = observations(pipeline, run_id)
    assert [o.id for o in resumed[: len(first_chunk)]] == [o.id for o in first_chunk]
    assert len({(o.timestamp_ms, o.bbox_x) for o in resumed}) == len(resumed)  # none twice
    pipeline.accept(run_id, apply_index=True)  # the resumed run's own (newest) job completes
    assert run_state(pipeline, run_id) == ProcessingRunState.COMPLETED
    assert job_state(pipeline, scheduled.job_id) == JobState.COMPLETED
    assert job_state(pipeline, started.job.id) == JobState.FAILED  # history is not rewritten


@pytest.mark.parametrize("why", ["models changed", "no chunk done"])
def test_a_video_run_that_cannot_resume_is_retried_as_a_new_run(
    pipeline: Pipeline, perception: PaintedPerception, video: uuid.UUID, why: str
) -> None:
    started = claim(pipeline, video)
    run_id = started.job.processing_run_id
    assert run_id is not None
    fail_at(perception, 5 if why == "models changed" else 2)
    with pytest.raises(OSError, match="disk went away"):
        video_executor(pipeline).execute(started)
    kept = observations(pipeline, run_id)

    scheduled = retrier(pipeline, runnable=why != "models changed").retry(started.job.id)

    assert scheduled.processing_run_id != run_id
    with pipeline.lib.session_factory() as session:
        new_run = session.get(ProcessingRun, scheduled.processing_run_id)
        assert new_run is not None
        assert new_run.parent_run_id == run_id
    assert run_state(pipeline, run_id) == ProcessingRunState.FAILED  # left as it ended
    assert [o.id for o in observations(pipeline, run_id)] == [o.id for o in kept]


def test_a_snapshot_is_runnable_only_while_it_can_be_planned(
    pipeline: Pipeline, perception: PaintedPerception, video: uuid.UUID
) -> None:
    started = claim(pipeline, video)
    packages = RuntimePackageStore(pipeline.lib.roots, new_id=pipeline.new_id)

    def unplannable(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeUnavailableError("the model is not installed", ())

    with pipeline.lib.session_factory() as session:
        run = session.get(ProcessingRun, started.job.processing_run_id)
        assert run is not None
        assert snapshot_runnable(packages, lambda *a, **k: pipeline.plan)(session, run)
        assert not snapshot_runnable(packages, unplannable)(session, run)
        run.configuration_snapshot_id = uuid.uuid4()  # (no such snapshot: malformed)
        assert not snapshot_runnable(packages, lambda *a, **k: pipeline.plan)(session, run)
        session.rollback()


# --- one heavy movie at a time (M6 step 7; TST-068) -------------------------------------------


def scheduler_for(pipeline: Pipeline, videos: bool) -> ProcessingScheduler:
    return ProcessingScheduler(
        pipeline.lib.unit_of_work,
        new_id=pipeline.new_id,
        clock=pipeline.clock,
        lease_for=timedelta(minutes=5),
        videos=videos,
    )


def test_one_movie_runs_at_a_time_while_images_go_on_beside_it(
    pipeline: Pipeline, perception: PaintedPerception, tmp_path: Path
) -> None:
    first = import_video(pipeline, painted_clip(tmp_path / "one.mp4", seconds=1))
    second = import_video(pipeline, painted_clip(tmp_path / "two.mp4", seconds=1))
    image = pipeline.import_image()
    for source in (first, second, image):
        pipeline.enqueue(source)
    movies, others = scheduler_for(pipeline, True), scheduler_for(pipeline, False)

    running = movies.claim_source_job("movies")
    assert running is not None
    assert movies.claim_source_job("movies") is None  # the second movie stays QUEUED
    beside = others.claim_source_job("others")
    assert beside is not None  # an image runs beside the movie
    assert others.claim_source_job("others") is None  # the other queue never takes a movie
    with pipeline.lib.session_factory() as session:
        claimed = session.get(ProcessingRun, beside.job.processing_run_id)
        assert claimed is not None
        assert claimed.source_id == image

    video_executor(pipeline).execute(running)  # (FINALIZING still holds the slot)
    assert movies.claim_source_job("movies") is None
    pipeline.accept(running.job.processing_run_id, apply_index=True)  # type: ignore[arg-type]
    after = movies.claim_source_job("movies")
    assert after is not None  # the first is done: the second starts


def test_a_provider_fallback_inside_a_chunk_redoes_it_under_the_new_segment(
    pipeline: Pipeline, perception: PaintedPerception, video: uuid.UUID
) -> None:
    started = claim(pipeline, video)
    run_id = started.job.processing_run_id
    assert run_id is not None
    real_detect = perception.detect

    def falls_back_once(pixels: Any) -> Detected:
        found = real_detect(pixels)
        if perception.log.count("detect") == 3:  # the first chunk's second batch
            failed = ProviderUnavailable(
                found.ran, MLErrorCode.RUNTIME_VARIANT_NOT_AVAILABLE, "no GPU"
            )
            return Detected(found.detections, found.ran, (ProviderFallback((failed,), found.ran),))
        return found

    perception.detect = falls_back_once  # type: ignore[method-assign]

    video_executor(pipeline).execute(started)

    first, second = segments(pipeline, run_id)
    assert first.ended_reason == "FALLBACK"
    with pipeline.lib.session_factory() as session:
        rows = session.scalars(
            select(Observation.execution_segment_id).where(Observation.processing_run_id == run_id)
        ).all()
        produced = session.scalars(
            select(Representation.execution_segment_id).where(
                Representation.processing_run_id == run_id
            )
        ).all()
    assert set(rows) == set(produced) == {second.id}  # nothing settled under the closed segment
    assert perception.log.count("detect") == 6 + 4  # chunk one's four frames were done again


def test_a_cancel_while_pausing_stops_the_run_at_the_next_batch(
    pipeline: Pipeline, perception: PaintedPerception, video: uuid.UUID
) -> None:
    started = claim(pipeline, video)
    run_id = started.job.processing_run_id
    assert run_id is not None
    canceller = CancelProcessingUseCase(pipeline.lib.unit_of_work, clock=pipeline.clock)

    def pause_then_cancel(number: int) -> None:
        if number == 1:
            pauser(pipeline).pause(run_id)
        if number == 2:
            assert canceller.cancel(run_id).outcome == CancelOutcome.REQUESTED  # not refused

    perception.on_detect = pause_then_cancel

    with pytest.raises(ProcessingCancelledError):
        video_executor(pipeline, frames_per_turn=2).execute(started)

    assert run_state(pipeline, run_id) == ProcessingRunState.CANCELLED
    assert job_state(pipeline, started.job.id) == JobState.CANCELLED
    assert observations(pipeline, run_id) == []  # the chunk in hand was never settled


def test_commands_to_an_older_attempt_do_not_reach_the_current_one(
    pipeline: Pipeline, perception: PaintedPerception, video: uuid.UUID
) -> None:
    started = claim(pipeline, video)
    run_id = started.job.processing_run_id
    assert run_id is not None
    fail_at(perception, 5)
    with pytest.raises(OSError, match="disk went away"):
        video_executor(pipeline).execute(started)
    retrier(pipeline).retry(started.job.id)  # a new job on the same run (D10)

    with pytest.raises(CancelError, match="not the current attempt"):
        CancelProcessingUseCase(pipeline.lib.unit_of_work, clock=pipeline.clock).cancel(
            run_id, job_id=started.job.id
        )
    with pytest.raises(PauseError, match="not the current attempt"):
        pauser(pipeline).resume(run_id, job_id=started.job.id)
    assert run_state(pipeline, run_id) == ProcessingRunState.PENDING  # the retry is untouched
    canceller = CancelProcessingUseCase(pipeline.lib.unit_of_work, clock=pipeline.clock)
    assert canceller.cancel(run_id).outcome == CancelOutcome.CANCELLED  # the run itself: fine
    with pytest.raises(CancelError, match="not the current attempt"):  # not "already", via old job
        canceller.cancel(run_id, job_id=started.job.id)
