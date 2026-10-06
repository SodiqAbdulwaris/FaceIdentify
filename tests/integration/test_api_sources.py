"""Sources over HTTP: import, list, detail and the original's media (M4 W3.2; TST-045).

A real application on a real temporary library: authenticated requests through the lifespan, files
on disk, the database behind it.
"""

import base64
import secrets
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

import anyio.to_thread
import httpx
from sqlalchemy import select

from backend.api.pagination import encode_cursor
from backend.api.startup import Backend, create_backend_app
from backend.app.sources.models import Artifact, ArtifactState
from tests.factories.models import ModelFactory
from tests.fixtures.api import MAX_BYTES, MAX_PIXELS, Api, error, imported, library_settings
from tests.fixtures.deterministic import FrozenClock, SeededUUIDs

# --- import ---------------------------------------------------------------------------------


async def test_a_managed_import_copies_the_image_into_the_library(api: Api) -> None:
    path = api.image("beach.png", size=(5, 4))

    source = await imported(api, path=str(path))

    assert source["type"] == "IMAGE"
    assert source["display_name"] == "beach"  # the file name without its extension
    assert source["availability"] == "AVAILABLE"
    assert source["processing_status"] == "NOT_PROCESSED"  # import is not processing
    assert source["storage_mode"] == "MANAGED"
    assert (source["width"], source["height"]) == (5, 4)
    assert source["mime_type"] == "image/png"
    assert source["thumbnail"] is None
    assert source["original"] == {
        "id": source["id"],
        "kind": "ORIGINAL",
        "url": f"/api/v1/sources/{source['id']}/media",
        "content_type": "image/png",
    }
    assert "path" not in str(source).lower().replace("storage_mode", "")  # no filesystem path
    assert str(path) not in str(source)
    path.unlink()  # the library no longer depends on the user's file
    media = await api.client.get(source["original"]["url"])
    assert media.status_code == 200


async def test_a_referenced_import_leaves_the_users_file_where_it_is(api: Api) -> None:
    path = api.image("holiday.jpg", fmt="JPEG")
    before = path.read_bytes()

    source = await imported(api, path=str(path), storage_mode="REFERENCED", display_name=" Trip ")

    assert source["storage_mode"] == "REFERENCED"
    assert source["display_name"] == "Trip"  # trimmed
    assert source["mime_type"] == "image/jpeg"
    assert path.read_bytes() == before  # never touched
    served = await api.client.get(source["original"]["url"])
    assert served.content == before  # served from where the user keeps it
    assert str(path) not in served.headers.get("content-disposition", "")


async def test_importing_the_same_file_twice_makes_two_sources(api: Api) -> None:
    path = api.image()

    first = await imported(api, path=str(path))
    second = await imported(api, path=str(path))

    assert first["id"] != second["id"]


async def test_import_failures_are_mapped_to_stable_codes(api: Api) -> None:
    post = api.client.post
    url = "/api/v1/sources/import"
    text = api.folder / "notes.txt"
    text.write_text("not an image")
    corrupt = api.folder / "broken.png"
    corrupt.write_bytes(api.image("good.png").read_bytes()[:40])
    big_pixels = api.image("wide.png", size=(MAX_PIXELS, 2))  # more pixels than allowed
    big_bytes = api.folder / "huge.png"
    big_bytes.write_bytes(b"\x89PNG" + b"0" * (MAX_BYTES + 1))

    error(
        await post(url, json={"path": str(api.folder / "absent.png")}),
        400,
        "SOURCE_FILE_UNREADABLE",
    )
    error(await post(url, json={"path": str(text)}), 415, "MEDIA_FORMAT_UNSUPPORTED")
    error(await post(url, json={"path": str(corrupt)}), 422, "MEDIA_CORRUPT")
    error(await post(url, json={"path": str(big_pixels)}), 413, "MEDIA_TOO_LARGE")
    error(await post(url, json={"path": str(big_bytes)}), 413, "SOURCE_FILE_TOO_LARGE")
    inside = api.backend.settings.library_root / "database" / "tiny.png"
    inside.write_bytes(b"x")  # small enough to reach the check that it is in the library
    error(
        await post(url, json={"path": str(inside), "storage_mode": "REFERENCED"}),
        400,
        "REFERENCED_FILE_INVALID",
    )
    named = await post(url, json={"path": str(api.image("n.png")), "display_name": "   "})
    detail = error(named, 422, "VALIDATION_ERROR")
    assert detail["details"]["fields"][0]["location"] == ["body", "display_name"]
    listing = (await api.client.get("/api/v1/sources")).json()
    assert [s["display_name"] for s in listing["items"]] == []  # nothing failed left a source


