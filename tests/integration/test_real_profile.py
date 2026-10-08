"""The real profile (M5 R2/R3): installed packages, a measured policy file, pooled workers.

Everything here runs on a fixture package (a manifest and files whose hashes match, no real model)
and a stand-in for the perception client. The real models through this same path are exercised by
the local `-m e2e` test; the abstain-only behavior over HTTP is pinned in
`test_api_development_profile.py`.
"""

import asyncio
import base64
import json
import secrets
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image
from sqlalchemy import select

from backend.api.real import (
    PACKAGE_KEY,
    PROVIDERS,
    PROVIDERS_ENV,
    ClientPool,
    load_policy,
    policy_path,
    providers_from,
    real_processing,
)
from backend.api.scheduler import SchedulerService
from backend.api.startup import (
    MediaLimits,
    ProcessingUnavailableError,
    create_backend_app,
)
from backend.app.lifecycle import OpenLibrary, open_library
from backend.app.processing.configuration import ProcessingRequestV1
from backend.app.runtime.models import RuntimePackageInstallation
from backend.app.runtime.perception_client import Detected, FaceVector, Represented
from backend.app.runtime.worker_config import PerceptionPlan, PlannedVariant
from backend.ml.contracts.messages import Detection
from tests.fixtures.api import Api, imported, library_settings, serving
from tests.fixtures.catalog_packages import manifest_dict, package_files
from tests.fixtures.deterministic import FrozenClock, SeededUUIDs

KEY = "reference-cpu"
ABSTAIN_ONLY = {
    "schema_version": 1,
    "version": "buffalo-l-abstain-only-v1",
    "min_detection_score": 0.5,
    "new_identity_ceiling": -1.0,
    "match_threshold": 2.0,
    "margin": 2.0,
}


# --- the pieces -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, PROVIDERS),
        ("", PROVIDERS),
        ("   ", PROVIDERS),
        ("CPUExecutionProvider", ("CPUExecutionProvider",)),
        (
            "CUDAExecutionProvider, CPUExecutionProvider",
            ("CUDAExecutionProvider", "CPUExecutionProvider"),
        ),
    ],
)
def test_the_providers_come_from_the_environment_cpu_by_default(
    value: str | None, expected: tuple[str, ...]
) -> None:
    assert providers_from({} if value is None else {PROVIDERS_ENV: value}) == expected


@pytest.mark.parametrize(
    "value", ["CUDAExecutionProviderr", "CPUExecutionProvider,CPUExecutionProvider", "CUDA,"]
)
def test_a_provider_typo_or_repeat_is_an_error_never_a_silent_cpu(value: str) -> None:
    with pytest.raises(ValueError, match=PROVIDERS_ENV):
        providers_from({PROVIDERS_ENV: value})


def test_the_policy_file_is_read_from_the_local_state_and_must_be_usable(tmp_path: Path) -> None:
    with pytest.raises(ProcessingUnavailableError, match="no measured decision policy"):
        load_policy(tmp_path, KEY)

    path = policy_path(tmp_path, KEY)
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ProcessingUnavailableError, match="cannot be read"):
        load_policy(tmp_path, KEY)

    path.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ProcessingUnavailableError, match="not an object"):
        load_policy(tmp_path, KEY)

    path.unlink()
    path.mkdir()  # a folder where the file should be: unreadable, not "missing"
    with pytest.raises(ProcessingUnavailableError, match="cannot be read"):
        load_policy(tmp_path, KEY)

    path.rmdir()
    path.write_text(json.dumps(ABSTAIN_ONLY), encoding="utf-8")
    assert load_policy(tmp_path, KEY) == ABSTAIN_ONLY


def variant(n: int, kind: str) -> PlannedVariant:
    return PlannedVariant(
        component_version_id=uuid.UUID(int=n),
        runtime_variant_id=uuid.UUID(int=100 + n),
        kind=kind,
        contract="c",
        provider="CPUExecutionProvider",
        device="CPU",
        package_key=KEY,
        model_path=Path("m.onnx"),
        sha256=b"x" * 32,
    )


@dataclass
class FakeSupervisor:
    stopped: int = 0
    state: str = "STOPPED"
    refuses: bool = False

    def stop(self) -> None:
        self.stopped += 1
        if self.refuses:
            raise RuntimeError("will not stop")


def plan(space: int, n: int) -> PerceptionPlan:
    return PerceptionPlan(
        uuid.UUID(int=space),
        4,
        (variant(n, "FACE_DETECTOR"),),
        (variant(n + 1, "FACE_REPRESENTATION"),),
    )


