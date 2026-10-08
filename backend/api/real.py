"""The real profile: installed runtime packages, a persistent supervised worker per plan, and a
measured decision policy (M5 track R; the development profile is `backend.api.development`).

* `prepare` registers every installed package in the library's catalog (find-or-create, so it is
  safe on every start). A package that cannot be registered leaves the backend FAILED.
* `client_for` gives the executor one `PerceptionClient` per plan, kept for the life of the
  process: loading the models costs seconds, so a worker is not started per job. `close` stops
  every worker at shutdown.
* `request_for` builds the processing request from the registered catalog and the measured policy
  file `<local state root>/policies/<package key>.json`, read on every request so a newly measured
  policy applies without a restart. With no catalog or no policy it raises
  `ProcessingUnavailableError` (the route answers 503): nothing is ever decided under invented
  numbers. The file holds the `decision_policy` object of the request (schema 1) and nothing else;
  the run is frozen under it and reports the mode `UNCALIBRATED` (raw cosine scores, never
  probabilities).
"""

import json
import os
import threading
import uuid
from collections.abc import Callable, Mapping
from datetime import timedelta
from pathlib import Path
from typing import Any, Final

from sqlalchemy.orm import Session

from backend.api.library_profile import LibraryProfile
from backend.api.startup import (
    PROVISIONAL_MAX_PIXELS,
    UNAVAILABLE,
    LibrarySettings,
    ProcessingSettings,
    ProcessingUnavailableError,
)
from backend.app.lifecycle import OpenLibrary
from backend.app.processing.configuration import ProcessingConfigurationError, ProcessingRequestV1
from backend.app.runtime.package_store import InstalledPackage
from backend.app.runtime.perception_client import PerceptionClient, supervisor_for
from backend.app.runtime.registration import DETECTOR, EMBEDDER, RegisteredPackage, register_package
from backend.app.runtime.worker_config import PerceptionPlan
from backend.ml.supervisor.supervisor import MLSupervisor, SupervisorPolicy

PACKAGE_KEY: Final = "insightface-buffalo-l"
POLICY_DIRECTORY: Final = "policies"
PROVIDERS: Final = ("CPUExecutionProvider",)
# Provisional worker limits (the first real load takes seconds; nothing has measured these).
WORKER_POLICY: Final = SupervisorPolicy(120, 120, 10, 10, 1, 600)


PROVIDERS_ENV: Final = "FACEIDENTIFY_PROVIDERS"
KNOWN_PROVIDERS: Final = ("CUDAExecutionProvider", "CPUExecutionProvider")


def providers_from(environ: Mapping[str, str]) -> tuple[str, ...]:
    """The execution providers to try, preferred first, from `FACEIDENTIFY_PROVIDERS` (a comma list,
    for example `CUDAExecutionProvider,CPUExecutionProvider`). Unset means the CPU alone. A name
    this application does not know is an error, never ignored: a typo must not silently mean CPU."""
    value = environ.get(PROVIDERS_ENV)
    if value is None or not value.strip():
        return PROVIDERS
    names = tuple(part.strip() for part in value.split(","))
    unknown = [name for name in names if name not in KNOWN_PROVIDERS]
    if unknown or len(set(names)) != len(names):
        raise ValueError(f"{PROVIDERS_ENV} must list distinct known providers, not {value!r}")
    return names


def policy_path(local_state_root: Path, package_key: str) -> Path:
    return local_state_root / POLICY_DIRECTORY / f"{package_key}.json"


def load_policy(local_state_root: Path, package_key: str) -> dict[str, Any]:
    """The measured `decision_policy` object, or `ProcessingUnavailableError` when there is none
    or it is not a usable one."""
    path = policy_path(local_state_root, package_key)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ProcessingUnavailableError("no measured decision policy is installed") from None
    except (OSError, ValueError):
        raise ProcessingUnavailableError("the measured decision policy cannot be read") from None
    if not isinstance(value, dict):
        raise ProcessingUnavailableError("the measured decision policy is not an object")
    return value


