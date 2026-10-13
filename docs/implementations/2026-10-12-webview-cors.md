# Fix: the web view could not read any answer from the backend (CORS)

- **Date:** 2026-10-12
- **Milestone / tracker IDs:** M4/M5 defect found by the owner's first real desktop run; no tracker row
- **Status:** fixed and tested; **confirmed in the real desktop window by the owner on 2026-10-13**
- **Commits:** PR to be recorded when merged

## The defect

`npm run tauri dev` showed "Opening your library..." for ever. The backend was healthy (a probe of the host
reached READY or DEGRADED in about a second, and FAILED with a reason when it should), but the web view is a
different origin (`http://localhost:5173` in development, `http://tauri.localhost` packaged) from the loopback
server, and **the backend sent no CORS headers and answered the browser's preflight with 401**. A browser
therefore refuses to hand the page any response, the readiness query fails, and the library gate keeps
polling. Every earlier test called the API from Python (a browser enforces none of this), so nothing could
have caught it. It was found from the owner's terminal log (the repeating "connection reset" warnings were
the web view's failed preflights).

## The fix

- `create_app(allowed_origins=...)` adds Starlette's `CORSMiddleware` for **exactly the origins named**:
  never `*`, no credentials (the capability travels in a header the page sets), methods GET/POST/PATCH/DELETE,
  headers Authorization/Content-Type/If-None-Match, `ETag` exposed. It is added after the capability check so
  it is outermost: a preflight (which carries no token) is answered there; every real request still needs the
  token (a request without one is `401`, and the page may read that `401`).
- The host takes `--allow-origin <origin>` (repeatable; an exact `http(s)://host[:port]` or
  `tauri://localhost`, validated; none by default, in which case there are no CORS headers at all).
- The shell passes `http://tauri.localhost`, `https://tauri.localhost` and `tauri://localhost`, and in a
  **debug build only** `http://localhost:5173` (the Vite dev server). A release build never allows the dev
  server.

## Tests

- `tests/unit/test_cors.py` (5): a preflight from an allowed origin is answered without a token; a real request
  still needs the token and is readable only by an allowed origin; another origin gets nothing; with no
  origins named there are no CORS headers and a preflight is `401`; the host takes exact origins only.
- Rust: each origin becomes its own `--allow-origin` argument; the dev server is allowed only in a debug build.
- `cargo test` (21 passed, 1 ignored as before), `cargo check`, `cargo fmt`.

## After the independent review

- The unexpected-error response (`500 INTERNAL_ERROR`) is built by the server-error layer, outside the CORS
  middleware, so it carried no CORS headers and a page could not read even the diagnostic id. The handler now
  adds them for an allowed origin (test with a route that raises).
- The API spec paragraph is an agent design awaiting the owner's confirmation, not a decision.
- **Known, existing, not changed here:** the face-search path form rejects literal network paths (`\server`,
  `//server`) but not a mapped network drive (`Z:\...`) or a junction that points at a share; opening one can
  contact the share before the image is validated. A follow-up needs a drive-type and reparse-target check
  with Windows tests.

## Not covered

- The window itself: no automated test drives a real web view. The owner's `npm run tauri dev` is the check.
- WebSocket events: a browser sends an Origin on a WebSocket but does not enforce CORS on it; the server still
  validates the capability. Origin validation for WebSockets is unchanged.