def supervised() -> tuple[list[FakeSupervisor], Any]:
    made: list[FakeSupervisor] = []

    def supervise(_plan: PerceptionPlan, _policy: Any) -> Any:
        made.append(FakeSupervisor())
        return made[-1]

    return made, supervise


def test_one_worker_per_plan_is_kept_and_all_are_stopped_at_the_end() -> None:
    made, supervise = supervised()
    pool = ClientPool(uuid.uuid4, supervise=supervise)

    first = pool.client_for(plan(1, 1))
    again = pool.client_for(plan(1, 1))
    pool.client_for(plan(1, 5))  # other variants
    pool.client_for(plan(2, 1))  # another space

    assert len(made) == 3  # the same plan reused its worker; the others started their own
    assert first is not again  # but a client is never shared between jobs
    assert first._supervisor is again._supervisor

    pool.close()
    assert [s.stopped for s in made] == [1, 1, 1]
    pool.close()  # nothing left to stop
    assert [s.stopped for s in made] == [1, 1, 1]
    pool.client_for(plan(1, 1))  # a pool used again starts afresh
    assert len(made) == 4


def test_a_client_carries_nothing_from_one_job_to_the_next() -> None:
    _, supervise = supervised()
    pool = ClientPool(uuid.uuid4, supervise=supervise)

    first = pool.client_for(plan(1, 1))
    first._ruled_out[("FACE_DETECTOR", uuid.UUID(int=101))] = "CUDA would not start"
    second = pool.client_for(plan(1, 1))

    assert second._ruled_out == {}  # so it tries its preferred provider


def test_a_worker_that_will_not_stop_does_not_keep_the_others_running_and_is_retried() -> None:
    made, supervise = supervised()
    pool = ClientPool(uuid.uuid4, supervise=supervise)
    for space in (1, 2, 3):
        pool.client_for(plan(space, 1))
    made[0].refuses = True

    with pytest.raises(RuntimeError, match="will not stop"):
        pool.close()

    assert [s.stopped for s in made] == [1, 1, 1]  # every worker got its turn
    made[0].refuses = False
    pool.close()  # the one that failed is tried again; the others are not stopped twice
    assert [s.stopped for s in made] == [2, 1, 1]


@pytest.mark.parametrize(
    ("states", "expected"),
    [
        ([], "NOT_STARTED"),
        (["STOPPED"], "NOT_STARTED"),
        (["READY"], "READY"),
        (["READY", "BUSY"], "READY"),
        (["READY", "STARTING"], "STARTING"),
        (["READY", "FAILED"], "FAILED"),
        (["UNAVAILABLE", "READY"], "UNAVAILABLE"),
    ],
)
def test_the_worker_state_reported_to_readiness_is_the_supervisors_own(
    states: list[str], expected: str
) -> None:
    made, supervise = supervised()
    pool = ClientPool(uuid.uuid4, supervise=supervise)
    for space, state in enumerate(states, start=1):
        pool.client_for(plan(space, 1))
        made[-1].state = state

    assert pool.worker_state() == expected


