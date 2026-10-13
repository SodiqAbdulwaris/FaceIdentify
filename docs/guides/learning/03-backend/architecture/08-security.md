# Architecture 08 Security: who may talk to the backend

## 1. What this is and why it exists

The backend holds photographs and names of real people, and it listens on a network port. Anything else on the computer
(another program, a web page in a browser) could try to talk to it. So the design has one rule: **nothing is answered unless
the caller proves it was launched by the shell**. The proof is a random one-time secret, the **launch token**, that the
shell makes, hands to the backend through an environment variable, and then sends on every request. This lesson lists the
protections that exist, where each lives, and the tests that pin them.

## 2. Where it lives

| Protection | Where |
|---|---|
| Token validation (canonical 256-bit URL-safe base64), constant-time compare | `backend/api/app.py`, `backend/api/host.py` (`read_launch_token`) |
| Bearer check on every HTTP route | the authentication dependency in `backend/api/app.py` |
| WebSocket check | `event_stream` in `backend/api/app.py` ([events](07-events.md)) |
| One error envelope that hides inputs and tracebacks | `backend/api/errors.py` |
| Loopback only, exclusive port on Windows | `serve` in `backend/api/host.py` |
| CORS: exact origins only, never `*`, no credentials; added outermost so a token-less preflight is answered, while every real request still needs the token | `create_app(allowed_origins=...)` in `backend/api/app.py`; host flag `--allow-origin`; `tests/unit/test_cors.py` (6) |
| Safe storage keys, UNC paths refused for face search | `backend/infrastructure/storage` and the face-search route |
| Model files hashed before use | [packages and catalog](../runtime-and-worker/04-packages-and-catalog.md) |
| Tests | `tests/contracts/test_api_launch_capability.py`, `tests/security/test_test_data_isolation.py`, `tests/integration/test_api_host.py`, `test_api_lifespan.py`, `test_library_profile.py` |

## 3. How it works

- **The token never travels on a command line** (other programs can list command lines) and is never written to a log or an
  error. The host reads it from `FACEIDENTIFY_LAUNCH_TOKEN`; a missing or malformed token stops the process with exit code
  2 *before a port is bound*, and the message never contains the token.
- **Every HTTP route needs `Authorization: Bearer <token>`**, including `/health`, `/readiness`, `/docs` and
  `/openapi.json`. A failure is `401` with `WWW-Authenticate: Bearer`. The comparison is constant-time, so response timing
  does not leak how many characters matched.
- **The WebSocket** cannot send a header from a browser, so it carries the token as a sub-protocol; the server accepts
  with only `faceidentify.v1` selected and never echoes the token; otherwise it closes with code 1008.
- **The listening socket is `127.0.0.1` only** (never reachable from another machine), on a port the operating system picks.
- **Errors are one envelope** with a code and a short message. They do not echo request bodies, file paths or stack traces.
- **Paths** coming from a caller are refused when they are network (UNC) paths in face search, and managed files use
  **safe storage keys** (never a caller-chosen name) so a request cannot write outside the library
  ([storage lesson](../../02-data-and-storage/08-storage-roots-and-artifacts.md)).
- **Models** are verified against their recorded hash, and the inference session is built from the bytes that were hashed,
  not from a second read of the file.
- **Test data is isolated**: the tests run with the user-data locations pointed at a sandbox, and a storage guard rejects
  any path outside it, so a test can never touch your real library.

## 4. Try it

**Works with no models. Verified 2026-10-12.**

1. Start the backend as in [start-here 07](../../00-start-here/07-run-it-and-see-it-work.md) and ask without the token:
   `curl -i $B/readiness` prints `401` and a `WWW-Authenticate: Bearer` header; with `-H "$H"` it answers. Do the same
   for `/docs`.
2. Run the security tests:

   ```bash
   uv run pytest tests/contracts/test_api_launch_capability.py tests/security -q
   ```

   Expected: `13 passed` (observed; with `test_api_host.py`, `test_api_lifespan.py` and
   `test_library_profile.py` added, the total was `53 passed`). Read the names: `test_every_http_route_requires_the_current_bearer_capability`,
   `test_websocket_requires_the_same_capability_without_echoing_it`,
   `test_hostile_non_ascii_credentials_are_ordinary_authentication_failures`.
3. Give the host a short token (as in the host lesson, "Break it"): exit code 2 and the message
   `the launch token is not 256 bits`.

## 5. Change it

A new route needs **no** security code: it is attached to the application whose dependency already checks the token, and
`test_every_http_route_requires_the_current_bearer_capability` walks every registered route, so a route that escaped the
check would fail it. Never add an "unauthenticated for convenience" route, a token in a URL, or a log line containing a
header.

## 6. Break it on purpose

In a scratch edit, make the check accept any non-empty header and run the contract test: it fails on the wrong-credential
cases. Restore with `git restore`.

## 7. Exercises

1. Why is the token passed in an environment variable and not an argument?
2. Why does `/health` need the token too?
3. How does the browser authenticate the WebSocket?
4. What stops a request from writing outside the library?

**Answers**

1. Command lines are visible to other programs on the computer; environment variables are not listed that way.
2. Anything answering without proof would let other programs probe the backend.
3. Through the second sub-protocol `fi.<token>`; the server selects only `faceidentify.v1`.
4. Safe storage keys: the library chooses the file names, not the caller.

## 8. Related files

- Previous: [07 Events](07-events.md) · Up: [Architecture](README.md)
- [`backend/api/app.py`](../../../../../backend/api/app.py), [`backend/api/host.py`](../../../../../backend/api/host.py)
- [The sidecar contract](../../05-desktop-shell/03-sidecar-contract.md)
