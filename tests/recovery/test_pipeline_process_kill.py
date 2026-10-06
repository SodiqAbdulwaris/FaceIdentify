"""The M3 pipeline in a real process, killed at each stage, and the next start (M3.2; TST-043,
TST-030; persistence sections 16, 28 and 30).

A child opens the library through `open_library`, runs one image through the real pipeline with
planted perception, and parks at a named stage; the parent kills the child's whole process tree and
reopens the library. Recovery must never run perception, never expose PENDING output, and finish
exactly what the FINAL checkpoint allows, once. A crash before FINAL is only interrupted; the work
is then redone as a retry (a new Job and Run), never by requeueing the old one.
"""

import json
import subprocess
from contextlib import AbstractContextManager
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from backend.app.identities.models import Evidence, Identity
from backend.app.jobs.models import Job
from backend.app.lifecycle import OpenLibrary, open_library
from backend.app.memory.index_coordinator import RetryPolicy
from backend.app.memory.models import (
    IndexOperation,
    Observation,
    Occurrence,
    Representation,
)
from backend.app.processing.models import ExecutionSegment, ProcessingRun
from backend.app.processing.retry import RetryProcessingUseCase
from backend.infrastructure.db.unit_of_work import TransactionRetry
from backend.infrastructure.indexing.representation_index import RepresentationIndex
from tests.fixtures.deterministic import FrozenClock, SeededUUIDs
from tests.fixtures.pipeline import NDIM, Pipeline, prepare_catalog
from tests.fixtures.processes import acquire_soon, close_streams, kill_tree, start_until

CHILD = "from tests.fixtures.pipeline_child import main; main()"


class Library:
    def __init__(self, tmp_path: Path, clock: FrozenClock, new_id: SeededUUIDs) -> None:
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
        """Migrate the library, register the fake catalog and import the one image."""
        with self.open() as lib:
            self.catalog = prepare_catalog(lib, self.clock, self.new_id)
            self.catalog["source_id"] = str(
                Pipeline(lib, self.clock, self.new_id, self.catalog).import_image()
            )
            self.catalog["vector"] = [1.0, 0.0, 0.0, 0.0]
        self.spec.write_text(json.dumps(self.catalog), encoding="utf-8")

    def pipeline(self, lib: OpenLibrary) -> Pipeline:
        return Pipeline(lib, self.clock, self.new_id, self.catalog)

    def kill_at(self, stage: str) -> None:
        """Run the child to `stage`, then kill its whole tree and wait for the library lock."""
        child: subprocess.Popen[str] = start_until(
            CHILD, str(self.root), str(self.local), self.clock().isoformat(), str(self.spec),
            stage, ready="READY",
        )  # fmt: skip
        try:
            kill_tree(child)  # no chance to release or finish anything
        finally:
            close_streams(child)
        acquire_soon(self.root)


@pytest.fixture
def library(tmp_path: Path, clock: FrozenClock, new_id: SeededUUIDs) -> Library:
    lib = Library(tmp_path, clock, new_id)
    lib.prepare()
    return lib


def states(pipeline: Pipeline, model: Any) -> list[str]:
    with pipeline.lib.session_factory() as session:
        return sorted(session.scalars(select(model.state)))


def assert_private(
    pipeline: Pipeline, *, observations: list[str], representations: list[str]
) -> None:
    """Nothing is visible: no identity, occurrence, evidence or index operation exists."""
    assert states(pipeline, Observation) == observations
    assert states(pipeline, Representation) == representations
    assert pipeline.count(Identity) == pipeline.count(Occurrence) == 0
    assert pipeline.count(Evidence) == pipeline.count(IndexOperation) == 0


def indexed_keys(pipeline: Pipeline) -> list[int]:
    directory = pipeline.lib.coordinator.index_directory(pipeline.space_id)
    index = RepresentationIndex.open(
        directory, representation_space_id=pipeline.space_id, ndim=NDIM, metric="cos"
    )
    with pipeline.lib.session_factory() as session:
        keys = [k for k in session.scalars(select(Representation.ann_key)) if k is not None]
    return sorted(k for k in keys if index.contains(k))


