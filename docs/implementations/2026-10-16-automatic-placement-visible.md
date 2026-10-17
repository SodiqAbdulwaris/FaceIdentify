# M5: an automatic match is told apart from a confirmed face (TST-057B)

- **Date:** 2026-10-16
- **Milestone / tracker IDs:** M5 track R; TST-057B (proposed `PASSING`, owner to confirm)
- **Status:** done, with tests; review recorded on the pull request
- **Commits:** PR to be recorded when merged (`feat(api): say how a face was placed`)

## Audit (owner request 2026-10-15/16)

Questions, and what the code did before this change:

| Question | Finding |
|---|---|
| Is an automatically accepted face distinguishable from a confirmed one, in the API and the UI? | **No.** `OccurrenceSummary` carried no origin, so the screens showed an automatic match exactly like a person's decision. **Fixed here.** |
| Can the owner see and undo it? | Yes. `POST /occurrences/{id}/confirm` and `/reassign` (to another identity, or `identity_id: null` to separate it) and the identity page's split and merge all work on a matched face; each writes `USER_CORRECTION` Evidence and rewrites nothing. Now covered by a test on a matched face. |
| Does Evidence record the automatic decision with similarity and margin? | Yes. `IDENTITY_MATCHED` Evidence carries the outcome, reason, candidates with similarity, `margin` and the policy (version, threshold, margin). Now asserted end to end over HTTP. |
| Do faces processed before the policy change stay abstained? | Yes. Nothing re-decides an abstention; a restart under the new policy leaves it, its Evidence and its missing occurrence untouched. Now asserted. |

A consequence worth knowing (not a defect, the margin rule working): while an old abstained face is
still unresolved it is a neighbour with no identity, as close to a new picture of the same person
as the founder is, so the margin is nil and the new face abstains as `AMBIGUOUS_CANDIDATES` too.
Resolving the old faces (or the owner confirming them) is what lets later pictures match.

## What changed

- `OccurrenceSummary` gains `placement` (`AUTOMATIC_MATCH`, `AUTOMATIC_NEW` for the first face of an
  empty library, `USER`, or `null` when no decision is recorded), `match_similarity` and
  `match_margin` (the margin is `null` with one candidate). It is read from the Evidence citing the
  occurrence's representative face as SUBJECT; any `USER_CORRECTION` wins over an automatic
  decision whatever the timestamps. The generated OpenAPI document and TypeScript types follow.
- `FaceCorrection` (source screen and identity page) says "Matched automatically (similarity score
  0.97, lead 0.31). Check it, and move it if it is wrong." for an automatic match, "Created
  automatically as a new person. Check it, and move it if it is wrong." for the first automatic
  identity, and "Checked by you." after a person's decision; the open panel says "matched
  automatically to".
- Tests: `tests/integration/test_api_automatic_acceptance.py` (development host under the approved
  point: marking, score, Evidence, confirm and separate, a face abstained before the change),
  `FaceCorrection.test.tsx`; `test_a_face_can_be_read_and_confirmed` now expects `placement: USER`
  after a confirmation (the intended change).

## Verification

`uv run ruff format --check . && uv run ruff check . && uv run mypy`, `uv run pytest`,
`npm run typecheck && npm run lint -- --deny-warnings && npm test && npm run build`: see the pull request.

## Real-model check under the installed policy

The live policy file equals `APPROVED_MATCHING` (compared as JSON); neither policy file was written (SHA-256 identical before and after; `local-models` was only read, through a junction in the worktree). `uv run pytest -m e2e tests/e2e/test_real_host.py -k approved_point`: 1 passed (real weights, CPU, private state with the same policy). The test now also asserts `placement == AUTOMATIC_MATCH` and a similarity at or above 0.45 on the matched photograph. The tracker row is proposed `PASSING`; confirming is the owner's.

## Open

No threshold, margin or policy changed. The real-model check and the how-to guide are separate entries.
