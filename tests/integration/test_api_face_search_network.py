"""Face search by path on an approved network share (issue #174, PR B).

The share is faked at the Win32 boundary (`tests/fixtures/fake_share.py`); the approvals, the route,
the path policy, the handle walk, the search and the library are real.
"""

import logging
from pathlib import Path

import pytest

from tests.fixtures.api import Api, error
from tests.fixtures.fake_share import HOST, ROOT_OPEN, SHARE, UNC, install
from tests.integration.test_api_face_search import FACE_SEARCH, snapshot
from tests.integration.test_api_search import FACES, face, name_identity

ROOTS = "/api/v1/settings/network-roots"


async def approve(api: Api, path: str) -> None:
    response = await api.client.post(ROOTS, json={"path": path})
    assert response.status_code == 201, response.text


async def test_an_approved_share_is_searched_and_nothing_is_remembered(
    processing_api: Api, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = processing_api
    assert api.perception is not None
    await name_identity(api, await face(api, "ada.png", 0), "Ada")
    api.perception.vector = FACES[0]
    fake = install(monkeypatch, tmp_path / "the-share")
    api.image("q.png").replace(fake.folder / "q.png")
    await approve(api, UNC)
    before = snapshot(api)

    response = await api.client.post(FACE_SEARCH, json={"path": fake.path("q.png")})

    assert response.status_code == 200, response.text
    names = [
        p["identity"]["person"]["display_name"]
        for p in response.json()["faces"][0]["possible_people"]
    ]
    assert names[0] == "Ada"
    assert fake.contacts == [ROOT_OPEN]
    assert snapshot(api) == before  # no source, identity, evidence, job or file


async def test_a_share_nobody_approved_is_refused_and_never_contacted(
    processing_api: Api, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = processing_api
    fake = install(monkeypatch, tmp_path / "the-share")
    (fake.folder / "q.png").write_bytes(b"x")
    await approve(api, r"\\other\share")

    extended = "\\".join(["", "", "?", "UNC", HOST, SHARE, "q.png"])
    for path in (fake.path("q.png"), "//SRV/SHARE/q.png", extended):
        refused = error(
            await api.client.post(FACE_SEARCH, json={"path": path}), 400, "QUERY_PATH_NOT_LOCAL"
        )
        assert "approved" in refused["message"]
        assert path not in str(refused)
    assert fake.contacts == []


async def test_revoking_a_share_stops_the_next_search(
    processing_api: Api, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = processing_api
    assert api.perception is not None
    api.perception.vector = FACES[0]
    fake = install(monkeypatch, tmp_path / "the-share")
    api.image("q.png").replace(fake.folder / "q.png")
    root = (await api.client.post(ROOTS, json={"path": UNC})).json()
    assert (
        await api.client.post(FACE_SEARCH, json={"path": fake.path("q.png")})
    ).status_code == 200

    assert (await api.client.delete(f"{ROOTS}/{root['id']}")).status_code == 204

    error(
        await api.client.post(FACE_SEARCH, json={"path": fake.path("q.png")}),
        400,
        "QUERY_PATH_NOT_LOCAL",
    )
    assert len(fake.contacts) == 1  # only the first search reached the share


async def test_a_big_picture_on_a_share_is_too_large_and_a_missing_one_is_unreadable(
    processing_api: Api, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = processing_api
    fake = install(monkeypatch, tmp_path / "the-share")
    (fake.folder / "big.bin").write_bytes(b"x" * 100_001)
    (fake.folder / "folder").mkdir()
    await approve(api, UNC)

    error(
        await api.client.post(FACE_SEARCH, json={"path": fake.path("big.bin")}),
        413,
        "MEDIA_TOO_LARGE",
    )
    for name in ("missing.png", "folder"):
        error(
            await api.client.post(FACE_SEARCH, json={"path": fake.path(name)}),
            400,
            "QUERY_IMAGE_UNREADABLE",
        )


async def test_an_unreachable_approved_host_is_a_read_failure_without_the_path_in_the_log(
    processing_api: Api,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    api = processing_api
    install(monkeypatch, tmp_path / "the-share")
    await approve(api, r"\\gone-host\private-share\secret-folder")
    caplog.set_level(logging.DEBUG)

    failed = await api.client.post(
        FACE_SEARCH, json={"path": r"\\gone-host\private-share\secret-folder\q.png"}
    )

    error(failed, 400, "QUERY_IMAGE_UNREADABLE")
    assert "gone-host" not in failed.text
    assert "gone-host" not in caplog.text
    assert "private-share" not in caplog.text
