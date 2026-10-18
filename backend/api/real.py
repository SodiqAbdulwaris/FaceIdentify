"""The real profile: installed runtime packages, a supervised worker per plan, and a measured
decision policy (M5 track R; the development profile is `backend.api.development`).

* `prepare` registers the installed packages in the library's catalog (find-or-create, so it is safe
  on every start) and rebuilds what it knows from scratch each time. A package that cannot be
  registered (damaged, or a different package under its key) is skipped and reported through the
  `runtime_package` capability when it is the one this profile runs; it never takes the library
  down. Only infrastructure failures (the database) leave the backend FAILED.
* `client_for` gives the executor a fresh `PerceptionClient` over a supervisor kept for the life of
  the process: loading the models costs seconds, so a worker is not started per job, while the
  client's per-job state (which providers it has ruled out) is never carried between jobs, so every
  job records its own fallbacks. `close` stops every worker at shutdown and keeps trying the rest
  when one will not stop.
* `request_for` builds the processing request from the registered catalog and the measured policy
  file `<local state root>/policies/<package key>.json`, read on every request so a newly measured
  policy applies without a restart. With no catalog entry, a package no longer on this machine, or
  no usable policy it raises `ProcessingUnavailableError` (the route answers 503): nothing is ever
  decided under invented numbers. The file holds the `decision_policy` object of the request
  (schema 1) and nothing else; the run is frozen under it and reports the mode `UNCALIBRATED` (raw
  cosine scores, never probabilities).
* **A policy file cannot enable matching on its own** (owner decisions 2026-10-07, 2026-10-08 and
  2026-10-15): it is admitted when it abstains first (a `match_threshold` above 1) or when it
  equals, version and numbers, an operating point the owner approved in `APPROVED_MATCHING`,
  which only a code change can extend. Either way the `new_identity_ceiling` is -1: no identity is
  ever created from a weak score (an automatic new identity needs its own approved budget, ML spec
  17.2). Any other file is refused, however plausible its numbers, because nothing binds it to a
  measurement.
* Readiness: `runtime_package` (the package this profile runs is installed and registered),
  `processing_policy` (a usable policy file exists) and `ml_worker` (the supervisors' own state:
  `NOT_STARTED` until a job starts one, then `READY`, `FAILED`...), `execution_provider` (the
  provider that last ran, `NOT_STARTED` before any) and `provider_fallback` (`ACTIVE` when that was
  not the preferred provider, else `NONE`). A change of provider is logged, a fallback as a warning:
  asking for DirectML or CUDA on a machine where it cannot start is never a silent CPU run.
"""

import json
import logging
import os
import re
import sys
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
from backend.app.recognition.reasoner import MAX_SIMILARITY
from backend.app.runtime.package_store import InstalledPackage, RuntimePackageStore
from backend.app.runtime.perception_client import PerceptionClient, supervisor_for
from backend.app.runtime.registration import (
    DETECTOR,
    EMBEDDER,
    RegisteredPackage,
    RegistrationError,
    mark_missing_installations,
    missing_dependencies,
    register_package,
)
from backend.app.runtime.worker_config import PerceptionPlan, PlannedVariant
from backend.ml.contracts.protocol import WorkerState
from backend.ml.supervisor.lease import WorkerLease
from backend.ml.supervisor.supervisor import MLSupervisor, SupervisorPolicy

PACKAGE_KEY: Final = "insightface-buffalo-l"
POLICY_DIRECTORY: Final = "policies"
PROVIDERS: Final = ("CPUExecutionProvider",)
# The shipped Windows build (onnxruntime-windowsml) runs DirectML on any DirectX 12 GPU, then the
# CPU (owner decision 2026-10-15). CUDA stays a developer option: named explicitly, never a default.
WINDOWS_PROVIDERS: Final = ("DmlExecutionProvider", "CPUExecutionProvider")
# Provisional worker limits (the first real load takes seconds; nothing has measured these).
WORKER_POLICY: Final = SupervisorPolicy(120, 120, 10, 10, 1, 600)
READY: Final = "READY"
NOT_STARTED: Final = "NOT_STARTED"
NONE: Final = "NONE"
_SAFE_KEY: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")

LOG: Final = logging.getLogger("faceidentify.runtime")

PROVIDERS_ENV: Final = "FACEIDENTIFY_PROVIDERS"
KNOWN_PROVIDERS: Final = ("DmlExecutionProvider", "CUDAExecutionProvider", "CPUExecutionProvider")


