# Walkthrough 01 One photograph, from click to person

## 1. What this is and why it exists

Every lesson in this guide describes one part. This one strings the parts together: the life of a single photograph in the order
things happen. Read it with the files open. Each row names the files and the lesson that explains them. Finish it and you can narrate
the whole system.

## 2. Where it lives

Every file named in the table below; the table is the map.

## 3. How it works

| # | What happens | Where to look | Lesson |
|---|---|---|---|
| 1 | The window starts; the shell makes a token, starts Python, reads the handshake | `desktop/src-tauri/src/sidecar.rs`, `lib.rs`; `backend/api/host.py` | [sidecar contract](../05-desktop-shell/03-sidecar-contract.md), [host](../03-backend/architecture/03-host-and-startup.md) |
| 2 | The backend opens the library: lock, migrations, storage, index coordinator, **startup recovery**; then the scheduler starts | `backend/app/lifecycle.py` (`open_library`), `backend/api/startup.py`, `backend/app/recovery/startup.py` | [recovery](../03-backend/architecture/06-recovery.md) |
| 3 | The page asks the shell where the backend is, then polls `/readiness` until `READY` or `DEGRADED` | `frontend/src/app/BackendGate.tsx`, `frontend/src/native/backend.ts` | [the gate](../04-frontend/04-app-structure-and-gate.md) |
| 4 | You pick an image; the shell's file picker returns its path; the page calls `POST /sources/import` | `frontend/src/features/library/LibraryPage.tsx`, `backend/api/routes/sources.py` | [library screen](../04-frontend/07-library-and-source-screens.md), [sources routes](../03-backend/api/routes/sources.md) |
| 5 | Import: decode, fingerprint (SHA-256), record an Artifact and a Source (reserve, write, then one transaction) | `backend/app/sources/import_source.py`, `artifact_storage.py` | [sources and artifacts](../03-backend/domain/02-sources-and-artifacts.md) |
| 6 | You press process: `POST /sources/{id}/process`; one transaction writes the Job, the ProcessingRun and the frozen snapshot; answer `202` | `backend/api/routes/processing.py`, `backend/app/processing/process_source.py`, `configuration.py` | [jobs and runs](../03-backend/processing/01-jobs-and-runs.md), [snapshots](../03-backend/processing/02-configuration-snapshots.md) |
| 7 | The scheduler wakes, claims the job (priority order, with a lease), the runner starts it | `backend/api/scheduler.py`, `backend/app/processing/scheduler.py`, `runner.py` | [scheduler and runner](../03-backend/architecture/05-scheduler-and-runner.md) |
| 8 | Decode the pixels; build the plan from installed packages; ask the worker (pipe plus shared memory) to detect | `backend/infrastructure/media/image.py`, `backend/app/runtime/worker_config.py`, `perception_client.py`, `backend/ml/worker/perception_handlers.py` | [perception client](../03-backend/runtime-and-worker/03-perception-client-and-providers.md), [worker](../03-backend/runtime-and-worker/01-worker-and-messages.md) |
| 9 | Inside the worker: SCRFD letterbox, ONNX Runtime on CUDA or CPU, decode boxes, non-maximum suppression | `backend/ml/perception/detection.py`, `backend/ml/worker/onnx_session.py` | [the face pipeline](../01-basics/recognition-ideas/03-the-face-pipeline.md) |
| 10 | Each face is written as a `PENDING` Observation; alignment warps it to 112 x 112; ArcFace gives 512 numbers; written as a `PENDING` Representation | `backend/ml/perception/alignment.py`, `backend/app/processing/pending_output.py` | [observations and representations](../03-backend/domain/03-observations-and-representations.md) |
| 11 | Retrieval: this run's own faces (run-local pool) plus the global USearch index; candidates revalidated against SQLite and grouped by identity | `backend/app/recognition/retrieval.py`, `assessment.py`, `backend/infrastructure/indexing/` | [retrieval](../03-backend/recognition/01-retrieval.md), [assessment](../03-backend/recognition/02-assessment.md) |
| 12 | The reasoner decides `MATCH_EXISTING`, `CREATE_NEW` or `ABSTAIN` with a recorded reason | `backend/app/recognition/reasoner.py` | [decision policy](../03-backend/recognition/03-decision-policy.md) |
| 13 | Decisions are persisted privately; a `FINAL` checkpoint is written; the run becomes `FINALIZING` | `backend/app/processing/execute_job.py` | [executing an image](../03-backend/processing/03-executing-an-image.md) |
| 14 | **Acceptance**, one transaction: revalidate, activate, write Occurrences and Evidence, create identities, append index `ADD` operations, complete the run | `backend/app/processing/accept_run.py` | [checkpoints and acceptance](../03-backend/processing/04-checkpoints-and-acceptance.md), [decisions in memory](../03-backend/recognition/04-decisions-in-memory.md) |
| 15 | After the commit: the coordinator applies the index operations; an event is published | `backend/app/memory/index_coordinator.py`, `backend/api/events.py` | [vector index and outbox](../02-data-and-storage/06-vector-index-and-outbox.md), [events](../03-backend/architecture/07-events.md) |
| 16 | The page receives the event, invalidates the right queries, refetches, shows the faces and people | `frontend/src/api/events.ts`, `invalidation.ts`, `frontend/src/features/source/SourcePage.tsx` | [events and routing](../04-frontend/06-events-and-routing.md) |
| 17 | You rename or correct: `POST /people`, `PATCH /people/{id}`, `POST /occurrences/{id}/reassign`, merges and splits; each is one atomic transaction that writes Evidence | `backend/app/people/use_cases.py`, `backend/app/identities/corrections.py`, `use_cases.py`, `backend/api/routes/` | [people and naming](../03-backend/domain/05-people-and-naming.md), [identities and lineage](../03-backend/domain/04-identities-and-lineage.md) |
| 18 | You close the window; stdin closes; the backend stops the scheduler and workers and closes the library; next start recovers whatever was interrupted | `backend/api/host.py`, `backend/api/startup.py`, `backend/app/recovery/startup.py` | [host and startup](../03-backend/architecture/03-host-and-startup.md) |

