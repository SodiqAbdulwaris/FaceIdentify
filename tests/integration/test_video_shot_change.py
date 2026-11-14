"""A cut that puts another face in the same place does not give one person the other's time
(issue #283; M6 steps 5 and 6).

The clips are painted squares (`tests/fixtures/video_pipeline.py`): the red "person", enrolled
first, fills a square; at a cut the whole picture changes (the background turns grey) and a slightly
smaller green square, another person, stands where the red one was; at the next cut the red one is
back. The tracker links by position, so before the fix the green face continued the red track: in
the first clip its faces lost the merit ranking to the red ones and none was kept, in the second
the track had spent its lifetime budget before the cut, so nothing after it was kept at all. Either
way the red person's appearance covered the green one's time and the green faces were never
recorded.
"""

import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from backend.app.identities.models import Identity
from backend.app.memory.models import Observation, Occurrence
from backend.app.processing.video_chunks import video_tracks
from backend.app.runtime.perception_client import ProviderFallback, ProviderUnavailable, Represented
from backend.ml.contracts.protocol import MLErrorCode
from tests.fixtures.media import make_clip
from tests.fixtures.pipeline import Pipeline
from tests.fixtures.video_pipeline import (
    PaintedPerception,
    import_video,
    video_executor,
    video_perception,
)

Interrupt = Callable[[PaintedPerception, Callable[[], Any]], None]
# (track, start ms, end ms, kept faces): red, then green from the cut, then red again
EXPECTED_TRACKS = [(0, 0, 3520, 3), (1, 4000, 5520, 3), (2, 6000, 7520, 3)]


def cut_clip(path: Path, *, seconds: float, green: tuple[float, float]) -> Path:
    """Red for the whole clip but `green` (start, end in seconds), where a cut shows a grey
    picture with a smaller green square in the red one's place."""
    between = f"between(t,{green[0]},{green[1]})"
    graph = (
        f"[0:v]drawbox=x=0:y=0:w=iw:h=ih:color=gray:t=fill:enable='{between}',"
        f"drawbox=x=63:y=43:w=30:h=30:color=red:t=fill:enable='not({between})',"
        f"drawbox=x=66:y=46:w=24:h=24:color=lime:t=fill:enable='{between}'"
    )
    return make_clip(
        path,
        seconds=seconds,
        source="color=c=black",
        encode=("-vf", graph.removeprefix("[0:v]"), "-c:v", "mpeg4", "-q:v", "2"),
    )


def enrol_red(pipeline: Pipeline) -> uuid.UUID:
    """An image whose one face is the red vector: the first face makes the identity."""
    pipeline.accept(pipeline.execute(pipeline.import_image()), apply_index=True)
    with pipeline.lib.session_factory() as session:
        return session.scalars(select(Identity)).one().id


@pytest.mark.parametrize(
    ("seconds", "green", "settings"),
    [
        # one chunk of four seconds: the red faces outrank the green ones (larger, same score)
        (4, (1.25, 2.25), {"chunk_frames": 8, "keep_per_track": 3, "max_per_track": 12}),
        # the track's lifetime budget (3) is spent in the first chunk, before the cut
        (8, (3.75, 5.75), {"chunk_frames": 8, "keep_per_track": 3, "max_per_track": 3}),
    ],
    ids=["outranked", "after-the-budget"],
)
def test_a_cut_to_another_face_in_the_same_place_is_not_the_first_person_s_time(
    pipeline: Pipeline,
    tmp_path: Path,
    seconds: float,
    green: tuple[float, float],
    settings: dict[str, Any],
) -> None:
    check_the_cut(pipeline, tmp_path, seconds, green, settings)


class Crash(BaseException):
    """The process was killed here."""


def kill_in_the_second_chunk(perception: PaintedPerception, run: Callable[[], Any]) -> None:
    def crash(number: int) -> None:
        if number == 10:  # the second chunk's second batch, where the green face is
            raise Crash

    perception.on_detect = crash
    with pytest.raises(Crash):
        run()
    perception.on_detect = None


def fall_back_in_the_second_chunk(perception: PaintedPerception, _run: Callable[[], Any]) -> None:
    real = perception.represent

    def represent(pixels: Any, detections: tuple[Any, ...]) -> Represented:
        found = real(pixels, detections)
        if perception.log.count("represent") == 5:  # the second chunk's first embedding turn
            assert found.ran is not None
            failed = ProviderUnavailable(
                found.ran, MLErrorCode.RUNTIME_VARIANT_NOT_AVAILABLE, "gone"
            )
            return Represented(found.vectors, found.ran, (ProviderFallback((failed,), found.ran),))
        return found

    perception.represent = represent  # type: ignore[method-assign]


@pytest.mark.parametrize(
    "interrupt",
    [None, kill_in_the_second_chunk, fall_back_in_the_second_chunk],
    ids=["uninterrupted", "killed-and-resumed", "chunk-redone-after-a-fallback"],
)
def test_a_resumed_or_redone_chunk_makes_the_same_tracks(
    pipeline: Pipeline, tmp_path: Path, interrupt: Interrupt | None
) -> None:
    """The second chunk starts where the green face first appears, after the red track has spent
    its budget. Resumed from the first chunk's checkpoint (which holds no face) or redone after a
    provider fallback in the embedding pass, the track's face is its kept face again (read back
    from the library on a resume), so every run makes the same tracks as one never interrupted."""
    run_id = check_the_cut(
        pipeline,
        tmp_path,
        8,
        (3.75, 5.75),
        {"chunk_frames": 8, "keep_per_track": 3, "max_per_track": 3},
        interrupt=interrupt,
    )

    with pipeline.lib.session_factory() as session:
        tracks = [
            (t["track"], t["start_ms"], t["end_ms"], len(t["observations"]))
            for t in video_tracks(session, run_id)
        ]
    assert tracks == EXPECTED_TRACKS


def check_the_cut(
    pipeline: Pipeline,
    tmp_path: Path,
    seconds: float,
    green: tuple[float, float],
    settings: dict[str, Any],
    interrupt: "Interrupt | None" = None,
) -> uuid.UUID:
    red = enrol_red(pipeline)
    source_id = import_video(pipeline, cut_clip(tmp_path / "cut.mp4", seconds=seconds, green=green))
    perception = video_perception(pipeline)
    pipeline.enqueue(source_id)
    started = pipeline.scheduler().claim_source_job("worker")
    assert started is not None
    if interrupt is not None:
        interrupt(perception, lambda: video_executor(pipeline, **settings).execute(started))

    run_id = video_executor(pipeline, **settings).execute(started).processing_run_id
    pipeline.accept(run_id, apply_index=True)

    start, end = (round(v * 1000) for v in green)
    with pipeline.lib.session_factory() as session:
        reds = session.scalars(
            select(Occurrence).where(
                Occurrence.processing_run_id == run_id, Occurrence.identity_id == red
            )
        ).all()
        spans = [(o.start_timestamp_ms or 0, o.end_timestamp_ms or 0) for o in reds]
        assert all(last < start or first > end for first, last in spans)  # never green's time
        assert any(last < start for _f, last in spans)  # but red's own, before the cut
        assert any(first > end for first, _l in spans)  # and after it
        recorded = session.scalars(
            select(Observation.timestamp_ms).where(
                Observation.processing_run_id == run_id,
                Observation.timestamp_ms >= start,
                Observation.timestamp_ms <= end,
            )
        ).all()
        assert recorded  # the green person's faces are kept, for review
    return run_id
