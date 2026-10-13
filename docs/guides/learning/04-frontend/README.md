# 04 The front end

The screen you see is a **React** application written in **TypeScript**, built by **Vite**, running inside the Tauri window. It
holds no truth of its own: every name, face and status comes from the backend over HTTP, and a WebSocket only says "something
changed, ask again".

| Lesson | Teaches |
|---|---|
| [01 The web and JavaScript](01-web-and-javascript.md) | what a browser page is, and the JavaScript you need |
| [02 TypeScript and tooling](02-typescript-and-tooling.md) | types, the generated API types, Vite, lint, typecheck |
| [03 React](03-react.md) | components, state, effects, in this codebase's words |
| [04 App structure and the gate](04-app-structure-and-gate.md) | `App`, the backend gate, the provider, the layout |
| [05 The API client and queries](05-api-client-and-queries.md) | one client, one endpoints file, TanStack Query keys |
| [06 Events and routing](06-events-and-routing.md) | the event client, invalidation, hash routes |
| [07 Library and source screens](07-library-and-source-screens.md) | the two main screens, line by line |
| [08 People and search screens](08-people-and-search-screens.md) | people, one person, search, face search |
| [09 Styling and front-end tests](09-styling-and-frontend-tests.md) | Tailwind, shadcn, the scripted-backend test harness |
| [10 Add a screen](10-add-a-screen.md) | a worked, dry-run recipe |

**Works with no models and no desktop shell. Verified 2026-10-12 (Linux).** Four checks you can run from the repository folder
after `npm ci`:

```bash
npm test            # 24 test files, 193 tests, about 17 s
npm run typecheck   # tsc -b: no output means no type errors
npm run lint        # oxlint
npm run test:e2e    # the real web app against the real backend, about 11 s (needs `uv sync` first)
```

Observed: `Test Files  24 passed (24)`, `Tests  193 passed (193)`; typecheck and lint print only their header line; the end-to-end test
printed `Test Files  1 passed (1)`.

**Browser development (verified 2026-10-12).** A plain browser page is a different origin from the loopback backend, so the backend must be told to
answer it (CORS). Since the fix recorded in `docs/implementations/2026-10-12-webview-cors.md`, the host takes `--allow-origin <exact origin>` (repeatable;
the desktop shell passes the web view's origins itself). To use `npm run dev` without the shell, start a backend by hand with
`--development-profile --allow-origin http://localhost:5173`, then start Vite with `VITE_BACKEND_URL=http://127.0.0.1:<port>` and
`VITE_BACKEND_TOKEN=<token>` (the handshake line gives the port; the token is the one you set in `FACEIDENTIFY_LAUNCH_TOKEN`). Observed with Chromium: the
library screen appears (empty library, "Live"). Without the flag the page stays on "Opening your library…" with a CORS error in the console, which is how the
defect showed itself before the fix. (In the desktop app the packaged window's connection is still for the owner to confirm on Windows.)

Back to the [guide index](../README.md).
