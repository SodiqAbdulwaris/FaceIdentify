"""The approved network locations through the API (issue #174, PR A)."""

import socket

import pytest

from tests.fixtures.api import Api, error

ROOTS = "/api/v1/settings/network-roots"


async def test_a_location_is_approved_listed_and_revoked(api: Api) -> None:
    assert (await api.client.get(ROOTS)).json() == {"roots": []}

    created = await api.client.post(ROOTS, json={"path": "//NAS/Family/Trips/"})

    assert created.status_code == 201, created.text
    root = created.json()
    assert root["path"] == r"\\NAS\Family\Trips"
    assert (await api.client.get(ROOTS)).json() == {"roots": [root]}

    gone = await api.client.delete(f"{ROOTS}/{root['id']}")

    assert gone.status_code == 204
    assert (await api.client.get(ROOTS)).json() == {"roots": []}


async def test_the_approval_is_kept_with_this_computer_not_with_the_library(api: Api) -> None:
    await api.client.post(ROOTS, json={"path": r"\\nas\family"})

    kept = api.backend.library.roots.local_state_root / "network-roots.json"  # type: ignore[union-attr]
    assert kept.is_file()
    assert not any(api.backend.library.roots.library_root.rglob("network-roots.json"))  # type: ignore[union-attr]


async def test_approving_does_not_contact_the_host(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*_: object, **__: object) -> None:
        raise AssertionError("a host was contacted")

    for name in ("getaddrinfo", "gethostbyname", "create_connection"):
        monkeypatch.setattr(socket, name, refuse)

    response = await api.client.post(ROOTS, json={"path": r"\\unreachable.invalid\share"})

    assert response.status_code == 201, response.text


@pytest.mark.parametrize(
    "path", ["", r"C:\photos", r"\\.\pipe\x", r"\\?\GLOBALROOT\x", r"\\hostonly", "http://x/y"]
)
async def test_something_that_is_not_a_share_is_refused(api: Api, path: str) -> None:
    response = await api.client.post(ROOTS, json={"path": path})

    error(response, 400, "NETWORK_ROOT_INVALID")
    assert path not in response.text or path == ""
    assert (await api.client.get(ROOTS)).json() == {"roots": []}


async def test_revoking_a_location_that_is_not_approved_is_not_found(api: Api) -> None:
    error(await api.client.delete(f"{ROOTS}/0123456789abcdef"), 404, "NETWORK_ROOT_NOT_FOUND")


async def test_the_routes_need_the_launch_token(api: Api) -> None:
    api.client.headers.pop("Authorization")

    assert (await api.client.get(ROOTS)).status_code == 401
