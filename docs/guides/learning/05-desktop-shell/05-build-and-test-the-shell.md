# Desktop shell 05 Build and test the shell

## 1. What this is and why it exists

How the shell is built, tested and run, and what CI checks. Most of it needs **Windows** (the product's target) or a Linux machine with
Tauri's system libraries. This lesson is explicit about what could and could not be run in the session that wrote it.

## 2. Where it lives

| Thing | Where |
|---|---|
| Crate and dependencies | `desktop/src-tauri/Cargo.toml`, `Cargo.lock` |
| Tauri configuration | `desktop/src-tauri/tauri.conf.json` (`devUrl` `http://localhost:5173`, `beforeDevCommand` `npm run dev`, `frontendDist` `../../frontend/dist`) |
| Root scripts | `npm run tauri dev` / `npm run tauri build` (`@tauri-apps/cli`) |
| CI job "Desktop shell (TST-047)" | `.github/workflows/ci.yml`: `npm ci`, `npm run build`, `cargo fmt --check`, `cargo clippy --all-targets -- -D warnings`, `cargo test`, `cargo test -- --ignored` (real backend), `npm run test:e2e` |
| Setup | [set up your machine](../00-start-here/06-set-up-your-machine.md) (Rust, WebView2, C++ build tools) |

## 3. How it works

- **`npm run tauri dev`**: starts Vite (`beforeDevCommand`), compiles the Rust shell, opens the window pointing at `http://localhost:5173`; the shell then
  starts the backend with `--development-profile` (a debug build) from the repository's `.venv`. Edits to the front end reload live; edits to Rust recompile.
- **`npm run tauri build`**: builds the front end (`beforeBuildCommand`) and bundles an installer. A **packaged** build does not yet ship its own
  Python (the code says so); packaging is a later milestone.
- **Checks**: `cargo fmt --check` (format), `cargo clippy ... -D warnings` (lint, warnings are errors), `cargo test` (unit tests: the `config.rs` logic and `sidecar.rs`
  with fake hosts), `cargo test -- --ignored` (the one test that starts the **real** backend and needs `uv sync`).
- **The fake-host trick**: shell tests write a tiny `backend/api/host.py` into a temp folder, so start-up, handshake errors, timeouts and the stop grace
  period are tested in milliseconds without the real backend.
- **What CI does not cover**: the visible window itself (no display), WebView2 behaviour, the file dialogs. Those are checked by hand on Windows.

## 4. Try it

**Partly verified, 2026-10-12 (Linux).**

```bash
cd desktop/src-tauri
cargo fmt --check        # verified: no output, exit 0
```

*Unverified here, with the reason:*

| Command | Why not run |
|---|---|
| `cargo test` | needs the Tauri system libraries (`webkit2gtk`; `pkg-config` could not find them) and a crates.io download that this environment lacks; CI runs it on Windows |
| `cargo clippy --all-targets -- -D warnings` | same |
| `npm run tauri dev` | needs the same libraries and a display |

What *is* runnable anywhere and exercises the same contract from the other side: `uv run pytest tests/integration/test_api_host.py -q`, the
[play-the-shell script](03-sidecar-contract.md), and `npm run test:e2e` (the real web app against the real backend, started the way the shell starts it:
`frontend/e2e/backend.ts` mirrors `sidecar.rs`).

On Windows, the first run: install Rust and the Windows prerequisites (set-up lesson), `uv sync`, `npm ci`, then `npm run tauri dev`.
Expected: a window titled "FaceIdentify" showing "Starting FaceIdentify…", then "Opening your library…", then the library screen. The first compile takes minutes.

## 5. Change it

A shell change is: edit Rust, `cargo fmt`, `cargo clippy --all-targets -- -D warnings`, `cargo test`, then (if the contract moved) the Python host tests and
`npm run test:e2e`; on a branch with a PR so CI runs the Windows job. Do not push a Rust change you could not at least format and lint.

## 6. Break it on purpose

(On Windows.) Set `FACEIDENTIFY_PYTHON` to a path that does not exist and start `npm run tauri dev`: the window shows "FaceIdentify could not start" with
"could not start the backend: ..." (the `SidecarError::Spawn` text) instead of hanging. *Reasoned from the code; not run here.*

## 7. Exercises

1. Which CI step starts the real backend from Rust?
2. Why does a shell test write a fake `host.py`?
3. What is not covered by any automated check?

**Answers**

1. `cargo test -- --ignored`.
2. To test start-up and shutdown behaviour fast and deterministically, without the real backend.
3. The visible window, the native dialogs and WebView2's own behaviour.

## 8. Related files

- Previous: [04](04-library-folder-and-dialogs.md) · Up: [Desktop shell](README.md)
- [`.github/workflows/ci.yml`](../../../../.github/workflows/ci.yml), [CI lesson](../01-basics/tools/06-ci.md)
