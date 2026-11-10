"""A video run in a real process, killed at each stage, and the next start (M6 step 7; TST-067,
TST-064 video half, TST-066; the milestone gate: interrupted and recovered without corrupting
identity memory).

The parent enrols the red "person" from an image and imports a clip of painted squares; a child runs
the video through the real pipeline and parks at a stage; the parent kills the child's process tree
and reopens the library. A run killed mid-video is interrupted and resumed by a retry from its last
chunk (D10); one killed while pausing is paused and resumed; one killed after FINAL is accepted by
recovery. Each ends with one appearance of the red person over the whole clip, no observation twice.
"""

import json
import subprocess
import uuid
from contextlib import AbstractContextManager
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from backend.app.identities.models import Identity
from backend.app.jobs.models import Job
from backend.app.lifecycle import OpenLibrary, open_library
from backend.app.memory.index_coordinator import RetryPolicy
from backend.app.memory.models import Observation, Occurrence, OccurrenceKind
from backend.app.processing.models import ProcessingCheckpoint, ProcessingRun
from backend.app.processing.pause import PauseProcessingUseCase
from backend.app.processing.retry import RetryProcessingUseCase
from backend.infrastructure.db.unit_of_work import TransactionRetry
from tests.fixtures.deterministic import FrozenClock, SeededUUIDs
from tests.fixtures.pipeline import Pipeline, prepare_catalog
from tests.fixtures.processes import acquire_soon, close_streams, kill_tree, start_until
from tests.fixtures.video_pipeline import (
    import_video,
    painted_clip,
    video_executor,
    video_perception,
)

CHILD = "from tests.fixtures.video_child import main; main()"


class Library:
    def __init__(self, tmp_path: Path, clock: FrozenClock, new_id: SeededUUIDs) -> None:
        self.tmp = tmp_path
        self.root = tmp_path / "library"
        self.root.mkdir()
        self.local = tmp_path / "local"
        self.spec = tmp_path / "spec.json"
        self.clock, self.new_id = clock, new_id
        self.catalog: dict[str, Any] = {}

    def open(self) -> AbstractContextManager[OpenLibrary]:
        return open_library(
            library_root=self.root, local_state_root=self.local, clock=self.clock,
            new_id=self.new_id, index_batch=50, max_index_passes=5,
            transaction_retry=TransactionRetry(max_attempts=3, backoff=lambda n: 0.1 * n),
            retry=RetryPolicy(max_attempts=3, backoff=lambda n: timedelta(minutes=n)),
        )  # fmt: skip

    def prepare(self) -> None:
        """The catalog, the red person enrolled from an image, and the clip imported."""
        with self.open() as lib:
            self.catalog = prepare_catalog(lib, self.clock, self.new_id)
            pipeline = Pipeline(lib, self.clock, self.new_id, self.catalog)
            pipeline.accept(pipeline.execute(pipeline.import_image()), apply_index=True)
            clip = painted_clip(self.tmp / "squares.mp4")
            self.catalog["video_id"] = str(import_video(pipeline, clip))
        self.spec.write_text(json.dumps(self.catalog), encoding="utf-8")

    def kill_at(self, stage: str) -> None:
        child: subprocess.Popen[str] = start_until(
            CHILD, str(self.root), str(self.local), self.clock().isoformat(), str(self.spec),
            stage, ready="READY",
        )  # fmt: skip
        try:
            kill_tree(child)
        finally:
            close_streams(child)
        acquire_soon(self.root)

    def pipeline(self, lib: OpenLibrary) -> Pipeline:
        pipeline = Pipeline(lib, self.clock, self.new_id, self.catalog)
        video_perception(pipeline)
        return pipeline


@pytest.fixture
def library(tmp_path: Path, clock: FrozenClock, new_id: SeededUUIDs) -> Library:
    lib = Library(tmp_path, clock, new_id)
    lib.prepare()
    return lib


