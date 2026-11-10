"""A track keeps a few faces over its whole life, through a restart and a provider fallback (M6
step 5; second and third reviews of PR #247)."""

import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from backend.app.memory.models import Observation
from backend.app.processing.models import ProcessingCheckpoint
from backend.app.processing.scheduler import StartedProcessingJob
from backend.app.runtime.perception_client import Detected, ProviderFallback, ProviderUnavailable
from backend.ml.contracts.protocol import MLErrorCode
from tests.fixtures.pipeline import Pipeline
from tests.fixtures.video_pipeline import (
    PaintedPerception,
    import_video,
    painted_clip,
    video_executor,
    video_perception,
)

SETTINGS: dict[str, Any] = {"chunk_frames": 2, "frames_per_turn": 1, "keep_per_track": 2, "max_per_track": 3}


class Crash(BaseException):
    """The process was killed here."""


@pytest.fixture
def perception(pipeline: Pipeline) -> PaintedPerception:
    return video_perception(pipeline)


@pytest.fixture
def started(pipeline: Pipeline, tmp_path: Path) -> StartedProcessingJob:
    source = import_video(pipeline, painted_clip(tmp_path / "squares.mp4", seconds=4))
    pipeline.enqueue(source)
    claimed = pipeline.scheduler().claim_source_job("worker")
    assert claimed is not None
    return claimed


def kept_per_track(pipeline: Pipeline, run_id: uuid.UUID) -> dict[int, int]:
    counts: dict[int, int] = {}
    with pipeline.lib.session_factory() as session:
        for payload in session.scalars(
            select(ProcessingCheckpoint.payload_json).where(
                ProcessingCheckpoint.processing_run_id == run_id
            )
        ):
            for _observation, track in payload.get("video", {}).get("observations", []):
                counts[track] = counts.get(track, 0) + 1
        assert len(session.scalars(select(Observation)).all()) == sum(counts.values())
    return counts


def test_a_long_track_keeps_no_more_than_its_budget(
    pipeline: Pipeline, perception: PaintedPerception, started: StartedProcessingJob
) -> None:
    run_id = video_executor(pipeline, **SETTINGS).execute(started).processing_run_id

    counts = kept_per_track(pipeline, run_id)
    assert counts[0] == 3  # the red face: four chunks of two kept would be eight


def test_the_budget_holds_across_a_restart(
    pipeline: Pipeline, perception: PaintedPerception, started: StartedProcessingJob
) -> None:
    def crash(number: int) -> None:
        if number == 5:  # inside the third chunk, after two were committed
            raise Crash

    perception.on_detect = crash
    with pytest.raises(Crash):
        video_executor(pipeline, **SETTINGS).execute(started)
    perception.on_detect = None

    run_id = video_executor(pipeline, **SETTINGS).execute(started).processing_run_id

    assert kept_per_track(pipeline, run_id)[0] == 3


def test_the_budget_holds_across_a_chunk_redone_after_a_fallback(
    pipeline: Pipeline, perception: PaintedPerception, started: StartedProcessingJob
) -> None:
    real_detect = perception.detect

    def falls_back_once(pixels: Any) -> Detected:
        found = real_detect(pixels)
        if perception.log.count("detect") == 4:  # the second chunk's second frame
            failed = ProviderUnavailable(
                found.ran, MLErrorCode.RUNTIME_VARIANT_NOT_AVAILABLE, "no GPU"
            )
            return Detected(found.detections, found.ran, (ProviderFallback((failed,), found.ran),))
        return found

    perception.detect = falls_back_once  # type: ignore[method-assign]

    run_id = video_executor(pipeline, **SETTINGS).execute(started).processing_run_id

    assert kept_per_track(pipeline, run_id)[0] == 3  # the redone chunk did not count twice
