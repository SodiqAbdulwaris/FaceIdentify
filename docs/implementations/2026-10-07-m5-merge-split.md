# M5 step 3: merging identities and splitting faces off one

- **Date:** 2026-10-07
- **Milestone / tracker IDs:** M5 step 3 (TST-058, API and UI part); CONTEXT question 16
- **Status:** done, except the `IdentityState.SPLIT` removal (a separate schema-cleanup revision, see
  follow-ups)
- **Commits:** PR to be recorded when merged

## What changed

- **Occurrences move** (CONTEXT question 16, owner decision 2026-10-07). `merge_identities` now
  moves the loser's ACTIVE occurrences to the survivor in the same transaction and names them in the
  `IDENTITY_MERGED` Evidence (`moved_occurrence_ids`); a survivor with no representative face takes
  the loser's. `split_identity` moves the occurrences whose supporting representations are all
  selected (named in the `IDENTITY_SPLIT` Evidence), gives the new identity a representative face, and
  refreshes the source's. The shared `refresh_representative` and `occurrence_support` helpers live in
  `identities/use_cases.py` (the correction use cases use the same helper).
- **A mixed-support occurrence is an explicit conflict** (owner decision): when a selection takes some
  of the representations an occurrence rests on and not others, `split_identity` raises
  `SplitConflictError` naming those occurrences, before writing anything.
- **Atomicity.** Each is one use case in one `UnitOfWork` transaction: the identity states and
  lineage, representations, occurrences, person link, Evidence and representative faces commit
  together or not at all; the index is untouched (ownership is not part of it).
- **Routes** (`routes/identity_changes.py`): `POST /identities/merge` (`identities` with the
  revisions the caller saw, and the preferred survivor; 422 `INVALID_MERGE`, 409 `IDENTITY_CHANGED`,
  404 `IDENTITY_NOT_FOUND`) and `POST /identities/{id}/split` (`occurrence_ids`; 422 `INVALID_SPLIT`,
  404 `OCCURRENCE_NOT_FOUND`, 409 `SPLIT_CONFLICT` with the conflicting `occurrence_ids`). Each
  publishes `identity.updated` after the commit. `IdentitySummary` carries its `revision`.
- **Person conflict on merge** (the plan's "to verify"): the existing rule stands and is now shown to
  the user before they confirm: the survivor's own person link wins and the loser's is carried over
  only if the survivor has none.
- **Frontend:** the person screen has "This is the same person as…" (choose a person, read what will
  happen, confirm; it goes to the surviving person) and a checkbox on each appearance with "These are
  someone else" (splits the chosen faces into a new person and goes to them); a conflict is shown
  with a button that adds the faces involved to the choice.

## Why

M5 plan step 3 and the owner's decisions of 2026-10-07: occurrences move with merge and split;
mixed support is a conflict; merge and split are atomic across entities.

## Decisions

> **Decision 2026-10-07:** The route names and shapes (`/identities/merge`, `/identities/{id}/split`
> by occurrence) are the agent's design: the API spec gives the conceptual merge request (identity
> ids and a preferred identity) and says a split "identifies selected observations/evidence", and
> neither is more precise. They are in the generated contract; the owner is asked to confirm them.

- Splitting is chosen by face (occurrence) in the UI and API, and translated to representations in the
  backend; the use case keeps its representation-level interface.
- Merging more than two identities is one request that merges each other identity into the survivor
  in the same transaction.

## Verification

- `tests/integration/test_identity_merge_split.py` (42): occurrences move on merge (active only, not
  a run's private output), the evidence names them, the representative face rules, a split moves the
  occurrences of the selected representations, the conflict writes nothing and resolves when the
  selection is completed, a representation with no occurrence can be split off, an occurrence known
  only through membership rows. Six mutations of the new code; the one survivor is an equivalent
  mutant (the conflict check already makes "all" and "any" the same), so the code was simplified.
- `tests/integration/test_api_identity_changes.py` (11): 100% of the module, four guard mutations
  closed by tests.
- Frontend: `MergeSplit.test.tsx` (6): `npm test` 141 passed, typecheck and `oxlint` clean.
- Full backend gate: see the PR.

## Open issues / follow-ups

- Removing `IdentityState.SPLIT` (CONTEXT question 15) is a schema revision (`0009`) in its own small
  PR; nothing assigns the value today.
- The identity list still shows one card per identity; a Person with several identities appears once
  per identity.
