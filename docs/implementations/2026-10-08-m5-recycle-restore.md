# M5 step 4a: recycle and restore a source

- **Date:** 2026-10-08
- **Milestone / tracker IDs:** M5 step 4a; TST-059 (first part)
- **Status:** done; permanent delete (4b) and forget (4c) follow
- **Commits:** PR to be recorded when merged

## What changed

- **Routes** (API sections 5.5 and 5.6): `DELETE /api/v1/sources/{id}` recycles (`204`) and
  `POST /api/v1/sources/{id}/restore` restores (`200` with the Source). Both are idempotent: a repeat
  changes nothing and announces nothing. A change publishes `source.updated`.
  - `409 SOURCE_BUSY` when a processing run of the Source is `PENDING`, `RUNNING`, `PAUSING`,
    `PAUSED`, `CANCELLING` or `FINALIZING`: acceptance needs an `ACTIVE` Source, so the run would
    fail at its end (`SourceBusyError`, `recycle_source`).
  - `409 SOURCE_STATE_CONFLICT` when the Source is in no state that can move (for example `DELETING`)
    or its original is being or has been deleted.
  - `404 SOURCE_NOT_FOUND` for an unknown id.
  - The revision the lifecycle functions require is read inside the same write, so a client sends
    none.
- **Memory stays.** Recycling touches only the Source row. Its observations, representations,
  occurrences, evidence and the identities made from them are untouched, so the counts do not change.
  `OccurrenceSummary` gains `source_recycled` (true for a face of a recycled Source); the OpenAPI
  document and TypeScript types are regenerated.
- **The library list** already took `state=ACTIVE|RECYCLED`; it is now what the Recycle bin view uses.
  A recycled Source is not processed (the process route already refused a non-`ACTIVE` Source).
- **Screens.** The library has a Library / Recycle bin switch; cards offer Recycle (library) or
  Restore (bin, with no processing); the source page has a control to move the image to the bin or
  restore it, and a note when it is there; a person's faces from a recycled image say "From an image
  in the recycle bin" and are still counted. `ApiClient.delete`, `recycleSource`, `restoreSource`.
- The agent design (idempotent repeats, the busy refusal, the error codes) is recorded in the API
  spec as an agent design awaiting the owner's confirmation.

## Tests

- `tests/integration/test_api_source_lifecycle.py` (13): recycle hides from the library list and
  shows in the bin with its bytes still served and one `source.updated`; restore and repeats;
  unknown id; the busy refusal for five run states and recycling after the run ends; an original
  being deleted; a source in `DELETING` cannot be restored; a recycled source cannot be processed;
  its faces stay in identity and source occurrence lists marked recycled while the identity's counts
  are unchanged, and unmarked after restore. Six backend mutations (idempotence, swapped target,
  announce always, busy not mapped, busy guard off, marker off) each fail a test.
- Front end (5 new, 149 total): moving to the bin and the refreshed library; the bin view with
  restore and neither import nor process; a refusal shown as a notice; the source page control and
  note; the marker on a person's faces with counts intact. Six mutations; one survivor (the bin offering
  Recycle) closed by a new assertion. The test harness now answers `204` without a body, as served.

## Verification

- Front end: `npm run typecheck`, `npx oxlint --deny-warnings`, `npm test` (149 passed), `npm run build`.
- Backend gate: see the PR.

## Open issues / follow-ups

- Historical and name search (step 5a) will include recycled-source occurrences, marked and
  filterable by `source_recycled`.
- A restore after the original file disappears still succeeds (the file's availability is a separate
  state); the library card shows "The file is missing" as before.
