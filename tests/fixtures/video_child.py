"""A child process that runs one video through the real pipeline to a named stage, says READY and
waits to be killed (M6 step 7; TST-067). Started by `tests/recovery/test_video_process_kill.py`.

Stages: `chunk` (the first chunk committed, the second being detected), `pausing` (a pause asked,
the first chunk not yet settled), `final` (FINAL written, not accepted).
"""

import json
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from backend.app.lifecycle import open_library
from backend.app.memory.index_coordinator import RetryPolicy
from backend.app.processing.pause import PauseProcessingUseCase
from backend.infrastructure.db.unit_of_work import TransactionRetry
from tests.fixtures.pipeline import Pipeline
from tests.fixtures.video_pipeline import video_executor, video_perception


def park() -> None:
    print("READY", flush=True)
    sys.stdin.read()  # alive and holding the library until the parent kills the process tree


def main() -> None:
    library, local, instant, spec_path, stage = sys.argv[1:6]
    fixed = datetime.fromisoformat(instant)

    def now() -> datetime:
        return fixed

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
        perception = video_perception(pipeline)
        pipeline.enqueue(uuid.UUID(catalog["video_id"]))
        started = pipeline.scheduler().claim_source_job("child")
        assert started is not None
        run_id = started.job.processing_run_id
        assert run_id is not None

        def at(number: int) -> None:
            if stage == "chunk" and number == 5:
                park()
            if stage == "pausing" and number == 2:
                PauseProcessingUseCase(lib.unit_of_work, clock=now).pause(run_id)
            if stage == "pausing" and number == 3:
                park()

        perception.on_detect = at
        video_executor(pipeline).execute(started)
        if stage == "final":
            park()
        raise SystemExit(f"stage {stage!r} was never reached")
