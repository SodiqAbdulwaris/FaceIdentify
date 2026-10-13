# 05 The desktop shell

The shell is a small **Rust** program built with **Tauri**. It is the thing you double-click. It does four jobs and nothing else:
it opens the window, **starts the Python backend** as a hidden child process, **hands the window the one connection it may use**
(address and token), and **stops the backend cleanly** when the window closes. It holds no business rules.

| Lesson | Teaches |
|---|---|
| [01 Rust in ten minutes](01-rust-in-ten-minutes.md) | the Rust you need to read these 1000 lines |
| [02 Tauri commands](02-tauri-commands.md) | `backend_status`, the dialogs, `invoke` from the page |
| [03 The sidecar contract](03-sidecar-contract.md) | token, handshake, lifeline, parent pid: both ends |
| [04 Library folder and dialogs](04-library-folder-and-dialogs.md) | where data lives, what the page may ask the shell |
| [05 Build and test the shell](05-build-and-test-the-shell.md) | `cargo fmt`, `clippy`, `cargo test`, `npm run tauri dev`, CI |

**Honest status of verification (Linux session, 2026-10-12).** `cargo fmt --check` passes. **The shell's own tests (`cargo test`) were not run**:
building Tauri on Linux needs system libraries (`webkit2gtk`) and a crate download that this environment lacks, and the shell targets
Windows, where CI runs them. What *was* run is the Python side of the same contract: the host tests in
`tests/integration/test_api_host.py` and the real host driven from a script that does what `sidecar.rs` does
([host and startup](../03-backend/architecture/03-host-and-startup.md)), and the web app against the real backend (`npm run test:e2e`).

**One thing still for the owner on Windows.** The web view is a different origin from `127.0.0.1:<port>`, so the backend must answer it with CORS headers. That
was a real defect (the window stayed on "Opening your library…"); it was fixed on `main` (`docs/implementations/2026-10-12-webview-cors.md`): the shell passes the
web view's origins to the host with `--allow-origin`. The entry itself says the fix is **not yet confirmed in the real desktop window**; this guide could not
confirm it either (no display), so please check that the packaged window connects.

Back to the [guide index](../README.md).
