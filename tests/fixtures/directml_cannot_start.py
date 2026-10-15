"""A worker factory for a machine where DirectML is listed but cannot start.

The Windows ML build always lists `DmlExecutionProvider`; on a machine without a DirectX 12 adapter
creating the session raises. This factory reproduces that in the spawned worker process (on any
operating system, so CI runs it too) and is otherwise the real perception worker.
"""

from typing import Any

import onnxruntime as ort

from backend.ml.contracts.protocol import MLOperation
from backend.ml.worker.loop import Handler
from backend.ml.worker.perception_handlers import build_handlers as real_handlers

DIRECTML = "DmlExecutionProvider"
NO_ADAPTER = "887A0002 The object was not found: there is no adapter with the specified ordinal"


def build_handlers(config_text: str) -> dict[MLOperation, Handler]:
    real_session = ort.InferenceSession
    cpu_only = [name for name in ort.get_available_providers() if name != DIRECTML]

    def session(model: Any, *args: Any, providers: list[str], **kwargs: Any) -> Any:
        if DIRECTML in providers:
            raise RuntimeError(NO_ADAPTER)
        return real_session(model, *args, providers=providers, **kwargs)

    ort.get_available_providers = lambda: [DIRECTML, *cpu_only]
    ort.InferenceSession = session
    return real_handlers(config_text)
