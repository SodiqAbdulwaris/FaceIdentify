# Architecture 02 HTTP and FastAPI

## 1. What this is and why it exists

Everything the screens (and your `curl`) ask of the backend travels over **HTTP**, and the backend answers with the
**FastAPI** framework running on the **uvicorn** server. This lesson teaches the minimum web you need and the FastAPI ideas
the routes rely on, with a 25-line application you run yourself, then shows where this project deliberately changes
FastAPI's defaults.

## 2. Where it lives

| Thing | Where |
|---|---|
| The application factory (auth, `/health`, `/readiness`, the WebSocket) | `backend/api/app.py` (`create_app`) |
| The backend wiring (lifespan, routes, events) | `backend/api/startup.py` (`create_backend_app`) |
| The routes | `backend/api/routes/*.py` |
| Dependencies | `backend/api/dependencies.py` (`get_backend`, `require_library`, `Library`) |
| The project's error handlers | `backend/api/errors.py` |
| The server | `backend/api/host.py` (uvicorn, one socket on `127.0.0.1`) |

## 3. How it works

### The web in a paragraph

**HTTP** is how a client asks a server for something: a **request** (method, path, headers, optional body) and a
**response** (status code, headers, body). Methods: `GET` read, `POST` create or do, `PUT`/`PATCH` change, `DELETE` remove.
Status codes: `200` OK, `201` created, `202` accepted (will be done later), `204` no content, `400` bad request, `401`
unauthenticated, `404` not found, `409` conflict, `422` invalid input, `500` server fault, `503` unavailable.
**JSON** is the usual body format. A **path** like `/api/v1/sources/{source_id}` names a resource and `{source_id}` is a
**path parameter**; `?limit=20` is a **query parameter**. **REST** is the style of naming resources by path and acting on them
with methods. A **WebSocket** is a long-lived two-way connection (used here only to *push* events). **Loopback**
(`127.0.0.1`) is your own machine: a server bound there cannot be reached from the network. A **Bearer token** is a secret
sent in `Authorization: Bearer <token>`.

### FastAPI in five ideas

1. **A function plus a decorator is a route.** `@router.get("/{source_id}")` above a function.
2. **Type hints drive validation.** `source_id: uuid.UUID` means a malformed id is refused with `422` before your code runs.
   **Pydantic** (`BaseModel`) describes request and response bodies as typed classes that validate and serialise.
3. **`Depends(...)` is dependency injection.** FastAPI calls a helper (find the open library, check something) and passes
   the result in. `Library = Annotated[OpenLibrary, Depends(require_library)]` is why a route that takes `Library` is
   answered `503` until the library is open.
4. **Routers group routes.** Nine routers under `/api/v1`.
5. **OpenAPI comes free.** FastAPI describes every route as a document ([the contract](../api/03-openapi-and-contract.md)).

**ASGI** is the standard interface between Python async web applications and servers; **uvicorn** is the server that runs
the app and speaks HTTP and WebSocket (with the `websockets` library underneath). `async def` routes run on the event loop;
plain `def` routes run in a worker thread ([Python 06](../../01-basics/python/06-iterators-decorators-concurrency.md)).

### Where this project changes FastAPI's defaults

- **One error shape** for everything ([API README](../api/README.md)); FastAPI's default validation error echoes the
  input you sent (`"input": {...}`), which could be a path or personal data, so `backend/api/errors.py` replaces it with
  `{"location": [...], "type": "..."}` only.
- **Every HTTP request needs the Bearer token**, middleware in `create_app`, including `/health`, `/readiness`, `/docs`
  and `/openapi.json`.
- **Operation ids are function names** (`generate_unique_id_function=operation_id`) for a readable generated client.
- **Unexpected errors** are a generic `500 INTERNAL_ERROR` with a diagnostic id and no traceback.

## 4. Try it

**Works with no models. Verified 2026-10-12.** Write a tiny app in a scratch folder (not in the repository), `tiny.py`:

