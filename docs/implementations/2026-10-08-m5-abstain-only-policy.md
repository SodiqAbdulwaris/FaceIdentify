# M5: the abstain-only policy made visible, and the owner's decisions built

- **Date:** 2026-10-08
- **Milestone / tracker IDs:** M5 track R (R4 follow-up); TST-044 (policy), TST-057 (precondition: wording and notice)
- **Status:** done
- **Commits:** PR to be recorded when merged

## What changed

- **Bounded similarity, enforced centrally.** `RetrievedCandidate.similarity` now holds a cosine to its
  own range, -1 to 1, so float rounding in an index can never produce a score above 1. That is what
  makes a `match_threshold` above 1.0 a reliable way to turn automatic matching off.
  `DecisionPolicy.automatic_matching` (true when the threshold is at most 1.0) names the idea;
  `MAX_SIMILARITY` is the one constant.
- **The run says so.** `PolicyProvenance` (in every processing-run response) gains
  `automatic_matching`, computed from the run's frozen policy. The OpenAPI document and the TypeScript
  types are regenerated. The notice in the layout (`PolicyNotice`) now shows **"Automatic matching
  disabled"** (with "Similarity scores are not probabilities") for such a run, alone or together with
  the uncalibrated-results text.
- **Wording.** The faces-to-place list says "similarity score" (two decimals), never "% alike";
  explains that a score is how close two faces look to the model and not the probability that they are
  the same person; and labels the buttons as ranked possible matches, highest score first.
- **Rename events.** `person.updated` carries the stable person id and the new revision
  (`data.revision`), never the name; clients refetch by REST.
- **Usefulness target.** The conservative evaluation rule judges the final half against the
  configurable `--minimum-recall` (default 0.5, owner decision 2026-10-08), replacing the predeclared
  0.25. Missing it disables automatic acceptance; it relaxes nothing.
- **Regression tests for the abstain-only behavior** (`tests/integration/test_api_development_profile.py`),
  through the real host over HTTP across a restart: the first face creates a persistent unnamed
  identity; an identical later picture is not matched or attached (no occurrence) and waits as a
  ranked unresolved face; a different picture creates no identity either; after a restart the
  identity and the waiting faces persist, a further identical picture is still not matched, and a
  manual "someone new" resolution still works.
- Owner decisions recorded as a dated note in `docs/plans/M5_PLAN.md` and `CONTEXT.md`.

## Decisions (final: the owner settled the open reading on 2026-10-08)

The owner ruled that **ABSTAIN does not mean NEW IDENTITY**: the first face of an empty library may
create an unnamed identity; once identities exist an unmatched face abstains and waits for manual
resolution; no identity is created for every unmatched face. The sections below are therefore the
rule, not an open question. Recorded in the identity and ML specs, `CONTEXT.md` and the plan, and
enforced by tests (below).

- The owner's decision 1 says automatic identity creation continues. The agent keeps it for the first
  face (nothing to compare with) and, after that, lets a face that has candidates **abstain** (ceiling
  -1.0), because the same owner text for R4 says scores below the threshold abstain rather than force
  an assignment, and creating an identity for every unmatched photograph would split one person into
  many. Manual "this is someone new" creates it (confirmed).
- The condition "scores bounded to [0, 1]" is met as the cosine's own range, -1 to 1 (a negative cosine
  is meaningful and the validators and evidence already allow it); nothing can exceed 1.
- A separate `auto_match_enabled` policy field is not built now, as the owner said.

## Verification

- Mutation tests: removing the similarity bound, forcing `automatic_matching` to true, ignoring the
  recall target, re-enabling matching in the regression policy, and raising the ceiling to 2.0 each
  fail a test.
- Front end: `npm run typecheck`, `npx oxlint --deny-warnings`, `npm test` (144 passed); full backend
  gate results are in the PR.

## Open issues / follow-ups

- The real host profile (parked) will read the measured policy file; until then the application runs
  on the development profile, whose demo policy can match.
- Review (Codex) found six points, handled in follow-up commits: the creation-scope clarification above
  (documented, not a behavior change; see the identity spec note), evaluation cosines now bounded,
  `--minimum-recall` validated as a finite share, the regression test now asserts the cited
  abstention is the resolved face's own and that every abstention is unchanged by the resolution,
  the rename-event test compares revisions with the REST responses, and the status documents are
  updated. The creation-scope reading is the one point the owner may want to confirm.