def providers_from(environ: Mapping[str, str], platform: str = sys.platform) -> tuple[str, ...]:
    """The execution providers to try, preferred first, from `FACEIDENTIFY_PROVIDERS` (a comma list,
    for example `CUDAExecutionProvider,CPUExecutionProvider`). Unset means DirectML then the CPU on
    Windows, the CPU alone elsewhere. A name this application does not know is an error, never
    ignored: a typo must not silently mean CPU."""
    value = environ.get(PROVIDERS_ENV)
    if value is None or not value.strip():
        return WINDOWS_PROVIDERS if platform == "win32" else PROVIDERS
    names = tuple(part.strip() for part in value.split(","))
    unknown = [name for name in names if name not in KNOWN_PROVIDERS]
    if unknown or len(set(names)) != len(names):
        raise ValueError(f"{PROVIDERS_ENV} must list distinct known providers, not {value!r}")
    return names


def policy_path(local_state_root: Path, package_key: str) -> Path:
    """Where the measured policy for a package lives. The key names a file, never a path."""
    if _SAFE_KEY.fullmatch(package_key) is None or ".." in package_key:
        raise ValueError(f"{package_key!r} is not a package key")
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


# The automatic-matching operating points the owner approved, by policy version. The evidence for
# each is in its implementation entry
# (docs/implementations/2026-10-15-enable-automatic-acceptance.md).
APPROVED_MATCHING: Final[Mapping[str, Mapping[str, float]]] = {
    "buffalo-l-verified-match-v1": {
        "min_detection_score": 0.5,
        "match_threshold": 0.45,
        "margin": 0.10,
        "new_identity_ceiling": -1.0,
    },
}


def require_approved_policy(request: Mapping[str, Any]) -> None:
    """Refuse a request whose policy could create an identity from a score, or match under an
    operating point the owner has not approved (see the module docstring)."""
    try:
        policy = ProcessingRequestV1.parse(request).decision_policy
    except ProcessingConfigurationError:
        raise ProcessingUnavailableError("the measured decision policy is invalid") from None
    if policy["new_identity_ceiling"] == -1.0 and policy["match_threshold"] > MAX_SIMILARITY:
        return  # abstain first: nothing is matched or created from a score
    approved = APPROVED_MATCHING.get(policy["version"])
    if approved is None or any(policy[key] != value for key, value in approved.items()):
        raise ProcessingUnavailableError(
            "automatic matching is not permitted except at an owner-approved operating point: "
            "the policy must abstain first (a match threshold above 1 and a new-identity ceiling "
            "of -1) or equal an approved one"
        )


