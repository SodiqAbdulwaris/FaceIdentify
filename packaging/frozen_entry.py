"""Entry point of the frozen backend (PyInstaller): `faceidentify-backend.exe <host arguments>`.

The ML worker is a `spawn`ed child of the same executable. A frozen executable must call
`multiprocessing.freeze_support()` first: it recognises the child's `--multiprocessing-fork`
command line, runs the worker and exits, so no separate worker executable exists.

`--probe-providers` (a build check, used by `packaging/check_frozen_backend.py`) prints the ONNX
Runtime providers as seen by this process and by a spawned child, then exits.
"""

import json
import multiprocessing
import sys
from multiprocessing.connection import Connection


def _child_providers(connection: Connection) -> None:
    import onnxruntime

    connection.send(onnxruntime.get_available_providers())


def probe_providers() -> int:
    import onnxruntime

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
                "usearch_size": len(index),
                "avif": features.check("avif"),
            }
        )
    )
    return 0 if child_providers else 1


if __name__ == "__main__":
    multiprocessing.freeze_support()
    if sys.argv[1:] == ["--probe-providers"]:
        sys.exit(probe_providers())
    from backend.api.host import main

    sys.exit(main())
