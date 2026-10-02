"""A real backend process, killed mid-operation, and the next start (M2: TST-030; architecture
25.13; persistence section 28; issue 33).

The in-process recovery tests stop a function part way; these kill a whole process that has opened
the library through `open_library`, which is the only way to show that the library lock, the
database, the files and the index are all left in a state the next start reconciles. Each case
prepares the library in this process, lets a child do one risky thing and say so, kills the child's
whole process tree, and reopens.
"""

import subprocess
from contextlib import AbstractContextManager
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from backend.app.jobs.models import Job
from backend.app.lifecycle import OpenLibrary, open_library
from backend.app.memory.index_coordinator import RetryPolicy
from backend.app.memory.models import Representation
from backend.app.settings.app_state import WAL_TRUNCATION_OWED, AppStateRepository
from backend.app.sources.models import Artifact
from backend.infrastructure.storage.library_lock import LibraryLockedError
from tests.factories.models import ModelFactory, float32_vector
from tests.fixtures.deterministic import FrozenClock, SeededUUIDs
from tests.fixtures.processes import acquire_soon, close_streams, kill_tree, start_until

CHILD = """
import sys, uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from backend.app.lifecycle import open_library
from backend.app.memory.index_coordinator import RetryPolicy

library, local, mode, subject, instant = sys.argv[1:6]
fixed = datetime.fromisoformat(instant)
now = lambda: fixed  # the parent's clock, so nothing here depends on the wall clock
with open_library(
    library_root=Path(library), local_state_root=Path(local), clock=now, new_id=uuid.uuid4,
    retry=RetryPolicy(max_attempts=3, backoff=lambda n: timedelta(minutes=n)),
    index_batch=50, max_index_passes=5,
) as lib:
    if mode == "erase-queued":
        lib.eraser.queue([uuid.UUID(subject)])  # step one committed; nothing else done
    elif mode == "job-running":
        from backend.app.jobs.repository import JobRepository
        with lib.session_factory() as session:
            claimed = JobRepository(session).claim_next(
                owner="child", now=now(), lease_for=timedelta(minutes=5)
            )
            assert claimed is not None
            session.commit()
    elif mode == "artifact-pending":
        from backend.app.sources.artifact_storage import reserve_managed_artifact
        with lib.session_factory() as session:
            artifact = reserve_managed_artifact(
                session, "SOURCE_ORIGINAL", new_id=uuid.uuid4, clock=now
            )
            session.commit()
        # an interrupted write: bytes in staging, never moved into place
        lib.store.staging_path(artifact.storage_key).write_bytes(b"half a file")
    print("READY", flush=True)
    sys.stdin.read()  # alive and holding the library until the parent kills the tree
"""

SECRET = [123.25, -7.5, 99.125, 0.03125]
OTHER = [2.0, 4.0, 8.0, 16.0]


class Library:
    """A library under `tmp_path`: opened here for the checks, by a child to be killed."""

    def __init__(self, tmp_path: Path, clock: FrozenClock, new_id: SeededUUIDs) -> None:
        self.root = tmp_path / "library"
        self.root.mkdir()
        self.local = tmp_path / "local"
        self.clock, self.new_id = clock, new_id

    def open(self) -> AbstractContextManager[OpenLibrary]:
        return open_library(
            library_root=self.root, local_state_root=self.local, clock=self.clock,
            new_id=self.new_id, index_batch=50, max_index_passes=5,
            retry=RetryPolicy(max_attempts=3, backoff=lambda n: timedelta(minutes=n)),
        )  # fmt: skip

    def start_child(self, mode: str, subject: str = "-") -> subprocess.Popen[str]:
        instant = self.clock().isoformat()
        return start_until(
            CHILD, str(self.root), str(self.local), mode, subject, instant, ready="READY"
        )

    def kill(self, child: subprocess.Popen[str]) -> None:
        """Kill the child's whole tree, then wait for the operating system to free its lock."""
        try:
            kill_tree(child)  # no chance to release or finish anything
        finally:
            close_streams(child)
        acquire_soon(self.root)


