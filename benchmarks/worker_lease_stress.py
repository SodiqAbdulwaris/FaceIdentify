"""Stress the one worker: background processing with face searches arriving on top (#175, D5).

    uv run python benchmarks/worker_lease_stress.py                      # simulated inference
    uv run python benchmarks/worker_lease_stress.py --real \\
        --local-state-root <dir> --providers DmlExecutionProvider,CPUExecutionProvider face.jpg

A background thread processes `--images` images one job at a time (as the scheduler does: a fresh
client per job, a detection then a representation, each its own turn on the worker), while face
searches arrive at random (exponential gaps, `--search-gap-ms` on average, seeded), at most three in
flight (the route's `face_search_slots`). This is run once per fairness value in `--bursts`, and for
each it reports, per class, the wait for the worker (p50, p95, max), the inference time, the
background throughput and the searches' end-to-end time.

Simulated mode (the default) holds the real `WorkerLease` for `--detect-ms` and `--represent-ms`
(with a little seeded jitter) instead of running a model, so the numbers measure arbitration alone.
`--real` runs the installed models through the real `ClientPool` and worker process on the given
picture(s), which must show a face (a picture with none is never represented); nothing about the
picture is printed or kept, only timings. A local measurement, not part of CI.
"""

import argparse
import json
import math
import random
import statistics
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import Any

from backend.ml.supervisor.lease import TurnRecord, WorkerLease, interactive

SEARCH_SLOTS = 3  # the face search route's limit (backend/api/startup.py, face_search_slots)


def percentile(values: list[float], p: float) -> float:
    """The nearest-rank percentile: the smallest value with at least p% of the values at or below
    it (so the p50 of 1, 2, 3, 4 is 2, and the p95 of 20 values is the 19th)."""
    if not values:
        return float("nan")
    ordered = sorted(values)
    return ordered[max(1, math.ceil(p / 100 * len(ordered))) - 1]


class Simulated:
    """A perception client whose inferences hold the lease for a set time instead of a model."""

    def __init__(self, lease: WorkerLease, detect_s: float, represent_s: float, rng: random.Random):
        self._lease, self._detect, self._represent = lease, detect_s, represent_s
        self._rng, self._rng_lock = rng, threading.Lock()
        self._in_turn = False

    @contextmanager
    def turn(self) -> Iterator[None]:
        """One turn for several requests, as `PerceptionClient.turn` (a video batch, #242)."""
        with self._lease.held():
            self._in_turn = True
            try:
                yield
            finally:
                self._in_turn = False

    def _hold(self, seconds: float) -> None:
        with self._rng_lock:
            jitter = self._rng.uniform(0.9, 1.1)
        with nullcontext() if self._in_turn else self._lease.held():
            time.sleep(seconds * jitter)

    def detect(self, _pixels: Any) -> tuple[int]:
        self._hold(self._detect)
        return (1,)

    def represent(self, _pixels: Any, _detections: Any) -> None:
        self._hold(self._represent)


def run_once(
    burst: int,
    client_for: Callable[[WorkerLease], Any],
    pixels: Any,
    *,
    images: int,
    search_gap_s: float,
    seed: int,
    batch: int = 0,
) -> dict[str, Any]:
    """`batch` 0: the background processes images (a detection and a representation, each its own
    turn). `batch` N: it processes video frames, detecting N frames in ONE turn (#242)."""
    records: list[TurnRecord] = []
    lease = WorkerLease(burst=burst, observe=records.append)
    rng = random.Random(seed)
    searches: list[float] = []
    slots = threading.BoundedSemaphore(SEARCH_SLOTS)
    errors: list[BaseException] = []
    completed = 0  # background images detected and represented (written by `process` only)

    def process() -> None:
        nonlocal completed
        try:
            if batch:
                client = client_for(lease)  # one client for the video job
                for start in range(0, images, batch):
                    frames = min(batch, images - start)
                    with client.turn():
                        for _ in range(frames):
                            client.detect(pixels)
                    completed += frames
                return
            for _ in range(images):
                client = client_for(lease)  # a fresh client per job, as the executor gets
                found = client.detect(pixels)
                client.represent(pixels, _detections(found))
                completed += 1
        except BaseException as error:  # noqa: BLE001 - reported below
            errors.append(error)

    def search() -> None:
        started = time.perf_counter()
        try:
            client = client_for(lease)
            with interactive():
                found = client.detect(pixels)
                client.represent(pixels, _detections(found))
            searches.append(time.perf_counter() - started)
        except BaseException as error:  # noqa: BLE001 - reported below
            errors.append(error)
        finally:
            slots.release()

    began = time.perf_counter()
    background = threading.Thread(target=process)
    background.start()
    asked: list[threading.Thread] = []
    while background.is_alive():
        time.sleep(rng.expovariate(1 / search_gap_s))
        if background.is_alive() and slots.acquire(blocking=False):
            thread = threading.Thread(target=search)
            thread.start()
            asked.append(thread)
    elapsed = time.perf_counter() - began
    for thread in asked:
        thread.join()
    # (a workload error is reported with what was measured, not instead of it: see main)

    def of(cls: bool) -> dict[str, Any]:
        mine = [r for r in records if r.interactive is cls]
        waits = [r.waited * 1000 for r in mine if r.waited is not None]
        held = [r.held * 1000 for r in mine if r.held is not None]
        return {
            "requests": len(mine),
            "outcomes": {
                o: sum(r.outcome == o for r in mine) for o in ("RAN", "FAILED", "CANCELLED")
            },
            "unknown_times": sum(r.waited is None or r.held is None for r in mine),
            "wait_ms_p50": round(percentile(waits, 50), 1),
            "wait_ms_p95": round(percentile(waits, 95), 1),
            "wait_ms_max": round(max(waits, default=float("nan")), 1),
            "inference_ms_mean": round(statistics.fmean(held), 1) if held else None,
            "queued_at_grant_max": max(
                (r.queued_interactive + r.queued_background for r in mine), default=0
            ),
        }

    return {
        "burst": burst,
        "interactive": of(True),
        "background": of(False),
        # a background grant made while searches waited: the burst ran out (a fairness grant)
        "fairness_grants": sum(not r.interactive and r.queued_interactive > 0 for r in records),
        "background_images_completed": completed,
        "background_images_per_s": round(completed / elapsed, 2),  # (completed, not asked)
        "errors": sorted({type(error).__name__ for error in errors}),
        "searches": len(searches),
        "search_ms_p50": round(percentile([s * 1000 for s in searches], 50), 1),
        "search_ms_p95": round(percentile([s * 1000 for s in searches], 95), 1),
    }


