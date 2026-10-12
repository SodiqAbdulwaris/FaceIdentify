# The learning guide restructured into `docs/learning/`

- **Date:** 2026-10-12
- **Milestone / tracker IDs:** documentation (owner request); no tracker row is marked
- **Status:** done; documentation only
- **Commits:** PR to be recorded when merged (branch `docs/learning-guide-restructure`)

## What changed

The single 2,400-line guide `docs/research/codebase-learning-guide.md` (written 2026-10-08, see
[its entry](2026-10-08-codebase-learning-guide.md)) was restructured and extended into a folder of **130 Markdown files**
(about 13,500 lines; the longest is 311) under `docs/learning/`. Each lesson is a practical lesson of eight parts: what and why;
where it lives; how it works; **Try it** (exact commands, expected output, and a statement of whether it works with no models
or needs the local models, with a date and whether it was verified); **Change it**; **Break it on purpose**; exercises with answers; related files.

Only documentation changed: no code, test, configuration or generated file is touched (`git diff --name-only origin/main..HEAD` lists
paths under `docs/`, plus `.agents/CONTEXT.md`). Dry runs that edited code (adding a route, an Alembic column, a front-end screen, mutations
to prove tests catch them) were **discarded** with `git checkout`/`rm`; none is committed.

Files outside `docs/learning/` that changed: `docs/research/codebase-learning-guide.md` (now a short pointer),
`docs/plans/PROJECT_STATUS.md` (the "New to the code?" link), `docs/implementations/README.md` (this entry's row),
`docs/implementations/2026-10-08-codebase-learning-guide.md` (an update note), `.agents/CONTEXT.md` (the *Last updated* line and the
`docs/` map), and this entry.

### The folder map

| Folder | Files | Contents |
|---|---|---|
| `README.md` | 1 | the index, reading paths, a legend (profiles, Verified / Verified by test / Unverified), the accuracy promise and the safety rules |
| `00-start-here/` | 8 | what it is, the four programs, authoritative versus derived, layers and the repository map, one request end to end, set up your machine, run it and see it work |
| `01-basics/` | 27 | `python/` (7), `tools/` (7: terminal, uv, pytest, ruff and mypy, git, CI, JavaScript and Rust tools), `recognition-ideas/` (6), `topic-map/` (2), each with a README |
| `02-data-and-storage/` | 10 | SQL, SQLite and WAL, transactions and the unit of work, Alembic, SQLAlchemy, the vector index and outbox, erasure, storage roots and artifacts, reading a database and a log |
| `03-backend/` | 53 | `architecture/` (8: layers, HTTP and FastAPI, host and startup, profiles, scheduler and runner, recovery, events, security), `api/` (conventions, calling the API, adding a route, the OpenAPI contract, and `api/routes/` with one lesson per route module: sources, processing, jobs, memory, people, corrections, identity changes, search, face search), `domain/` (7), `processing/` (5), `recognition/` (5), `runtime-and-worker/` (4), `lifecycle/` (3: recycle and restore, permanent delete, forget) |
| `04-frontend/` | 11 | web and JavaScript, TypeScript and tooling, React, app structure and the gate, the API client and queries, events and routing, library and source screens, people and search screens, styling and tests, adding a screen |
| `05-desktop-shell/` | 6 | Rust in ten minutes, Tauri commands, the sidecar contract, library folder and dialogs, building and testing the shell |
| `06-evaluation-and-operations/` | 8 | evaluation overview, the operating point, the assisted gate and open set, the label-review tool, a real-model run, rules/branches/reviews, milestones/tracker/decisions |
| `07-walkthrough-and-glossary/` | 6 | one photograph in 18 steps, a reading path, exercises, a glossary (about 135 terms), further reading and keeping the guide true |

Every requested topic is covered: machine setup (`00-start-here/06`), running the backend and calling the API (`03-backend/api/01`: development
profile, `/readiness`, import, process, search, face search), running tests (`01-basics/tools/03`, `04-frontend/09`), adding a route
(`03-backend/api/02`), adding an Alembic column (`02-data-and-storage/04`, described and dry-run, not committed), adding a screen and
`npm run generate:api` (`04-frontend/10`), the evaluation scripts (`06-evaluation-and-operations/02` to `05`, described only because they need
local data), reading a log and a database with `sqlite3` (`02-data-and-storage/09`; the `sqlite3` command-line program is not installed in this
environment, so the lessons use Python's `sqlite3` module, which behaves the same, and name the shell as an alternative), and the
branch/commit/PR workflow (`06-evaluation-and-operations/06`, `01-basics/tools/05`).

## Where each part of the old guide went

Every part was moved (corrected against the code) or dropped with a reason. Nothing was dropped wholesale.

| Old section | Now |
|---|---|
| Preamble: what this is, who for, markers, accuracy promise | `docs/learning/README.md` |
| 1.1 to 1.5 | `00-start-here/01` to `05` |
| 2.1 to 2.6 (program, values, variables, operators, strings, collections) | `01-basics/python/01` |
| 2.7, 2.8 | `python/02` |
| 2.9, 2.10 | `python/03` |
| 2.11 | `python/04` (with dataclasses, enums and protocols) |
| 2.12 to 2.15 | `python/05` |
| 2.16 to 2.18 | `python/06` |
| 2.19 | `python/07` |
| 3.1 to 3.7 | `01-basics/tools/01` to `07` |
| 4.1, 4.2 | `recognition-ideas/01`; 4.3 to `02`; 4.4 to `03`; 4.5 to `04`; 4.6 to `05`; 4.7, 4.8 to `06` |
| 5.1 to 5.3; 5.4 to 5.7 | `topic-map/01`; `topic-map/02` |
| 6.1 to 6.7 | `02-data-and-storage/01` to `06` and `08` (erasure expanded in `07`; `09` is new) |
| 7.1, 7.2 | `architecture/02` and `api/README.md` |
| 7.3; 7.9; 7.10; 7.8 | `architecture/03`; `07`; `08`; `06` |
| 7.4, 7.5 | `processing/01` to `05` and `architecture/05` |
| 7.6; 7.7 | `runtime-and-worker/01`, `02`; `04` |
| 8.1, 8.2, 8.3, 8.7 | `domain/01` to `07` |
| 8.4 | `recognition/01` to `05` |
| 8.5, 8.6 | `domain/04`, `05`, the `api/routes/` lessons, and `lifecycle/01` to `03` |
| 8.8 | `04-frontend/04` and `07` (the policy notice) and `domain/06` (calibrated confidence) |
| 8.9 | `architecture/04` (profiles) |
| 9.1 to 9.8 | `04-frontend/01` to `09` |
| 10.1 to 10.4 | `05-desktop-shell/01` to `05` |
| 11.1, 11.2; 11.3 to 11.5 | `06-evaluation-and-operations/06`; `07` |
| 12.1 to 12.6 | `07-walkthrough-and-glossary/01` to `05` |

New material with no old counterpart: the per-route lessons, adding a route and a column, calling the API with real output, the sidecar played
from a script, the scheduler and runner outcomes, events, security, the lifecycle lessons, reading a database and a log, the label-review tool and
the real-model run, and the verified `Try it` sections throughout.

## Why

The owner asked for a guide that is easy to use for learning the code: small, practical, runnable, with exact commands and honest statements of
what could not be run. A single 2,400-line file could not be done step by step, did not show commands that had been run, and had begun to drift from
`main` (see Findings).

## Decisions

- Code and specs are the source of truth. Anything the old guide said that the code contradicted was corrected (examples below).
- Commands are written only if they were **run** in this session (Linux, 2026-10-12) or can be read directly from code and tests. Everything else says
  *unverified* and why (no display, Windows only, needs local models, needs network).
- The profile used is marked on each lesson ("works with no models" or "needs the local models").
- The old path is kept as a short pointer so older links work; every link in the repository that pointed to it is updated or still resolves.

### Decisions for the owner

Ambiguities were resolved conservatively; please confirm or overrule.

1. **Branch name.** `docs/learning-guide-restructure`, as you specified. It is a valid name under `.githooks/check-branch-name` (checked).
2. **Commit size.** You asked for small commits, "one per big area". Each area commit is therefore far larger than the ~400-line guide in
   `.agents/rules/commits.md`. They are all documentation, one logical area each, and each leaves the repository consistent; split further if you prefer.
3. **Stub, not deletion.** `docs/research/codebase-learning-guide.md` stays as a pointer instead of being deleted, so existing links keep working.
4. **`sqlite3`.** The shell program is not installed here, so reading a database uses Python's `sqlite3` module; the lessons say the shell works the same.
5. **Platform.** Everything was run on Linux; the product targets Windows. PowerShell forms and anything Windows-specific are marked unverified.
6. **Evaluation scripts** are described, shown with their real `--help`, and unit-tested through their no-photograph tests, but **not run** (no local dataset
   or models). The label-review tool *was* exercised on a synthetic set of invented pictures that was deleted afterwards.
7. **The review and unrun Rust tests.** No CLI reviewer (Codex, OpenCode, Antigravity) is installed here, so the independent review uses a read-only
   subagent as `branches.md` allows. The shell's own tests (`cargo test`) could not be run (see Findings).
8. **CONTEXT.md.** Its header is dated 2026-10-07 although later work exists. I only prepended a 2026-10-12 note and did not rewrite the file (out of scope);
   you may want it brought up to date separately.
9. **No tracker row, spec or plan was changed** (rules: only verified status; specs only with approval).
10. **A new top-level docs folder.** `documentation.md` lists `specs/`, `plans/`, `guides/`, `strategy/`, `research/` and `archive/` and says not to create new top-level documents where one fits. You asked for `docs/learning/`, so I used it. The alternative is `docs/guides/learning/`. Recommendation: keep `docs/learning/` (it is a whole guide, not a how-to) and amend `documentation.md` to list it, which I did not do without your approval.
11. **Commit bodies.** Large area commits mostly lack the one-line body `commits.md` asks for; decision 2 is the disclosure. History is not rewritten without your permission.

## Findings (found while verifying; not fixed here)

1. **CORS (resolved on `main` while this PR was open).** My first draft found that a browser page was blocked by CORS: the page stayed on "Opening your library..." because the backend sent no cross-origin headers. `main` has since fixed it (`2026-10-12-webview-cors.md`: `--allow-origin`, exact origins). After merging `main` I re-ran the same Chromium check with `--allow-origin http://localhost:5173`: the library screen appears. The fix's own entry says it is not yet confirmed in the real Windows window; I could not confirm it either. The lessons now describe the fixed behaviour.
2. **Linux test failures that are Windows-only in effect.** `tests/integration/test_ml_supervisor.py` (11 tests) calls `tasklist`;
   three race tests in `test_runtime_package_store.py` rely on Windows refusing a rename onto a directory; in `tests/recovery`, one test depends on a
   Windows file lock (164 passed, 1 failed on Linux). CI runs on Windows.
3. **A stale docstring.** `scripts/install_reference_models.py` says registration at startup is "a later M5 step (R2)" and "today the package is installed, not yet
   used"; the real host profile now registers packages on startup.
4. **Registered but unused Tauri command.** `choose_library` (and the `libraryRoot()` wrapper of `library_info`) are not used by any screen.
5. **`.agents/CONTEXT.md`** carries a 2026-10-07 header (see decision 8).
6. **Behaviour worth knowing** (documented, not a defect): under the abstain-only policy an empty library still creates an identity for the first face
   (`NO_CANDIDATE` is decided before any threshold).

Corrections made to claims in the old guide or in my own drafts, after running them: `/health` and `/docs` also need the Bearer header; Ctrl+C on the host
ends with exit 130 and a traceback (use `kill -TERM` or close standard input for a clean stop, exit 0); USearch returns a *distance* equal to
`1 - cosine similarity`; the corrections test file has 20 tests; forgetting is built (the old glossary said designed); a layering violation is caught by
review/grep, not by the test suite (ruff reports only an unused import); a copied `library.db` without its WAL loses data (use the backup API).

## Verification

Run on 2026-10-12 on Linux from the repository folder:

- `uv run ruff format --check .`: 300 files already formatted. `uv run ruff check .`: all checks passed. `uv run mypy`: no issues in 293 source files.
- `npm run lint`: no findings (also with `--deny-warnings`, exit 0). `npm run typecheck`: clean. `npm test`: 24 files, 193 tests passed.
  `npm run build`: built. `npm run test:e2e`: 1 passed (the real web app against the real backend).
- Relative links: a small script (in `docs/learning/07-walkthrough-and-glossary/05-further-reading-and-keeping-true.md`, standard library only) reports
  that every relative link in `docs/learning/` resolves; a second pass over backticked repository paths found only intentional practice paths and placeholders.
- The pytest groups each lesson cites were run and their counts recorded in the lessons (for example processing 209, recognition 119, runtime 304 + 96 + 117,
  lifecycle 39 + 51 + 32 + 33, security 13 and 53). Failures on Linux are listed in Findings.
- The backend was started and called for real: the API tour, events over WebSocket, a `kill -9` and restart, the profile guard, the real profile without models, the
  stdin lifeline and `--parent-pid` stops, recycle/restore/permanent delete/forget, merge and naming, corrupted-index quarantine. Dry runs of adding a route, an
  Alembic column and a front-end screen passed and were discarded.
- **Not verified:** `cargo test` and `clippy` (no webkit libraries or crate cache here), `npm run tauri dev` and the visible window, PowerShell variants, anything
  needing the local models or datasets, the interactive `label_review.py serve` page, and external links and books in the reading lists (not opened).

Re-checked after merging `main` (2026-10-12, which added the CORS fix and the LFW/CelebA importer): ruff, mypy, typecheck, lint and the 193 front-end tests pass again; lessons updated for `--allow-origin`, the shell's 14 Rust tests and the new importer.

## Open issues / follow-ups

- The independent review of the pull request (read-only subagent) is recorded on the PR.
- Findings 1 to 4 above are for the owner to triage.
- The guide describes `main` on 2026-10-12 and must be updated when a milestone lands (see the last lesson).
