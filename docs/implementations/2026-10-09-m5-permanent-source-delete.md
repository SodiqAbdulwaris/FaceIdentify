# M5 step 4b: permanent deletion of a source

- **Date:** 2026-10-09
- **Milestone / tracker IDs:** M5 step 4b; TST-059 (second part)
- **Status:** done; forget (4c) follows
- **Commits:** PR to be recorded when merged

## What changed

- **Use case** `backend/app/sources/permanent_delete.py` (`PermanentSourceDeletion`), in the order the
  specs ask for (identity model §40-§45, §57; persistence §4.2; API §60): intent, then bytes, then
  vectors, then one finalizing transaction.
  1. *Intent* (one transaction): a `RECYCLED` Source becomes `DELETING`, and every managed artifact it
     owns (original, thumbnail, each face crop) gets its deletion intent. A referenced original is only
     marked `DELETED`: the user's file is never touched.
  2. *Bytes*: each artifact's bytes are removed and its row finalized (`complete_artifact_deletion`,
     new in `artifact_storage.py`; a failure leaves `DELETE_FAILED`, which startup recovery retries).
  3. *Vectors*: every face vector of the Source goes through `RepresentationEraser` (SQLite row, index
     files and write-ahead log).
  4. *Finalization*, only when 2 and 3 are done, in one transaction: delete the evidence links and index
     operations of those representations, the occurrences, the observations (their representations go
     with them), then the runs (their checkpoints, segments and jobs first) and their now-unreferenced
     configuration snapshots (CONTEXT question 29). A guard refuses while any vector is left.
- **What stays.** Evidence is never deleted: it keeps kind, source id, scores, ids and payload. It loses
  only what pointed at deleted material: its links to the deleted representations, the candidate's
  `representation_id` (the candidate keeps its identity and similarity), and its run id. A named
  identity stays `ACTIVE`; an `ACTIVE` identity with no occurrence and no person left becomes
  `DELETED`. The Source row stays as a tombstone (`DELETED`, name "Deleted image", no media facts,
  no thumbnail) so retained Evidence still resolves its `source_id`; `GET /sources/{id}` answers
  `404` for it.
- **Route** (API §5.7): `POST /api/v1/sources/{id}/permanent-delete`. `204` when nothing but the
  tombstone is left, `202` with `{state: DELETING, outstanding: [...]}` when part could not finish
  (a locked file); `404 SOURCE_NOT_FOUND`; `409 SOURCE_NOT_RECYCLED` (move it to the bin first);
  `409 SOURCE_BUSY` (a run is in flight). A repeat is harmless and announces nothing; a change is
  announced as `source.updated`.
- **Restart.** `resume()` runs in the backend's startup, after recovery and before any request: it
  carries on every `DELETING` Source and, if one cannot finish, reports the recovery capability as
  `DEGRADED` (`Backend.deletions` keeps the reports). Every step is repeatable.
