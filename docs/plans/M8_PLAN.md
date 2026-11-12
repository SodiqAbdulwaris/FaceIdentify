# M8 plan: packaging and release for personal use

**Status:** drafted 2026-11-10 by the agent under the owner's delegation (2026-11-09: "i'll leave the rest of
the decisions entirely to you"; scope "Everything through M8"). Every decision in section 8 is a **delegated
decision**: the owner may reverse any of them. Steps 1 to 4 are built (see their entries); the rest is not. **Scope:** tracker milestone M8 (TST-078
to TST-086) and SEC-008 in [`TESTING_IMPLEMENTATION_TRACKER.md`](TESTING_IMPLEMENTATION_TRACKER.md): a Windows
installer of FaceIdentify for **personal use** (the owner's own computers), not a public release.
**Milestone gate (tracker):** "The exact packaged release candidate passes its applicable release gates."

The plan sequences work and changes no spec. Steps that need spec text propose it in their PR (reviewed,
recorded as a delegated decision). It does not change the locked stack in `docs/research/tech-stack.md`; it
uses the packaging choices already locked there (Tauri, PyInstaller as the baseline, a Tauri-managed Python
sidecar) and says where it departs from the "online bootstrap installer" of section 12 of that file, and why
(R2).

## 1. Where things stand (2026-11-10)

- **Verified by reading the repository:** the Tauri v2 shell (`desktop/src-tauri`) has `bundle.active: true`,
  `targets: "all"`, default icons and no sidecar, resource or installer settings. It starts the backend as
  `python -m backend.api.host`, with the interpreter from `FACEIDENTIFY_PYTHON` or the repository's
  `.venv` (`config.rs`: "a packaged build ships its own (M8)"). The library root defaults to
  `app_data_dir()/library` (`lib.rs`), is saved in `shell.json` when the user picks another, and the shell
  hands the backend a local state root under `app_local_data_dir()/state`. The backend opens the library
  with Alembic migrations and refuses a database newer than itself (`DatabaseNewerThanApplicationError`,
  `backend/app/lifecycle.py`). No installer, signing, updater, first-run flow, notices file or packaged
  test exists. CI (`.github/workflows/ci.yml`) has six checks and builds the shell without bundling
  (`tauri build --debug --no-bundle`).
- **The runtime today:** Python 3.12, `onnxruntime-windowsml` 1.30.0 (DirectML then CPU), USearch, Pillow
  (AVIF through its wheel), NumPy, FastAPI, uvicorn, SQLAlchemy and Alembic; the ML worker is a `spawn`ed
  child process. The face weights, the runtime package and the policy file are installed **by hand** into
  the local state root (`docs/guides/INSTALLING_MODELS_WINDOWS.md`).
- **Video and cameras (M6, M7) are not built.** The FFmpeg runtime they need is recommended in the D2 record
  (`docs/research/licensing-and-commercialization.md` section 4.1, pending confirmation). M8 packages
  whatever M6 and M7 have landed; the steps are ordered so that an installer without video can be built first.
- **Release blockers already listed** (`PROGRESS.md` section 4, licensing record sections 1 and 11) are sorted
  in section 6 into what a personal-use build can ship with and what blocks a public release.

## 1a. What remains, and what depends on M6 and M7 (2026-11-12)

Built and merged: steps 1 to 4 (PR #258 shipped FFmpeg and turned telemetry off) and the first part of step 6 (the pre-migration copy). An unsigned
installer builds with `uv run --group build python packaging/build_installer.py` (the notices, the pinned FFmpeg, the frozen
backend, the shell) and was installed, driven on the development profile and uninstalled in a scratch folder.

**Left in M8** (none of it waits for M6 or M7): step 5, the first-run flow (the model installation use case and its
routes with the hash table, the recognition-mode choice, the self-check, the screens, the desktop end-to-end test); the rollback tests of
steps 4 and 5 (they need that installer); the installer-level upgrade, uninstall and reinstall tests of step 6; step 7, the on-demand CI
installer job and the process-tree and network checks; step 8, the real-model packaged check on the owner's machine.

**Depends on M6 (merged 2026-11-12):** nothing is left. The FFmpeg that video needs ships in the installer (step 4), hash-checked
before first use, and the notices carry its licence.

**Depends on M7 (cameras, in progress):** the packaging follow-up is **a rebuild**: re-freeze the backend (the spec lists every module
under `backend/` as a hidden import, so new camera modules are picked up), regenerate the notices, rebuild the installer. M7 reads cameras
through the FFmpeg already shipped; if it needs a build option the pinned build lacks, the pin changes and the notices follow. What
a rebuild does not cover and the camera step must check on an installed build: Windows' camera privacy setting for desktop apps, and
the camera screen on the installed shell.

**Owner requirement (2026-11-12): use a supported GPU, else the CPU, with no manual step.** The model package manifest the first-run flow
installs declares a DirectML, a CUDA and a CPU variant per model (`reference_manifest`), the frozen backend carries the DirectML runtime
(the provider probe lists `DmlExecutionProvider`), and `FACEIDENTIFY_PROVIDERS` forces the CPU. The installed-build check planned for step 7
(`packaging/check_installed.py`, in review as its own PR) is to prove the selection by default and forced to the CPU; running the real models on
each path is step 8. The
video session is changing adapter selection in `backend/ml/worker/onnx_session.py` (prefer the high-performance adapter, fall back): when that
merges, the packaging follow-up is **a re-freeze** (rebuild the installer), like M7's.

**Needs the owner:** the real-model packaged check (step 8) and the choice of when, if ever, to sign (R10).

## 2. What M8 must produce

1. An installer the owner runs on a Windows 11 machine that has none of the development tools (no Python,
   Node, Rust or Git), after which the app starts, creates or opens a library, and works.
2. The same app with the real models, after the user has installed the face models themselves.
3. An upgrade from one build to the next that keeps the library, the models and the policy.
4. An uninstall that removes the program and leaves the library and the user's data alone.
5. Evidence from the installed build, not the source tree, for TST-078 to TST-086 and SEC-008.

## 3. Constraints that shape the order

- **Locked stack:** Tauri shell, a Python sidecar, PyInstaller as the V1 baseline (Nuitka is the alternative
  only on a demonstrated advantage; a managed self-contained Python is Plan C), no new package manager.
- **The weights are research-only and are never bundled, copied into a repository, an installer or a
  release artifact, or fetched by the application** (owner-accepted risk for personal use, release blocker
  for any release). The installer contains no biometric data and no model weights.
- **The live policy file belongs to the owner.** The installer and upgrades never write, replace or delete
  it (R7).
- **Offline operation (SEC-005):** the installed app makes no network connection to do its work, and the
  installer needs none.
- **The development profile** (fake catalog and perception under an uncalibrated policy) must not be what a
  user gets by default (licensing checklist item 7); it stays reachable only by an explicit flag, and the CI
  test of the packaged build needs it because CI has no weights (R12).
- **Not delegable and unchanged:** no public release while the `buffalo_l` weights are research-only.

## 4. Steps

Each step is one or more small PRs with an implementation entry and an independent read-only review.

### Step 1. The licence inventory and the notices file

**Built 2026-11-10** ([entry](../implementations/2026-11-10-m8-step1-notices-inventory.md)): `scripts/generate_notices.py` (inventory, notices file, `--check`, run in CI). Left for M6: FFmpeg's `LICENSE.txt` and notices.

- Run the three inventory commands of licensing record section 8 (Python including transitive packages,
  JavaScript, Rust with `cargo-license` or `cargo deny`) and record the results in sections 5 to 7. Rust
  crates, transitive Python packages and the build tools are currently "not verified".
- Generate a third-party notices file from the inventory at build time (MIT, ISC, Apache-2.0, OFL and LGPL
  texts must travel with the software), including Microsoft's `DirectML.dll` terms and ONNX Runtime's
  notices, and (when M6 lands) FFmpeg's `LICENSE.txt` and the notices for the libraries inside the pinned build.
- Tracker: feeds TST-086 and SEC-008. No dependency is added except the inventory tools, recorded as build
  tools.

### Step 2. Freeze the backend

**Built 2026-11-10** ([entry](../implementations/2026-11-10-m8-step2-freeze-backend.md)): (a), (b) and (c) in one PR: spec, entry and headless check, CI job. The worker needs no flag: `freeze_support()` makes the spawned child run the worker. Real-model run in the frozen build: not yet (step 8).

Sized as three PRs: (a) the PyInstaller spec and the frozen host that starts and stops headless; (b) the native-library
collection hooks and the worker started from the same executable; (c) the headless CI job and the size and start-time record.

- A PyInstaller **onedir** build of the backend host and the ML worker (R3): `faceidentify-backend.exe` serving
  `backend.api.host`, and the worker started from the same executable (a flag, with
  `multiprocessing.freeze_support()` and the spawn guard the worker needs), plus a hook that collects
  `onnxruntime`'s native files (`onnxruntime.dll`, `DirectML.dll` and the providers' DLLs), USearch and
  Pillow's bundled codecs.
- Tests: the frozen host starts headless in a CI job on Windows, answers the handshake and `/readiness`,
  stops through the stdin lifeline, and its worker reports the `DmlExecutionProvider` and
  `CPUExecutionProvider` providers where the runner allows (DirectML needs a DirectX 12 device; a runner
  without one is expected to fall back visibly, which is itself a check). Record size and cold start time.
- Tracker: TST-078 (the backend half), TST-079.

### Step 3. The shell launches the frozen backend; installer build

- `tauri.conf.json`: the NSIS target only (R1), per-user install, the frozen backend directory shipped as
  Tauri `resources`, an application identifier and version policy (R9), WebView2 handling (the installer's
  bootstrapper; Windows 11 ships the runtime, an assumption to check on the clean machine).
- `config.rs`/`sidecar.rs`: resolve the backend executable beside the application when packaged, the
  repository's `.venv` otherwise; no Python needed on the machine.
- The default library folder moves out of the application-data folder (R8) so no uninstaller option can
  delete it; an existing library at the old default keeps being used.
- Tests: Rust unit tests for the resolution and the default-folder rule; a local `tauri build` produces the
  installer; CI builds it on demand (R12; that job is step 7a).
- Tracker: TST-078.

**Built 2026-11-11** ([entry](../implementations/2026-11-11-m8-step3-shell-packaged-installer.md)): launch resolution, `Documents\FaceIdentify` default, `FACEIDENTIFY_LOCAL_STATE_ROOT`, NSIS config and `packaging/build_installer.py`; installed, launched and uninstalled in a scratch folder.

### Step 4. Runtime packages: ONNX Runtime, FFmpeg, telemetry

- ONNX Runtime comes inside the frozen backend (step 2). The worker turns ONNX Runtime's telemetry events
  off (`onnxruntime.disable_telemetry_events()`, R4), a follow-up already recorded in the licensing record.
- FFmpeg (when M6 step 3 has merged): the zip pinned by SHA-256 is unpacked at build time into the package
  (without `ffplay`), its hash checked at build time and again by the app before first use; the app locates
  it beside the executable, with an environment override for development.
- Runtime activation keeps the previous runtime folder until the new one passes the self-check, and the
  active one is selected by a pointer written last (TST-082).
- Tests: a corrupted or wrong-hash runtime or model package is refused and the previous configuration still
  works (TST-080, TST-082).
- Tracker: TST-079, TST-080, TST-082.

**Built 2026-11-12** ([entry](../implementations/2026-11-12-m8-step4-ffmpeg-bundle-and-telemetry.md)): telemetry off, FFmpeg shipped and hash-checked, the runtime listed in the notices. The rollback tests move to step 5 (they need the model package installer).

### Step 5. First run: library, models, recognition mode, self-check

Sized as four PRs: (a) the backend model-installation use case and routes with the integrity tests; (b) the recognition-mode
choice and the self-check route; (c) the first-run screens; (d) the desktop end-to-end test through the flow.

- A first-run flow in the desktop app (spec text proposed in the PR; the routes extend the existing runtime
  and system resources): (1) choose or accept the library folder; (2) **install the face models yourself**:
  the screen says what `buffalo_l` is and its research-only licence, shows where InsightFace publishes it,
  and asks the user to point at the folder or zip they downloaded; the app checks each file against the
  SHA-256 table of `INSTALLING_MODELS_WINDOWS.md`, refuses a mismatch, and installs the runtime package with
  the logic of `scripts/install_reference_models.py` moved into the backend (R6); (3) choose the recognition
  mode (R7); (4) run the self-check: load both models, report the execution provider and whether DirectML
  fell back to the CPU, and process a generated image to show the pipeline end to end.
- **The test-only trust path:** the hash table is the only thing a production build trusts. Under the explicit development-profile flag, and only then, a fixture package whose manifest declares itself a fixture is accepted so CI can exercise the same flow without the weights; a test proves that a production-mode backend rejects that fixture and any other unhashed package.
- Until the model-installation part of this flow is done, processing is unavailable and says why (the existing 503 and readiness
  reporting), and everything else (browsing, an empty library) works.
- Tests: backend tests for hash checking and installation with fixture models, frontend tests for the flow,
  the desktop end-to-end test through the flow on the development profile.
- Tracker: TST-079, TST-083 (R11).

### Step 6. Upgrade, migration, downgrade, uninstall

- Before the backend applies any migration to an existing library it makes a consistent copy of the database
  (SQLite online backup) into the library's `backups/` folder (`pre-migration-<revision>-<date>.db`) and
  keeps the last three (R9). A library newer than the app is refused with a clear message and left untouched
  (already built). Rebuildable indexes are not backed up.
- The installer upgrades in place and never touches the library, the local state root, the models or the policy
  (R7, R8). The uninstaller removes program files only; it offers no option that deletes data (R8).
- Tests: a library at the previous revision is upgraded by the new build and keeps every row, the backup
  exists and restores; a newer library is refused; uninstall leaves the library, the state root and the
  policy in place; reinstall opens the same library.
- Tracker: TST-081, TST-085.

**Part built 2026-11-12** ([entry](../implementations/2026-11-12-m8-step6-pre-migration-backup.md)): the pre-migration copy (last three kept) with the previous-release upgrade test. Still open: the installer-level upgrade, uninstall and reinstall tests (step 7).

### Step 7. Installer in CI and the clean-install tests

Sized as three PRs: (a) the on-demand installer build and silent install job; (b) the first-run flow, process-tree and network checks on the installed build; (c) the integrity and rollback tests.

- A CI job (on demand and before a release, not on every push, because it builds the frozen backend and the
  installer) builds the installer, installs it silently on a fresh Windows runner, launches it on the
  development profile, completes the first-run flow with fixture models and an imported fixture image, and
  checks that the process tree stops cleanly and that no network connection was opened (SEC-005).
- Tests of integrity: a tampered installer-contained backend, a runtime package or a model file with the
  wrong hash is refused (TST-080); the installer's own SHA-256 is recorded in the release notes (R10).
- Tracker: TST-078, TST-079, TST-080, TST-081, TST-082, TST-085, SEC-008.

**Part built 2026-11-12** ([entry](../implementations/2026-11-12-m8-step7-installed-build-check.md)): `packaging/check_installed.py` and the path-filtered `installer.yml` job (installed backend, one image, one video through the shipped FFmpeg, both provider paths). Still open: the first-run flow checks, the integrity and rollback tests, the upgrade tests.

### Step 8. The real-model packaged check, release regression, release notes

- On the owner's machine, with the weights installed by the user: install the release candidate, run the
  first-run flow, import and process the real photographs, search, correct, restart, upgrade over the
  previous build, uninstall and reinstall. The existing desktop end-to-end test is pointed at the installed
  executable for the parts that do not need the owner (TST-084).
- A full regression: the backend gate, the frontend gate, the desktop gates and every earlier milestone's
  end-to-end test, run against the release-candidate commit (TST-086).
- Release notes for the personal build: the installer's SHA-256, the exact FFmpeg and ONNX Runtime builds, the
  unsigned consequence (R10), the licence blockers that make it personal-use only (section 6), and how to
  go back to the previous build.
- Tracker: TST-084, TST-086, SEC-008.

## 5. Dependencies, tracker IDs and definition of done

- **Depends on:** nothing for steps 1 to 3 (they package what M5 delivered); step 4's FFmpeg part waits for
  M6 step 3; the camera features (M7) are packaged by the same build when they land, and the camera
  permission question of M7 (Windows camera privacy) is part of step 8's check if M7 is in the candidate.
  Steps may overlap with M6 and M7 in time as long as the release candidate is cut after the features it
  claims are merged.
- **Tracker IDs:** TST-078 to TST-086, SEC-008 (with SEC-005 and SEC-006 re-run on the installed build).
- **Done when:** TST-078 to TST-086 are `PASSING` on the exact packaged release candidate with the evidence
  their rows ask for (TST-083 as scoped in R11), SEC-008 holds, the installer is built and checked by hash,
  an upgrade keeps a library, an uninstall keeps a library, the real-model packaged check is recorded, and
  the notices file and release notes exist.

## 6. Release blockers: what a personal-use build can ship with, and what blocks a public release

| Blocker (source) | Personal-use build | Public release |
|---|---|---|
| The `buffalo_l` weights are research-only (licensing 1 and 2; PROGRESS 4) | **Ships without them**: the user installs them; the owner accepted the risk of using them for a personal application | **Blocks.** Needs a commercial licence or other weights whose licence and training-data terms allow it, and a new representation space with the evaluation redone |
| LFW's own terms page not read, the Kaggle mirror grants nothing (#183; licensing 10.3) | Nothing from LFW or CelebA is shipped; they are evaluation data on the owner's machine. **No blocker** | **Blocks any publication of the numbers measured on them** until read; leakage with the training data is unassessed |
| FFmpeg builds' licences (D2; PROGRESS 4) | **Not resolved yet.** The D2 record recommends the pinned LGPL build, pending confirmation, and the licences of the libraries inside it are unread. Step 4 packages FFmpeg only after the recommendation is confirmed; the notices are generated in step 1. Distribution to anyone but the owner is not involved, so the LGPL conditions are not triggered for the personal build, but the record is completed first | The libraries inside the build are read and their notices, the build configuration and a source offer are shipped |
| Rust crates, transitive Python packages, build tools not inventoried (licensing 5 to 7, 11) | **Done in step 1 anyway** (cheap, and the notices file needs it) | Blocks until reviewed |
| No licence file for our own code (licensing 3) | No blocker | **Blocks:** the owner chooses a licence or stays proprietary |
| Microsoft `DirectML.dll` terms (licensing 4b) | Read: in-application redistribution is permitted; the terms file ships with the installer | Same, plus confirming the wheel's copy is covered by the terms that were read from the NuGet package |
| NVIDIA CUDA/cuDNN (licensing 4) | Not shipped (CUDA is developer-only, decision 2026-10-15). **No blocker** | No blocker while it stays unshipped |
| Biometric-privacy law (licensing 3 and 9) | The owner's own household use; no blocker | **Blocks** without a review per market, consent flows, retention and deletion |
| ONNX Runtime telemetry events (licensing 4) | Turned off in step 4 | Same |
| Developer-only items: the development profile, local weights, evaluation scripts (licensing 11.7) | The profile stays behind an explicit flag; evaluation scripts are not packaged | Removed or relabelled |
| Code signing (R10) | Unsigned; the consequences are stated | **Blocks** a smooth public install (SmartScreen, Defender reputation) |

## 7. Risks

- **PyInstaller and native libraries.** ONNX Runtime's DLLs, DirectML, USearch and Pillow's codecs are the usual
  trouble. Mitigation: step 2 is first and has a headless test; the Plan C of the tech-stack (a managed
  self-contained Python) is the fallback and is not built unless step 2 fails.
- **Antivirus false positives** on a frozen, unsigned executable are common (an assumption from experience
  with PyInstaller, not measured here). Mitigation: onedir rather than onefile, publish the hash, and add an
  exclusion on the owner's machine if needed.
- **Size.** The backend with ONNX Runtime Windows ML (about 74 MB installed), NumPy and the rest, plus FFmpeg
  (about 150 MB), puts the installer in the low hundreds of MB. Not a problem for personal use; measured in
  step 2.
- **DirectML on the test runner.** CI runners have no GPU, so the DirectML path is only exercised on the
  owner's machine in step 8; CI proves the CPU fallback.
- **Library location.** Moving the default (R8) must not strand an existing library. Mitigation: an existing
  library at the old default keeps being used, with a test.
- **WebView2.** Assumed present on Windows 11; the installer's bootstrapper covers an absent one; verified only
  on the clean machine of step 7.
- **A migration that fails half way** on the owner's real library. Mitigation: the pre-migration copy (R9) and
  the existing refusal of a newer library.

## 8. Decisions (delegated, 2026-11-10)

> **Decision 2026-11-10 (delegated decisions by the agent):** the owner delegated the remaining product and
> design decisions ("i'll leave the rest of the decisions entirely to you"). R1 to R12 are the agent's
> decisions, each with its reasoning and what reversing it costs. They are recorded in
> [the implementation entry](../implementations/2026-11-10-m8-plan.md).

| # | Question | Decision and reasoning (delegated) |
|---|---|---|
| R1 | The installer format | **Tauri's NSIS target, per-user (no administrator rights), one `.exe`.** It is Tauri's default Windows route, installs under the user's profile without elevation, and upgrades in place. MSI (WiX) is for managed fleets, which a personal install is not. Reversal: change the bundle target |
| R2 | Online bootstrap installer or offline | **One offline installer.** `tech-stack.md` section 12 locks an online hardware-aware bootstrapper for the normal distribution; it needs a download server, a manifest and signatures, none of which exist, and the personal build has no one to serve. The offline full bundle is the optional form the same section allows, minus the models. Hardware detection stays what it is today (DirectML, falling back to the CPU at run time). Reversal: build the bootstrapper when a public release exists |
| R3 | How the Python backend is packaged | **PyInstaller onedir, shipped as Tauri resources, started by the shell; the ML worker is the same executable with a flag.** Onedir starts faster and is less often flagged than onefile, which unpacks to a temporary folder on every start. It is the locked baseline. Reversal: Nuitka or a managed Python (the tech-stack's alternatives) only if step 2 fails |
| R4 | ONNX Runtime | **The `onnxruntime-windowsml` 1.30.0 build already shipped by decision (2026-10-15), collected into the frozen backend; ONNX Runtime's telemetry events disabled in the worker.** The application is offline and local; trace events through Windows' diagnostic channel serve no purpose here. Small code change in step 4 |
| R5 | FFmpeg in the package | **The pinned LGPL zip of the D2 record, unpacked without `ffplay`, hash-checked at build and at first use, with `LICENSE.txt`.** Contingent on the D2 recommendation being confirmed; if the PyAV wheel were chosen instead, this row becomes "inside the frozen backend" and the public-release row of section 6 gains the x264/x265 blocker |
| R6 | Model weights | **Never bundled and never downloaded by the app; the user installs them from a folder or zip they obtained, and the app verifies the recorded SHA-256 values.** The licence is research-only (the user's to accept), the app is offline, and a hash check keeps the evidence of the evaluation applicable to the files in use. Reversal: none that is safe while the licence stands |
| R7 | The decision policy | **The package ships no policy file and never overwrites or deletes an existing one. First run offers Assisted recognition (the abstain-only policy) as the default; the Automatic point (0.45 / margin 0.10) is installed only by the user's own explicit choice in the app, after it shows what it will write.** The live policy is the owner's, and only the two policies the code admits can be written. Without a policy processing is unavailable and says so. Reversal: ship the abstain-only file at first run |
| R8 | The library folder | **The default moves from the application-data folder to `Documents\FaceIdentify`; an existing library at the old default keeps being used; the uninstaller offers no deletion of data.** The NSIS "delete application data" option that Tauri's template offers (an assumption from the template, not checked here) would otherwise be one click from deleting the library, and a library the user can see and back up belongs in Documents. Uninstall keeps the library and the local state root (TST-085). Reversal: change the default |
| R9 | Upgrade, migration, downgrade | **In-place upgrade by running the newer installer (no updater); the backend backs up the database before migrating (last three kept), refuses a newer library, and never touches models or policy.** The Tauri updater needs a signing key and a server, which a personal build has neither of. Versions follow semantic versioning in `tauri.conf.json`; the migration chain already exists. Reversal: add the updater plugin later |
| R10 | Code signing | **Unsigned for personal use.** A certificate costs money and a reputation that a household build cannot use. Consequences, stated plainly: Windows SmartScreen shows "unknown publisher" and the owner must choose "More info, Run anyway" on each machine; Defender may flag the frozen executable (see risks); there is no verified publisher name; tampering is detected only by comparing the SHA-256 published in the release notes. Signing is a public-release blocker (section 6). Reversal: sign with a certificate when one exists |
| R11 | ML-component promotion (TST-083) | **Scoped to the one shipped component version:** a test that a model package whose hashes do not match, or a policy that is not one of the two the code admits, cannot be activated (fail closed), plus the evaluation evidence already recorded for `buffalo_l`. No promotion workflow with versions, decisions and activations is built (`tech-stack.md` section 14 describes one for a future with several components). Reversal: build the workflow when a second component exists |
| R12 | Testing the installed app | **CI: build the installer on demand, install it silently on a fresh Windows runner, run the development profile through the first-run flow with fixture models and a fixture image, and check the process tree and the network (no connections). Local: the real-model packaged check on the owner's machine, because the weights cannot be in CI.** The development profile stays in the personal build behind an explicit flag so CI can use it; a public release strips it (section 6). Reversal: none needed |

## 9. Open questions this plan leaves

1. **The FFmpeg recommendation** (D2 record) must be confirmed before step 4 packages it; R5 follows it.
2. **The default library folder** (R8): `Documents\FaceIdentify` is the proposal; the owner may prefer another
   place, and the existing development library stays where it is.
3. **Which machines** the personal build must run on (one Windows 11 laptop is assumed; other GPU vendors'
   DirectML behaviour stays unverified, as in M7).
4. **An updater** (R9) and **signing** (R10) are left out; say so if either is wanted before a public release.
5. **Whether the self-check image** (step 5) may be a generated picture or should be a public-domain portrait;
   the plan uses a generated one, which proves the pipeline loads but not that a face is found.

## 10. Not in this plan

A public release or any distribution to other people, code signing, an automatic updater, the online
bootstrapper and its server, model hosting, an installer for other operating systems, a multi-component
promotion workflow, and anything that changes a spec or the locked stack.
