"""A camera session in a real process, killed at each stage, and the next start (M7 step 4; plan C3,
C4; TST-071; the milestone gate: interrupted and recovered without corrupting identity memory).

The parent enrols the red "person" from an image and configures a camera; a child runs a session in
which the red person visits twice and parks at a stage; the parent kills the child's process tree
and reopens the library. Either way the run is `INTERRUPTED`, the first visit stays as its one
appearance, the second leaves no appearance (its faces, if written, stay private), no identity is
made, nothing restarts on its own, and a new session can start and record normally.
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
from backend.app.jobs.models import Job, JobType
from backend.app.lifecycle import OpenLibrary, open_library
from backend.app.memory.index_coordinator import RetryPolicy
from backend.app.memory.models import Observation, Occurrence
from backend.app.processing.models import ProcessingRun
from backend.infrastructure.db.unit_of_work import TransactionRetry
from tests.fixtures.camera_pipeline import Camera, empty, visit
from tests.fixtures.deterministic import FrozenClock, SeededUUIDs
from tests.fixtures.pipeline import Pipeline, prepare_catalog
from tests.fixtures.processes import acquire_soon, close_streams, kill_tree, start_until

CHILD = "from tests.fixtures.camera_child import main; main()"


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
        with self.open() as lib:
            self.catalog = prepare_catalog(lib, self.clock, self.new_id)
            pipeline = Pipeline(lib, self.clock, self.new_id, self.catalog)
            pipeline.accept(pipeline.execute(pipeline.import_image()), apply_index=True)
            self.catalog["camera_id"] = str(Camera(pipeline).id)
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


@pytest.fixture
def library(tmp_path: Path, clock: FrozenClock, new_id: SeededUUIDs) -> Library:
    lib = Library(tmp_path, clock, new_id)
    lib.prepare()
    return lib


@pytest.mark.parametrize(("stage", "private_faces"), [("open", False), ("private", True)])
def test_a_session_killed_keeps_its_closed_encounters_and_nothing_else(
    library: Library, stage: str, private_faces: bool
) -> None:
    library.kill_at(stage)

    with library.open() as reopened:
        pipeline = Pipeline(reopened, library.clock, library.new_id, library.catalog)
        camera = uuid.UUID(library.catalog["camera_id"])
        with reopened.session_factory() as session:
            (run,) = session.scalars(
                select(ProcessingRun).where(ProcessingRun.source_id == camera)
            ).all()
            assert run.state == "INTERRUPTED"
            job = session.scalars(select(Job).where(Job.processing_run_id == run.id)).one()
            assert job.state == "INTERRUPTED"
            (first,) = session.scalars(
                select(Occurrence).where(Occurrence.source_id == camera)
            ).all()  # the first visit only
            pending = session.scalars(
                select(Observation).where(
                    Observation.source_id == camera, Observation.state == "PENDING"
                )
            ).all()
            assert bool(pending) == private_faces  # private, in no appearance
            assert len(session.scalars(select(Identity)).all()) == 1
            assert (
                session.scalars(
                    select(Job).where(
                        Job.type == JobType.PROCESS_CAMERA_SESSION, Job.state == "RUNNING"
                    )
                ).all()
                == []
            )  # nothing restarted on its own (C4)

        again = Camera(pipeline, camera_id=camera)
        again.run(*visit("red", 0, 1), *empty(1, 1.6))  # a new session starts and records
        with reopened.session_factory() as session:
            occurrences = session.scalars(
                select(Occurrence).where(Occurrence.source_id == camera)
            ).all()
            assert len(occurrences) == 2
            assert {o.identity_id for o in occurrences} == {first.identity_id}
