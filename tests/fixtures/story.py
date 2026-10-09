"""A real library story shared by the deletion and forgetting tests.

Only perception is planted (unit-length 4-d vectors; no weights). Everything else is real: SQLite
through `open_library`, the scheduler, the executor, acceptance, the IndexCoordinator, USearch, the
managed files and restarts (`opened()` can be entered again on the same folders).
"""

import io
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.lifecycle import open_library
from backend.app.memory.index_coordinator import RetryPolicy
from backend.app.memory.models import Observation
from backend.app.sources.artifact_storage import storage_key_for
from backend.app.sources.models import ArtifactKind
from backend.infrastructure.db.unit_of_work import TransactionRetry
from tests.factories.models import ModelFactory
from tests.fixtures.deterministic import FrozenClock, SeededUUIDs
from tests.fixtures.pipeline import Pipeline, prepare_catalog, unit

A = unit(1, 0, 0, 0)
B = unit(0.95, 0.1, 0, 0)  # near A
C = unit(0, 1, 0, 0)  # unlike A and B


class SimulatedCrash(BaseException):
    """The process dying: no `except Exception` handler gets to tidy up after it."""


@pytest.fixture
def opened(tmp_path: Path, clock: FrozenClock, new_id: SeededUUIDs) -> Any:
    (tmp_path / "library").mkdir()
    state: dict[str, Any] = {}

    @contextmanager
    def opening() -> Iterator[Pipeline]:
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

    return opening


def process(lib: Pipeline, vector: np.ndarray) -> tuple[uuid.UUID, uuid.UUID]:
    """One image through the pipeline to an accepted, indexed result: (source id, run id)."""
    lib.perception.vector = vector
    source_id = lib.import_image()
    run_id = lib.execute(source_id)
    lib.accept(run_id, apply_index=True)
    return source_id, run_id


def only(lib: Pipeline, query: Any) -> list[Any]:
    with lib.lib.session_factory() as session:
        return list(session.scalars(query))


def files_containing(lib: Pipeline, vector: np.ndarray) -> list[str]:
    """The database file, its log and every index file whose bytes contain the vector."""
    needle = vector.tobytes()
    database = Path(str(lib.lib.engine.url.database))
    files = [database, database.with_name(database.name + "-wal")]
    files += [p for p in lib.lib.roots.local_state_root.rglob("*") if p.is_file()]
    return sorted({p.name for p in files if p.exists() and needle in p.read_bytes()})


def add_face_crop(lib: Pipeline, source_id: uuid.UUID) -> uuid.UUID:
    """Give the Source's observation a managed face-crop file, as a crop writer would."""
    with Session(lib.lib.engine) as session:
        observation = session.scalars(
            select(Observation).where(Observation.source_id == source_id)
        ).one()
        build = ModelFactory(session, lib.clock, lib.new_id)  # type: ignore[arg-type]
        artifact = build.artifact(kind=ArtifactKind.FACE_CROP)
        artifact.storage_key = storage_key_for(ArtifactKind.FACE_CROP, artifact.id)
        lib.lib.store.store(artifact.storage_key, io.BytesIO(b"a face crop"))
        observation.face_crop_artifact_id = artifact.id
        session.commit()
        return artifact.id
