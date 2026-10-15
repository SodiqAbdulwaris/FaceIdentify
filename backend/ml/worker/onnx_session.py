"""Loading an ONNX model for the worker: verified bytes, an exact provider, no silent fallback.

What is executed is what was hashed: the file is read once, its SHA-256 is compared with the
recorded one, and the session is created from those same bytes (not from the path again), so a file
swapped between the check and the load cannot run (SEC-007).

The provider is exactly the one asked for. ONNX Runtime will quietly run on the CPU when a
requested accelerator cannot start; the worker never decides that (Architecture 9: the backend
decides fallback), so a provider that is not available, or one that did not become the session's
first, is an error with a code the backend can act on.

An accelerator that is listed but cannot start (DirectML with no DirectX 12 adapter, a GPU driver
too old for CUDA) makes `InferenceSession` raise. For an accelerator that is a provider failure
(`RUNTIME_INITIALIZATION_FAILED`), so the backend falls back to the next variant. A broken model is
not: ONNX Runtime reports it with its own exception types (unparseable bytes, an invalid graph, an
operator nothing implements) on every provider, and those stay `COMPONENT_LOAD_FAILED`, so no
fallback is tried and a plan without a CPU variant still says what is wrong. On the CPU every load
failure is the model's.
"""

import hashlib
from pathlib import Path

import onnxruntime as ort
from onnxruntime.capi import onnxruntime_pybind11_state as ort_errors

from backend.ml.contracts.protocol import MLErrorCode
from backend.ml.worker.loop import WorkerError

CPU = "CPUExecutionProvider"
DIRECTML = "DmlExecutionProvider"
# What ONNX Runtime raises for the model itself, whichever provider was asked for.
MODEL_ERRORS = (
    ort_errors.InvalidProtobuf,
    ort_errors.InvalidGraph,
    ort_errors.NoModel,
    ort_errors.NotImplemented,
)


def load_session(path: Path, sha256: bytes, provider: str) -> ort.InferenceSession:
    try:
        data = path.read_bytes()
    except OSError as error:
        raise WorkerError(
            MLErrorCode.COMPONENT_LOAD_FAILED, f"the model file cannot be read ({error})"
        ) from error
    if hashlib.sha256(data).digest() != sha256:
        raise WorkerError(
            MLErrorCode.COMPONENT_LOAD_FAILED, "the model file does not match its recorded digest"
        )
    if provider not in ort.get_available_providers():
        raise WorkerError(
            MLErrorCode.RUNTIME_VARIANT_NOT_AVAILABLE,
            f"{provider} is not available on this machine",
        )
    options = ort.SessionOptions()
    options.log_severity_level = 3  # errors only: the worker's stderr is for the worker's own words
    if provider == DIRECTML:  # DirectML supports neither memory patterns nor parallel execution
        options.enable_mem_pattern = False
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    try:
        session = ort.InferenceSession(data, sess_options=options, providers=[provider])
    except Exception as error:  # ONNX Runtime raises its own exception types for a bad model
        if provider != CPU and not isinstance(error, MODEL_ERRORS):
            raise WorkerError(
                MLErrorCode.RUNTIME_INITIALIZATION_FAILED, f"{provider} cannot start ({error})"
            ) from error
        raise WorkerError(
            MLErrorCode.COMPONENT_LOAD_FAILED, f"the model cannot be loaded ({error})"
        ) from error
    if session.get_providers()[0] != provider:
        raise WorkerError(
            MLErrorCode.RUNTIME_INITIALIZATION_FAILED,
            f"{provider} was requested but the session runs on {session.get_providers()[0]}",
        )
    return session
