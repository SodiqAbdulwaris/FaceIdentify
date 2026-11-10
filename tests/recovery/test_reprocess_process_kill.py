"""Reprocessing in a real process, killed before, during and after activation (M6 step 1, issue
180 acceptance test 3; TST-067; persistence 12.1 item 6).

The parent processes one image to an accepted first generation (V1). A child then reprocesses it
through the real pipeline and parks at a named stage; the parent kills the child's whole process
tree and reopens the library. At every point exactly one generation is authoritative, and no face
is counted twice: before FINAL the reprocess run is only interrupted and V1 stays; after FINAL (and
during the open activation transaction) recovery activates V2 once, without perception; after the
commit only the index has to converge.
"""

import json
from typing import Any

import pytest
from sqlalchemy import select

from backend.app.memory.models import IndexOperation, Observation, Occurrence, Representation
from backend.app.processing.models import ProcessingRun
from backend.app.sources.models import Source
from tests.fixtures.deterministic import FrozenClock, SeededUUIDs
from tests.fixtures.pipeline import Pipeline, prepare_catalog
from tests.recovery.test_pipeline_process_kill import Library, indexed_keys


@pytest.fixture
def library(tmp_path: Any, clock: FrozenClock, new_id: SeededUUIDs) -> Library:
    lib = Library(tmp_path, clock, new_id)
    with lib.open() as opened:
        lib.catalog = prepare_catalog(opened, clock, new_id)
        pipeline = Pipeline(opened, clock, new_id, lib.catalog)
        source_id = pipeline.import_image()
        pipeline.accept(pipeline.execute(source_id), apply_index=True)
        lib.catalog["source_id"] = str(source_id)
        lib.catalog["vector"] = [1.0, 0.0, 0.0, 0.0]
        lib.catalog["reprocess"] = True
    lib.spec.write_text(json.dumps(lib.catalog), encoding="utf-8")
    return lib


def generations(pipeline: Pipeline) -> dict[str, Any]:
    with pipeline.lib.session_factory() as session:
        runs = {run.id: run for run in session.scalars(select(ProcessingRun))}
        (source,) = session.scalars(select(Source))
        return {
            "current": source.current_processing_run_id,
            "runs": sorted((r.state, r.supersedes_run_id is not None) for r in runs.values()),
            "observations": sorted(
                (o.state, runs[o.processing_run_id].supersedes_run_id is not None)
                for o in session.scalars(select(Observation))
            ),
            "active_representations": len(
                list(
                    session.scalars(select(Representation).where(Representation.state == "ACTIVE"))
                )
            ),
            "active_occurrences": len(
                list(session.scalars(select(Occurrence).where(Occurrence.state == "ACTIVE")))
            ),
            "first": next(r.id for r in runs.values() if r.supersedes_run_id is None),
        }


def test_a_crash_before_final_leaves_the_first_generation(library: Library) -> None:
    library.kill_at("decide")

    with library.open() as reopened:
        pipeline = library.pipeline(reopened)
        assert pipeline.perception.calls == 0
        seen = generations(pipeline)
        assert seen["current"] == seen["first"]
        assert seen["runs"] == [("COMPLETED", False), ("INTERRUPTED", True)]
        assert seen["observations"] == [("ACTIVE", False), ("PENDING", True)]
        assert seen["active_representations"] == seen["active_occurrences"] == 1

    with library.open() as again:
        assert again.startup.repaired_nothing


@pytest.mark.parametrize("stage", ["final", "accept-open", "accepted"])
def test_a_crash_after_final_converges_to_the_new_generation_once(
    library: Library, stage: str
) -> None:
    library.kill_at(stage)

    with library.open() as reopened:
        pipeline = library.pipeline(reopened)
        assert pipeline.perception.calls == 0  # recovery never runs perception
        report = reopened.startup
        assert len(report.finalizing.accepted) == (0 if stage == "accepted" else 1)
        assert report.finalizing.not_resumable == []
        seen = generations(pipeline)
        assert seen["current"] != seen["first"]
        assert seen["runs"] == [("COMPLETED", False), ("COMPLETED", True)]
        assert seen["observations"] == [("ACTIVE", True), ("SUPERSEDED", False)]
        assert seen["active_representations"] == seen["active_occurrences"] == 1  # never twice
        with reopened.session_factory() as session:
            assert sorted(set(session.scalars(select(IndexOperation.state)))) == ["APPLIED"]
        assert len(indexed_keys(pipeline)) == 1  # only the new generation is in the index

    with library.open() as again:
        assert again.startup.repaired_nothing
        assert generations(library.pipeline(again))["current"] == seen["current"]
