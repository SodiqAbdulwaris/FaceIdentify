# Front end 04 App structure and the gate

## 1. What this is and why it exists

Before any screen can show data, three things must be true: the shell has started the backend, the backend has opened the
library, and the page knows the token. The **gate** makes that visible ("Starting FaceIdentify…", "Opening your library…") and
renders the screens only when it is safe. Everything below the gate can simply assume a working backend.

## 2. Where it lives

| Piece | File |
|---|---|
| Entry | `frontend/src/main.tsx` → `App` |
| Query cache and router | `frontend/src/app/App.tsx` |
| The gate (`BackendGate`, `LibraryGate`) | `frontend/src/app/BackendGate.tsx` |
| The connection as context | `BackendProvider.tsx`, `useBackend.ts` |
| Live updates | `EventsBridge.tsx` ([events lesson](06-events-and-routing.md)) |
| The frame (header, nav, live badge, policy notice) | `Layout.tsx` |
| Talking to the shell | `frontend/src/native/backend.ts` |
| Tests | `BackendGate.test.tsx`, `Layout.test.tsx`, `App.test.tsx`, `native/backend.test.ts` |

## 3. How it works

```text
main.tsx
 └ App ── QueryClientProvider ── BackendGate ── RouterProvider ── Layout ── (a screen)
              staleTime 5 s        │
                                   ├ asks the shell: backend_status  (polls every 500 ms while "starting")
                                   ├ failed/starting → a plain notice
                                   └ ready → BackendProvider(connection)
                                              └ LibraryGate: asks GET /readiness (polls while INITIALIZING)
                                                   READY or DEGRADED → EventsBridge + screens
                                                   FAILED → "Your library could not be opened" + the failure class name
```

- **`backendStatus()`** returns `starting`, `ready` with a `Connection` (`base_url`, `events_url`, `token`, `protocol`), or `failed`.
  In the desktop app it is the Tauri command `backend_status`; outside the shell it falls back to `VITE_BACKEND_URL` and
  `VITE_BACKEND_TOKEN` (needs the host started with `--allow-origin`; see the [folder README](README.md)).
- **`BackendProvider`** builds one `ApiClient` and its `endpoints` per connection (`useMemo`), and puts them in context;
  every screen calls `useBackend()`.
- **`DEGRADED` is usable**: the gate lets the screens render, because the library works (something recoverable is outstanding).
- **`Layout`** shows the navigation (Library, People, Search), "Live" or "Reconnecting…" from `useUi`, and the
  **`PolicyNotice`** that says which decision policy produced the results on screen (the newest run's policy), including the
  uncalibrated warning.
- **Why a gate and not error handling in every screen?** One place owns "is the backend there", so the screens stay simple.

## 4. Try it

**Works with no models and no shell. Verified 2026-10-12.**

```bash
npm run test --workspace frontend -- src/app/BackendGate.test.tsx src/app/Layout.test.tsx src/native/backend.test.ts
```

Expected: `Tests  19 passed (19)` across the three files (observed). Read `BackendGate.test.tsx`'s seven test names: starting, why it could not start, waits while the library opens, degraded-but-serving, keeps trying while the backend is not answering, the library could not be opened and why, and that the launch token is sent. The harness replaces the shell's two native calls with scripted ones ([tests lesson](09-styling-and-frontend-tests.md)).
The real thing end to end: `npm run test:e2e` starts the real backend exactly as the shell does and drives the whole app
(`Test Files  1 passed (1)`, observed).

## 5. Change it

To show something new while the library opens, change `Notice` text in `BackendGate.tsx`, then update `BackendGate.test.tsx`.
To expose a new native capability, add the Tauri command first ([Tauri commands](../05-desktop-shell/02-tauri-commands.md)), then a typed
wrapper in `native/backend.ts` (with a no-shell fallback and a test in `backend.test.ts`).

## 6. Break it on purpose

Make `LibraryGate` render the children for `INITIALIZING` too (scratch edit): the gate tests fail, and in a real run the screens
would flash errors because the library is not open yet. Restore with `git restore`.

## 7. Exercises

1. Where does the token come from in the desktop app?
2. Why does `LibraryGate` poll `/readiness`?
3. Which readiness states let the screens render?

**Answers**

1. The shell's `backend_status` command returns the `Connection` that includes it.
2. The backend serves before the library has opened; `INITIALIZING` ends on its own.
3. `READY` and `DEGRADED`.

## 8. Related files

- Previous: [03](03-react.md) · Next: [05 The API client and queries](05-api-client-and-queries.md)
- [`frontend/src/app/BackendGate.tsx`](../../../frontend/src/app/BackendGate.tsx), [readiness](../03-backend/architecture/03-host-and-startup.md)
