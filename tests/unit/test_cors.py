"""The web view can read the loopback server's answers only from the origins the shell names.

The shell's web view is a different origin from the loopback server, so a browser refuses to hand a
page any answer unless the server says that origin may read it. Without this the desktop app sat
for ever on "Opening your library" (found 2026-10-12): the unit and end-to-end tests call the API
from Python, where no browser enforces any of it.
"""

import base64
import secrets

import httpx
import pytest

from backend.api.app import create_app
from backend.api.host import parse_options

TOKEN = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
ALLOWED = ("http://tauri.localhost", "http://localhost:5173")
PREFLIGHT = {
    "Access-Control-Request-Method": "GET",
    "Access-Control-Request-Headers": "authorization",
}


def client(origins: tuple[str, ...]) -> httpx.AsyncClient:
    app = create_app(TOKEN, allowed_origins=origins)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_a_preflight_from_an_allowed_origin_is_answered_without_a_token() -> None:
    response = await client(ALLOWED).options(
        "/readiness", headers={"Origin": "http://tauri.localhost", **PREFLIGHT}
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://tauri.localhost"
    assert "authorization" in response.headers["access-control-allow-headers"].lower()
    assert "access-control-allow-credentials" not in response.headers


async def test_a_real_request_still_needs_the_token_and_is_readable_only_by_an_allowed_origin() -> (
    None
):
    web = client(ALLOWED)
    origin = {"Origin": "http://localhost:5173"}

    without = await web.get("/readiness", headers=origin)
    with_token = await web.get("/readiness", headers={**origin, "Authorization": f"Bearer {TOKEN}"})

    assert without.status_code == 401  # nothing gets in without the capability
    assert without.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert with_token.status_code == 200
    assert with_token.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "access-control-allow-credentials" not in with_token.headers


async def test_another_origin_is_not_allowed() -> None:
    web = client(ALLOWED)

    preflight = await web.options(
        "/readiness", headers={"Origin": "http://evil.example", **PREFLIGHT}
    )
    real = await web.get(
        "/readiness", headers={"Origin": "http://evil.example", "Authorization": f"Bearer {TOKEN}"}
    )

    assert preflight.status_code == 400
    assert "access-control-allow-origin" not in preflight.headers
    assert "access-control-allow-origin" not in real.headers


async def test_with_no_origins_named_there_are_no_cors_headers_at_all() -> None:
    web = client(())

    preflight = await web.options(
        "/readiness", headers={"Origin": "http://tauri.localhost", **PREFLIGHT}
    )
    real = await web.get(
        "/readiness",
        headers={"Origin": "http://tauri.localhost", "Authorization": f"Bearer {TOKEN}"},
    )

    assert preflight.status_code == 401  # the capability check, as before
    assert "access-control-allow-origin" not in preflight.headers
    assert "access-control-allow-origin" not in real.headers


async def test_an_unexpected_error_is_still_readable_by_an_allowed_origin() -> None:
    app = create_app(TOKEN, allowed_origins=ALLOWED)

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("something broke")

    web = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    )
    auth = {"Authorization": f"Bearer {TOKEN}"}

    allowed = await web.get("/boom", headers={**auth, "Origin": "http://tauri.localhost"})
    other = await web.get("/boom", headers={**auth, "Origin": "http://evil.example"})

    assert allowed.status_code == 500
    assert allowed.headers["access-control-allow-origin"] == "http://tauri.localhost"
    assert allowed.json()["error"]["diagnostic_id"]  # the page can read it
    assert other.status_code == 500
    assert "access-control-allow-origin" not in other.headers


def test_the_host_takes_exact_origins_only() -> None:
    base = ["--library-root", "L", "--local-state-root", "S"]
    options = parse_options(
        [
            *base,
            "--allow-origin",
            "http://tauri.localhost",
            "--allow-origin",
            "http://localhost:5173",
        ]
    )

    assert options.allowed_origins == ("http://tauri.localhost", "http://localhost:5173")
    assert parse_options(base).allowed_origins == ()
    for bad in ("*", "http://x.example/path", "http://a.example,http://b.example", "file://x", ""):
        with pytest.raises(SystemExit):
            parse_options([*base, "--allow-origin", bad])
