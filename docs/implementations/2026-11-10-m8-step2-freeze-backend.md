# M8 step 2: the backend frozen with PyInstaller

- **Date:** 2026-11-10
- **Milestone / tracker IDs:** M8 step 2 (a, b, c) · TST-078 and TST-079, backend half (not `PASSING`: the installer, the shell and the first-run flow are not built)
- **Status:** done
- **Commits:** PR (number added when opened): `build(freeze): freeze the backend with PyInstaller`

## What changed

- `pyproject.toml`, `uv.lock`: a `build` dependency group with `pyinstaller` 6.22.3 (the plan names
  PyInstaller; it is a build tool, not a runtime dependency, and `uv sync` does not install it).
- `packaging/faceidentify-backend.spec`: the onedir build (decision R3). It lists every module under
  `backend/` as a hidden import (the worker factory is loaded by name and the migration scripts import
  modules nothing else does), collects Alembic, uvicorn, websockets and SQLAlchemy's SQLite dialect,
  the DLLs of `onnxruntime`, `usearch` and Pillow, and ships `backend/alembic` as data, where
  `backend/app/lifecycle.py` looks for it. setuptools, test tools and `onnx` are excluded.
- `packaging/frozen_entry.py`: calls `multiprocessing.freeze_support()` first, then the host's `main`.
  This is the whole "worker from the same executable" mechanism: the spawned worker is the same
  `.exe` with `--multiprocessing-fork`, so no flag or second executable exists. `--probe-providers` is
  a build check (see below).
- `packaging/frozen_probe.py`: model-free worker handlers; `--probe-worker` runs one detect request through the real `ProcessWorker`, the supervisor handshake and the shared-memory protocol of the frozen build (added after the review of this PR).
- `packaging/check_frozen_backend.py`: starts the executable headless on the development profile in a
  scratch library, reads the handshake, calls `/health` and `/readiness` until `READY`, closes standard
  input (the shell's stop signal), expects exit 0, and asks the executable which ONNX Runtime providers
  it and a spawned child see, and that `usearch` indexes and Pillow reads AVIF.
- CI: a `Frozen backend` job (Windows) builds and runs that check on every pull request.
- `.gitignore`: `build/` (frozen output and the generated notices file).

## Verification (this machine, Windows 11, DirectX 12 GPU)

- Build: 1 min 16 s; the folder is **159 MB** (the installer will be smaller, compressed).
- `uv run python packaging/check_frozen_backend.py build/dist/faceidentify-backend`: `/health` ok,
  `/readiness` `READY` with database, storage, index, recovery and scheduler `READY` (`ml_worker`
  `NOT_CONFIGURED`: the development profile has no real worker), the scratch database created, exit code 0
  after the stdin lifeline closed, a detect request through the real worker process returned one detection, providers `["DmlExecutionProvider", "CPUExecutionProvider"]` in the
  process **and** in a spawned child, `usearch` index of 1, AVIF available.
- **Start time:** about 1.3 s to the handshake when warm and 6 to 7 s on the first start after a build (a
  cold disk cache; antivirus scanning of the new files is a possible cause, not measured separately).
- Full backend gate: see the PR description. Not verified: the real `buffalo_l` models through the frozen
  worker (no weights in CI; that is step 8 on the owner's machine), CI's runner (no DirectX 12 device
  expected: the job's providers line shows what it has).

## Decisions (delegated, 2026-11-10; the owner may reverse any)

- The headless check is a script, not a pytest test: it needs a built artefact, and an e2e test that
  fails or skips when the artefact is absent would break the "never skip" rule.
- The job runs on every pull request (about 3 minutes), not on demand, because a change to `backend/`
  can break the frozen build silently (a missing hidden import shows only at run time).

## Open issues / follow-ups

- The frozen folder also carries the Python 3.12 runtime, OpenSSL, SQLite and the Microsoft Visual C++
  runtime DLLs; the notices file does not list them yet (the step 3 notices must).
- PyInstaller itself is GPL-2.0-or-later with a bootloader exception that allows the frozen output to be
  under any licence; recorded in the licensing record as a build tool.
- The real worker's *models* (`real_processing`, `onnx_session`) in the frozen build are untested until the models can
  be installed (M8 step 5) and the owner's machine is used (step 8).
