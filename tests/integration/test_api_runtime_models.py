"""Reading and installing the face models through the API (M8 step 5, R6)."""

import dataclasses
import hashlib
import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from backend.api.library_profile import LibraryProfile
from backend.api.startup import ProcessingSettings
from backend.app.runtime import model_install
from backend.app.runtime.package_store import InvalidPackageError
from tests.fixtures.api import Api, error
from tests.fixtures.onnx_models import detector_model, embedder_model

MODELS = "/api/v1/runtime/models"
DETECTOR, EMBEDDER = (known.name for known in model_install.KNOWN_FILES)


@pytest.fixture
def downloaded(tmp_path: Path) -> Path:
    """Small stand-in models under the real names, as if the user had unpacked the download."""
    folder = tmp_path / "downloaded"
    folder.mkdir()
    (folder / DETECTOR).write_bytes(detector_model(()))
    (folder / EMBEDDER).write_bytes(embedder_model(dimension=512))
    return folder


@pytest.fixture
def trusted(downloaded: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The table says the stand-ins are the selected models (real weights are never in a test)."""
    table = tuple(
        dataclasses.replace(
            known,
            size_bytes=(downloaded / known.name).stat().st_size,
            sha256=hashlib.sha256((downloaded / known.name).read_bytes()).hexdigest(),
        )
        for known in model_install.KNOWN_FILES
    )
    monkeypatch.setattr(model_install, "KNOWN_FILES", table)


async def test_the_table_and_the_licence_are_shown_before_anything_is_installed(api: Api) -> None:
    state = (await api.client.get(MODELS)).json()

    assert state["installed"] is False
    assert state["package_key"] == "insightface-buffalo-l"
    assert "non-commercial" in state["licence"]
    assert [file["name"] for file in state["files"]] == [DETECTOR, EMBEDDER]
    assert all(len(file["sha256"]) == 64 for file in state["files"])


async def test_models_that_match_the_table_are_installed(
    api: Api, downloaded: Path, trusted: None
) -> None:
    response = await api.client.post(f"{MODELS}/install", json={"path": str(downloaded)})

    assert response.status_code == 201, response.text
    assert response.json()["installed"] is True
    assert (await api.client.get(MODELS)).json()["installed"] is True
    again = await api.client.post(f"{MODELS}/install", json={"path": str(downloaded)})
    assert again.status_code == 201  # the same models again change nothing


async def test_a_file_that_is_not_the_selected_model_is_refused_with_the_reason(
    api: Api, downloaded: Path
) -> None:
    response = await api.client.post(f"{MODELS}/install", json={"path": str(downloaded)})

    refused = error(response, 400, "MODEL_SOURCE_INVALID")
    assert DETECTOR in refused["message"]
    assert (await api.client.get(MODELS)).json()["installed"] is False


async def test_a_relative_path_is_not_a_request(api: Api) -> None:
    response = await api.client.post(f"{MODELS}/install", json={"path": "downloaded"})

    assert response.status_code == 422


async def test_different_models_under_the_same_key_are_a_conflict(
    api: Api, downloaded: Path, trusted: None
) -> None:
    await api.client.post(f"{MODELS}/install", json={"path": str(downloaded)})
    (downloaded / EMBEDDER).write_bytes(embedder_model(dimension=512) + b"\x00")
    (downloaded / "fixture.json").write_text(json.dumps({"fixture": True}), encoding="utf-8")
    api.backend.processing = _processing(api, LibraryProfile.DEVELOPMENT)

    response = await api.client.post(f"{MODELS}/install", json={"path": str(downloaded)})

    error(response, 409, "MODELS_ALREADY_INSTALLED")


async def test_a_fixture_is_accepted_on_the_development_profile_only(
    api: Api, downloaded: Path
) -> None:
    (downloaded / "fixture.json").write_text(json.dumps({"fixture": True}), encoding="utf-8")
    refused = await api.client.post(f"{MODELS}/install", json={"path": str(downloaded)})
    error(refused, 400, "MODEL_SOURCE_INVALID")  # a production build: not in the table

    api.backend.processing = _processing(api, LibraryProfile.DEVELOPMENT)
    accepted = await api.client.post(f"{MODELS}/install", json={"path": str(downloaded)})
    assert accepted.status_code == 201, accepted.text


async def test_an_install_prepares_the_processing_configuration_again(
    api: Api, downloaded: Path, trusted: None
) -> None:
    prepared: list[str] = []

    def prepare(_library: Any) -> dict[str, str]:
        prepared.append("prepared")
        return {"runtime_package": "READY"}

    api.backend.processing = dataclasses.replace(
        _processing(api, LibraryProfile.REAL), prepare=prepare
    )
    await api.client.post(f"{MODELS}/install", json={"path": str(downloaded)})

    assert prepared == ["prepared"]
    assert api.backend.capabilities["runtime_package"] == "READY"


async def test_a_package_the_store_cannot_install_is_a_refused_source(
    api: Api, downloaded: Path, trusted: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise InvalidPackageError("the package does not match its manifest")

    monkeypatch.setattr("backend.api.routes.runtime_models.install_models", refuse)

    response = await api.client.post(f"{MODELS}/install", json={"path": str(downloaded)})

    refused = error(response, 400, "MODEL_SOURCE_INVALID")
    assert "manifest" not in refused["message"]  # the store's own words stay in the logs


def _processing(api: Api, profile: LibraryProfile) -> Any:
    return ProcessingSettings(
        client_for=lambda _plan: None,
        request_for=lambda _session: {},
        max_pixels=1000,
        recognition_k=5,
        lease_for=timedelta(minutes=1),
        idle_seconds=1.0,
        owner="test",
        profile=profile,
    )


async def test_readiness_follows_what_is_true_now_not_what_was_true_at_the_start(
    api: Api,
) -> None:
    async def state() -> str:
        return str((await api.client.get("/readiness")).json()["state"])

    api.backend.capabilities["runtime_package"] = "UNAVAILABLE"  # a first run: no models yet
    assert await state() == "DEGRADED"
    api.backend.capabilities["runtime_package"] = "READY"  # the user installed them
    assert await state() == "READY"
    api.backend.capabilities["recovery"] = "DEGRADED"  # work owed later (a deletion to finish)
    assert await state() == "DEGRADED"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("NOT_STARTED", "READY"),  # the worker starts on first use
        ("READY", "READY"),
        ("UNAVAILABLE", "DEGRADED"),
        ("DEGRADED", "DEGRADED"),
        ("FAILED", "DEGRADED"),  # a worker that keeps crashing
        ("STOPPED", "DEGRADED"),
    ],
)
async def test_readiness_follows_the_capabilities_the_processing_reports_live(
    api: Api, value: str, expected: str
) -> None:
    live = {"ml_worker": "READY"}
    api.backend.processing = dataclasses.replace(
        _processing(api, LibraryProfile.REAL), capabilities=lambda: live
    )
    assert (await api.client.get("/readiness")).json()["state"] == "READY"

    live["ml_worker"] = value
    body = (await api.client.get("/readiness")).json()

    assert (body["state"], body["capabilities"]["ml_worker"]) == (expected, value)
