"""A video job: decode, detect in batches, track, select, embed, checkpoint each chunk (M6 steps
4 and 5; #242; TST-063, TST-065, TST-067, TST-069).

The real executor, lease, decoder and database on a clip of painted squares
(`tests/fixtures/video_pipeline.py`); only perception is painted.
"""

import threading
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select, update

from backend.app.jobs.models import Job, JobState
from backend.app.memory.models import Observation, Representation
from backend.app.processing.execute_job import ProcessingCancelledError, ProcessingExecutionError
from backend.app.processing.models import (
    CheckpointKind,
    ProcessingCheckpoint,
    ProcessingRun,
    ProcessingRunState,
)
from backend.app.processing.process_source import ProcessSourceError
from backend.app.processing.repository import SegmentRepository
from backend.app.processing.retry import RetryProcessingUseCase
from backend.app.processing.scheduler import StartedProcessingJob
from backend.app.runtime.perception_client import Detected, ProviderFallback, ProviderUnavailable
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


def test_a_failed_video_run_is_not_retried_yet(
    pipeline: Pipeline, perception: PaintedPerception, video: uuid.UUID
) -> None:
    started = claim(pipeline, video)
    perception.drop_vector = True
    with pytest.raises(ProcessingExecutionError):
        video_executor(pipeline).execute(started)

    with pytest.raises(ProcessSourceError, match="video run cannot be retried yet"):
        RetryProcessingUseCase(
            pipeline.lib.unit_of_work,
            new_id=pipeline.new_id,
            clock=pipeline.clock,
            wake_scheduler=lambda: None,
        ).retry(started.job.id)


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

    with pipeline.lib.session_factory() as session:
        first, second = SegmentRepository(session).list_for_run(run_id)
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
