"""A camera session's runtime on this machine: latency per provider and a soak (M7 step 7; TST-073
to TST-077).

    PYTHONPATH=. uv run python benchmarks/camera_soak.py --picture <a photograph with one face> \\
        --state-from local-models/state --workdir <a Git-ignored scratch folder> \\
        --report <workdir>/camera-soak.json [--minutes 10] [--providers ...] [--searches 30]

No camera is used. The picture is turned by the pinned ffmpeg into a looping clip (the face shown
for 3 seconds of every 10, black otherwise) and read through the real capture pipe in real time,
as a camera would be (`-re`), at the session's sampling rate. Everything else is the
application's own:
a fresh library in `--workdir` (never the owner's library), the installed model package and policy
**copied** from `--state-from` (nothing there is written), the real worker and lease, the real
session, encounters, acceptance and index.

1. **Latency** (per provider in `--providers`, each a fresh worker): detect and embed times of the
   picture, p50 and p95 over `--samples` runs, and the provider that actually ran.
2. **Soak** (the first provider list): a session runs for `--minutes` while a face search arrives
   every `--search-every` seconds (interactive class) and a background thread asks the worker
   for a detection every `--background-every` seconds (background class, as batch work does).
   Reported: frames read and dropped, encounters recorded, the worker lease's waits per class
   (p50, p95, max), the process's memory at the start and end and its growth, and the number of
   indexed faces (USearch growth).

The report is written to `--report`; nothing of the picture or the frames is kept outside the
scratch folder, which the caller deletes. A local measurement, not part of CI.
"""

import argparse
import base64
import ctypes
import dataclasses
import json
import math
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from backend.api.real import ClientPool, policy_path, real_processing
from backend.api.routes.face_search import search_picture
from backend.api.startup import LibrarySettings, MediaLimits, create_backend_app
from backend.app.cameras.session import CameraSettings
from backend.app.memory.index_coordinator import RetryPolicy
from backend.app.memory.models import Representation, RepresentationState
from backend.infrastructure.db.unit_of_work import TransactionRetry
from backend.infrastructure.media.camera import (
    CaptureDevice,
    FfmpegFrameSource,
    capture_command,
)
from backend.infrastructure.media.image import decode_image
from backend.infrastructure.media.video import NO_WINDOW, media_tools
from backend.ml.supervisor.lease import ServiceClass, TurnRecord, WorkerLease

PACKAGE_DIRS = ("runtime", "policies")


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(1, math.ceil(p / 100 * len(ordered))) - 1]


def summary(values: list[float]) -> dict[str, float | int | None]:
    return {
        "count": len(values),
        "p50": percentile(values, 50),
        "p95": percentile(values, 95),
        "max": max(values) if values else None,
    }


