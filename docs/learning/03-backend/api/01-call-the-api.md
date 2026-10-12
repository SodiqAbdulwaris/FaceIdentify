# API 01 Call the API by hand

## 1. What this is and why it exists

The screens are only one client of the backend. Anything they do you can do with `curl`, a few lines of Python,
or a test. Calling the API by hand is the fastest way to understand a route, to reproduce a bug without the
window, and to check a change you made. This lesson is the cookbook: start the backend, call every kind of
route, listen to events, and write the same call as an automated test.

## 2. Where it lives

| Thing | Where |
|---|---|
| The routes | `backend/api/routes/*.py`; the full map in [the API README](README.md) |
| The machine-readable description | `frontend/src/api/openapi.json` (committed; see [OpenAPI](03-openapi-and-contract.md)) |
| The test client | `tests/fixtures/api.py` (`api`, `processing_api`, `imported`, `error`) |
| The events | `WS /api/v1/events` in `backend/api/app.py` |

## 3. How it works

You need three things: **where** the backend is (the port from its handshake line), **who you are** (the launch
token, sent as `Authorization: Bearer ...`), and a **library with some content** (from
[start-here 07](../../00-start-here/07-run-it-and-see-it-work.md)). There is no interactive API page you can open
in a browser: `/docs` and `/openapi.json` exist, but like every route they need the Bearer header, which a browser
address bar cannot send. Use the committed `frontend/src/api/openapi.json`, or `curl` them with the header.

## 4. Try it

**Works with no models. Verified 2026-10-12** (bash and `curl`; Python works everywhere; PowerShell notes at the end).

### Start a backend and keep its coordinates

```bash
export FACEIDENTIFY_LAUNCH_TOKEN="$(uv run python -c 'import secrets; print(secrets.token_urlsafe(32))')"
uv run python -m backend.api.host --library-root ~/faceidentify-play/lib \
  --local-state-root ~/faceidentify-play/state --development-profile > host.out 2> host.err &
sleep 6
PORT=$(python3 -c "import json; print(json.loads(open('host.out').readline())['port'])")
B=http://127.0.0.1:$PORT
H="Authorization: Bearer $FACEIDENTIFY_LAUNCH_TOKEN"
J="Content-Type: application/json"
curl -s -H "$H" $B/readiness
```

Expected: `{"state":"READY","capabilities":{...}}`. (The handshake is the first line of `host.out`.)

### A small helper to pick values out of JSON

```bash
j() { python3 -c "import sys,json; d=json.load(sys.stdin); print(eval(sys.argv[1]))" "$1"; }
SID=$(curl -s -H "$H" "$B/api/v1/sources?limit=1" | j "d['items'][0]['id']")
```

### The kinds of call

1. **Read one thing:** `curl -s -H "$H" $B/api/v1/sources/$SID | python3 -m json.tool`.
2. **Read a collection, with pages:**

   ```bash
   curl -s -H "$H" "$B/api/v1/sources?limit=2" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d['items']), d['page'])"
   CUR=$(curl -s -H "$H" "$B/api/v1/sources?limit=2" | j "d['page']['next_cursor']")
   curl -s -H "$H" "$B/api/v1/sources?limit=2&cursor=$CUR" | python3 -c "import sys,json; print([i['display_name'] for i in json.load(sys.stdin)['items']])"
   ```

   Expected: `2 {'next_cursor': 'eyJ2Ijoi...', 'has_more': True}` then the next two names. A cursor from a different
   query (`/identities?cursor=$CUR`) gives `400 INVALID_CURSOR`.
3. **Create or command (JSON body):** import, name, merge: see the route lessons. Always `-H "$J"` and `-d '{...}'`.
4. **A command that works later (202):** `curl -s -X POST -H "$H" $B/api/v1/sources/$SID/process` returns the run
   immediately in state `PENDING`; ask `GET /api/v1/processing-runs/<id>` until `COMPLETED`.
5. **A body that is a file, not JSON:** face search:
   `curl -s -X POST -H "$H" -H "Content-Type: image/png" --data-binary @picture.png $B/api/v1/search/face`.
6. **A binary answer with a cache check:** the original image:

   ```bash
   curl -s -D - -o /dev/null -H "$H" $B/api/v1/sources/$SID/media | head -7
   ```

   Observed: `200 OK`, `cache-control: private, no-cache`, `etag: "<the file's SHA-256>"`, `content-type: image/png`.
   Repeat with `-H "If-None-Match: <that etag>"` and the answer is `304`.
7. **Failures are data:** the same call without the token gives `401`; a malformed id (`/sources/not-a-uuid`) gives
   `422 VALIDATION_ERROR` with `"location":["path","source_id"],"type":"uuid_parsing"`; an unknown path `404 NOT_FOUND`; a
   wrong method `405 METHOD_NOT_ALLOWED`. Read `error.code`, not the message.

### The same in Python

