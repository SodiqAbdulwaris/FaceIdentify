"""What a video run records between chunks, and how it is read back (M6 steps 4 and 5).

A video is processed in chunks of sampled frames (`ExecuteProcessingJob`); each chunk ends with ONE
transaction holding its selected observations, their representations and an `INTERMEDIATE`
checkpoint whose payload is small (positions and ids, never pixels):

    {"schema_version": 1, "video": {
        "slot": <the last slot done>, "sequence": <the next sequence_in_run>,
        "tracker": <the tracker's state>,
        "spans": {"<track>": [start_ms, end_ms, start_frame, end_frame]},   # this chunk's
        "observations": [["<observation id>", <track>], ...]}}            # this chunk's

A resumed run starts after the newest such checkpoint's slot with its tracker state
(`resume_point`): only a chunk that was not committed is done again, so no observation is
recorded twice, and a track continues across the boundary.
The run's tracks are the chunks' entries merged in order (`video_tracks`): the FINAL hand-off
carries them, and acceptance turns each into an occurrence over time (step 6).
"""

import math
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.processing.models import CheckpointKind, CheckpointState, ProcessingCheckpoint
from backend.app.processing.repository import CheckpointRepository
from backend.infrastructure.media.frames import SAMPLE_RATE

VIDEO = "video"


@dataclass(frozen=True, slots=True)
class VideoProcessing:
    """How videos are processed. `frames_per_turn` (one worker turn per batch of frames, #242) is
    measured with `benchmarks/worker_lease_stress.py --background-batch`; the others are
    provisional until the real-world check (step 8)."""

    rate: float = SAMPLE_RATE  # frames a second given to detection (D4)
    chunk_frames: int = 20  # a checkpoint every ten seconds of video at two frames a second
    frames_per_turn: int = 2  # measured, #242: see the step 5 entry
    keep_per_track: int = 3  # observations embedded and kept per track and chunk
    # Frames are scaled so the longer side is at most this (4K exists in real libraries; the
    # detector works at 640): a chunk of 4K frames then holds a quarter of the memory.
    max_side: int = 1920

    def __post_init__(self) -> None:
        if (
            min(
                self.rate,
                self.chunk_frames,
                self.frames_per_turn,
                self.keep_per_track,
                self.max_side,
            )
            <= 0
        ):
            raise ValueError("every video processing setting must be positive")


@dataclass(frozen=True, slots=True)
class ResumePoint:
    slot: int = -1  # the last slot done
    sequence: int = 0  # the next observation's sequence_in_run
    tracker: dict[str, Any] | None = None


def resume_point(session: Session, run_id: uuid.UUID) -> ResumePoint:
    """Where a run stopped: its newest valid chunk checkpoint, or the start."""
    checkpoint = CheckpointRepository(session).latest_valid(run_id)
    if checkpoint is None:  # (a running video run's checkpoints are all chunk checkpoints)
        return ResumePoint()
    video = checkpoint.payload_json[VIDEO]
    return ResumePoint(video["slot"], video["sequence"], video["tracker"])


def chunk_payload(
    *,
    slot: int,
    sequence: int,
    tracker: dict[str, Any],
    spans: dict[int, list[int]],
    observations: list[tuple[uuid.UUID, int]],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        VIDEO: {
            "slot": slot,
            "sequence": sequence,
            "tracker": tracker,
            "spans": {str(track): span for track, span in spans.items()},
            "observations": [[str(observation), track] for observation, track in observations],
        },
    }


def video_tracks(session: Session, run_id: uuid.UUID) -> list[dict[str, Any]]:
    """Every track of a run that kept an observation: its observations in time order and the time
    and frames it spans, merged from the run's chunk checkpoints."""
    tracks: dict[str, dict[str, Any]] = {}
    for payload in session.scalars(
        select(ProcessingCheckpoint.payload_json)
        .where(
            ProcessingCheckpoint.processing_run_id == run_id,
            ProcessingCheckpoint.kind == CheckpointKind.INTERMEDIATE,
            ProcessingCheckpoint.state == CheckpointState.VALID,
        )
        .order_by(ProcessingCheckpoint.ordinal)
    ):
        video = payload[VIDEO]
        for track, (start_ms, end_ms, start_frame, end_frame) in video["spans"].items():
            entry = tracks.setdefault(
                track,
                {
                    "track": int(track),
                    "start_ms": start_ms,
                    "start_frame": start_frame,
                    "observations": [],
                },
            )
            entry["end_ms"], entry["end_frame"] = end_ms, end_frame
        for observation, track in video["observations"]:
            tracks[str(track)]["observations"].append(observation)
    return [track for track in tracks.values() if track["observations"]]


def frame_index(timestamp_ms: int, slot: int, frame_rate: tuple[int, int] | None) -> int:
    """The source frame at a presentation time (nearest, from the average rate); the slot when the
    rate is unknown. Times are authoritative; the index is for display."""
    if frame_rate is None:
        return slot
    numerator, denominator = frame_rate
    return math.floor(timestamp_ms * numerator / (denominator * 1000) + 0.5)
