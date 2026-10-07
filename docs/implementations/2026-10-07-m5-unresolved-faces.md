# M5 step 2b: placing a face recognition declined to place (issue #79)

- **Date:** 2026-10-07
- **Milestone / tracker IDs:** M5 step 2 (TST-054, third part); issue #79
- **Status:** done
- **Commits:** PR to be recorded when merged

## What changed

- `resolve_representation` (`backend/app/identities/corrections.py`): an accepted ABSTAIN leaves an
  identity-less ACTIVE representation, no identity, no occurrence and `RECOGNITION_ABSTAINED`
  Evidence. Resolving it gives the representation its identity (an existing one, or a new unknown
  one created ACTIVE), creates the face's occurrence (IMAGE, ACTIVE, with its observation as
  member), and adds one `USER_CORRECTION` Evidence row (`RESOLVE` or `RESOLVE_NEW`) that cites the
  abstention it resolves (exactly one abstention linked to the face as its SUBJECT is required: none,
  or two, is refused). The abstention is never rewritten. The representation is already in the
  index under its `ann_key`, so no index operation is written. A representation that is retired,
  already owned, whose observation is no longer current, or whose face already has an occurrence
  (as representative or as a member) is refused and nothing is written.
- Routes: `GET /sources/{id}/unresolved-faces` (each face, its box and up to three people its
  abstention compared it with, best similarity first, each person once, only active identities) and
  `POST /representations/{id}/resolve` (`identity_id` null for a new person; `404 FACE_NOT_FOUND`,
  `404 IDENTITY_NOT_FOUND`, `409 FACE_NOT_RESOLVABLE`). A resolution publishes `occurrence.updated`.
- Frontend: the source screen shows "Faces to place": each face cropped, with a button for each
  person it resembled ("This is Bob (38% alike)"), "This is someone new", and a picker for anyone in
  the library. The picker is shared with the correction panel (`usePeopleChoices`).

## Why

M5 plan step 2. With the owner's rule that recognition abstains when it cannot reach 99% precision,
many real faces will end up unplaced: without this they would be invisible and stuck.

## Decisions

> **Decision 2026-10-07:** The route names and the "likely" hints are the agent's design. The API
> spec requires corrections to leave history (section 7) but defines no route for them; these are the
> smallest routes the owner-approved M5 scope needs, they are in the generated OpenAPI contract, and
> the owner is asked to confirm them (no spec text was changed). The similarity is shown as a percentage of the raw cosine, labelled "alike", never
> as a probability or a confidence: the policy is uncalibrated in that sense (owner decision).

## Verification

- `tests/integration/test_corrections.py` (now 27) and `tests/integration/test_api_corrections.py`
  (now 13): the resolution of each kind, the evidence and the citation, nothing written on a refusal,
  hints ordered, deduplicated, limited and active-only, superseded observations not listed. Mutation
  checks on the use case (six) and the routes (five): two survivors in each were closed by tests and
  re-checked. 100% line and branch coverage of both modules.
- Frontend: 6 tests (`UnresolvedFaces.test.tsx`), `npm test` 133 passed, typecheck and `oxlint` clean.
- Full backend gate: see the PR. Review (Codex, read-only), all seven findings answered: the
  single-SUBJECT-abstention rule, the membership-aware occurrence guard, the current-observation
  rule, the SUBJECT-only hint lookup, an error state for the list, a busy-commit retry test, and the
  route-design note above.

## Open issues / follow-ups

- The hints come from the candidate evidence of the abstention; they are not recomputed, so they
  can name a person who has since been merged away (such a person is filtered out as not active).
