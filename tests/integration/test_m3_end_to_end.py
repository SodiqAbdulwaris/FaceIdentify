"""M3 end to end: request -> claim -> private execution -> FINAL -> acceptance -> index -> restart
(TST-043 "results survive restart"; persistence §30).

Only perception is faked (a client that returns planted detections and vectors, never real weights).
Everything else is real: SQLite through `open_library`, the scheduler, the executor, acceptance, the
IndexCoordinator, USearch and startup recovery. The story, with unit-length 4-d vectors:

* A creates identity I1;
* B is a face near A and matches I1 with no new identity;
* C is a different face and creates I2;
* the process restarts and the index is lost, so recovery rebuilds it from SQLite;
* D is a face near A and matches I1 through the rebuilt index.

B is also run with the process "crashing" after execution (FINAL written, not accepted) and after
acceptance (ADD queued, not applied): the next start finishes the work without rerunning ML.
"""

import shutil
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from sqlalchemy import select

from backend.app.identities.models import Evidence, Identity
from backend.app.lifecycle import open_library
from backend.app.memory.index_coordinator import RetryPolicy
from backend.app.memory.models import IndexOperation, Occurrence, Representation
from backend.app.processing.models import ProcessingRun
from backend.infrastructure.db.unit_of_work import TransactionRetry
from tests.fixtures.deterministic import FrozenClock, SeededUUIDs
from tests.fixtures.pipeline import Pipeline, prepare_catalog, unit

A = unit(1, 0, 0, 0)
B = unit(0.95, 0.1, 0, 0)  # near A
C = unit(0, 1, 0, 0)  # unlike A and B
D = unit(0.9, 0, 0.1, 0)  # near A


@pytest.fixture
def story(tmp_path: Path, clock: FrozenClock, new_id: SeededUUIDs) -> tuple[Any, ...]:
    (tmp_path / "library").mkdir()
    state: dict[str, Any] = {}

    @contextmanager
    def opened() -> Iterator[Pipeline]:
        with open_library(
            library_root=tmp_path / "library",
            local_state_root=tmp_path / "local",
            clock=clock,
            new_id=new_id,
            index_batch=50,
            max_index_passes=5,
            transaction_retry=TransactionRetry(max_attempts=3, backoff=lambda n: 0.1 * n),
            retry=RetryPolicy(max_attempts=3, backoff=lambda n: timedelta(minutes=n)),
        ) as lib:
            if not state:
                state["catalog"] = prepare_catalog(lib, clock, new_id)
            yield Pipeline(lib, clock, new_id, state["catalog"])

    return opened, state, tmp_path


def recognise(library: Pipeline, vector: np.ndarray, *, stop: str = "done") -> uuid.UUID:
    """One image through the pipeline, stopping where a crash would. `stop` is `execute` (FINAL
    written, not accepted), `accept` (accepted, index not applied) or `done`."""
    library.perception.vector = vector
    run_id = library.execute(library.import_image())
    if stop != "execute":
        library.accept(run_id, apply_index=stop == "done")
    return run_id


@pytest.mark.parametrize("stop_b", ["done", "accept", "execute"])
def test_recognition_survives_restart_and_a_rebuilt_index(story: Any, stop_b: str) -> None:
    opened, _state, _tmp_path = story

    with opened() as lib:  # --- first process
        run_a = recognise(lib, A)
        assert lib.count(Identity) == 1  # A created I1
        run_b = recognise(lib, B, stop=stop_b)

    with opened() as lib:  # --- restart: recovery finishes whatever B left
        assert lib.perception.calls == 0  # recovery never ran ML
        with lib.lib.session_factory() as session:
            runs = list(session.scalars(select(ProcessingRun.state)))
        assert sorted(runs) == ["COMPLETED", "COMPLETED"]
        assert lib.count(Identity) == 1  # B matched I1: no new identity
        run_c = recognise(lib, C)  # C creates I2
        assert lib.count(Identity) == 2
        with lib.lib.session_factory() as session:
            assert not list(
                session.scalars(select(IndexOperation).where(IndexOperation.state != "APPLIED"))
            )
        space = lib.space_id
        index_directory = lib.lib.coordinator.index_directory(space)

    # the index is lost between processes; SQLite still holds every vector
    assert index_directory.exists()
    shutil.rmtree(index_directory)

    with opened() as lib:  # --- restart with no index
        assert lib.lib.startup.indexes_rebuilt == [space]
        rebuilt = lib.global_index(space)
        assert len(rebuilt) == 3  # A, B and C are in it again
        run_d = recognise(lib, D)  # D matches I1 through the rebuilt index

        with lib.lib.session_factory() as session:
            identities = list(session.scalars(select(Identity).order_by(Identity.created_at)))
            kinds = sorted(session.scalars(select(Evidence.kind)))
            representations = list(session.scalars(select(Representation)))
        assert len(identities) == 2
        assert all(i.state == "ACTIVE" for i in identities)
        assert kinds == ["IDENTITY_CREATED"] * 2 + ["IDENTITY_MATCHED"] * 2
        assert lib.count(Occurrence) == 4
        assert all(r.state == "ACTIVE" for r in representations)
        identity_of = {r.processing_run_id: r.identity_id for r in representations}
        i1, i2 = identity_of[run_a], identity_of[run_c]
        assert i1 is not None
        assert i2 is not None
        assert i1 != i2
        assert identity_of[run_b] == i1  # B matched I1
        assert identity_of[run_d] == i1  # D matched I1 through the rebuilt index
        with lib.lib.session_factory() as session:
            assert not list(
                session.scalars(select(IndexOperation).where(IndexOperation.state != "APPLIED"))
            )
        assert len(lib.global_index(space)) == 4
