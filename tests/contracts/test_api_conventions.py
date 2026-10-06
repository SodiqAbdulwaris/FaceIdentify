"""The API conventions every route inherits: the error shape, validation, cursors, library gating
(API and Contracts sections 23 to 27; M4 W3.1; TST-045).

A throwaway router stands in for real routes, so each convention is shown on its own.
"""

import base64
import json
import logging
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from fastapi import APIRouter, FastAPI
from pydantic import BaseModel

from backend.api.app import create_app
from backend.api.dependencies import Library
from backend.api.errors import ApiError
from backend.api.pagination import (
    CURSOR_VERSION,
    DEFAULT_LIMIT,
    MAX_LIMIT,
    PageQuery,
    decode_cursor,
    encode_cursor,
    paginate,
)
from backend.api.startup import Backend, LibrarySettings, LifecycleState
from backend.app.lifecycle import OpenLibrary
from backend.app.memory.index_coordinator import RetryPolicy
from backend.infrastructure.db.unit_of_work import TransactionRetry

SECRET = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
AUTH = {"Authorization": f"Bearer {SECRET}"}
ERROR_FIELDS = {"code", "message", "details", "retryable", "diagnostic_id"}


class Widget(BaseModel):
    name: str
    size: int


def backend_in(state: LifecycleState, *, library: bool, failure: str | None = None) -> Backend:
    settings = LibrarySettings(
        library_root=Path("unused"),
        local_state_root=Path("unused"),
        clock=lambda: datetime.now(UTC),
        new_id=lambda: cast(Any, None),
        retry=RetryPolicy(max_attempts=1, backoff=lambda n: timedelta(seconds=n)),
        transaction_retry=TransactionRetry(max_attempts=1, backoff=lambda n: 0.0),
        index_batch=1,
        max_index_passes=1,
    )
    backend = Backend(settings)
    backend.state = state
    backend.failure = failure
    backend.library = cast(OpenLibrary, object()) if library else None
    return backend


def application(backend: Backend | None = None) -> FastAPI:
    app = create_app(SECRET)
    app.state.backend = backend or backend_in(LifecycleState.READY, library=True)
    router = APIRouter(prefix="/api/v1")

    @router.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret detail C:/Users/someone/private.jpg")

    @router.get("/missing")
    async def missing() -> None:
        raise ApiError(
            404, "SOURCE_NOT_FOUND", "The requested source could not be found.",
            details={"source_id": "abc"},
        )  # fmt: skip

    @router.get("/flaky")
    async def flaky() -> None:
        raise ApiError(503, "INDEX_UNAVAILABLE", "The index is rebuilding.", retryable=True)

    @router.post("/widgets")
    async def make(widget: Widget) -> Widget:
        return widget

    @router.get("/needs-library")
    async def needs_library(library: Library) -> dict[str, bool]:
        return {"has_library": library is not None}

    @router.get("/numbers")
    async def numbers(page: PageQuery) -> dict[str, Any]:
        context = "numbers"
        start = 0 if page.cursor is None else decode_cursor(page.cursor, context)[0]
        rows = list(range(start + 1, start + page.limit + 2))[: page.limit + 1]
        rows = [n for n in rows if n <= 7]  # seven items in all, ordered by their number
        result = paginate(
            rows, page.limit, context=context, key=lambda n: [n], item=lambda n: {"n": n}
        )
        return result.model_dump()

    app.include_router(router)
    return app


async def call(app: FastAPI, method: str, path: str, **kwargs: Any) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, headers=AUTH, **kwargs)