def video_run(pipeline: Pipeline, library: Library) -> ProcessingRun:
    with pipeline.lib.session_factory() as session:
        return session.scalars(
            select(ProcessingRun).where(
                ProcessingRun.source_id == uuid.UUID(library.catalog["video_id"])
            )
        ).one()


def finish(pipeline: Pipeline) -> uuid.UUID:
    started = pipeline.scheduler().claim_source_job("parent")
    assert started is not None
    run_id = video_executor(pipeline).execute(started).processing_run_id
    pipeline.accept(run_id, apply_index=True)
    return run_id


def assert_one_clean_appearance(pipeline: Pipeline, run_id: uuid.UUID) -> None:
    with pipeline.lib.session_factory() as session:
        (occurrence,) = session.scalars(
            select(Occurrence).where(Occurrence.processing_run_id == run_id)
        ).all()
        assert occurrence.kind == OccurrenceKind.TRACK
        assert (occurrence.start_timestamp_ms, occurrence.end_timestamp_ms) == (0, 2520)
        assert len(session.scalars(select(Identity)).all()) == 1  # no identity made twice
        faces = session.scalars(
            select(Observation).where(Observation.processing_run_id == run_id)
        ).all()
        assert {face.state for face in faces} == {"ACTIVE"}
        assert len({(face.timestamp_ms, face.bbox_x) for face in faces}) == len(faces)


def test_a_video_killed_mid_run_is_resumed_from_its_last_chunk(library: Library) -> None:
    library.kill_at("chunk")

    with library.open() as reopened:
        pipeline = library.pipeline(reopened)
        run = video_run(pipeline, library)
        assert run.state == "INTERRUPTED"
        (job_id,) = reopened.startup.interrupted.jobs

        scheduled = RetryProcessingUseCase(
            reopened.unit_of_work, new_id=library.new_id, clock=library.clock,
            wake_scheduler=lambda: None,
        ).retry(job_id)  # fmt: skip
        assert scheduled.processing_run_id == run.id  # D10: the same run continues
        assert finish(pipeline) == run.id
        assert pipeline.perception.log.count("detect") == 2  # type: ignore[attr-defined]
        assert_one_clean_appearance(pipeline, run.id)

    with library.open() as again:
        assert again.startup.repaired_nothing


def test_a_video_killed_while_pausing_is_paused_and_resumes(library: Library) -> None:
    library.kill_at("pausing")

    with library.open() as reopened:
        pipeline = library.pipeline(reopened)
        run = video_run(pipeline, library)
        assert run.state == "PAUSED"  # recovery settles the request a crash left behind
        with reopened.session_factory() as session:  # (the kill came before the first chunk was
            # settled: a recovered pause has no chunk yet, so the resume starts at the beginning)
            assert (
                session.scalars(
                    select(ProcessingCheckpoint).where(
                        ProcessingCheckpoint.processing_run_id == run.id
                    )
                ).all()
                == []
            )
        with reopened.session_factory() as session:
            assert (
                session.scalars(select(Job.state).where(Job.processing_run_id == run.id)).one()
                == "PAUSED"
            )

        PauseProcessingUseCase(reopened.unit_of_work, clock=library.clock).resume(run.id)
        assert finish(pipeline) == run.id
        assert pipeline.perception.log.count("detect") == 6  # type: ignore[attr-defined]
        assert_one_clean_appearance(pipeline, run.id)


def test_a_video_killed_after_final_is_accepted_by_recovery(library: Library) -> None:
    library.kill_at("final")

    with library.open() as reopened:
        pipeline = library.pipeline(reopened)
        run = video_run(pipeline, library)
        assert run.state == "COMPLETED"
        assert len(reopened.startup.finalizing.accepted) == 1
        assert pipeline.perception.log == []  # type: ignore[attr-defined]  # no ML on recovery
        assert_one_clean_appearance(pipeline, run.id)
