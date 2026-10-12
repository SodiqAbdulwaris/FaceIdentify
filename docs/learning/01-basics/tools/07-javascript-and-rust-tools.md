# Tools 07 JavaScript and Rust tools

## 1. What this is and why it exists

The front end and the desktop shell each come with their own toolchain. You do not need to master them,
but you need to know the handful of commands that run, check and build each, and what each tool is for,
because CI runs them all.

## 2. Where it lives

| Tool | What it is | Config / where |
|---|---|---|
| **Node.js** | Runs JavaScript outside a browser (for tools). Version pinned in `.nvmrc` (`24`) | |
| **npm** | Installs JavaScript packages into `node_modules/`. **Workspaces**: the root `package.json` lists `frontend` as a workspace, so root scripts forward to it | `package.json`, `frontend/package.json`, `package-lock.json`, `.npmrc` |
| **Vite** | Dev server with instant reload (`npm run dev`, port 5173) and the production bundler (`npm run build`) | `frontend/vite.config.ts` |
| **TypeScript** (`tsc`) | The type checker for `.ts` and `.tsx` (`npm run typecheck` is `tsc -b`) | `frontend/tsconfig*.json` |
| **Vitest** + **Testing Library** + **jsdom** | The front-end test runner, a simulated browser, and helpers that find elements the way a user does (by role and text) | `test` block in `vite.config.ts`; setup in `src/test/setup.ts` |
| **oxlint** | The linter (`npm run lint`). The project does **not** use Prettier: the style is single quotes, no semicolons, and a formatter run would rewrite whole files | |
| **openapi-typescript** | Turns the backend's OpenAPI document into `schema.d.ts` (`npm run generate:types --workspace frontend`) | `frontend/src/api/` |
| **Cargo** | Rust's build tool and package manager (`cargo build`, `test`, `fmt`, `clippy`) | `desktop/src-tauri/Cargo.toml`, `Cargo.lock` |
| **Tauri CLI** | `@tauri-apps/cli` installed by npm; `npm run tauri dev` opens the desktop app | `desktop/src-tauri/tauri.conf.json` |
| **gh** | GitHub's command line (`gh pr create`, `gh pr checks`) | |
| **codex** | The independent read-only code reviewer used by the PR procedure | |

`.npmrc` sets `legacy-peer-deps=true`: a *documented temporary exception* because `openapi-typescript`
declares a peer range for TypeScript 5 while the app uses TypeScript 6. It is repository-wide, so it
hides every peer conflict, not just that one; remove it when the generator supports TypeScript 6
(accepted by the owner on 2026-10-07).

## 3. How it works

The root scripts you will use (`package.json`):

| Command (from the repository root) | Does |
|---|---|
| `npm run dev` | starts Vite; open `http://localhost:5173` |
| `npm test` | `vitest run` once in the frontend workspace |
| `npm run typecheck` | `tsc -b` |
| `npm run lint` | `oxlint` (CI adds `-- --deny-warnings`) |
| `npm run build` | `tsc -b && vite build` into `frontend/dist/` |
| `npm run generate:api` | `uv run python -m backend.api.openapi` (regenerates `openapi.json` from the routes) **then** `generate:types` |
| `npm run test:e2e` | the full desktop workflow against the **real Python backend**, with a restart (CI's desktop job runs it) |
| `npm run tauri dev` | the desktop app in development: Vite plus the Rust shell |
| `npx tauri build --debug --no-bundle` | does-it-compile check for the shell (about 3 minutes cold) |

In the Rust folder: `cargo fmt --check`, `cargo clippy --all-targets -- -D warnings`, `cargo test`, and
`cargo test -- --ignored` (the tests that start the real Python backend).

## 4. Try it

**Works with no models. Verified 2026-10-12 on Linux, Node 22** (except where marked).

1. Install exactly what the lockfile says: `npm ci`. Expected: `node_modules/` appears and
   `git status` shows no change.
2. The checks, each from the root:

   ```bash
   npm run typecheck        # prints "> tsc -b" and nothing else
   npm run lint             # prints only the npm banner: no errors
   npm test                 # Tests 193 passed (193), about 20 seconds
   npm run build            # "built in <1s" and the file sizes
   ```

3. **One test file** (faster feedback): `npm exec --workspace frontend -- vitest run src/features/StatusBadge.test.tsx`.
   Expected: `Test Files 1 passed (1)`, `Tests 13 passed (13)`.
4. **See the dev server.** `npm run dev`, then in another terminal `curl http://localhost:5173/`. Expected:
   an HTML page that loads Vite's client script and `main.tsx`. Open it in a browser: with no desktop
   shell and no backend the app shows its connection gate rather than data (it needs a backend; see
   [the app structure and gate](../../04-frontend/04-app-structure-and-gate.md)). Stop it with Ctrl+C.
5. `cd desktop/src-tauri && cargo fmt --check` printed nothing and exited 0 (`cargo 1.97.0`). Building or
   testing the shell on Linux needs the Tauri system libraries; `cargo clippy` and `cargo test` were
   *not* run here, and the desktop window was not opened.

## 5. Change it

The smallest real front-end change is to a label. Open `frontend/src/features/status.ts` and read how a
machine state becomes human text; its test is `frontend/src/features/StatusBadge.test.tsx`. Change a
label (say, the text for `RUNNING`, from `'Processing'` to `'Working'`), run the one test file from step 3, and read the failure it gives:

```text
FAIL  src/features/StatusBadge.test.tsx > StatusBadge > shows RUNNING as "Processing" in its own colour
TestingLibraryElementError: Unable to find an element with the text: Processing. ...
Tests  1 failed | 12 passed (13)
```

(Observed 2026-10-12 with the label changed to `Working`.) Restore the label (`git restore frontend/src/features/status.ts`). The lesson is the loop: change, run
the one file, read the failure, restore. For adding a whole screen see [add a screen](../../04-frontend/10-add-a-screen.md).

## 6. Break it on purpose

Use `npm install` where you meant `npm ci` and look at `git status`: on Linux with Node 22 on 2026-10-12 it
rewrote `package-lock.json` (93 lines removed). Restore with `git restore package-lock.json`. Or run
`npm test` before `npm ci` on a fresh clone: an error that `vitest` is not found (not repeated by hand), because `node_modules/` does not exist
yet.

## 7. Exercises

1. Which command regenerates the TypeScript types after you change a route?
2. What is the difference between `npm test` and `npm run test:e2e`?
3. Why does the repository have a `.npmrc` with `legacy-peer-deps=true` and what is its downside?
4. Where do `cargo test` and `cargo test -- --ignored` differ?

**Answers**

1. `npm run generate:api` (routes to `openapi.json` to `schema.d.ts`); `npm run generate:types --workspace frontend` only
   regenerates the TypeScript from the committed JSON.
2. `npm test` runs fast unit and component tests against fakes; `test:e2e` drives the real Python host
   through the whole image workflow.
3. A peer-dependency range mismatch between `openapi-typescript` and TypeScript 6; the downside is that it
   hides every peer conflict until removed.
4. `--ignored` runs the tests that start the real Python backend.

## 8. Related files

- Previous: [06 CI](06-ci.md) · [Tools index](README.md)
- [`package.json`](../../../../package.json), [`frontend/package.json`](../../../../frontend/package.json)
- [04-frontend](../../04-frontend/README.md), [05-desktop-shell](../../05-desktop-shell/README.md)
