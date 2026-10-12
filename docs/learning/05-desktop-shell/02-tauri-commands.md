# Desktop shell 02 Tauri commands

## 1. What this is and why it exists

The web page runs in a sandbox: it cannot start programs, read your disk or open native dialogs. The shell can. A **Tauri command**
is a Rust function the page is allowed to call by name, through `invoke`. The set of commands is the *entire* power the page has over
your computer, so it is deliberately short and each one is explained here.

## 2. Where it lives

| Thing | Where |
|---|---|
| The commands | `backend_status`, `library_info`, `choose_library`, `choose_images`, `choose_picture` in `desktop/src-tauri/src/lib.rs` |
| Registration | `tauri::generate_handler![...]` in `run()` |
| The page's side | `frontend/src/native/backend.ts` (`invoke('backend_status')` and the others) |
| Permissions | `desktop/src-tauri/capabilities/default.json` (`core:default`) and `tauri_plugin_dialog` |
| Tests of the page's side | `frontend/src/native/backend.test.ts` (81 lines) |

## 3. How it works

| Command | Returns | Used by |
|---|---|---|
| `backend_status` | `{state: "starting"}`, `{state: "ready", connection: {base_url, events_url, token, protocol}}` or `{state: "failed", error}` | `BackendGate`, polled every 500 ms while starting |
| `library_info` | `{library_root}` | `libraryRoot()` in `native/backend.ts` (no screen shows it yet) |
| `choose_library` | the folder the user picked, saved for the **next** start | **not called by any screen today** (found by `grep` on 2026-10-12) |
| `choose_images` | file paths the user picked (jpg, jpeg, png, bmp, webp) | library import |
| `choose_picture` | one picture path for face search | face search |

- **Only paths cross**, never pixels: the backend runs on the same machine and reads the file itself (`POST /sources/import {path}`).
- `#[tauri::command]` plus `#[serde(tag = "state", rename_all = "snake_case")]` is why the JSON says `"state": "ready"`.
- Dialog commands are `async` and run the blocking dialog in `spawn_blocking`, so the window stays responsive.
- **In a plain browser** (`npm run dev`) there is no shell: `inShell()` is false, `chooseImages()` returns `[]`, and `backendStatus()` falls back
  to the `VITE_BACKEND_*` variables, which work only if the host was started with `--allow-origin` for the page's origin (see the [front-end README](../04-frontend/README.md)).
- The Rust enum `BackendStatus` and the TypeScript union `BackendStatus` in `native/backend.ts` are **written twice by hand** and must
  agree; `backend.test.ts` checks the page's half.

## 4. Try it

**Page side: verified. Rust side: unverified here.**

```bash
npm run test --workspace frontend -- src/native/backend.test.ts
```

Observed (as part of the three-file run in the front-end lessons): the file's tests pass. In the real app, in the developer tools
console of the window, the same call the gate makes would be `await window.__TAURI_INTERNALS__.invoke('backend_status')` (*not run
here: no display*; opening the dev tools in a debug build is the standard Tauri feature).

## 5. Change it

Adding a command is four edits: the Rust function with `#[tauri::command]`, its name in `generate_handler!`, a typed wrapper in
`native/backend.ts` with a no-shell fallback, and a test in `backend.test.ts`. Ask first whether the page truly needs it: each command
widens what a compromised page could do. A command that returns a path or a secret needs special care.

## 6. Break it on purpose

Remove `choose_picture` from `generate_handler!`: the project still compiles but `invoke('choose_picture')` fails at run time in the window
(face search by file picker would break). The Rust compiler cannot see the page; the page's tests stub `invoke`. (*Reasoned from the
code; not run.*)

## 7. Exercises

1. Which command carries the token to the page, and in what?
2. Why do file pickers return paths instead of file contents?
3. Which command is registered but unused by any screen?

**Answers**

1. `backend_status`, inside the `connection` object when ready.
2. The backend is on the same machine and reads the file itself; copying pixels through the page would be slow and pointless.
3. `choose_library`.

## 8. Related files

- Previous: [01](01-rust-in-ten-minutes.md) · Next: [03 The sidecar contract](03-sidecar-contract.md)
- [`desktop/src-tauri/src/lib.rs`](../../../desktop/src-tauri/src/lib.rs), [`frontend/src/native/backend.ts`](../../../frontend/src/native/backend.ts)
