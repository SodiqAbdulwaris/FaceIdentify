# Decide Q25 and Q26: erasure and startup recovery

- **Date:** 2026-10-01
- **Milestone / tracker IDs:** M2 (TST-030, TST-031); decisions only, no code
- **Status:** done (documents); the implementation is tracked in GitHub issues
- **Commits:** PR (number added when opened): `docs(specs): decide erasure and recovery of paused and
  cancelling work`, `docs: record the Q25 and Q26 decisions`

## What changed

The owner approved CONTEXT open questions 25 and 26 on 2026-10-01 with the recommendations recorded
there, and added three requirements: **queued erasures are excluded from retrieval at once, old index
generations containing erased vectors are securely retired, and startup recovery is idempotent.**
Specs and test requirements now say so, each spec edit marked "Decision 2026-10-01":

- `docs/specs/PERSISTENCE_IMPLEMENTATION.md`
  - 6.2: the representation state `ERASING`, and the two-step erasure rule.
  - 23: eligibility, and retiring index generations.
  - 28: recovery rows for `PAUSING`, `CANCELLING` and `ERASING`; idempotence stated as a property.
- `docs/specs/IMPLEMENTATION_ARCHITECTURE.md` 23.2, 23.6, 23.8: matching notes.
- `docs/strategy/TESTING_STRATEGY.md`: new INDEX-03 (queued erasure excluded from retrieval at once),
  INDEX-04 (superseded generations retired), INDEX-05 (erasure and the coordinator do not race), PER-07
  (erasure is crash-safe); PER-06, the recovery
  test section and the deletion note extended.
- `docs/plans/TESTING_IMPLEMENTATION_TRACKER.md`: TST-030 and TST-031 carry the decided requirements.
- `.agents/CONTEXT.md`: Q25 and Q26 recorded as decided; Q24 decided; Q17-Q19 deferred to their
  milestones; Q20, Q21, Q23 and Q27 recorded as agreed provisional directions to validate when their
  work begins.

## The decisions

**Q25, erasure.** Two steps. Step one, one transaction: `ACTIVE` -> `ERASING` and a `REMOVE` is queued.
Step two, only when the `REMOVE` is `APPLIED`, the generation without the vector is persisted and every
superseded and quarantined generation file is verifiably gone: `ERASING` -> `ERASED`, clearing vector and
key. Bulk forget does step one for all, one rebuild, then step two for all. Quarantined generations have
no time-based retention and are deleted when an erasure in their space finishes.

**Q26, recovery.** A job or run found `PAUSING` becomes `PAUSED`; one found `CANCELLING` becomes
`CANCELLED` (partial output stays private). A `RUNNING` job stays `INTERRUPTED`, never requeued. The rest
of Q26 (`FINALIZING`, pending output without a final checkpoint, runtime installs) waits for M3.

**Q24.** `Source.UNAVAILABLE` stays unassigned; a missing original is derived from the artifact.

## Design points worth knowing

- **`ERASING` is the new piece, and it is mine.** The owner asked that a queued erasure be excluded from
  retrieval immediately and that recovery be idempotent. With no durable marker between "queued" and
  "cleared", startup recovery cannot tell an erasure from an ordinary `REMOVE` (a deactivation), and
  eligibility would have to be checked against the operation queue everywhere. A representation state
  gives both at once: `ERASING` is not `ACTIVE`, so the coordinator's rebuild source (which selects `ACTIVE`
  only) already excludes it, recognition revalidation will once it resolves candidates at representation
  level (it does not yet; see Review), and recovery finds work by state.
  It is a CHECK change on `representations`, so it needs an Alembic revision, which is also the
  populated-database, batch-mode migration that Q18 asks for. The owner approved the two-step flow; this
  marker is how I made it durable and is flagged for validation when TST-031 starts (issue below).
- **"Securely retired" is verified deletion, not physical erasure.** TESTING_STRATEGY section 11 already
  says logical deletion is not a guarantee of physical erasure from SSD storage; the new text repeats it
  rather than overpromise.
- **A gap this surfaced, not decided:** the erased vector's bytes were also in SQLite (the `vector`
  blob) and may linger in WAL or free pages after step two. Whether to enable `PRAGMA secure_delete`
  and/or checkpoint after an erasure is a separate decision, raised as an issue.
- **The coordinator rule changes when TST-031 is built:** a `REMOVE` will not be `APPLIED` while a
  superseded generation of the space remains. Today only the keyless-`REMOVE` rebuild requires that. The
  keyless rebuild stays as a safety net.

