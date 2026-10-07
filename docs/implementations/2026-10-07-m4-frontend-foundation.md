# M4 W7.1: the frontend foundation

- **Date:** 2026-10-07
- **Milestone / tracker IDs:** M4 W7 · TST-049, TST-050 (the client half)
- **Status:** partial; the screens (library, source, people, processing) follow in W7.2 to W7.4
- **Commits:** PR (this change): `feat(frontend): connect the web view to the backend`

## What changed

- **Native bridge** (`frontend/src/native/backend.ts`): the web view asks the Tauri shell, never the
  network, where the backend is (`backend_status`: `starting`, `ready` with the connection, or
  `failed` with a reason), plus `choose_images` and `library_info`. Outside the shell (a plain
  browser, `npm run dev`) a hand-started backend can be named with `VITE_BACKEND_URL` and
  `VITE_BACKEND_TOKEN`; otherwise the app says it needs the desktop shell.
- **HTTP client** (`api/client.ts`): the launch token on every request, the one error shape turned
  into one `ApiError` (status, code, details, retryable), a network failure as a retryable
  `NETWORK_ERROR`, and a `blob` call for files (an `<img src>` cannot carry the token). Typed by
  the generated schema (`api/types.ts` names it; `api/endpoints.ts` has one function per operation
  the screens use).
- **Events** (`api/events.ts`): the connection offers `faceidentify.v1` and the token as protocols;
  a greeting sets the baseline sequence; a repeat is ignored; a gap, and every (re)connection,
  asks for a refetch; a lost connection is retried with a doubling delay (0.5 s to 15 s) that
  resets after a success. Stopping (or starting again) detaches the old socket's handlers and
  cancels any pending retry, so nothing late reaches the app. `api/invalidation.ts` maps an event to the queries it makes stale
  (`api/keys.ts` holds the keys, so what an event invalidates and what a screen reads cannot drift).
- **App** (`app/`): TanStack Query for server state, a small Zustand store only for client state
  (the events connection status), and hash routing for `/library`, `/library/source/:id`,
  `/identities`, `/identities/:id` and `/processing/:runId` (placeholders until W7.2 to W7.4).
  `BackendGate` shows what the backend is doing (starting, opening the library, failed and why) and
  renders the app only when the library can be used; `EventsBridge` wires events to the query
  cache.
- Dependencies (decision 5 and one agent's choice): `@tanstack/react-query`, `zustand`, and
  `react-router` (hash routing; the plan names the routes, not the router).
- Desktop: a `choose_images` command (a native multi-select with the formats the backend imports),
  with a test that the picker offers exactly those formats.

## Why

W7 of the completion plan. The foundation is its own change so that every screen after it shares
one way to reach the backend, one cache, and one way to stay fresh, each already tested.

## Decisions

> **Decision 2026-10-07 (agent's, for the owner to confirm; M4 W7):** `react-router` with hash
> routing is the router. Routes are the ones the plan names; hash routing avoids asking the app's
> custom protocol for a file that does not exist when a deep path is reloaded. Swapping it later
> touches only `app/routes.tsx`.

> **Decision 2026-10-07:** Owner confirmed. React Router hash routing; clean URLs have no product
> value in a desktop app, and hash routes avoid custom-protocol rewrite problems.

## Verification

- `npm test` (38): the client (token, query building, post bodies, the error shape, a non-API
  failure, a network failure, blobs); the events client against a fake socket (protocols, greeting
  baseline, repeats, a single lost event, a loss right after the greeting, ignored non-events,
  growing and resetting reconnection delay, stop, a stale socket's late close, a stopped socket's late frames, starting twice, the delay rule,
  envelope validation); invalidation; the gate (starting, failed, the library opening then ready,
  degraded, a backend not yet answering, a failed library with its reason, the token on the readiness
  call); the native bridge in and out of the shell; the app without a shell.
- Mutation probes (23 by hand on the events client, the HTTP client, invalidation, the gate and the
  bridge): all killed after tests were added for a single lost event, a lost event right after the
  greeting, and a half-named development backend.
- `npm run typecheck`, `npm run lint -- --deny-warnings` and `npm run build` pass; `cargo test`,
  `cargo fmt --check` and clippy pass.
