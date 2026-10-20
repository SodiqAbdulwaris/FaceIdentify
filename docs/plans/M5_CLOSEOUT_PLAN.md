# M5 close-out plan

**Status:** approved by the owner on 2026-10-17; in progress. This plan orders the
remaining M5 work without changing the scope or decisions in
[`M5_PLAN.md`](M5_PLAN.md).

## Goal and boundaries

Close M5 only when every remaining definition-of-done criterion has evidence. Automatic
acceptance remains the owner-approved `buffalo-l-verified-match-v1` policy (threshold 0.45,
margin 0.10, no automatic new identity). This plan does not change a threshold, policy,
model, dependency, specification, or M6 scope.

## Ordered work

### 1. Resolve the active PR queue

1. Re-review PR #213 at its exact current head, check its exact-head CI, and merge only with the
   owner's explicit merge instruction. If it merges, close #175 only if the PR's accepted scope is
   met; leave #221 open for M6's one-worker-process follow-up.
2. Re-review PR #219 at its exact current head because the previous review findings were fixed
   afterwards. Check the API and desktop consumers show automatic placement and preserve the
   established correction paths. Merge only with the owner's explicit merge instruction.

**Acceptance criteria:** each PR has an independent read-only review recorded against the exact
head, every review finding is answered, all required CI checks are green on that head, and the
owner authorizes its rebase merge. The two PRs are handled one at a time.

**Progress (2026-10-20):** PR #213 merged on 2026-10-19. Its 2026-10-17 review had found that
`ClientPool.close()` could stop a worker after `execute()` but before `PerceptionClient` attached
and released its shared-memory result; the PR added active-operation draining and a deterministic
shutdown-versus-`represent()` regression before it was re-reviewed and merged. PR #219 is next.

### 2. Record the live automatic-acceptance check (TST-057B)

Run the real host with the owner-installed policy file in `local-models/state/policies/`, using an
isolated temporary library. The run must read the installed policy and must not create, replace or
otherwise write it. It proves the recorded version is active, a same-person face is automatically
placed, a different person abstains, and the resulting placement is visible and correctable through
the existing application flow.

**Acceptance criteria:** the provider and fallback, policy version, automatic placement,
stranger abstention, and correction outcome are recorded in an implementation entry and the
TST-057B tracker row. Tests and user data stay isolated from the live library.

### 3. Add the missing correction end-to-end proof (TST-054)

Extend the existing desktop workflow in `frontend/e2e/workflow.e2e.tsx` with one correction flow.
It must operate through the visible application, then restart or reload and prove the authoritative
placement persists. Keep the existing API and component coverage; this task supplies the missing
end-to-end layer.

**Acceptance criteria:** the new test is deterministic, uses the existing harness and no wall-clock
coordination, and the relevant desktop and frontend checks pass.

### 4. Resolve evidence-only tracker rows

1. Review TST-044 against the 48-identity verified operating point and DirectML re-measure. Mark
   it `PASSING` only if the criterion's reproducible-baseline requirement is met; otherwise record
   the exact missing evidence.
2. Record the owner's decision that local-only real-weight evidence closes TST-038 and TST-039.
   The weights remain outside CI; the decision relies on verified provenance and recorded local real
   host evidence rather than pretending CI ran them.

**Acceptance criteria:** each status change cites concrete tests or reports, and no superseded
`BLOCKED` or pre-install wording remains in the active tracker row.

### 5. Reconcile documentation and issues

After the preceding evidence lands, make one docs-only reconciliation PR covering
`.agents/CONTEXT.md`, `PROJECT_STATUS.md`, `TESTING_IMPLEMENTATION_TRACKER.md`, the relevant M5
plans, the implementation log and a dated implementation entry. It removes only claims that have
become demonstrably stale.

Issue handling is individual: #174 remains open for its documented residual race; #180 and #221
remain M6 work; #173, #176, #181 and #183 remain open unless their own criteria are independently
met. Verify #66 against its actual UnitOfWork work before deciding whether it is stale.

**Acceptance criteria:** the status documents agree, every retained issue has a current reason,
and no deferred M6 work is presented as complete.

## Verification checkpoints

After each implementation PR: run its focused checks, an independent read-only review, and
exact-head CI before a merge request. Before declaring M5 complete: run the applicable full backend
and frontend gates, verify CI on merged `main`, then audit every item in `M5_PLAN.md` section 5.

## Dependencies and risks

| Dependency or risk | Handling |
|---|---|
| Shared status documents conflict across PRs | Merge and rebase one PR at a time; reconcile status last. |
| Real weights and owner policy are machine-local | Use only ignored local state, isolated temporary libraries, and record real output. |
| Automatic match can be wrong | Keep Evidence, correction, reassignment, split and new-person paths testable; do not alter the approved policy. |
| M6 scope leaks into M5 | Leave #180 and #221 open until the owner approves M6. |