@pytest.mark.parametrize("key", ["../x", "a/b", "a\\b", "", ".hidden", "a..b", "x y"])
def test_a_package_key_names_a_file_never_a_path(key: str, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not a package key"):
        policy_path(tmp_path, key)


# --- the profile against a real library -------------------------------------------------------


@dataclass
class World:
    settings: Any
    folder: Path
    policy_file: Path = field(init=False)

    def __post_init__(self) -> None:
        self.policy_file = policy_path(self.settings.local_state_root, KEY)


@pytest.fixture
def world(tmp_path: Path, clock: FrozenClock, new_id: SeededUUIDs) -> World:
    return World(library_settings(tmp_path, clock, new_id), tmp_path / "pictures")


def install_package(world: World, clock: FrozenClock, new_id: SeededUUIDs) -> Path:
    """Put the fixture package into the machine-local store, the way the installer does."""
    source = package_files(world.folder.parent / "source", manifest_dict(KEY))
    settings = world.settings
    with open_library(
        library_root=settings.library_root,
        local_state_root=settings.local_state_root,
        clock=clock,
        new_id=new_id,
        retry=settings.retry,
        transaction_retry=settings.transaction_retry,
        index_batch=50,
        max_index_passes=5,
    ) as library:
        return library.packages.install(source, {}).path


def write_policy(world: World, policy: dict[str, Any] | None = None) -> None:
    world.policy_file.parent.mkdir(parents=True, exist_ok=True)
    world.policy_file.write_text(json.dumps(policy or ABSTAIN_ONLY), encoding="utf-8")


@contextmanager
def opened(world: World, clock: FrozenClock, new_id: SeededUUIDs) -> Iterator[OpenLibrary]:
    settings = world.settings
    with open_library(
        library_root=settings.library_root,
        local_state_root=settings.local_state_root,
        clock=clock,
        new_id=new_id,
        retry=settings.retry,
        transaction_retry=settings.transaction_retry,
        index_batch=50,
        max_index_passes=5,
    ) as library:
        yield library


def test_the_profile_registers_the_package_and_builds_the_request_from_catalog_and_policy(
    world: World, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    install_package(world, clock, new_id)
    write_policy(world)
    processing = real_processing(world.settings, package_key=KEY)
    with opened(world, clock, new_id) as library:
        assert processing.prepare is not None
        assert processing.prepare(library) == {"runtime_package": "READY"}

        request = library.unit_of_work.read(processing.request_for)

    parsed = ProcessingRequestV1.parse(request)  # the real validator accepts it as built
    assert parsed.decision_policy["match_threshold"] == 2.0  # automatic matching off
    assert parsed.decision_policy["version"] == "buffalo-l-abstain-only-v1"
    assert (
        request["calibration"]["mode"] == "UNCALIBRATED"
    )  # raw cosine scores, never probabilities
    assert request["runtime_policy"] == {
        "schema_version": 1,
        "providers": ["CPUExecutionProvider"],
        "allow_fallback": False,
    }


def test_two_providers_allow_the_planned_fallback_one_does_not(
    world: World, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    install_package(world, clock, new_id)
    write_policy(world)
    both = ("CUDAExecutionProvider", "CPUExecutionProvider")
    processing = real_processing(world.settings, package_key=KEY, providers=both)
    with opened(world, clock, new_id) as library:
        assert processing.prepare is not None
        processing.prepare(library)
        request = library.unit_of_work.read(processing.request_for)

    assert request["runtime_policy"]["providers"] == list(both)
    assert request["runtime_policy"]["allow_fallback"] is True


def test_without_the_package_or_a_valid_policy_nothing_is_decided(
    world: World, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    processing = real_processing(world.settings, package_key=KEY)
    assert processing.prepare is not None
    with opened(world, clock, new_id) as library:
        assert processing.prepare(library) == {"runtime_package": "UNAVAILABLE"}  # nothing there
        with pytest.raises(ProcessingUnavailableError, match="is not installed"):
            library.unit_of_work.read(processing.request_for)

        source = package_files(world.folder.parent / "again", manifest_dict(KEY))
        library.packages.install(source, {})
        assert processing.prepare(library) == {"runtime_package": "READY"}  # found, registered
        with pytest.raises(ProcessingUnavailableError, match="no measured decision policy"):
            library.unit_of_work.read(processing.request_for)  # no policy file: still nothing

        write_policy(world, {**ABSTAIN_ONLY, "margin": 0.0})  # a margin must be above 0
        with pytest.raises(ProcessingUnavailableError, match="policy is invalid"):
            library.unit_of_work.read(processing.request_for)


@pytest.mark.parametrize(
    "edit",
    [
        {"match_threshold": 0.1, "margin": 0.01},  # plausible numbers that enable matching
        {"match_threshold": 1.0},  # a cosine of 1 is reachable by an identical face
        {"match_threshold": 0.9, "new_identity_ceiling": 0.5},  # the demo policy
        {"new_identity_ceiling": 0.0},  # a weak score could create an identity
        {"new_identity_ceiling": -0.99},
    ],
)
def test_a_policy_file_that_enables_matching_or_creation_is_refused_whatever_its_numbers(
    world: World, clock: FrozenClock, new_id: SeededUUIDs, edit: dict[str, float]
) -> None:
    install_package(world, clock, new_id)
    write_policy(world, {**ABSTAIN_ONLY, **edit})  # same version name, different numbers
    processing = real_processing(world.settings, package_key=KEY)
    assert processing.prepare is not None
    assert processing.capabilities is not None
    with opened(world, clock, new_id) as library:
        processing.prepare(library)

        with pytest.raises(ProcessingUnavailableError, match="not permitted"):
            library.unit_of_work.read(processing.request_for)

    assert processing.capabilities()["processing_policy"] == "UNAVAILABLE"  # and readiness says so


def test_a_package_removed_after_start_is_not_used_and_prepare_forgets_it(
    world: World, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    installed = install_package(world, clock, new_id)
    write_policy(world)
    processing = real_processing(world.settings, package_key=KEY)
    assert processing.prepare is not None
    assert processing.capabilities is not None
    with opened(world, clock, new_id) as library:
        processing.prepare(library)
        assert processing.capabilities()["runtime_package"] == "READY"

        (installed / "manifest.json").unlink()

        # No second prepare: the very next command still notices.
        with pytest.raises(ProcessingUnavailableError, match="no longer installed"):
            library.unit_of_work.read(processing.request_for)
        assert processing.capabilities()["runtime_package"] == "UNAVAILABLE"
        forgotten = processing.prepare(library)  # and a fresh start forgets it
        assert forgotten == {"runtime_package": "UNAVAILABLE"}
        # The catalog says so too: the package's installation record follows the disk.
        with library.session_factory() as session:
            states = [r.state for r in session.scalars(select(RuntimePackageInstallation))]
        assert states == ["MISSING"]
        with pytest.raises(ProcessingUnavailableError, match="is not installed"):
            library.unit_of_work.read(processing.request_for)


def test_a_damaged_package_that_is_not_the_one_we_run_does_not_take_the_library_down(
    world: World, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    install_package(world, clock, new_id)  # the healthy, selected one
    write_policy(world)
    processing = real_processing(world.settings, package_key=KEY)
    assert processing.prepare is not None
    with opened(world, clock, new_id) as library:
        other = package_files(world.folder.parent / "other", manifest_dict("other-package"))
        damaged = library.packages.install(other, {}).path
        (damaged / "models" / "detector.onnx").write_bytes(b"swapped after the install")

        assert processing.prepare(library) == {"runtime_package": "READY"}  # the library carries on
        assert library.unit_of_work.read(processing.request_for)["schema_version"] == 1


def test_the_selected_package_being_damaged_makes_it_unavailable_not_the_library_failed(
    world: World, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    installed = install_package(world, clock, new_id)
    write_policy(world)
    (installed / "models" / "detector.onnx").write_bytes(b"swapped after the install")
    processing = real_processing(world.settings, package_key=KEY)
    assert processing.prepare is not None
    with opened(world, clock, new_id) as library:
        assert processing.prepare(library) == {"runtime_package": "UNAVAILABLE"}
        with pytest.raises(ProcessingUnavailableError, match="is not installed"):
            library.unit_of_work.read(processing.request_for)


def test_the_default_package_is_the_reference_model() -> None:
    assert PACKAGE_KEY == "insightface-buffalo-l"


# --- through the application -----------------------------------------------------------------


class FixturePerception:
    """One face per image, always the same vector: stands in for the worker."""

    def __init__(self, plan: PerceptionPlan) -> None:
        self._plan = plan

    def detect(self, pixels: Any) -> Detected:
        box = Detection(0, 0, (0.2, 0.2, 0.8, 0.8), 0.9, None)
        return Detected((box,), self._plan.detector[0])

    def represent(self, pixels: Any, detections: tuple[Detection, ...]) -> Represented:
        vector = np.zeros(self._plan.dimension, dtype="<f4")
        vector[0] = 1.0
        faces = tuple(FaceVector(d.detection_index, vector, "L2_NORMALIZED") for d in detections)
        return Represented(faces, self._plan.embedder[0], ())


class RecordingPool(ClientPool):
    def __init__(self) -> None:
        super().__init__(uuid.uuid4)
        self.closed = 0
        self.asked = 0

    def client_for(self, plan: PerceptionPlan) -> Any:
        self.asked += 1
        return FixturePerception(plan)

    def close(self) -> None:
        self.closed += 1


async def process_and_wait(api: Api, source_id: str) -> dict[str, Any]:
    response = await api.client.post(f"/api/v1/sources/{source_id}/process")
    assert response.status_code == 202, response.text
    run_id = response.json()["id"]
    async with asyncio.timeout(30):
        while True:
            run: dict[str, Any] = (await api.client.get(f"/api/v1/processing-runs/{run_id}")).json()
            if run["state"] == "COMPLETED":
                return run
            assert run["state"] not in ("FAILED", "NOT_RESUMABLE"), run
            await asyncio.sleep(0.02)


def application(world: World, pool: ClientPool) -> Any:
    secret = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
    processing = real_processing(world.settings, package_key=KEY, pool=pool)
    app = create_backend_app(
        secret,
        world.settings,
        processing=processing,
        media_limits=MediaLimits(max_pixels=1_000_000, max_bytes=1_000_000),
    )
    return app, secret


def picture(folder: Path, name: str) -> str:
    folder.mkdir(exist_ok=True)
    path = folder / name
    Image.new("RGB", (8, 6), (10, 20, 30)).save(path, format="PNG")
    return str(path)


async def test_the_real_profile_runs_the_abstain_only_policy_through_the_application(
    world: World, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    install_package(world, clock, new_id)
    write_policy(world)
    pool = RecordingPool()
    app, secret = application(world, pool)

    async with serving(app, secret, world.folder.parent / "files", clock) as api:
        ready = (await api.client.get("/readiness")).json()
        assert ready["state"] == "READY"
        assert ready["capabilities"]["runtime_package"] == "READY"
        assert ready["capabilities"]["processing_policy"] == "READY"
        assert ready["capabilities"]["ml_worker"] == "NOT_STARTED"  # no job has started one yet
        assert ready["capabilities"]["scheduler"] == "READY"

        first = await imported(api, path=picture(world.folder, "a.png"))
        run = await process_and_wait(api, first["id"])
        assert run["policy"] == {
            "calibration_mode": "UNCALIBRATED",
            "decision_policy_version": "buffalo-l-abstain-only-v1",
            "calibrated": False,
            "automatic_matching": False,  # what the screen says: matching disabled
        }
        identities = (await api.client.get("/api/v1/identities")).json()["items"]
        assert len(identities) == 1  # the first face made an identity

        second = await imported(api, path=picture(world.folder, "b.png"))
        await process_and_wait(api, second["id"])
        assert len((await api.client.get("/api/v1/identities")).json()["items"]) == 1
        waiting = await api.client.get(f"/api/v1/sources/{second['id']}/unresolved-faces")
        assert len(waiting.json()["items"]) == 1  # an identical face was not matched
        assert pool.asked >= 2
        assert pool.closed == 0

    assert pool.closed == 1  # the workers are stopped when the application shuts down


async def test_the_real_profile_without_a_policy_refuses_to_process_and_says_why(
    world: World, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    install_package(world, clock, new_id)  # a package, but no measured policy
    app, secret = application(world, RecordingPool())

    async with serving(app, secret, world.folder.parent / "files", clock) as api:
        source = await imported(api, path=picture(world.folder, "a.png"))
        refused = await api.client.post(f"/api/v1/sources/{source['id']}/process")

        assert refused.status_code == 503
        assert refused.json()["error"]["code"] == "PROCESSING_UNAVAILABLE"
        ready = (await api.client.get("/readiness")).json()
        assert ready["capabilities"]["runtime_package"] == "READY"
        assert ready["capabilities"]["processing_policy"] == "UNAVAILABLE"  # and readiness says so


async def test_the_real_profile_without_the_package_is_degraded_and_unavailable(
    world: World, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    write_policy(world)  # a policy, but nothing installed
    app, secret = application(world, RecordingPool())

    async with serving(app, secret, world.folder.parent / "files", clock) as api:
        ready = (await api.client.get("/readiness")).json()

        assert ready["state"] == "DEGRADED"
        assert ready["capabilities"]["runtime_package"] == "UNAVAILABLE"
        assert ready["capabilities"]["processing_policy"] == "READY"  # the policy is not the gap


async def test_a_failing_close_still_releases_the_library(
    world: World, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    class Failing(RecordingPool):
        def close(self) -> None:
            raise RuntimeError("a worker would not stop")

    install_package(world, clock, new_id)
    write_policy(world)
    app, secret = application(world, Failing())

    with pytest.raises(RuntimeError, match="would not stop"):
        async with serving(app, secret, world.folder.parent / "files", clock):
            pass

    with opened(world, clock, new_id) as again:  # the library lock was released: it opens again
        assert again.unit_of_work is not None


async def test_a_scheduler_that_will_not_drain_still_stops_the_workers_and_frees_the_library(
    world: World, clock: FrozenClock, new_id: SeededUUIDs, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def refuses(_self: Any) -> None:
        raise RuntimeError("the drain failed")

    monkeypatch.setattr(SchedulerService, "stop", refuses)
    install_package(world, clock, new_id)
    write_policy(world)
    pool = RecordingPool()
    app, secret = application(world, pool)

    with pytest.raises(RuntimeError, match="the drain failed"):
        async with serving(app, secret, world.folder.parent / "files", clock):
            pass

    assert pool.closed == 1  # the workers were still stopped
    with opened(world, clock, new_id) as again:  # and the library lock was released
        assert again.unit_of_work is not None