def files_with(directory: Path, needle: bytes) -> list[Path]:
    return [p for p in directory.rglob("*") if p.is_file() and needle in p.read_bytes()]


@pytest.fixture
def library(tmp_path: Path, clock: FrozenClock, new_id: SeededUUIDs) -> Library:
    return Library(tmp_path, clock, new_id)


def test_a_live_backend_blocks_a_second_one_and_a_killed_one_does_not(library: Library) -> None:
    with library.open():
        pass
    child = library.start_child("idle")
    try:
        with pytest.raises(LibraryLockedError), library.open():
            pass  # the child is alive and holds the library
    finally:
        library.kill(child)

    with library.open() as reopened:  # killed without releasing anything: the OS freed the lock
        assert reopened.startup.clean


def test_a_backend_killed_while_it_ran_a_job_is_recovered_on_the_next_start(
    library: Library, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    with library.open() as opened, opened.session_factory() as session:
        job_id = ModelFactory(session, clock, new_id).job(state="QUEUED").id
        session.commit()

    library.kill(library.start_child("job-running"))

    with library.open() as reopened:
        assert reopened.startup.interrupted.jobs == [job_id]
        with reopened.session_factory() as session:
            job = session.get(Job, job_id)
            assert job is not None
            assert (job.state, job.lease_owner) == ("INTERRUPTED", None)  # never requeued
    with library.open() as again:
        assert again.startup.repaired_nothing  # and a second start has nothing more to do


def test_a_backend_killed_after_queueing_an_erasure_finishes_it_on_the_next_start(
    library: Library, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    with library.open() as opened, opened.session_factory() as session:
        build = ModelFactory(session, clock, new_id)
        space = build.representation_space(dimension=4)
        victim, survivor = (
            build.representation(
                representation_space_id=space.id, state="ACTIVE", identity_id=build.identity().id,
                ann_key=key, vector=float32_vector(SECRET if key == 1 else OTHER),
            )
            for key in (1, 2)
        )  # fmt: skip
        for rep in (victim, survivor):
            build.index_operation(rep, operation="ADD")
        session.commit()
        victim_id, survivor_id, space_id = victim.id, survivor.id, space.id
        assert opened.coordinator.apply_pending(limit=10).applied  # both are in the index file
        indexes = opened.roots.local_state_root / "indexes"
        assert files_with(indexes, float32_vector(SECRET))

    library.kill(library.start_child("erase-queued", str(victim_id)))

    with library.open() as reopened:
        assert reopened.startup.erasure.erased == [victim_id]
        assert reopened.startup.unresolved == []
        with reopened.session_factory() as session:
            row = session.execute(
                select(Representation.state, Representation.vector, Representation.ann_key).where(
                    Representation.id == victim_id
                )
            ).one()
            assert tuple(row) == ("ERASED", None, None)
            assert (
                session.scalar(select(Representation.state).where(Representation.id == survivor_id))
                == "ACTIVE"
            )
            assert AppStateRepository(session).get(WAL_TRUNCATION_OWED) is None
        indexes = reopened.roots.local_state_root / "indexes"
        assert files_with(indexes, float32_vector(SECRET)) == []  # the vector is in no index file
        assert files_with(indexes / space_id.hex, float32_vector(OTHER))  # the survivor stays
        database = reopened.roots.database_path
        for name in (database.name, database.name + "-wal"):
            candidate = database.with_name(name)
            assert not candidate.exists() or float32_vector(SECRET) not in candidate.read_bytes()


def test_a_backend_killed_mid_import_leaves_nothing_the_next_start_cannot_settle(
    library: Library,
) -> None:
    with library.open():
        pass

    library.kill(library.start_child("artifact-pending"))

    with library.open() as reopened:
        report = reopened.startup.artifacts
        assert len(report.write_not_completed) == 1  # the PENDING row whose write never finished
        assert len(report.staging_removed) == 1  # and the half-written bytes it left in staging
        with reopened.session_factory() as session:
            states = session.scalars(select(Artifact.state)).all()
        assert "PENDING" not in states  # settled, not left dangling
        assert not list((reopened.roots.library_root / "staging").iterdir())
    with library.open() as again:
        assert again.startup.repaired_nothing
