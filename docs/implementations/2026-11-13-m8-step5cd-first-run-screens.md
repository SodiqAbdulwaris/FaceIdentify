# M8 step 5(c) and (d): the first-run setup screens and their end-to-end test

- **Date:** 2026-11-13
- **Milestone / tracker IDs:** M8 step 5(c), 5(d) · TST-079 (not `PASSING`: the real-model check and the rollback tests are not built)
- **Status:** done
- **Commits:** PR (number added when opened): `feat(shell): let the user pick the face models in a dialog`, `feat(web): first-run setup for the face models and the recognition mode`, and its docs commit

## Why

M8 step 5: a fresh install has no models and no recognition policy (R6, R7). The user needs a screen that says what the models are and under
what licence, installs them from what they downloaded, lets them choose how recognition works, and shows what the app found, without
any step on the command line.

## What changed

- `frontend/src/features/setup/SetupPage.tsx`, route `#/setup`: step 1 (the licence, the source, the files and their expected sizes and SHA-256, a path box with
  "Choose the zip…" / "Choose the folder…" and "Install the models"; a refused file shows the backend's reason), step 2 (Assisted is offered first, each option's
  description and, under "Exactly what will be saved", the exact policy; "Use … recognition" saves it; an owner-made policy is reported and not offered a change), step 3
  (what the app found, from `/readiness`: models, mode, and the graphics card line, which says a supported card is used and otherwise everything runs on the processor
  with nothing to do, and fills in after the first picture).
- A library step: it shows where the library is kept and lets the user choose another folder (the shell saves it; it is used after a restart, nothing is moved), as M8 step 5 says "choose or accept the library folder".
- `BackendGate`: a one-line notice with a link to the setup while the models or the mode are missing (only the real profile reports those capabilities).
- `ApiClient.put`, the endpoints and types for the model and mode routes; `chooseModels` in `native/backend.ts` and the shell command `choose_models` (a zip or a
  folder; only the path crosses to the web view).
- `frontend/e2e/setup.e2e.tsx`: the real web app and the real backend on the development profile: a folder of stand-in model files declaring itself a fixture is installed,
  Automatic is chosen, and the saved policy is the approved one in the scratch state folder (never the owner's).

## Verification (this machine, Windows 11, 2026-11-13)

- Frontend: `npm run typecheck`, `npm run lint -- --deny-warnings`, `npm test` (**245 passed**, 28 files; 13 of them the setup screen, plus tests for the notice, `put`, `chooseModels` and `chooseLibrary`), `npm run build`: all exit 0.
- End to end: `npx vitest run --config vitest.e2e.config.ts e2e/setup.e2e.tsx` (**1 passed**): the real web app against the real backend on the development profile installs the stand-in fixture models from a folder and saves Automatic; the policy file in the scratch state folder is exactly `buffalo-l-verified-match-v1` at 0.45 / margin 0.1.
- Rust: `cargo fmt --check`, `cargo clippy --all-targets -- -D warnings`, `cargo test` (**26 passed**, 1 ignored), `npx tauri build --debug --no-bundle`: all exit 0.
- The installed build (installer built from this stack, scratch install): `packaging/check_installed.py` passes (READY, image `COMPLETED`, video imported, 2 frames decoded through the shipped FFmpeg, both provider paths, exit 0); the installed `faceidentify.exe` starts its backend, which creates the library in the scratch folder, closing the window ends both processes, and the silent uninstall keeps the library.
- Not verified: the setup page in the real desktop window with the native dialogs (CI has no display; step 8, on the owner's machine), and a real `buffalo_l` install. The library step is covered by tests with the shell's dialog stood in.

## Decisions (delegated, 2026-11-13; the owner may reverse any)

- The steps are independent and in any order, on one page, with a notice in the rest of the app instead of a wizard that blocks it: the plan says everything else works without recognition.
- The graphics-card line is honest about timing: the worker loads its models on the first picture, so the provider is known after it (see the step 5(b) entry).

## Open issues / follow-ups

- The rollback tests (TST-080, TST-082): a corrupted package keeps the previous configuration. The store's refusal paths are covered by its own tests; the app-level test belongs with step 7(c).
- Step 6's installer-level upgrade, uninstall and reinstall tests; step 8.
