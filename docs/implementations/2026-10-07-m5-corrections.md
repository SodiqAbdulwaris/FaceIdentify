# M5 step 2a: correcting a recognised face

- **Date:** 2026-10-07
- **Milestone / tracker IDs:** M5 step 2 (TST-054, second part)
- **Status:** partial: confirm, move and separate are built; resolving an ABSTAIN face (issue #79) is step 2b
- **Commits:** PR to be recorded when merged

## What changed

- `backend/app/identities/corrections.py`: `confirm_occurrence` and `reassign_occurrence`. Each writes
  one `USER_CORRECTION` Evidence row (action `CONFIRM`, `REASSIGN` or `SEPARATE`; the occurrence, the
  identities and the representations it moved; the representations cited as `SUBJECT`). Ownership
  moves only: the occurrence and the ACTIVE representations of its observations that its identity
  owned. `ann_key` and the index are untouched and no `IndexOperation` is written. A separated face
  gets a new identity created ACTIVE with a `SPLIT_FROM` lineage edge citing the correction. The
  first identity stays ACTIVE even if this was its last face, and its representative face is never
  one that has left it. `expected_identity_id` (the identity the user saw the face under) makes a
  stale view `StaleRevisionError`.
- Routes (`backend/api/routes/corrections.py`): `GET /occurrences/{id}`, `POST
  /occurrences/{id}/confirm` and `/reassign` (`identity_id: null` separates into a new person).
  `404 OCCURRENCE_NOT_FOUND`, `409 OCCURRENCE_MOVED`, `409 FACE_NOT_CORRECTABLE`. Each committed
  change publishes `occurrence.updated`; a refusal publishes nothing. `occurrence_summaries` in
  `routes/memory.py` is now shared by the list and the correction replies.
- Frontend: the source screen lists each face with "Check this face": confirm, "someone new", or a
  chosen existing person; the correction panel reports a stale face and any other failure. The
  `occurrence.` events refresh every screen that shows a name.

## Why

M5 plan step 2. Owner decision 2026-10-07: corrections need no new schema; confirm is Evidence only;
reject and reassign move the face with Evidence; there is no cannot-link constraint.

## Decisions

> **Decision 2026-10-07:** The API spec says corrections must leave history but defines no route for
> them. The two commands and their names are the agent's design, flagged for the owner.

- A correction does not stop recognition choosing the same identity for a similar face again (no
  cannot-link). The UI says nothing about that yet; flagged.
- Confirmation does not yet change how recognition treats the face.

## Verification

- `tests/integration/test_corrections.py` (16): the evidence, the move, the separation and its
  lineage, the representative face, a refusal writes nothing, a stale view, retired and unowned
  representations stay; 100% line and branch coverage of the module; nine mutations of the guards,
  one survivor (the representation state filter) fixed by a test and re-checked.
- `tests/integration/test_api_corrections.py` (7), 100% of the route module.
- Frontend: 5 tests (`FaceCorrection.test.tsx`), `npm test` 125 passed, typecheck, `oxlint` and build clean.
- Full backend gate: see the PR.

## Open issues / follow-ups

- Step 2b: faces the system abstained on (identity-less, no occurrence), issue #79.
- Merge moving occurrences (step 3) will use the same ownership rules.