class ClientPool:
    """One supervised worker per plan, kept for the life of the process, and a fresh client for
    every job; all workers are stopped together."""

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
        self._supervisors: dict[object, MLSupervisor] = {}
        # One turn-taking boundary for the single worker, whatever the plan (#175): a job on a
        # frozen CPU-only plan and a search on a DirectML plan queue in the same line.
        self.lease = WorkerLease()
        # stage -> (the provider that last ran it, whether that was a fallback)
        self._ran: dict[str, tuple[str, bool]] = {}

    def client_for(self, plan: PerceptionPlan) -> PerceptionClient:
        key = (
            plan.representation_space_id,
            tuple(v.runtime_variant_id for v in plan.detector),
            tuple(v.runtime_variant_id for v in plan.embedder),
        )
        with self._lock:
            supervisor = self._supervisors.get(key)
            if supervisor is None:
                supervisor = self._supervise(plan, self._policy)
                self._supervisors[key] = supervisor
        # A client remembers which providers it has ruled out; a new one per job means each job
        # tries its preferred provider and records its own fallbacks.
        return PerceptionClient(
            supervisor,
            plan,
            new_id=self._new_id,
            on_ran=lambda ran: self._record(plan, ran),
            lease=self.lease,
        )

    def _record(self, plan: PerceptionPlan, ran: PlannedVariant) -> None:
        """Remember the provider a stage ran on; log when it changes, a fallback as a warning."""
        stage = plan.detector if ran.kind == plan.detector[0].kind else plan.embedder
        now = (ran.provider, ran.provider != stage[0].provider)
        with self._lock:
            before = self._ran.get(ran.kind)
            self._ran[ran.kind] = now
        if now == before:
            return
        if now[1]:
            LOG.warning(
                "%s is running on %s: the preferred %s is not available (see the run's segments)",
                ran.kind,
                ran.provider,
                stage[0].provider,
            )
        else:
            LOG.info("%s is running on %s", ran.kind, ran.provider)

    def provider_state(self) -> dict[str, str]:
        """The provider in use for readiness: what last ran, and whether it was a fallback."""
        with self._lock:
            ran = list(self._ran.values())
        if not ran:
            return {"execution_provider": NOT_STARTED, "provider_fallback": NONE}
        return {
            "execution_provider": ",".join(sorted({provider for provider, _ in ran})),
            "provider_fallback": "ACTIVE" if any(fell for _, fell in ran) else NONE,
        }

    def close(self) -> None:
        """Stop every worker. One that will not stop does not keep the others running; it stays in
        the pool so a second `close` tries it again, and the first failure is raised."""
        self.lease.close()  # queued requests are refused before any worker is stopped
        self.lease.wait_until_idle()  # a returned output is attached and released before shutdown
        with self._lock:
            held = list(self._supervisors.items())
        failures: list[Exception] = []
        for key, supervisor in held:
            try:
                supervisor.stop()
            except Exception as error:  # noqa: BLE001 - every worker gets its turn to stop
                failures.append(error)
                continue
            with self._lock:
                self._supervisors.pop(key, None)
        if failures:
            raise failures[0]

    def worker_state(self) -> str:
        """The workers' own state for readiness: nothing until a job has started one."""
        with self._lock:
            states = [supervisor.state for supervisor in self._supervisors.values()]
        if not states:
            return NOT_STARTED
        for bad in (WorkerState.FAILED, WorkerState.UNAVAILABLE):
            if bad in states:
                return str(bad)
        if all(state in (WorkerState.READY, WorkerState.BUSY) for state in states):
            return READY
        if WorkerState.STARTING in states:
            return str(WorkerState.STARTING)
        return NOT_STARTED


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
    store: list[RuntimePackageStore] = []  # the library's package store, once it is open
    opened: list[OpenLibrary] = []  # the open library, for the dependency report

    def installed() -> bool:
        return bool(store) and package_key in registered and store[0].get(package_key) is not None

    def prepare(library: OpenLibrary) -> dict[str, str]:
        registered.clear()  # what is known is rebuilt from what is installed now
        store[:] = [library.packages]
        opened[:] = [library]
        # Installation records follow the disk before anything is registered: a package that left
        # this machine is MISSING, and registering what is installed reinstates what came back.
        library.unit_of_work.write(mark_missing_installations)
        for package in library.packages.installed():
            try:
                registered[package.key] = _register(library, package, settings)
            except RegistrationError:
                continue  # a damaged or conflicting package is unavailable, not a dead library
        needed = dependencies()
        return {
            "runtime_package": READY if installed() else UNAVAILABLE,
            "library_packages": UNAVAILABLE if needed else READY,
        }

    def dependencies() -> list[str]:
        """The packages the library's own vectors need that are not installed on this machine."""
        return opened[0].unit_of_work.read(missing_dependencies) if opened else []

    def request_for(session: Session) -> dict[str, Any]:
        package = registered.get(package_key)
        if package is None:
            raise ProcessingUnavailableError(f"{package_key} is not installed")
        if not installed():
            raise ProcessingUnavailableError(f"{package_key} is no longer installed")
        request = _request(package, load_policy(settings.local_state_root, package_key), providers)
        require_approved_policy(request)
        return request

    def capabilities() -> dict[str, str]:
        try:
            require_approved_policy(
                _policy_probe(load_policy(settings.local_state_root, package_key), providers)
            )
            policy = READY
        except ProcessingUnavailableError:
            policy = UNAVAILABLE
        return {
            "runtime_package": READY if installed() else UNAVAILABLE,
            "processing_policy": policy,
            "library_packages": UNAVAILABLE if dependencies() else READY,
            "ml_worker": clients.worker_state(),
            **clients.provider_state(),
        }

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
        capabilities=capabilities,
        dependencies=dependencies,
    )


def _register(
    library: OpenLibrary, package: InstalledPackage, settings: LibrarySettings
) -> RegisteredPackage:
    """Record one installed package in the catalog (find-or-create) in its own write."""

    def work(session: Session) -> RegisteredPackage:
        return register_package(session, package, new_id=settings.new_id, clock=settings.clock)

    return library.unit_of_work.write(work)


def _policy_probe(policy: dict[str, Any], providers: tuple[str, ...]) -> dict[str, Any]:
    """A request shell around a policy, for judging the policy alone (no catalog needed)."""
    nil = str(uuid.UUID(int=0))
    return {
        "schema_version": 1,
        "detector": {"component_version_id": nil, "model_export_id": nil},
        "embedder": {"component_version_id": nil, "model_export_id": nil},
        "representation_space_id": nil,
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


def _request(
    package: RegisteredPackage, policy: dict[str, Any], providers: tuple[str, ...]
) -> dict[str, Any]:
    detector = next(e for e in package.exports if e.kind == DETECTOR)
    embedder = next(e for e in package.exports if e.kind == EMBEDDER)
    assert embedder.representation_space_id is not None  # (an embedder's export has one)
    request = _policy_probe(policy, providers)
    request["detector"] = {
        "component_version_id": str(detector.component_version_id),
        "model_export_id": str(detector.model_export_id),
    }
    request["embedder"] = {
        "component_version_id": str(embedder.component_version_id),
        "model_export_id": str(embedder.model_export_id),
    }
    request["representation_space_id"] = str(embedder.representation_space_id)
    return request
