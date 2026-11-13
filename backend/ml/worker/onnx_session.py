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
not: ONNX Runtime reports it with its own exception types (unparseable bytes, a model with no
graph, an invalid graph, an operator nothing implements) on every provider, and those stay
`COMPONENT_LOAD_FAILED`, so no fallback is tried and a plan without a CPU variant still says what is
wrong. On the CPU every load failure is the model's.

**Which GPU DirectML runs on** (owner decision 2026-11-12: "if there is a GPU that supports it, use
it; with only a CPU, run everything on the CPU", with no manual step). DirectML is asked for the
high-performance DirectX 12 adapter (`performance_preference=high_performance`, `device_filter=gpu`:
the discrete GPU of a laptop that also has an integrated one); if a session cannot start there,
the adapter DirectML picks by itself is tried; if that fails too, the provider has failed and the
backend falls back to the CPU variant as before. `FACEIDENTIFY_DIRECTML_ADAPTER` overrides the
first choice: `default` (DirectML's own choice only) or an adapter number. The adapter used is
written to the worker's standard error, which the host log keeps.
"""

import contextlib
import hashlib
import os
import sys
import weakref
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
    ort_errors.InvalidArgument,  # a model that fails validation, such as one with no graph
    ort_errors.InvalidGraph,
    ort_errors.NoModel,
    ort_errors.NotImplemented,
)
ADAPTER_ENV = "FACEIDENTIFY_DIRECTML_ADAPTER"
HIGH_PERFORMANCE = {"performance_preference": "high_performance", "device_filter": "gpu"}


def directml_choices(setting: str | None) -> list[dict[str, str]]:
    """The DirectML adapter options to try, in order (an empty one: DirectML's own choice)."""
    value = (setting or "").strip().lower()
    if value in ("", "high_performance"):
        return [HIGH_PERFORMANCE, {}]
    if value == "default":
        return [{}]
    if value.isdigit():
        return [{"device_id": value}, {}]
    raise WorkerError(
        MLErrorCode.RUNTIME_INITIALIZATION_FAILED,
        f"{ADAPTER_ENV} must be high_performance, default or an adapter number, not {setting!r}",
    )


def adapter_name(options: dict[str, str]) -> str:
    """The adapter `options` select, as Windows names it, for the log (never decides anything)."""
    try:
        devices = [d for d in ort.get_ep_devices() if d.ep_name == DIRECTML]
    except Exception:  # noqa: BLE001 - a name for the log is not worth failing a load over
        devices = []
    if "device_id" in options:
        chosen = [d for d in devices if d.ep_options.get("device_id") == options["device_id"]]
    elif options:  # the high-performance GPU: the one DXGI ranks first for performance
        chosen = [d for d in devices if d.device.metadata.get("DxgiHighPerformanceIndex") == "0"]
    else:
        chosen = []
    if len(chosen) == 1:
        return str(chosen[0].device.metadata.get("Description", "an unnamed adapter"))
    return "the adapter DirectML chose"


# Which device each loaded session runs on, for the provenance the worker returns.
_ADAPTERS: "weakref.WeakKeyDictionary[ort.InferenceSession, str]" = weakref.WeakKeyDictionary()


def adapter_of(session: ort.InferenceSession) -> str:
    """The device a session loaded here runs on ("CPU", or the DirectML adapter's name); empty for
    a session this module did not load."""
    try:
        return _ADAPTERS.get(session, "")
    except TypeError:  # (an object that cannot be weakly referenced was never recorded)
        return ""


def load_session(path: Path, sha256: bytes, provider: str) -> ort.InferenceSession:
    ort.disable_telemetry_events()  # the app is offline and local; no trace events (M8 R4)
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
    choices = directml_choices(os.environ.get(ADAPTER_ENV)) if provider == DIRECTML else [{}]
    failure = ""
    for adapter in choices:
        wanted: str | tuple[str, dict[str, str]] = (provider, adapter) if adapter else provider
        try:
            session = ort.InferenceSession(data, sess_options=options, providers=[wanted])
        except Exception as error:  # ONNX Runtime raises its own exception types for a bad model
            if provider == CPU or isinstance(error, MODEL_ERRORS):
                raise WorkerError(
                    MLErrorCode.COMPONENT_LOAD_FAILED, f"the model cannot be loaded ({error})"
                ) from error
            failure = f"{provider} cannot start ({error})"
            continue
        if session.get_providers()[0] == provider:
            if provider == DIRECTML:
                name = adapter_name(adapter)
                print(f"ml-worker: DirectML runs on {name}", file=sys.stderr)
            else:
                name = "CPU" if provider == CPU else provider
            with contextlib.suppress(TypeError):
                _ADAPTERS[session] = name
            return session
        # (ONNX Runtime fell back to the CPU by itself: the next adapter, or a provider failure)
        failure = f"{provider} was requested but the session runs on {session.get_providers()[0]}"
    raise WorkerError(MLErrorCode.RUNTIME_INITIALIZATION_FAILED, failure)
