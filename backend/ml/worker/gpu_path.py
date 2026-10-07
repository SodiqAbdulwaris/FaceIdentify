"""Making a machine-local GPU build of ONNX Runtime visible to the worker.

`onnxruntime-gpu` and the NVIDIA CUDA 12 libraries are not part of the locked environment (they
are large and machine-specific). They live in a directory the owner installs into, named by the
`FACEIDENTIFY_ORT_GPU_DIR` environment variable. The worker is a spawned process, so it activates
the directory itself, before any model library is imported: the directory goes first on `sys.path`
(so its `onnxruntime` shadows the CPU one) and every `nvidia/*/bin` in it goes on the DLL search
path. With the variable unset nothing changes, and a worker that cannot start CUDA fails with a
provider error the backend turns into the CPU fallback (`load_session` never falls back itself).
The variable is trusted, owner-set configuration: an absolute path of a directory the owner
installed into, which can shadow any module under it by design.
"""

import os
import sys
from pathlib import Path
from typing import Any

GPU_DIR_ENV = "FACEIDENTIFY_ORT_GPU_DIR"

# The handles `os.add_dll_directory` returns: a directory stays on the search path until its handle
# is closed, so they are kept for the life of the process.
_dll_handles: list[Any] = []


def activate(environ: dict[str, str] | os._Environ[str] = os.environ) -> Path | None:
    """Activate the GPU directory the environment names, if any; returns it when activated."""
    value = environ.get(GPU_DIR_ENV)
    if not value:
        return None
    root = Path(value)
    if not root.is_dir():
        return None
    bins = sorted(str(path) for path in (root / "nvidia").glob("*/bin") if path.is_dir())
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    for directory in bins:
        _dll_handles.append(os.add_dll_directory(directory))  # type: ignore[attr-defined,unused-ignore]
    if bins:
        environ["PATH"] = os.pathsep.join([*bins, environ.get("PATH", "")])
    return root