def _detections(found: Any) -> Any:
    return getattr(found, "detections", found)


def real_clients(
    arguments: argparse.Namespace,
) -> tuple[Callable[[WorkerLease], Any], Any, Any, Callable[[], dict[str, str]]]:
    """The installed models behind the real pool: (client_for, pixels, close, provider state)."""
    import numpy as np
    from PIL import Image

    from backend.api.real import ClientPool
    from backend.app.runtime.package_store import RuntimePackageStore
    from backend.infrastructure.storage.layout import StorageRoots
    from scripts.smoke_real_models import plan_from

    store = RuntimePackageStore(StorageRoots(Path(), arguments.local_state_root), new_id=uuid.uuid4)
    plan = plan_from(store, arguments.key, arguments.providers.split(","))
    pool = ClientPool(uuid.uuid4)
    pixels = np.asarray(Image.open(arguments.pictures[0]).convert("RGB"), dtype=np.uint8)
    warm = pool.client_for(plan)  # start the worker and load the models before measuring
    found = warm.detect(pixels)
    assert found.detections, "the picture must show a face"
    warm.represent(pixels, found.detections)

    def client_for(lease: WorkerLease) -> Any:
        pool.lease = lease  # (each run measures on its own lease; the pool's turns read it)
        return pool.client_for(plan)

    return client_for, pixels, pool.close, pool.provider_state


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bursts", default="1,2,3,5", help="fairness values to compare")
    parser.add_argument("--images", type=int, default=200, help="background images per run")
    parser.add_argument("--search-gap-ms", type=float, default=400.0, help="mean gap")
    parser.add_argument("--detect-ms", type=float, default=40.0, help="simulated detection")
    parser.add_argument("--represent-ms", type=float, default=25.0, help="simulated embedding")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument(
        "--background-batch",
        type=int,
        default=0,
        help="0: images; N: video frames detected N to a worker turn (#242)",
    )
    parser.add_argument("--real", action="store_true", help="run the installed models")
    parser.add_argument("--local-state-root", type=Path)
    parser.add_argument("--key", default="insightface-buffalo-l")
    parser.add_argument("--providers", default="CPUExecutionProvider")
    parser.add_argument("--json", type=Path, help="also write the report here")
    parser.add_argument("pictures", nargs="*", type=Path)
    arguments = parser.parse_args()

    close: Callable[[], None] = lambda: None  # noqa: E731
    ran_on: Callable[[], dict[str, str] | None] = lambda: None  # noqa: E731
    if arguments.real:
        assert arguments.local_state_root, "--real needs --local-state-root"
        assert arguments.pictures, "--real needs a picture that shows a face"
        client_for, pixels, close, ran_on = real_clients(arguments)
    else:
        rng = random.Random(arguments.seed)
        detect_s, represent_s = arguments.detect_ms / 1000, arguments.represent_ms / 1000

        def client_for(lease: WorkerLease) -> Any:
            return Simulated(lease, detect_s, represent_s, rng)

        pixels = None
    try:
        report = {
            "mode": "real" if arguments.real else "simulated",
            "providers": arguments.providers if arguments.real else None,
            "images": arguments.images,
            "search_gap_ms": arguments.search_gap_ms,
            "background_batch": arguments.background_batch,
            "runs": [
                run_once(
                    int(burst),
                    client_for,
                    pixels,
                    images=arguments.images,
                    search_gap_s=arguments.search_gap_ms / 1000,
                    seed=arguments.seed,
                    batch=arguments.background_batch,
                )
                for burst in arguments.bursts.split(",")
            ],
            "ran_on": ran_on(),  # the provider that actually ran, and whether it was a fallback
        }
    finally:
        close()
    print(
        "burst | search wait p50/p95/max ms | job wait p50/p95/max ms | images/s | search ms"
        " | fairness grants | search ran/failed/cancelled | job ran/failed/cancelled"
    )
    for run in report["runs"]:
        i, b = run["interactive"], run["background"]
        print(
            f"{run['burst']:>5} | {i['wait_ms_p50']}/{i['wait_ms_p95']}/{i['wait_ms_max']}"
            f" | {b['wait_ms_p50']}/{b['wait_ms_p95']}/{b['wait_ms_max']}"
            f" | {run['background_images_per_s']} | {run['search_ms_p50']}/{run['search_ms_p95']}"
            f" | {run['fairness_grants']} | {_outcomes(i)} | {_outcomes(b)}"
        )
    if arguments.json:
        arguments.json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    failed = {name for run in report["runs"] for name in run["errors"]}
    if failed:
        raise SystemExit(f"the workload raised {', '.join(sorted(failed))}: see the report above")


def _outcomes(of_class: dict[str, Any]) -> str:
    counts = of_class["outcomes"]
    return f"{counts['RAN']}/{counts['FAILED']}/{counts['CANCELLED']}"


if __name__ == "__main__":
    main()