```python
import os, time, httpx
api = httpx.Client(base_url="http://127.0.0.1:PORT",
                   headers={"Authorization": "Bearer " + os.environ["FACEIDENTIFY_LAUNCH_TOKEN"]}, timeout=30)
sources = api.get("/api/v1/sources", params={"limit": 2}).json()
run = api.post(f"/api/v1/sources/{sources['items'][0]['id']}/process").json()
while api.get(f"/api/v1/processing-runs/{run['id']}").json()["state"] not in ("COMPLETED", "FAILED"):
    time.sleep(0.5)
```

### Listen to events

Events are pushed on a WebSocket, authenticated by offering the token as a sub-protocol (a browser cannot set an
`Authorization` header on a WebSocket). `websockets` is a project dependency:

```python
import asyncio, json, os, urllib.request
import websockets

PORT, TOKEN = 49433, os.environ["FACEIDENTIFY_LAUNCH_TOKEN"]     # your port

def post(path):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", method="POST",
                                 headers={"Authorization": "Bearer " + TOKEN})
    return json.load(urllib.request.urlopen(req))

async def main():
    url = f"ws://127.0.0.1:{PORT}/api/v1/events"
    async with websockets.connect(url, subprotocols=["faceidentify.v1", "fi." + TOKEN]) as ws:
        print("subprotocol:", ws.subprotocol)
        print(json.loads(await ws.recv())["type"])                       # the greeting
        await asyncio.get_running_loop().run_in_executor(None, post, "/api/v1/sources/<SOURCE ID>/process")
        for _ in range(3):
            event = json.loads(await asyncio.wait_for(ws.recv(), 10))
            print(event["sequence"], event["type"], event["resource"]["type"], event["data"])

asyncio.run(main())
```

Observed output: `subprotocol: faceidentify.v1`, `system.hello`, then
`1 processing_run.created processing_run {'state': 'PENDING', 'source_id': '...'}`,
`2 processing_run.updated processing_run {'state': 'RUNNING', ...}`,
`3 processing_run.updated processing_run {'state': 'COMPLETED', ...}`. Note the numbered `sequence`, and that the
event says only *that* something changed: a client refetches.

### As an automated test

The tests do the same through the real application in memory. Look at `tests/integration/test_api_sources.py`:

```python
async def test_a_managed_import_copies_the_image_into_the_library(api: Api) -> None:
    path = api.image("beach.png", size=(5, 4))
    source = await imported(api, path=str(path))
    assert source["display_name"] == "beach"
    media = await api.client.get(source["original"]["url"])
    assert media.status_code == 200
```

`api` is a fixture that starts the application with a real temporary library; `api.client` is an `httpx` client
already carrying the Bearer header. Run it: `uv run pytest tests/integration/test_api_sources.py -q`.

### PowerShell

In PowerShell `curl` means `Invoke-WebRequest`; call `curl.exe`, and quote JSON carefully (single-quote the body
and double the inner quotes, or put it in a file and use `-d "@body.json"`): *unverified here*. The Python snippets
need no changes.

## 5. Change it

Make a call fail in a way you choose and read it. Ask for a page size beyond the maximum: `?limit=500` gives
`422 VALIDATION_ERROR` (the limit is 1 to 200, `MAX_LIMIT` in `backend/api/pagination.py`). To change a limit for
real you edit that constant and update the tests that pin it (`tests/contracts/test_api_conventions.py`); the
front end reads `has_more` and `next_cursor`, never the number.

## 6. Break it on purpose

Send the right body to the wrong content type: `curl -X POST -H "$H" -d '{"path":"x"}' $B/api/v1/sources/import`
without `-H "$J"`. Expected: `422 VALIDATION_ERROR` (FastAPI cannot read the body as JSON). Forgetting the
`Content-Type` is the most common reason a correct command "does nothing".

## 7. Exercises

1. Which header carries the token on HTTP, and how does a WebSocket carry it?
2. A cursor returned from `/sources` is sent to `/identities`. What happens and why?
3. `POST .../process` returned instantly with `state: PENDING`. How do you learn it finished?
4. Which status code means "your copy is stale, reload"?
5. What does a `304` on the media route tell you?

**Answers**

1. `Authorization: Bearer <token>`; as the WebSocket sub-protocol value `fi.<token>` next to `faceidentify.v1`.
2. `400 INVALID_CURSOR`: a cursor names the query that made it.
3. Poll `GET /processing-runs/{id}` or listen for `processing_run.updated` events, then refetch.
4. `409` with a revision-style code (`PERSON_REVISION_CONFLICT`, `IDENTITY_CHANGED`, `OCCURRENCE_MOVED`).
5. Your cached copy matches the file's SHA-256 (the `ETag`); nothing is sent again.

## 8. Related files

- Next: [02 Add a route](02-add-a-route.md) · [API README](README.md)
- [`tests/fixtures/api.py`](../../../../tests/fixtures/api.py), [`backend/api/app.py`](../../../../backend/api/app.py)
- [Events](../architecture/07-events.md)