async def test_an_invalid_import_request_is_a_validation_error(api: Api) -> None:
    url = "/api/v1/sources/import"

    relative = error(
        await api.client.post(url, json={"path": "photo.png"}), 422, "VALIDATION_ERROR"
    )
    assert relative["details"]["fields"][0]["location"] == ["body", "path"]
    error(await api.client.post(url, json={}), 422, "VALIDATION_ERROR")
    error(
        await api.client.post(url, json={"path": str(api.image()), "storage_mode": "COPIED"}),
        422,
        "VALIDATION_ERROR",
    )


# --- list and detail ------------------------------------------------------------------------


async def test_the_list_pages_newest_first_without_repeats_or_gaps(api: Api) -> None:
    ids = [(await imported(api, path=str(api.image(f"p{n}.png"))))["id"] for n in range(5)]

    seen: list[str] = []
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        body = (await api.client.get("/api/v1/sources", params=params)).json()
        seen += [item["id"] for item in body["items"]]
        assert set(body["items"][0]) == {
            "id", "type", "display_name", "availability", "processing_status", "thumbnail",
            "created_at", "updated_at",
        }  # fmt: skip
        if not body["page"]["has_more"]:
            assert body["page"]["next_cursor"] is None
            break
        cursor = body["page"]["next_cursor"]

    assert seen == sorted(ids, reverse=True)  # same instant: the unique id breaks ties, descending
    assert len(set(seen)) == 5


async def test_the_list_filters_by_state_and_refuses_bad_input(api: Api) -> None:
    await imported(api, path=str(api.image()))

    recycled = (await api.client.get("/api/v1/sources", params={"state": "RECYCLED"})).json()
    assert recycled["items"] == []
    assert recycled["page"]["has_more"] is False
    error(
        await api.client.get("/api/v1/sources", params={"state": "DELETED"}),
        422,
        "VALIDATION_ERROR",
    )
    error(await api.client.get("/api/v1/sources", params={"cursor": "junk"}), 400, "INVALID_CURSOR")
    # a cursor from another query is not accepted here
    other = (await api.client.get("/api/v1/sources", params={"limit": 1})).json()
    await imported(api, path=str(api.image("again.png")))
    wrong = (
        other["page"]["next_cursor"]
        or (
            (await api.client.get("/api/v1/sources", params={"limit": 1})).json()["page"][
                "next_cursor"
            ]
        )
    )
    error(
        await api.client.get("/api/v1/sources", params={"state": "RECYCLED", "cursor": wrong}),
        400,
        "INVALID_CURSOR",
    )


