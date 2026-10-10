# M5 remaining work: the order, the gates and what needs the owner

_Written 2026-10-08, after the abstain-first decisions. This plan only orders what
[`M5_PLAN.md`](M5_PLAN.md) already decided; it does not change scope. Status of what is built is in
[`PROJECT_STATUS.md`](PROJECT_STATUS.md)._

## 1. Where M5 stands

Built and merged: library-profile guard (R0), model selection and installation (R1), real inference on
CPU and CUDA (R3, R2), the measured operating point (R4, result: automatic matching disabled), naming,
corrections, unplaced faces, merge and split, the `SPLIT` state removal, the codebase learning guide.
Merged: the abstain-only visibility work (notice, similarity-score wording, regression tests). The
real host profile (`backend/api/real.py`) is merged, and the installation sweep of issue #80 is in
review.

## 2. The order, with what each step needs

| # | Step | Depends on | Done when | Owner needed? |
|---|---|---|---|---|
| 1 | Land the abstain-only PR | its gate and review | merged, CI green on the exact head | no |
| 2 | **Real host wiring** (R2/R3 remainder): `backend/api/real.py` (persistent supervised worker per plan, closed at shutdown through `ProcessingSettings.close`; `prepare` registers installed packages; `request_for` builds the request from the catalog and the measured policy file, 503 until one exists), host default = real profile, real-model integration test through the host and catalog, issue #80's installation-MISSING sweep, GPU first with CPU fallback as a request setting | 1 | TST-038/039 close on the real path (local `-m e2e`, evidence in the tracker); #80 closed; the abstain-only policy file is what the real host reads | no |
| 3 | **Step 4a: recycle and restore** over `recycle_source`/`restore_source` (routes, library list hides recycled, identity views keep their Occurrences marked as recycled, UI marker and an undo) **built 2026-10-08** | none (parallel to 2) | routes + tests; TST-059 first part | no |
| 4 | **Step 4b: permanent Source delete**: runs then now-unreferenced snapshots, managed artifacts through the Storage Manager cleanup, representations through `RepresentationEraser`, **Evidence and named people kept**, an unnamed identity left with nothing becomes `DELETED` **built 2026-10-09** | 3 | restart-proof tests; TST-059 | no (decided 2026-10-07) |
| 5 | **Step 4c: `ForgetIdentity` and "forget person"**: the only operation removing biometric memory; Person record and name kept; `IDENTITY_FORGOTTEN` Evidence kept; resurrection impossible after processing, index rebuild and restart **built 2026-10-09** | 4 | TST-059 and SEC-006 `PASSING` (byte-level) | no (decided 2026-10-07) |
| 6 | **Step 5a: historical and name/person search** over authoritative data, recycled-source Occurrences included, marked and filterable | 3 | TST-055 `PASSING`; search screen **built 2026-10-09** | no (read `universal-search-and-retrieval-architecture-v1.md` first; ask only where it is silent) |
| 7 | **Step 5b: face search** (query-only; never persists; ranked possible matches with similarity scores, no thresholds needed) | 2 | TST-056 `PASSING` including after a restart **built 2026-10-10** | no |
| 8 | **Assisted cross-source recognition and the M5 real-world gate**: TST-057A (Recall@1, Recall@5, MRR on real independent-source images, manual confirmation, persistence after restart); the gate runs the assisted workflow with automatic matching explicitly disabled. TST-057B (automatic recognition) stays `BLOCKED pending calibration` and is not claimed | 2, 5, 7 | TST-057A `PASSING` and the gate recorded with evidence; TST-057B recorded as blocked **evidence recorded 2026-10-10; TST-057A awaits the owner's acceptance level and manual confirmation** | no |
| R5 | **Label-review utility** (parallel, after 2): a lightweight local tool to review doubtful same-person/different-person pairs; keeps reviewed labels, reviewer decisions and evaluation provenance; reviewed calibration examples are never reused as the untouched final set; re-run the measurement on the reviewed set | 2 | tool + tests + a re-run; a policy that passes the conservative rule enables matching (TST-057B) | **yes: the agent asks for the dataset requirements when it starts** |

Every step is its own branch and small PRs, mutation-tested guards, the full gate, an independent
Codex review answered before merge, CI green on the exact head, and the usual documentation (entry,
`CONTEXT.md`, `PROJECT_STATUS.md`, tracker, licensing row for anything new).

## 3. The contradiction, and how the owner resolved it (2026-10-08)

**Resolved:** option 1 now, option 2 in parallel; TST-057 is split into assisted (TST-057A) and
automatic (TST-057B, blocked pending calibration). The text below is kept as the record of the
question; the decision is in `M5_PLAN.md`.

### The question as asked

TST-057 and the M5 gate say real images of the same person from independent sources are "recognised
under the initial calibrated policy". The measured result and the owner's rule leave **automatic
matching disabled** on the current evaluation set (5 false accepts in 40, interval 74% to 94%). With
matching off, the application can rank possible matches and let a person confirm them, but it will not
recognise anyone by itself. The two cannot both hold. Options, in the agent's order of preference:

1. **Accept ranked-suggestion recognition as the M5 evidence**: cross-source recognition means "the
   right identity is ranked first with a clear similarity score and one confirmation places it", and
   TST-057/the gate are written that way. Automatic matching stays off until option 2 succeeds.
2. **Earn automatic matching with better evidence**: grow and *verify* the evaluation set (the labels
   are unverified Commons categories, and the false accepts scored up to 0.62, far above the
   different-person tail, which suggests label error as much as model error). A small label-review
   tool would let the owner confirm or correct the doubtful pairs in minutes; the measurement is then
   re-run, and a policy that passes the owner's conservative rule enables matching. Needs the owner's
   time and, for more photographs, a download.
3. **Change the definition of done** for TST-057 by owner decision (not recommended: it weakens the
   row).

Steps 1 to 7 do not depend on calibration. Step 5's permanent-delete tests also assert that retained
Evidence exposes no deleted biometric material, and step 7's face search keeps ranking independent of
the matching thresholds and persists nothing.

## 4. Smaller follow-ups (no owner input needed)

- Re-measure the operating point on CUDA and record the provider in the report (vectors differ in the
  fifth decimal; expect no change).
- A `docs/guides` how-to for installing the GPU runtime and the model package from scratch.
- Update the learning guide's [built]/[designed] markers as each step lands (Part 12.6).
- The unconstrained model columns (CONTEXT question 11) stay open; nothing in M5 forces them.

## 5. How the agent works unattended

- One branch at a time; the stash with the real host work is restored for step 2.
- Merge only with the full gate green, an independent review answered, and CI green on the exact head.
- Stop and write down the question (instead of guessing) on: a conflict between code and a spec, a
  security or erasure doubt, a failing check that is not understood, anything needing the owner's
  photographs, or any new dependency or model.
- Report in a few lines at each merge; questions are batched in section 3 and the PR comments.

## 6. Questions waiting for the owner (batched)

1. When R5 begins: the label-review dataset requirements (how many photographs, from where, who
   reviews, the review rules). The agent asks then.
2. Nothing else is outstanding.