# --- a crash before FINAL --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("stage", "observations", "representations"),
    [("represent", ["PENDING"], []), ("decide", ["PENDING"], ["PENDING"])],
)
def test_a_crash_before_final_is_interrupted_private_and_redone_as_a_retry(
    library: Library, stage: str, observations: list[str], representations: list[str],
) -> None:  # fmt: skip
    library.kill_at(stage)

    with library.open() as reopened:
        pipeline = library.pipeline(reopened)
        assert pipeline.perception.calls == 0  # recovery never ran perception
        report = reopened.startup
        assert len(report.interrupted.runs) == len(report.interrupted.jobs) == 1
        assert report.finalizing.accepted == report.finalizing.not_resumable == []
        assert states(pipeline, ProcessingRun) == ["INTERRUPTED"]
        assert states(pipeline, Job) == ["INTERRUPTED"]  # never requeued
        assert states(pipeline, ExecutionSegment) == ["INTERRUPTED"]
        assert_private(pipeline, observations=observations, representations=representations)
        old_job = report.interrupted.jobs[0]
        old_run = report.interrupted.runs[0]

        # the retry is a new Job and Run; the old attempt and its private output are left alone
        scheduled = RetryProcessingUseCase(
            reopened.unit_of_work, new_id=library.new_id, clock=library.clock,
            wake_scheduler=lambda: None,
        ).retry(old_job)  # fmt: skip
        assert scheduled.processing_run_id != old_run
        new_run = pipeline.run_next()
        assert new_run == scheduled.processing_run_id
        pipeline.accept(new_run, apply_index=True)
        assert pipeline.count(Identity) == 1  # one identity: no duplicate memory
        assert pipeline.count(Occurrence) == 1
        assert sorted(states(pipeline, ProcessingRun)) == ["COMPLETED", "INTERRUPTED"]
        assert states(pipeline, Observation).count("PENDING") == 1  # the old attempt: still private
        assert states(pipeline, Observation).count("ACTIVE") == 1
        assert len(indexed_keys(pipeline)) == 1

    with library.open() as again:
        assert again.startup.repaired_nothing  # and a further start finds nothing to do


# --- a crash after FINAL, before the acceptance committed -----------------------------------


@pytest.mark.parametrize("stage", ["final", "accept-open"])
def test_a_crash_after_final_is_accepted_once_on_the_next_start_without_ml(
    library: Library, stage: str
) -> None:
    library.kill_at(stage)

    with library.open() as reopened:
        pipeline = library.pipeline(reopened)
        assert pipeline.perception.calls == 0
        report = reopened.startup
        assert len(report.finalizing.accepted) == 1
        assert report.finalizing.not_resumable == []
        assert states(pipeline, ProcessingRun) == ["COMPLETED"]
        assert states(pipeline, Job) == ["COMPLETED"]
        # recovery redid nothing: still the child's one run, one job and one segment
        assert pipeline.count(ProcessingRun) == pipeline.count(Job) == 1
        assert pipeline.count(ExecutionSegment) == 1
        assert states(pipeline, Observation) == ["ACTIVE"]
        assert states(pipeline, Representation) == ["ACTIVE"]
        assert pipeline.count(Identity) == pipeline.count(Occurrence) == 1  # once, not twice
        assert pipeline.count(Evidence) == 1
        assert states(pipeline, IndexOperation) == ["APPLIED"]  # recovery's own index pass
        assert len(indexed_keys(pipeline)) == 1

    with library.open() as again:
        assert again.startup.repaired_nothing


# --- a crash after the acceptance committed, before the index caught up ----------------------


def test_a_crash_after_acceptance_leaves_only_the_index_to_converge(library: Library) -> None:
    library.kill_at("accepted")

    with library.open() as reopened:
        pipeline = library.pipeline(reopened)
        assert reopened.startup.finalizing.accepted == []  # nothing left to accept
        assert states(pipeline, ProcessingRun) == ["COMPLETED"]
        assert pipeline.count(ProcessingRun) == pipeline.count(ExecutionSegment) == 1
        assert pipeline.count(Identity) == pipeline.count(Occurrence) == 1
        assert states(pipeline, IndexOperation) == ["APPLIED"]  # queued by acceptance, applied now
        assert len(indexed_keys(pipeline)) == 1

    with library.open() as again:
        assert again.startup.repaired_nothing
