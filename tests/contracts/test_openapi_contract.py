"""The generated API contract (M4 W5; TST-046): the committed OpenAPI document matches the routes,
every operation declares the one error shape, and operation ids read as function names.

The frontend's TypeScript types are generated from the committed document, and CI regenerates them
to prove they match; this test is the other half, proving the document matches the backend.
"""

import runpy
import sys
from pathlib import Path
from typing import Any

import pytest

from backend.api.openapi import OPENAPI_PATH, main, openapi_document, render

HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


def operations(document: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    return [
        (path, method, op)
        for path, item in document["paths"].items()
        for method, op in item.items()
        if method in HTTP_METHODS
    ]


def test_the_committed_document_is_what_the_application_produces() -> None:
    committed = OPENAPI_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")

    assert committed == render(openapi_document()), (
        "frontend/src/api/openapi.json is stale: run `npm run generate:api` and commit the result"
    )


def test_every_api_operation_declares_the_one_error_shape() -> None:
    document = openapi_document()

    api = [(p, m, op) for p, m, op in operations(document) if p.startswith("/api/v1/")]

    assert len(api) >= 17  # the routes written so far; more only ever add
    for path, method, op in api:
        default = op["responses"]["default"]["content"]["application/json"]["schema"]
        assert default == {"$ref": "#/components/schemas/ErrorEnvelope"}, (path, method)
    error = document["components"]["schemas"]["ErrorBody"]
    assert set(error["properties"]) == {"code", "message", "details", "retryable", "diagnostic_id"}


def test_operation_ids_are_the_unique_function_names() -> None:
    ids = [op["operationId"] for _, _, op in operations(openapi_document())]

    assert len(ids) == len(set(ids))
    assert "import_source" in ids
    assert all("_api_v1_" not in i for i in ids)  # not FastAPI's long path-derived default


def test_the_document_names_no_launch_secret_or_filesystem_path() -> None:
    text = render(openapi_document())

    assert "Bearer" not in text.replace("securitySchemes", "")  # the token is never described
    assert "unused" not in text  # the placeholder settings never leak into the document


def test_the_exporter_writes_the_rendered_document(tmp_path: Path) -> None:
    target = tmp_path / "openapi.json"

    assert main(target) == 0

    written = target.read_bytes()
    assert written == render(openapi_document()).encode("utf-8")
    assert b"\r" not in written  # always LF, whatever the platform


def test_running_the_module_rewrites_the_committed_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / OPENAPI_PATH.parent).mkdir(parents=True)

    monkeypatch.delitem(sys.modules, "backend.api.openapi")  # run it fresh, as `python -m` would
    with pytest.raises(SystemExit) as stopped:
        runpy.run_module("backend.api.openapi", run_name="__main__")

    assert stopped.value.code == 0
    assert (tmp_path / OPENAPI_PATH).read_text(encoding="utf-8") == render(openapi_document())