```python
import uuid

from fastapi import Depends, FastAPI
from pydantic import BaseModel

app = FastAPI()


class Echo(BaseModel):
    name: str
    count: int = 1


def current_user() -> str:
    return "ada"


@app.get("/hello/{thing_id}")
def hello(thing_id: uuid.UUID, shout: bool = False, user: str = Depends(current_user)) -> dict[str, str]:
    text = f"hello {user}, thing {thing_id.hex[:6]}"
    return {"text": text.upper() if shout else text}


@app.post("/echo", status_code=201)
def echo(body: Echo) -> Echo:
    return body
```

Run it from the repository folder (so the project's FastAPI is used) and call it from a second terminal:

```bash
uv run uvicorn tiny:app --app-dir path/to/the/scratch/folder --port 8123
curl -s "http://127.0.0.1:8123/hello/3f2504e0-4f89-11d3-9a0c-0305e82c3301?shout=true"
curl -s "http://127.0.0.1:8123/hello/not-a-uuid"
curl -s -i -X POST -H "Content-Type: application/json" -d '{"name":"x"}' http://127.0.0.1:8123/echo
curl -s -X POST -H "Content-Type: application/json" -d '{"count":"many"}' http://127.0.0.1:8123/echo
curl -s http://127.0.0.1:8123/openapi.json
```

Observed: `{"text":"HELLO ADA, THING 3F2504"}`; for the bad id a `detail` list with `"type":"uuid_parsing"`, `"loc":["path","thing_id"]`
and, note, `"input":"not-a-uuid"` (FastAPI's default echoes the input, which FaceIdentify removes); `HTTP/1.1 201 Created`
with `{"name":"x","count":1}` (the default was filled in); for the bad body two errors, `missing` for `body.name` and
`int_parsing` for `body.count`; and an OpenAPI document listing `/hello/{thing_id}` and `/echo`. Open
`http://127.0.0.1:8123/docs` in a browser for the interactive page (this toy app has no token, so a browser works; the
real backend's `/docs` needs the Bearer header). Stop uvicorn with Ctrl+C.

Compare with the real backend: send the same bad id to `/api/v1/sources/not-a-uuid` (needs the token): the answer is the
**project's** shape, `{"error": {"code": "VALIDATION_ERROR", ..., "details": {"fields": [{"location": ["path", "source_id"],
"type": "uuid_parsing"}]}}}`, with no `input`.

## 5. Change it

Add a query parameter to the toy app (`limit: int = 5`) and a `Field(ge=1, le=10)` constraint, restart, and call with
`?limit=50`: `422` with `less_than_equal`. That is exactly how the real routes bound `limit` (`Query(ge=1, le=200)` in
`pagination.py`). Then read how the real app builds on it: `create_app` in `backend/api/app.py` is about 70 lines, readable
in one sitting. The tests that pin the shared behaviour are in `tests/contracts/test_api_conventions.py` and
`test_api_launch_capability.py` (`uv run pytest tests/contracts -q`).

## 6. Break it on purpose

Annotate a route parameter wrongly (`thing_id: int` and send a UUID): `422 int_parsing`. Return something that does not
match the declared model: FastAPI raises `ResponseValidationError` and the client sees `500`. Forget `Content-Type:
application/json` when posting JSON: `422` (`model_attributes_type`), the most common "my command did nothing" mistake.

## 7. Exercises

1. What does `thing_id: uuid.UUID` do before your function runs?
2. What does `201` tell the client that `200` does not?
3. Why does the real backend need a Bearer header even for `/health`?
4. What is the difference between a path parameter and a query parameter?
5. Which FastAPI feature hands a route the open library?

**Answers**

1. Parses the path text as a UUID and answers `422` if it is not one.
2. A new thing was created.
3. Every route is guarded by one middleware; the token is a per-launch capability, so unrelated programs on the machine
   cannot call anything.
4. A path parameter is part of the address and names the resource; a query parameter (after `?`) refines or filters.
5. `Depends`, through the `Library` annotation (`require_library`).

## 8. Related files

- Previous: [01 Layers and rules](01-layers-and-rules.md) · Next: [03 The host and startup](03-host-and-startup.md)
- [`backend/api/app.py`](../../../../../backend/api/app.py), [`backend/api/errors.py`](../../../../../backend/api/errors.py)
- Further reading: the FastAPI tutorial (fastapi.tiangolo.com), MDN "HTTP" overview
