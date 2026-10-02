"""Loading an ONNX model for the worker: verified bytes, an exact provider, no silent fallback.

What is executed is what was hashed: the file is read once, its SHA-256 is compared with the
recorded one, and the session is created from those same bytes (not from the path again), so a file
swapped between the check and the load cannot run (SEC-007).

The provider is exactly the one asked for. ONNX Runtime will quietly run on the CPU when a
requested accelerator cannot start; the worker never decides that (Architecture 9: the backend
decides fallback), so a provider that is not available, or one that did not become the session's
first, is an error with a code the backend can act on.
"""

import hashlib
from pathlib import Path

import onnxruntime as ort

from backend.ml.contracts.protocol import MLErrorCode
from backend.ml.worker.loop import WorkerError


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
    try:
        session = ort.InferenceSession(data, sess_options=options, providers=[provider])
    except Exception as error:  # ONNX Runtime raises its own exception types for a bad model
        raise WorkerError(
            MLErrorCode.COMPONENT_LOAD_FAILED, f"the model cannot be loaded ({error})"
        ) from error
    if session.get_providers()[0] != provider:
        raise WorkerError(
            MLErrorCode.RUNTIME_INITIALIZATION_FAILED,
            f"{provider} was requested but the session runs on {session.get_providers()[0]}",
        )
    return session
