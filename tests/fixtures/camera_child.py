"""A child process that runs a camera session through the real pipeline to a named stage, says READY
and waits to be killed (M7 step 4; TST-071, TST-076 live half). Started by
`tests/recovery/test_camera_process_kill.py`.

The red person visits twice. Stages: `open` (the first visit accepted, the second one in front of
the camera, nothing of it written), `private` (the second visit's faces written as the run's private
output, not yet decided or accepted).
"""

import json
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from backend.app.lifecycle import open_library
from backend.app.memory.index_coordinator import RetryPolicy
from backend.infrastructure.db.unit_of_work import TransactionRetry
from tests.fixtures.camera_pipeline import Camera, empty, frames, visit
from tests.fixtures.pipeline import Pipeline


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
        camera = Camera(pipeline, camera_id=uuid.UUID(catalog["camera_id"]))
        executor = camera.executor()
        decide = executor._decide

        def decide_or_park(*args: Any) -> Any:
            if stage == "private" and camera.closed:  # (the second visit's decision)
                park()
            return decide(*args)

        executor._decide = decide_or_park  # type: ignore[method-assign, assignment]

        def scenes() -> Any:
            yield from frames(*visit("red", 0, 1), *empty(1, 1.6), *visit("red", 2.6, 1))
            if stage == "private":  # the second visit closes: written, then parked at its decision
                yield from frames(*empty(3.6, 1.6))
            park()  # stage `open`: the second visit has not closed

        executor.run(camera.start(), scenes(), closed=camera.closed.append)
        raise SystemExit(f"stage {stage!r} was never reached")