## 4. Try it

**Works with no models. Verified 2026-10-12.** Watch steps 4 to 16 happen on the development profile (the fake perception stands in for steps 8 to 10):
build the practice library from [start-here 07](../00-start-here/07-run-it-and-see-it-work.md), run the event listener from
[call the API](../03-backend/api/01-call-the-api.md) while you import and process a picture, and see the events arrive in the order the table predicts
(`processing_run.created`, then `RUNNING`, then `COMPLETED`: steps 6, 7 and 14). Then read the rows it left:

```bash
uv run python q.py ~/faceidentify-play/lib "select state, revision from processing_runs" "select kind, count(*) from evidence group by 1"
```

([`q.py` is in the domain README](../03-backend/domain/README.md).) The same flow end to end through the real screens, run by a test:
`npm run test:e2e`.

## 5. Change it

Pick one row and write its lesson's "Change it" down as a plan without editing anything; then check which tests would have to change. That is
the skill the walkthrough is for.

## 6. Break it on purpose

For each of three rows (3, 14, 18) say what the user would see if that step failed and what recovers it (the gate's notice; rollback and `NOT_RESUMABLE`;
startup recovery). Check your answers against [recovery](../03-backend/architecture/06-recovery.md).

## 7. Exercises

1. At which step does a face first become visible to search?
2. Which step can be repeated after a crash without running a model again?
3. At which step is the vector index changed?

**Answers**

1. Step 14, acceptance (before it, everything is `PENDING` and private).
2. Step 14 (a `FINAL` checkpoint is accepted without ML at startup).
3. Step 15, after the commit, from the durable `ADD` operations.

## 8. Related files

- Next: [02 A reading path](02-reading-path.md)
- [`docs/specs/processing-architecture-v1.md`](../../specs/processing-architecture-v1.md), [`docs/specs/IMPLEMENTATION_ARCHITECTURE.md`](../../specs/IMPLEMENTATION_ARCHITECTURE.md)