async def test_detail_reports_the_latest_processing_run(
    api: Api, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    source = await imported(api, path=str(api.image()))
    assert api.backend.library is not None
    with api.backend.library.session_factory() as session:
        build = ModelFactory(session, clock, new_id)
        earlier = clock() - timedelta(hours=1)
        build.run(source_id=uuid.UUID(source["id"]), state="FAILED", created_at=earlier)
        run = build.run(source_id=uuid.UUID(source["id"]), state="RUNNING")
        session.commit()
        run_id = run.id

    detail = (await api.client.get(f"/api/v1/sources/{source['id']}")).json()
    summary = (await api.client.get("/api/v1/sources")).json()["items"][0]

    assert detail["processing_status"] == "RUNNING" == summary["processing_status"]
    assert detail["latest_processing_run"] == {"id": str(run_id), "state": "RUNNING"}
    assert detail["state"] == "ACTIVE"
    assert detail["recycled_at"] is None


async def test_an_unknown_or_malformed_source_id(api: Api) -> None:
    missing = error(
        await api.client.get(f"/api/v1/sources/{uuid.UUID(int=99)}"), 404, "SOURCE_NOT_FOUND"
    )
    assert missing["details"] == {"source_id": str(uuid.UUID(int=99))}
    error(await api.client.get("/api/v1/sources/not-a-uuid"), 422, "VALIDATION_ERROR")
    error(
        await api.client.get(f"/api/v1/sources/{uuid.UUID(int=99)}/media"), 404, "SOURCE_NOT_FOUND"
    )


# --- media ----------------------------------------------------------------------------------


async def test_media_streams_the_original_with_a_content_type_and_an_etag(api: Api) -> None:
    path = api.image("photo.png")
    source = await imported(api, path=str(path))

    response = await api.client.get(f"/api/v1/sources/{source['id']}/media")

    assert response.status_code == 200
    assert response.content == path.read_bytes()
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "private, no-cache"
    etag = response.headers["etag"]
    assert etag.startswith('"')
    assert len(etag) == 66  # the SHA-256 in hex, quoted


async def test_media_answers_304_to_a_matching_etag_and_not_to_another(api: Api) -> None:
    source = await imported(api, path=str(api.image()))
    url = f"/api/v1/sources/{source['id']}/media"
    etag = (await api.client.get(url)).headers["etag"]

    same = await api.client.get(url, headers={"If-None-Match": etag})
    listed = await api.client.get(url, headers={"If-None-Match": f'"other", {etag}'})
    different = await api.client.get(url, headers={"If-None-Match": '"other"'})
    wildcard = await api.client.get(url, headers={"If-None-Match": "*"})
    weak = await api.client.get(url, headers={"If-None-Match": f"W/{etag}"})

    assert (same.status_code, same.content) == (304, b"")
    assert (wildcard.status_code, weak.status_code) == (304, 304)
    assert same.headers["etag"] == etag
    assert listed.status_code == 304
    assert different.status_code == 200


async def test_media_for_a_missing_original_is_a_stable_error(api: Api) -> None:
    managed = await imported(api, path=str(api.image("a.png")))
    referenced_path = api.image("b.png")
    referenced = await imported(api, path=str(referenced_path), storage_mode="REFERENCED")
    referenced_path.unlink()  # the user moved their file away
    assert api.backend.library is not None
    with api.backend.library.session_factory() as session:  # and recovery has marked one MISSING
        artifact = session.scalars(select(Artifact).where(Artifact.storage_key.is_not(None))).one()
        artifact.state = ArtifactState.MISSING
        session.commit()

    gone = error(await api.client.get(referenced["original"]["url"]), 404, "SOURCE_FILE_MISSING")
    flagged = error(
        await api.client.get(f"/api/v1/sources/{managed['id']}/media"), 404, "SOURCE_FILE_MISSING"
    )

    assert gone["details"] == {"availability": "MISSING"}
    assert flagged["details"] == {"availability": "MISSING"}
    detail = (await api.client.get(f"/api/v1/sources/{managed['id']}")).json()
    assert detail["availability"] == "MISSING"
    assert detail["original"] is None  # no media reference to bytes that are not there


async def test_a_well_formed_cursor_with_a_nonsense_key_is_invalid(api: Api) -> None:
    forged = encode_cursor("sources:ACTIVE", ["not-a-date", "not-an-id"])

    error(await api.client.get("/api/v1/sources", params={"cursor": forged}), 400, "INVALID_CURSOR")


async def test_media_is_missing_when_the_file_is_gone_even_if_the_row_still_says_available(
    api: Api,
) -> None:
    source = await imported(api, path=str(api.image()))
    assert api.backend.library is not None
    with api.backend.library.session_factory() as session:
        key = session.scalars(select(Artifact.storage_key)).one()
    assert key is not None
    api.backend.library.store.roots.path_for(key).unlink()  # lost behind the application's back

    gone = error(await api.client.get(source["original"]["url"]), 404, "SOURCE_FILE_MISSING")

    assert gone["details"] == {"availability": "MISSING"}


async def test_media_without_a_recorded_hash_has_no_etag_and_is_always_served(api: Api) -> None:
    path = api.image()
    source = await imported(api, path=str(path), storage_mode="REFERENCED")
    assert api.backend.library is not None
    with api.backend.library.session_factory() as session:
        session.scalars(select(Artifact)).one().sha256 = None
        session.commit()

    first = await api.client.get(source["original"]["url"])
    again = await api.client.get(source["original"]["url"], headers={"If-None-Match": '"any"'})

    assert first.content == again.content == path.read_bytes()
    assert "etag" not in first.headers


# --- access ---------------------------------------------------------------------------------


async def test_every_source_route_requires_the_launch_capability(api: Api) -> None:
    transport = httpx.ASGITransport(app=api.app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as anonymous:
        for method, path in (
            ("GET", "/api/v1/sources"),
            ("GET", f"/api/v1/sources/{uuid.UUID(int=1)}"),
            ("GET", f"/api/v1/sources/{uuid.UUID(int=1)}/media"),
            ("POST", "/api/v1/sources/import"),
        ):
            assert (await anonymous.request(method, path)).status_code == 401


async def test_the_source_routes_wait_for_the_library(
    tmp_path: Path, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    secret = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
    app = create_backend_app(secret, library_settings(tmp_path, clock, new_id))
    # the application object without its lifespan: the library never opens
    app.state.backend = Backend(library_settings(tmp_path, clock, new_id))

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", headers={"Authorization": f"Bearer {secret}"}
    ) as client:
        body = (await client.get("/api/v1/sources")).json()["error"]

    assert body["code"] == "LIBRARY_UNAVAILABLE"
    assert body["retryable"] is True


async def test_import_is_unavailable_until_the_host_configures_its_limits(
    tmp_path: Path, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    secret = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
    app = create_backend_app(secret, library_settings(tmp_path, clock, new_id))  # no limits
    async with app.router.lifespan_context(app):
        assert await anyio.to_thread.run_sync(app.state.backend.settled.wait, 60)
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"Authorization": f"Bearer {secret}"},
        ) as client:
            response = await client.post("/api/v1/sources/import", json={"path": str(tmp_path)})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "IMPORT_UNAVAILABLE"