def memory_bytes() -> int:
    """This process's working set (Windows), or 0 elsewhere."""
    windll = getattr(ctypes, "windll", None)
    if windll is None:  # (not Windows)
        return 0

    class Counters(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("PageFaultCount", ctypes.c_ulong),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    counters = Counters()
    counters.cb = ctypes.sizeof(Counters)
    current = windll.kernel32.GetCurrentProcess
    current.restype = ctypes.c_void_p  # (a 64-bit pseudo-handle, not a C int)
    info = windll.psapi.GetProcessMemoryInfo
    info.argtypes = [ctypes.c_void_p, ctypes.POINTER(Counters), ctypes.c_ulong]
    info(current(), ctypes.byref(counters), counters.cb)
    return int(counters.WorkingSetSize)


def make_clip(tools_dir: Path, picture: Path, clip: Path) -> None:
    """Ten seconds: the picture for 3, black for 7, at 25 fps (looped by the reader)."""
    ffmpeg = media_tools(tools_dir).ffmpeg
    graph = "[1:v]scale=640:-2[face];[0:v][face]overlay=(W-w)/2:(H-h)/2:enable='lt(t,3)'"
    subprocess.run(
        [str(ffmpeg), "-v", "error", "-y", "-f", "lavfi",
         "-i", "color=c=black:size=1280x720:rate=25", "-loop", "1", "-i", str(picture),
         "-filter_complex", graph, "-t", "10", "-c:v", "mpeg4", "-q:v", "3", str(clip)],
        check=True, capture_output=True, creationflags=NO_WINDOW,
    )  # fmt: skip


def scratch_state(source: Path, target: Path) -> None:
    """The installed package and policy copied into a scratch state root (read-only use of the
    real one: nothing under `source` is written)."""
    for name in PACKAGE_DIRS:
        if (source / name).is_dir():
            shutil.copytree(source / name, target / name, dirs_exist_ok=True)


def settings_for(workdir: Path, state: Path) -> LibrarySettings:
    return LibrarySettings(
        library_root=workdir / "library",
        local_state_root=state,
        clock=lambda: datetime.now(UTC),
        new_id=uuid.uuid4,
        retry=RetryPolicy(max_attempts=3, backoff=lambda n: timedelta(seconds=n)),
        transaction_retry=TransactionRetry(max_attempts=5, backoff=lambda n: 0.1 * n),
        index_batch=200,
        max_index_passes=10,
    )


class Running:
    """The application in this process, on the scratch library, with the real profile."""

    def __init__(self, workdir: Path, state: Path, providers: tuple[str, ...], clip: Path):
        self.records: list[TurnRecord] = []
        self.pool = ClientPool(uuid.uuid4)
        self.pool.lease = WorkerLease(observe=self.records.append)
        self.plans: list[
            Any
        ] = []  # the plans clients were made for (the session's, for contention)
        made = self.pool.client_for

        def client_for(plan: Any) -> Any:
            self.plans.append(plan)
            return made(plan)

        self.pool.client_for = client_for  # type: ignore[method-assign]
        settings = settings_for(workdir, state)
        (workdir / "library").mkdir(parents=True, exist_ok=True)
        processing = real_processing(settings, providers=providers, pool=self.pool)
        tools = media_tools(state)

        def open_camera(device: CaptureDevice, camera: CameraSettings) -> FfmpegFrameSource:
            looped = ["-re", "-stream_loop", "-1", "-i", str(clip)]
            command = capture_command(
                tools, looped, rate=camera.sample_fps, max_side=camera.max_side
            )
            return FfmpegFrameSource(command, max_pixels=camera.max_side**2)

        processing = dataclasses.replace(processing, open_camera=open_camera)
        token = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
        self.app = create_backend_app(
            token, settings, processing=processing, media_limits=MediaLimits(10**8, 10**8)
        )
        self.processing = processing

    def run(self, body: Callable[[Any], dict[str, Any]]) -> dict[str, Any]:
        import anyio

        result: dict[str, Any] = {}

        async def main() -> None:
            async with self.app.router.lifespan_context(self.app):
                backend = self.app.state.backend
                await anyio.to_thread.run_sync(backend.settled.wait, 120)
                result.update(await anyio.to_thread.run_sync(body, backend))

        anyio.run(main)
        return result


def latency(workdir: Path, state: Path, providers: tuple[str, ...], clip: Path,
            picture: Path, samples: int) -> dict[str, Any]:  # fmt: skip
    running = Running(workdir / f"latency-{'-'.join(providers)}", state, providers, clip)
    data = picture.read_bytes()

    def body(backend: Any) -> dict[str, Any]:
        library = backend.library
        times = []
        for _ in range(samples + 1):  # (the first loads the model and is reported apart)
            began = time.perf_counter()
            search_picture(library, backend.processing, data)
            times.append(time.perf_counter() - began)
        detect = [r.held for r in running.records if r.held is not None]
        return {
            "providers": list(providers),
            "ran": running.pool.provider_state(),
            "first_search_s": times[0],
            "search_s": summary(times[1:]),
            "worker_turn_s": summary(detect[2:]),
        }

    return running.run(body)


def soak(workdir: Path, state: Path, providers: tuple[str, ...], clip: Path, picture: Path,
         minutes: float, search_every: float,
         background_every: float) -> dict[str, Any]:  # fmt: skip
    running = Running(workdir / "soak", state, providers, clip)
    data = picture.read_bytes()

    def body(backend: Any) -> dict[str, Any]:
        cameras, library = backend.cameras, backend.library
        camera = cameras.configure("Soak", CaptureDevice("synthetic", None))
        memory_start = memory_bytes()
        began = time.monotonic()
        cameras.start(camera)
        stop = threading.Event()
        searches: list[float] = []

        def search() -> None:
            while not stop.wait(search_every):
                t = time.perf_counter()
                search_picture(library, backend.processing, data)
                searches.append(time.perf_counter() - t)

        def background() -> None:
            """Batch work on the same worker: a detection every `background_every` seconds,
            outside any interactive or live scope (the background class)."""
            pixels = decode_image(data, max_pixels=10**8).pixels
            while not stop.wait(background_every):
                if running.plans:
                    running.pool.client_for(running.plans[-1]).detect(pixels)

        searcher = threading.Thread(target=search, daemon=True)
        searcher.start()
        worker = threading.Thread(target=background, daemon=True)
        worker.start()
        samples = []
        while time.monotonic() - began < minutes * 60:
            time.sleep(5)
            status = cameras.status(camera)
            samples.append(
                {
                    "t": round(time.monotonic() - began, 1),
                    "frames": status.frames,
                    "dropped": status.dropped,
                    "encounters": status.encounters,
                    "memory": memory_bytes(),
                }  # fmt: skip
            )
        stop.set()
        searcher.join(120)
        worker.join(120)
        cameras.stop(camera)
        status = cameras.status(camera)
        memory_end = memory_bytes()
        indexed = library.unit_of_work.read(
            lambda s: s.scalar(
                select(func.count())
                .select_from(Representation)
                .where(Representation.state == RepresentationState.ACTIVE)
            )
        )
        waits: dict[str, list[float]] = {c.value: [] for c in ServiceClass}
        for record in running.records:
            if record.waited is not None:
                waits[record.service.value].append(record.waited)
        return {
            "providers": list(providers),
            "ran": running.pool.provider_state(),
            "minutes": minutes,
            "frames": status.frames,
            "dropped": status.dropped,
            "encounters": status.encounters,
            "ended": status.state,
            "failure_code": status.failure_code,
            "searches": summary(searches),
            "lease_wait_s": {name: summary(values) for name, values in waits.items()},
            "memory_start_mb": round(memory_start / 2**20, 1),
            "memory_end_mb": round(memory_end / 2**20, 1),
            "memory_growth_mb": round((memory_end - memory_start) / 2**20, 1),
            "memory_samples_mb": [round(s["memory"] / 2**20, 1) for s in samples],
            "indexed_faces": indexed,
            "samples": samples,
        }

    return running.run(body)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--picture", type=Path, required=True)
    parser.add_argument("--state-from", type=Path, required=True)
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--minutes", type=float, default=10)
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--search-every", type=float, default=20)
    parser.add_argument("--background-every", type=float, default=0.5)
    parser.add_argument(
        "--providers",
        nargs="+",
        default=["DmlExecutionProvider,CPUExecutionProvider", "CPUExecutionProvider"],
        help="provider lists for the latency runs; the first is used for the soak",
    )
    parser.add_argument("--skip-soak", action="store_true")
    args = parser.parse_args()
    if not policy_path(args.state_from, "insightface-buffalo-l").is_file():
        sys.exit("no installed policy under --state-from")
    args.workdir.mkdir(parents=True, exist_ok=True)
    state = args.workdir / "state"
    scratch_state(args.state_from, state)
    clip = args.workdir / "clip.mp4"
    make_clip(state, args.picture, clip)
    report: dict[str, Any] = {
        "when": datetime.now(UTC).isoformat(),
        "machine": {"platform": sys.platform, "cpus": os.cpu_count()},
        "latency": [],
    }
    for providers in args.providers:
        chosen = tuple(p for p in providers.split(",") if p)
        report["latency"].append(
            latency(args.workdir, state, chosen, clip, args.picture, args.samples)
        )
        args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if not args.skip_soak:
        first = tuple(p for p in args.providers[0].split(",") if p)
        report["soak"] = soak(
            args.workdir,
            state,
            first,
            clip,
            args.picture,
            args.minutes,
            args.search_every,
            args.background_every,
        )
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "soak"}, indent=2))
    if "soak" in report:
        print(json.dumps({k: v for k, v in report["soak"].items() if k != "samples"}, indent=2))


if __name__ == "__main__":
    main()
