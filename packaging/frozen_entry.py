"""Entry point of the frozen backend (PyInstaller): `faceidentify-backend.exe <host arguments>`.

The ML worker is a `spawn`ed child of the same executable. A frozen executable must call
`multiprocessing.freeze_support()` first: it recognises the child's `--multiprocessing-fork`
command line, runs the worker and exits, so no separate worker executable exists.

Three build checks. `--probe-providers` prints the ONNX Runtime providers as seen by this
process and by a spawned child, and `--probe-worker` runs one request through the real worker
process (`packaging/frozen_probe.py` supplies handlers in place of models); both are used by
`packaging/check_frozen_backend.py`. `--probe-video <file>`, used by `packaging/check_installed.py`
on an installed build, probes a video with the FFmpeg this build finds, as an installed
application does, and decodes its sampled frames.
"""

import json
import multiprocessing
import os
import sys
import uuid
from multiprocessing.connection import Connection


def _child_providers(connection: Connection) -> None:
    import onnxruntime

    connection.send(onnxruntime.get_available_providers())


def probe_providers() -> int:
    import onnxruntime

    from backend.api.real import providers_from

    context = multiprocessing.get_context("spawn")
    parent_end, child_end = context.Pipe()
    child = context.Process(target=_child_providers, args=(child_end,))
    child.start()
    child_providers = parent_end.recv() if parent_end.poll(120) else None
    child.join(30)
    import numpy
    from PIL import features
    from usearch.index import Index

    index = Index(ndim=4, metric="cos")
    index.add(1, numpy.array([1.0, 0.0, 0.0, 0.0], dtype=numpy.float32))
    print(
        json.dumps(
            {
                "process": onnxruntime.get_available_providers(),
                "child": child_providers,
                "selected": list(providers_from(os.environ)),  # what the real profile would try
                "usearch_size": len(index),
                "avif": features.check("avif"),
            }
        )
    )
    return 0 if child_providers else 1


def probe_worker() -> int:
    from backend.infrastructure.resources.shared_memory import OwnedSegment
    from backend.ml.contracts.messages import DetectFacesInput, MLRequest
    from backend.ml.contracts.protocol import MLOperation, MLStatus
    from backend.ml.supervisor.process import ProcessWorker
    from backend.ml.supervisor.supervisor import MLSupervisor, SupervisorPolicy

    policy = SupervisorPolicy(
        handshake_timeout=120,
        request_timeout=120,
        ping_timeout=30,
        shutdown_timeout=30,
        max_restarts=1,
        restart_window=600,
    )
    supervisor = MLSupervisor(lambda: ProcessWorker("frozen_probe:build_handlers"), policy)
    segment = OwnedSegment("uint8", (4, 4, 3), new_id=uuid.uuid4)
    segment.write(200)
    try:
        response = supervisor.execute(
            MLRequest(
                "probe-1",
                MLOperation.DETECT_FACES,
                "probe",
                DetectFacesInput((segment.descriptor,)),
                {},
            )
        )
        found = len(response.output.detections) if response.status is MLStatus.SUCCESS else None
        print(json.dumps({"status": str(response.status), "detections": found}))
        return 0 if found == 1 else 1
    finally:
        segment.release()
        supervisor.stop()


def probe_video(path: str) -> int:
    from pathlib import Path

    from backend.infrastructure.media.frames import sampled_frames
    from backend.infrastructure.media.video import media_tools
    from backend.infrastructure.media.video import probe_video as read_facts

    tools = media_tools(Path(sys.argv[0]).parent / "unused-state")  # (the shipped folder wins)
    facts = read_facts(tools, Path(path))
    frames = list(sampled_frames(tools, Path(path), width=facts.width, height=facts.height))
    print(
        json.dumps(
            {
                "ffmpeg": str(tools.ffmpeg),
                "width": facts.width,
                "height": facts.height,
                "duration_ms": facts.duration_ms,
                "frames": len(frames),
            }
        )
    )
    return 0 if frames else 1


if __name__ == "__main__":
    multiprocessing.freeze_support()
    if sys.argv[1:] == ["--probe-worker"]:
        sys.exit(probe_worker())
    if sys.argv[1:] == ["--probe-providers"]:
        sys.exit(probe_providers())
    if len(sys.argv) == 3 and sys.argv[1] == "--probe-video":
        sys.exit(probe_video(sys.argv[2]))
    from backend.api.host import main

    sys.exit(main())