def assert_error(response: httpx.Response, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status
    error: dict[str, Any] = response.json()["error"]
    assert set(error) == ERROR_FIELDS
    assert error["code"] == code
    return error


# --- the error shape -------------------------------------------------------------------------


async def test_an_expected_error_keeps_its_status_code_details_and_retryability() -> None:
    app = application()

    missing = assert_error(await call(app, "GET", "/api/v1/missing"), 404, "SOURCE_NOT_FOUND")
    assert missing["details"] == {"source_id": "abc"}
    assert missing["retryable"] is False
    assert missing["diagnostic_id"] is None

    flaky = assert_error(await call(app, "GET", "/api/v1/flaky"), 503, "INDEX_UNAVAILABLE")
    assert flaky["retryable"] is True


async def test_a_validation_failure_is_normalized_and_never_echoes_what_was_sent() -> None:
    app = application()

    response = await call(app, "POST", "/api/v1/widgets", json={"name": "C:/private/secret.jpg"})
    error = assert_error(response, 422, "VALIDATION_ERROR")

    fields = error["details"]["fields"]
    assert fields[0]["location"] == ["body", "size"]
    assert set(fields[0]) == {"location", "type"}  # no `msg`, no `input`
    assert "secret.jpg" not in response.text  # the client's input is not reflected back
    ok = await call(app, "POST", "/api/v1/widgets", json={"name": "a", "size": 2})
    assert ok.json() == {"name": "a", "size": 2}


async def test_unknown_routes_and_methods_use_the_same_shape() -> None:
    app = application()

    assert_error(await call(app, "GET", "/api/v1/nowhere"), 404, "NOT_FOUND")
    assert_error(await call(app, "DELETE", "/api/v1/missing"), 405, "METHOD_NOT_ALLOWED")


async def test_an_unexpected_error_is_internal_error_with_a_diagnostic_id_and_no_detail(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = application()

    with caplog.at_level(logging.ERROR, logger="faceidentify.api"):
        response = await call(app, "GET", "/api/v1/boom")

    error = assert_error(response, 500, "INTERNAL_ERROR")
    assert error["diagnostic_id"]
    assert error["details"] is None
    assert "secret" not in response.text  # neither the message nor the path nor a traceback
    assert "Traceback" not in response.text
    logged = [r for r in caplog.records if r.name == "faceidentify.api"]
    assert len(logged) == 1
    assert error["diagnostic_id"] in logged[0].getMessage()  # matched to the local log
    assert "RuntimeError" in logged[0].getMessage()


async def test_the_authentication_failure_has_the_full_error_shape() -> None:
    app = application()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/missing")  # no capability

    assert_error(response, 401, "UNAUTHORIZED")
    assert response.headers["www-authenticate"] == "Bearer"


# --- library gating --------------------------------------------------------------------------


async def test_a_route_that_needs_the_library_is_served_once_it_is_open() -> None:
    for state in (LifecycleState.READY, LifecycleState.DEGRADED):
        app = application(backend_in(state, library=True))
        response = await call(app, "GET", "/api/v1/needs-library")
        assert response.json() == {"has_library": True}


@pytest.mark.parametrize(
    ("state", "library", "failure", "retryable"),
    [
        (LifecycleState.INITIALIZING, False, None, True),
        (LifecycleState.FAILED, False, "LibraryLockedError", False),
        (LifecycleState.FAILED, True, "KeyError", False),
        (LifecycleState.SHUTTING_DOWN, False, None, False),
    ],
)
async def test_a_route_that_needs_the_library_is_503_until_it_is_open_and_never_after_a_failure(
    state: LifecycleState, library: bool, failure: str | None, retryable: bool
) -> None:
    app = application(backend_in(state, library=library, failure=failure))

    error = assert_error(
        await call(app, "GET", "/api/v1/needs-library"), 503, "LIBRARY_UNAVAILABLE"
    )

    assert error["retryable"] is retryable
    expected = {"state": state.value} | ({"failure": failure} if failure else {})
    assert error["details"] == expected  # the state and a class name, nothing else


# --- cursors ---------------------------------------------------------------------------------


def test_a_cursor_round_trips_its_key_for_the_query_it_was_made_for() -> None:
    cursor = encode_cursor("sources:created", ["2026-10-07T00:00:00Z", "id-1", 7, None])

    assert decode_cursor(cursor, "sources:created") == ["2026-10-07T00:00:00Z", "id-1", 7, None]
    assert "=" not in cursor  # URL-safe, unpadded


@pytest.mark.parametrize(
    "cursor",
    [
        "not base64 !!",
        "",
        base64.urlsafe_b64encode(b"not json").decode(),
        base64.urlsafe_b64encode(b"[1, 2]").decode(),  # valid JSON, wrong shape
        base64.urlsafe_b64encode(json.dumps({"v": 99, "c": "q", "k": [1]}).encode()).decode(),
        base64.urlsafe_b64encode(json.dumps({"v": CURSOR_VERSION, "c": "q"}).encode()).decode(),
        base64.urlsafe_b64encode(
            json.dumps({"v": CURSOR_VERSION, "c": "q", "k": [{"a": 1}]}).encode()
        ).decode(),  # a nested structure is not a key
        "é",
    ],
)
def test_a_malformed_cursor_is_invalid(cursor: str) -> None:
    with pytest.raises(ApiError) as error:
        decode_cursor(cursor, "q")
    assert (error.value.status_code, error.value.code) == (400, "INVALID_CURSOR")


def test_a_page_holds_at_least_one_item() -> None:
    with pytest.raises(ValueError, match="at least one"):
        paginate([1, 2], 0, context="q", key=lambda n: [n], item=lambda n: n)


def test_a_cursor_made_for_another_query_is_invalid() -> None:
    cursor = encode_cursor("sources:created", [1])

    with pytest.raises(ApiError) as error:
        decode_cursor(cursor, "identities:created")

    assert error.value.code == "INVALID_CURSOR"


async def test_pages_walk_the_whole_collection_forward_with_a_has_more_flag() -> None:
    app = application()
    seen: list[int] = []
    cursor: str | None = None

    for expected_more in (True, True, False):
        params: dict[str, Any] = {"limit": 3}
        if cursor:
            params["cursor"] = cursor
        body = (await call(app, "GET", "/api/v1/numbers", params=params)).json()
        seen += [item["n"] for item in body["items"]]
        assert body["page"]["has_more"] is expected_more
        assert (body["page"]["next_cursor"] is not None) is expected_more
        cursor = body["page"]["next_cursor"]

    assert seen == [1, 2, 3, 4, 5, 6, 7]  # in order, each once, none skipped


async def test_a_page_that_ends_exactly_on_the_limit_has_no_more() -> None:
    app = application()

    body = (await call(app, "GET", "/api/v1/numbers", params={"limit": 7})).json()

    assert [item["n"] for item in body["items"]] == [1, 2, 3, 4, 5, 6, 7]
    assert body["page"] == {"next_cursor": None, "has_more": False}


async def test_a_bad_cursor_or_limit_is_refused_in_the_standard_shape() -> None:
    app = application()

    assert_error(
        await call(app, "GET", "/api/v1/numbers", params={"cursor": "garbage"}),
        400,
        "INVALID_CURSOR",
    )
    for limit in (0, -1, MAX_LIMIT + 1):
        assert_error(
            await call(app, "GET", "/api/v1/numbers", params={"limit": limit}),
            422,
            "VALIDATION_ERROR",
        )
    assert_error(
        await call(app, "GET", "/api/v1/numbers", params={"cursor": "x" * 600}),
        422,
        "VALIDATION_ERROR",
    )
    default = (await call(app, "GET", "/api/v1/numbers")).json()
    assert len(default["items"]) == 7 <= DEFAULT_LIMIT  # the default limit is 50
    assert (
        len(
            (await call(app, "GET", "/api/v1/numbers", params={"limit": MAX_LIMIT})).json()["items"]
        )
        == 7
    )
