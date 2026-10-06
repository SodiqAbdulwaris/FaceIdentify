"""A child process that runs one image through the real pipeline to a named stage, says READY and
waits to be killed (M3.2). Started by `tests/recovery/test_pipeline_process_kill.py`; it must not
finish on its own, so the kill lands exactly where the stage says.

Stages: `represent` (observations settled, embedding in flight), `decide` (private output settled,
recognition about to read the index), `final` (FINAL written, not accepted), `accept-open`
(acceptance's transaction written but not committed), `accepted` (committed, index not applied).
"""

import json
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from backend.app.lifecycle import open_library
from backend.app.memory.index_coordinator import RetryPolicy
from backend.app.processing.accept_run import AcceptProcessingRunUseCase
from backend.infrastructure.db.unit_of_work import TransactionRetry
from tests.fixtures.pipeline import Pipeline, unit


def park() -> None:
    print("READY", flush=True)
    sys.stdin.read()  # alive and holding the library until the parent kills the process tree


def main() -> None:
    library, local, instant, spec_path, stage = sys.argv[1:6]
    fixed = datetime.fromisoformat(instant)

    def now() -> datetime:
        return fixed  # the parent's clock: nothing here depends on the wall clock

    catalog = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    with open_library(
        library_root=Path(library),
        local_state_root=Path(local),
        clock=now,
        new_id=uuid.uuid4,
        retry=RetryPolicy(max_attempts=3, backoff=lambda n: timedelta(minutes=n)),
        index_batch=50,
        max_index_passes=5,
        transaction_retry=TransactionRetry(max_attempts=3, backoff=lambda n: 0.1 * n),
    ) as lib:
        pipeline = Pipeline(lib, now, uuid.uuid4, catalog)
        pipeline.perception.vector = unit(*catalog["vector"])
        if stage == "represent":
            pipeline.perception.on_represent = park
        elif stage == "decide":
            pipeline.before_global_index = park
        elif stage == "accept-open":
            real_accept = AcceptProcessingRunUseCase._accept

            def accept_then_park(self, session, run_id):  # type: ignore[no-untyped-def]
                result = real_accept(self, session, run_id)
                park()  # written in the open transaction; the kill rolls it back
                return result

            AcceptProcessingRunUseCase._accept = accept_then_park  # type: ignore[method-assign]
        run_id = pipeline.execute(uuid.UUID(catalog["source_id"]))
        if stage == "final":
            park()
        pipeline.accept(run_id, apply_index=False)
        if stage == "accepted":
            park()
        raise SystemExit(f"stage {stage!r} was never reached")