class ClientPool:
    """One started-on-demand worker and client per plan, stopped together."""

    def __init__(
        self,
        new_id: Callable[[], uuid.UUID],
        *,
        policy: SupervisorPolicy = WORKER_POLICY,
        supervise: Callable[[PerceptionPlan, SupervisorPolicy], MLSupervisor] = supervisor_for,
    ) -> None:
        self._new_id = new_id
        self._policy = policy
        self._supervise = supervise
        self._lock = threading.Lock()
        self._entries: dict[object, tuple[MLSupervisor, PerceptionClient]] = {}

    def client_for(self, plan: PerceptionPlan) -> PerceptionClient:
        key = (
            plan.representation_space_id,
            tuple(v.runtime_variant_id for v in plan.detector),
            tuple(v.runtime_variant_id for v in plan.embedder),
        )
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                supervisor = self._supervise(plan, self._policy)
                entry = (supervisor, PerceptionClient(supervisor, plan, new_id=self._new_id))
                self._entries[key] = entry
            return entry[1]

    def close(self) -> None:
        with self._lock:
            entries, self._entries = list(self._entries.values()), {}
        for supervisor, _ in entries:
            supervisor.stop()


def real_processing(
    settings: LibrarySettings,
    *,
    package_key: str = PACKAGE_KEY,
    providers: tuple[str, ...] = PROVIDERS,
    pool: ClientPool | None = None,
) -> ProcessingSettings:
    """The processing configuration of the real profile. The limits are provisional, like the
    host's other operating limits. `allow_fallback` is on only when more than one provider is
    named: the CPU is the fallback of an accelerator, never a silent substitute for a lone one."""
    clients = pool or ClientPool(settings.new_id)
    registered: dict[str, RegisteredPackage] = {}

    def prepare(library: OpenLibrary) -> dict[str, str]:
        for package in library.packages.installed():
            registered[package.key] = _register(library, package, settings)
        # The worker is "ready" when the package this profile runs is installed and registered;
        # otherwise processing answers 503 and readiness says so (never another package instead).
        return {"ml_worker": "READY" if package_key in registered else UNAVAILABLE}

    def request_for(session: Session) -> dict[str, Any]:
        package = registered.get(package_key)
        if package is None:
            raise ProcessingUnavailableError(f"{package_key} is not installed")
        request = _request(package, load_policy(settings.local_state_root, package_key), providers)
        try:
            ProcessingRequestV1.parse(request)
        except ProcessingConfigurationError:
            raise ProcessingUnavailableError("the measured decision policy is invalid") from None
        return request

    return ProcessingSettings(
        client_for=clients.client_for,
        request_for=request_for,
        max_pixels=PROVISIONAL_MAX_PIXELS,
        recognition_k=5,
        lease_for=timedelta(minutes=10),
        idle_seconds=2.0,
        owner=f"sidecar-{os.getpid()}",
        prepare=prepare,
        profile=LibraryProfile.REAL,
        close=clients.close,
    )


def _register(
    library: OpenLibrary, package: InstalledPackage, settings: LibrarySettings
) -> RegisteredPackage:
    """Record one installed package in the catalog (find-or-create) in its own write."""

    def work(session: Session) -> RegisteredPackage:
        return register_package(session, package, new_id=settings.new_id, clock=settings.clock)

    return library.unit_of_work.write(work)


def _request(
    package: RegisteredPackage, policy: dict[str, Any], providers: tuple[str, ...]
) -> dict[str, Any]:
    detector = next(e for e in package.exports if e.kind == DETECTOR)
    embedder = next(e for e in package.exports if e.kind == EMBEDDER)
    assert embedder.representation_space_id is not None  # (an embedder's export has one)
    return {
        "schema_version": 1,
        "detector": {
            "component_version_id": str(detector.component_version_id),
            "model_export_id": str(detector.model_export_id),
        },
        "embedder": {
            "component_version_id": str(embedder.component_version_id),
            "model_export_id": str(embedder.model_export_id),
        },
        "representation_space_id": str(embedder.representation_space_id),
        "calibration": {
            "mode": "UNCALIBRATED",
            "interpretation": "COSINE_UNCALIBRATED",
            "profile_id": None,
        },
        "runtime_policy": {
            "schema_version": 1,
            "providers": list(providers),
            "allow_fallback": len(providers) > 1,
        },
        "crop_policy": {"schema_version": 1},
        "quality_policy": {"schema_version": 1},
        "decision_policy": policy,
        "command_options": {"schema_version": 1},
    }