- **Front end.** `PermanentDelete` (a card in the Recycle bin and the source page of a recycled image):
  it asks in place ("The image and its faces are removed and cannot be brought back. People you have
  named stay."), shows the API's message on a refusal and a note when the deletion is only partly done.
  `ApiClient.command` answers a request that is `204` or carries a body. The contract is regenerated.

## Changes after the independent review

The review (Codex, on the PR) found real defects; all were fixed:

- **The log.** Finalization sets the durable `wal_truncation_owed` marker and the log is truncated
  before the deletion is reported done (landmarks, quality data and payloads of the deleted rows sat in
  earlier pages of the log). A repeat of the request, or the next start, settles an owed log. A bug
  found while testing it: the settle ran while a read session was still open, which blocks the
  truncation.
- **Intent hides the faces at once.** The same commit that records the intent queues the vectors for
  erasure (so recognition cannot match them), moves a `DELETED`-state representation, which keeps its
  vector and which the eraser ignores, to `ERASING`, and marks the occurrences and observations
  `DELETED` (every reader shows only `ACTIVE`).
- **Nothing is skipped.** A `PENDING` artifact gets its intent too; its staged file goes with it;
  completion is refused while any owned artifact is not `DELETED`.
- **Two requests at once** are harmless: finishing an already finished artifact or Source is a no-op.
- **Long histories**: statements over snapshots and identities are chunked.
- **Live hints.** The "who it resembled" hints on unplaced faces now need a still-existing face behind
  the recorded candidate (members read from the candidate's details) and use the best surviving
  similarity, so a deleted or erased face no longer ranks anyone.
- **A surviving identity gets a new representative face**; the metadata of deleted files (name, type,
  hash, size) is cleared; `changed` is true only for a real transition.
- **Front end.** Deleting removes everything fetched for the image (its bytes included) and refreshes
  the runs; the image hook hides cached bytes when disabled; focus moves to "Keep it", Escape returns
  it to the button, and the warning is the dialog's description.

A second review (same reviewer) found more, and these were fixed too:

- A `DELETED`-state representation could carry an ordinary `REMOVE` that only took its key out of the
  live index (the file keeps the bytes); intent now forgets every `REMOVE` it had, so erasure queues
  and applies its own by a rebuild.
- Startup recovery marks an artifact `DELETED` before it tries its staged file, so a locked `.part`
  file was skipped: deletion now removes the staged files of every owned managed artifact itself and
  stays unfinished while one cannot be removed.
- Deleting from an open source page leaves the page (a mounted observer keeps what it loaded after the
  cache is cleared), which releases the picture and its object URL.
- Completing an artifact's deletion tolerates the other request finishing at any step, including after
  this one's own failure; `changed` is reported only by the request whose guarded write finalized the
  Source.
- A hint needs the supporting face to still belong to the person the candidate was for (a correction
  or split may have moved it).
- The index coordinator's attempt-count query is chunked; a test lowers SQLite's variable limit to
  prove it (the earlier test only covered the snapshot statements).
- Focus returns to the button after a refused deletion.

A third review found five more, also fixed:

- The deleted card in the Recycle bin hides itself at once (its picture is released), whatever the list
  refetch does; a `202` warning from the source page travels to the library with the navigation.
- Settling an artifact (failure or finish) runs in the unit of work, so a busy database is retried; the
  decision is made inside the write lock.
- Beginning a deletion bumps the revision of every active identity that loses a face, so a merge or
  split prepared earlier is refused.
- The hint-support query is chunked like the others (a test lowers SQLite's variable limit).

Not changed, and why: a referenced original's `external_path` stays on the tombstone because the
artifact `location` CHECK requires it (see the question below). The 820-line test commit is one new
module for one use case.

## Agent designs (confirmed by the owner on 2026-10-09, with safeguards)

The owner confirmed all of these on 2026-10-09: delete only from the Recycle bin, the detached audit
log, and the `204` / `202` / `409` answers, with the clarification that a pending (`202`) Source is
unreachable through every route, retries are idempotent and what is owed stays visible. Revision `0010`
(clear a deleted referenced original's path; a non-biometric `SOURCE_PERMANENTLY_DELETED` history entry)
was approved to be built with step 4c.

- Only a *recycled* Source can be deleted for good (identity model §39: media first goes to the bin).
- Evidence rows are kept but detached (links and run id removed) rather than deleted; the run and
  snapshot are deleted as decided on 2026-10-01. `Evidence.source_id` keeps pointing at the tombstone.
- A `SOURCE_PERMANENTLY_DELETED` history entry is not written yet: the owner approved it (2026-10-09),
  and it comes with revision `0010` in step 4c.
- The tombstone keeps its row, so a `DELETED` Source's id stays resolvable; its name is replaced.
- The path of a *referenced* original stays on its artifact row for now, because the `location` CHECK
  demands an `external_path` for every referenced artifact. The owner approved revision `0010`
  (2026-10-09), which lets a `DELETED` artifact have none; it is built with step 4c. Managed artifacts
  keep only their id-derived storage key.
- A deleted face is never presented while the deletion is pending: its observations and occurrences are
  already marked `DELETED` (every reader shows only `ACTIVE`), and every source, run, job and face route
  answers `404` for a pending or finished deletion.

## Tests

- `tests/integration/test_permanent_source_delete.py` (36), on a real library (SQLite, USearch, managed
  files, restarts): only a recycled Source; busy; bytes, crop, thumbnail, faces, vectors, runs, jobs,
  snapshots gone, the other image untouched, and the vector's bytes found in no database, log or
  index file; repeat; referenced originals (available and missing) untouched; shared and lone
  identities; a named person survives; retained Evidence keeps provenance and exposes no deleted
  representation; crashes before finalization and during erasure finished by the next start; bytes
  that cannot be removed, reported and retried; guard edges.
- `tests/integration/test_api_source_permanent_delete.py` (14 after the visibility work of PR 157): the
  route, its refusals, a face's identity disappearing, `202`, the next start finishing a cut-short
  deletion, a deletion still owed at start being reported as degraded recovery, a source with a pending
  deletion gone from every source, run, job and face route (and `/readiness` degraded), and commands
  that lose a race with the deletion's first transaction answering `404`, not their own refusal.
- Mutations (backend): 47 guards and statements were broken one at a time (26 before the review, 21
  after); every survivor (a redundant `continue`, an untested thumbnail clear, an untested artifact-state
  guard, a state set that only AVAILABLE exercised, a redundant representation delete, an untested
  settle of an owed log, a race guard, two hint rules) was removed or closed by a test.
- Front end (11 new, 161 total): ask first and cancel, focus and Escape, forgetting what was fetched, the
  partial notice, the refusal, cached bytes of an unavailable image, and the source page; thirteen
  mutations, one survivor (the card offering it outside the bin) closed by an assertion.
- `test_api_corrections.py` gains seven tests for the live hints; `test_index_operation_repository.py`
  one for the bounded query.

## Verification

- Front end: `npm run typecheck`, `npx oxlint --deny-warnings`, `npm test` (161 passed), `npm run build`.
- Backend gate: see the PR.

## Open issues / follow-ups

- Step 4c (`ForgetIdentity`, "forget person") is the only operation that removes an identity's
  biometric memory while the source stays; it reuses the same eraser.
- Historical and name search (5a) must treat `DELETED` Sources as gone and `RECYCLED` ones as marked.
- Machine-unlearning is out of scope (identity model §42.1): a model already trained on a deleted face
  is not retrained.