## Review

Independent review by Codex CLI (`codex exec -s read-only`, disposable worktree): request changes,
four findings, all checked against the code and all correct.

| Finding | Resolution |
|---|---|
| `ERASING` is not excluded by the existing candidate revalidation: `resolve_recognition_candidates` takes identity ids and checks only `Identity.state`, so a stale index could return an `ERASING` vector for an active identity | Confirmed. My claim that every existing eligibility check already excludes `ERASING` was true only of the coordinator's rebuild source. The spec now requires revalidation to resolve each `ann_key` to its representation row (same space, `ACTIVE`, active identity), says plainly that this step is not built yet, and INDEX-03 must exercise a stale index holding the vector |
| No fence between the coordinator and the erasure transition; `append_batch` deletes a pending `ADD` the coordinator may be settling | Partly a real bug, partly a wrong remedy. The ordering the reviewer wants already exists and is now stated: the coordinator is the sole writer and serializes passes, so an in-flight `ADD` finishes before the `REMOVE` queued by step one is claimed, and retrieval is excluded by revalidation meanwhile. **The bug is real:** `_settle` indexes `seen[operation_id]` and raises `KeyError` for an operation deleted meanwhile. Fixed in a separate PR (#43); INDEX-05 now tests the race, a second erasure, bulk forget, reactivation and merge/split |
| "Every recovery step" and "a repeat is a no-op" overstate recovery: startup requeues every `FAILED` index operation, so a persistently failing one changes on every start | Confirmed (the requeue docstring says one fresh set of attempts per call). The claim is narrowed in the persistence, architecture and strategy text: after one completed run a second is a no-op; a condition that keeps failing externally is retried once per start, bounded, and reported as unresolved, not claimed absent |
| The requirements omit decisive windows: a crash after the `REMOVE` is `APPLIED` but before `ERASING` -> `ERASED`; a locked superseded or quarantined file; recursive quarantine; the coordinator race | Added to PER-07 and INDEX-04, with INDEX-05 for the race. The quarantine search is recursive because quarantined generations live in a subdirectory |

## Tracking

Every pending item is a GitHub issue so none is forgotten:

| Issue | Item |
|---|---|
| [#29](https://github.com/SodiqAbdulwaris/FaceIdentify/issues/29) | TST-031: two-step erasure with `ERASING` (Q25) |
| [#30](https://github.com/SodiqAbdulwaris/FaceIdentify/issues/30) | TST-030: recover `PAUSING` and `CANCELLING` (Q26) |
| [#31](https://github.com/SodiqAbdulwaris/FaceIdentify/issues/31) | Decide: SQLite `secure_delete` / WAL checkpoint after an erasure |
| [#32](https://github.com/SodiqAbdulwaris/FaceIdentify/issues/32) | TST-022: remaining repositories |
| [#33](https://github.com/SodiqAbdulwaris/FaceIdentify/issues/33) | TST-030: lifespan wiring and process-level kill tests |
| [#34](https://github.com/SodiqAbdulwaris/FaceIdentify/issues/34) | Q26 remainder (M3): `FINALIZING`, pending output, runtime installs |
| [#35](https://github.com/SodiqAbdulwaris/FaceIdentify/issues/35) | TST-032: second Alembic revision (Q18, Q19) |
| [#36](https://github.com/SodiqAbdulwaris/FaceIdentify/issues/36) | Q17: how the application learns the library root |
| [#37](https://github.com/SodiqAbdulwaris/FaceIdentify/issues/37) | Q20: `BEGIN IMMEDIATE` and retry (provisional) |
| [#38](https://github.com/SodiqAbdulwaris/FaceIdentify/issues/38) | Q21: `ann_key` allocation and run-local labels (provisional) |
| [#39](https://github.com/SodiqAbdulwaris/FaceIdentify/issues/39) | Q23: exclusive library lock (provisional) |
| [#40](https://github.com/SodiqAbdulwaris/FaceIdentify/issues/40) | Q24: derive original availability from the artifact |
| [#41](https://github.com/SodiqAbdulwaris/FaceIdentify/issues/41) | Q27: validate superseding by deleting (provisional) |

## Verification

Documents only; no code or schema changed. `uv run ruff format --check .` and `uv run ruff check .`
are unaffected. Every anchor of the spec edits was matched exactly once before writing.
