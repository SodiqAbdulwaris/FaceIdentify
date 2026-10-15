# M5 definition-of-done audit (2026-10-16)

An audit of [`M5_PLAN.md`](M5_PLAN.md) section 5 against the repository as it stands on
2026-10-16 (main at the merge of PR 206, during the unattended overnight run). Each criterion is
**met**, **not met** or **owner-blocked** (only the owner can close it), with its evidence. This
audit changes no status: the tracker is updated only with verified evidence, by the change that
supplies it.

**Summary: M5 is not done.** Coverage, search, assisted recognition, the CI desktop end-to-end test
and two of the three issues are met; #69 closes with PR 207. What is left is mostly bookkeeping the
tracker never caught up with (TST-054, TST-058 and the TST-059 parts have no `PASSING` row although
their work is built and tested) and two owner steps (TST-038/039's local-only evidence, the
live automatic-acceptance policy and its backup); the smoke test was reported done but not itemised.

| # | Criterion (M5 plan section 5) | Verdict | Evidence |
|---|---|---|---|
| 1 | TST-054 (naming, corrections) `PASSING` | **Not met (tracker)** | Built and tested 2026-10-07 ([naming](../implementations/2026-10-07-m5-naming.md), [corrections](../implementations/2026-10-07-m5-corrections.md), [unresolved faces](../implementations/2026-10-07-m5-unresolved-faces.md)), but the tracker has **no status row** for TST-054 (only its definition, line 267). Needs a row with the tests as evidence |
| 2 | TST-058 (merge and split) `PASSING` | **Not met (tracker)** | Built and tested 2026-10-07 ([merge and split](../implementations/2026-10-07-m5-merge-split.md)); no status row in the tracker (definition only, line 271) |
| 3 | TST-059 (recycle, delete, forget) `PASSING` | **Not met** | 4c (forget) `PASSING`; 4a (recycle and restore) and 4b (permanent delete) still `IN_PROGRESS` although their entries record the work done ([4a](../implementations/2026-10-08-m5-recycle-restore.md), [4b](../implementations/2026-10-09-m5-permanent-source-delete.md)). Needs the remaining parts named or the rows closed with evidence |
| 4 | SEC-006 (deletion privacy) `PASSING` | **Not met (tracker)** | Byte-level checks exist (`test_permanent_source_delete.py`, `test_forget_identity.py`, cited in TST-059 4c), but SEC-006 has no status row (definition only, line 357) |
| 5 | TST-055 (historical and name search) `PASSING` | **Met** | Tracker row 5a `PASSING` (2026-10-09) |
| 6 | TST-056 (face search) `PASSING` | **Met** | Tracker row 5b `PASSING` (2026-10-10, AVIF added 2026-10-15) |
| 7 | TST-057 on real models | **Partly met; owner-blocked** | TST-057A (assisted) `PASSING` (owner, 2026-10-12). TST-057B (automatic) `IN_PROGRESS`: built and verified at the owner-confirmed point 0.45 / 0.10; remains open until the owner installs the live policy file ([entry](../implementations/2026-10-15-enable-automatic-acceptance.md)). Observed 2026-10-16: `local-models/state/policies/insightface-buffalo-l.json` already holds the matching policy (written 2026-10-15 23:58), but so does its backup `insightface-buffalo-l.abstain-only-v1.json`, so the way back to abstain-only is broken until the backup is rewritten. The owner should confirm the install and fix the backup before TST-057B is marked `PASSING` |
| 8 | TST-038 / TST-039 on the real path | **Owner-blocked** | Row 191 `IN_PROGRESS`: "Still open: the owner's decision whether local-only evidence closes these rows" (the weights are never in CI). Row 189 (`BLOCKED` on issue 69) is stale: the weights were selected 2026-10-07 and #69 closes with PR 207 |
| 9 | TST-044 (initial calibrated policy) | **Not met (tracker)** | Row 192 `IN_PROGRESS`, "Remaining: a larger verified set (track R5)"; the 48-identity verified set (2026-10-15) and the verified operating point now exist, and a DirectML re-measure is pending its record (see the last column). Needs the row reviewed against that evidence. (The DirectML re-measure of 2026-10-16 matched the CPU operating point on all 686 photographs; it is recorded in its own overnight PR, **not yet merged**, so it is not evidence here until it is) |
| 10 | Issue #69 closed | **Met once PR 207 merges** | PR 207 re-hashes the files in use against the record and adds the install guide; the licence stays a release blocker |
| 11 | Issue #80 closed | **Met** | Closed (installation sweep, [entry](../implementations/2026-10-08-m5-installation-sweep.md)) |
| 12 | Issue #137 closed | **Met** | Closed (profile guard, `backend/api/library_profile.py`) |
| 13 | Real-world gate run and recorded | **Met, with a gap in the record** | Many local runs recorded (LFW, CelebA, Commons 36 and 48 verified identities, hard negatives, CelebA restart phases). The owner's independent smoke test was **reported done on 2026-10-14** (tracker TST-057A row; [entry](../implementations/2026-10-14-m5-celeba-gate-and-acceptance-decision.md) "Also recorded"), but its checklist outcomes were not itemised, and [`M5_REMAINING_WORK.md`](M5_REMAINING_WORK.md) item 8 still says it is owed (stale) |
| 14 | Milestone gate: identity-management workflows preserve current state and historical evidence | **Met by tests, pending 1 to 4** | The workflow checks (10 of 10 in every verified gate run, restart included) and the integration suites behind TST-054/058/059; formally holds once rows 1 to 4 are closed |
| 15 | Full backend gate with 100% coverage | **Met** | `uv run pytest --cov` on main at `16323bf` (2026-10-16; PRs 205 and 206, merged since, change nothing under `backend/`, the measured source): 3,081 passed, 3 deselected; 10,435 statements and 2,136 branches, **100%**, no file below 100% |
| 16 | Desktop end-to-end test passes on the development profile in CI | **Met** | CI job "Desktop shell (TST-047)" runs `npm run test:e2e` (`.github/workflows/ci.yml`); the `push` run on `main` at `fa9ef67` (run 38822065103) passed it, and so did the run at `210bcce` |
| 17 | CI green on `main` | **Met up to `fa9ef67`; `210bcce` pending** | `push` runs on `main`: `16323bf` and `fa9ef67` succeeded (all six jobs); the run at `210bcce` (PR 206, docs only) had five jobs green and the backend tests still running when this was written |
| 18 | CONTEXT, PROJECT_STATUS, the implementation log and the tracker agree | **Not met** | The tracker lags the implementation log: rows 1 to 4, the stale TST-038/039 writer row (row 8) and TST-044 (row 9) |

## What would close M5, in order

1. A tracker-only PR that adds or closes TST-054, TST-058, TST-059 (4a, 4b) and SEC-006 rows with
   the test files and counts from their implementation entries (re-running those suites to quote
   real results), and retires the stale TST-038/039 writer row.
2. Merge PR 207 (#69).
3. The owner: decide whether local-only evidence closes TST-038/039; confirm the live policy install
   and rewrite the abstain-only backup, then mark TST-057B; optionally itemise the smoke test's
   checklist outcomes (reported done 2026-10-14), and `M5_REMAINING_WORK.md` item 8 updated to match.
4. Review TST-044 against the verified operating point, and the DirectML re-measure once its PR merges.
