# Walkthrough 04 Glossary

## 1. What this is and why it exists

One line per term, so a word you meet in code or in a lesson can be looked up. Where a lesson teaches the term, its link follows the line.
This glossary carries over every term of the old research guide and adds the terms the newer lessons introduced (profile, readiness, tombstone,
lifeline, abstain-first and others). Markers: **[built]** exists and is tested, **[designed]** is written in a spec only.

## 2. Where it lives

This file. The authoritative vocabulary of the product is `docs/specs/identity-and-memory-model-v1.md`; if this glossary and a spec disagree, the spec wins.

## 3. How it works

**ABSTAIN**: the decision "I am not sure"; no identity is assigned automatically ([lesson](../03-backend/recognition/03-decision-policy.md)).

**Abstain-first policy**: the rule that a policy file is accepted only if it can never match automatically (threshold above 1, ceiling -1) ([lesson](../03-backend/architecture/04-profiles.md)).

> **Decision 2026-10-15:** the owner decided to enable automatic acceptance (TST-057B). The real profile now also admits a matching policy that equals an owner-approved operating point in `APPROVED_MATCHING` (`require_approved_policy`, `backend/api/real.py`); a policy file alone still cannot enable matching. The point is pending owner confirmation, and the installed policy is abstain-only until then. Evidence: [`docs/implementations/2026-10-15-enable-automatic-acceptance.md`](../../../../docs/implementations/2026-10-15-enable-automatic-acceptance.md).

**Acceptance**: the single transaction that makes a finished run's private output authoritative ([lesson](../03-backend/processing/04-checkpoints-and-acceptance.md)).

**ACID**: atomic, consistent, isolated, durable: the guarantees of a transaction ([lesson](../02-data-and-storage/03-transactions-and-unit-of-work.md)).

**ANN / approximate nearest neighbour**: finding vectors close to a query without checking all of them.

**ArcFace**: the face-embedding model family used (ResNet-50 variant); trained with an angular margin loss.

**Artifact**: a file the system tracks (original, copy, model export) with a hash and a state ([lesson](../03-backend/domain/02-sources-and-artifacts.md)).

**Association (identity-person)**: the current or past link between an identity and a person; at most one is active per identity.

**Async / await**: Python and JavaScript syntax for tasks that wait without blocking each other.

**Atomic**: all-or-nothing; used of transactions and of file renames.

**Authoritative**: the truth; not rebuildable. Opposite: derived ([lesson](../00-start-here/03-authoritative-and-derived.md)).

**Backend gate**: the front-end component that shows 'Starting...' and 'Opening your library...' until the backend can be used ([lesson](../04-frontend/04-app-structure-and-gate.md)).

**Bearer token**: a secret sent in the `Authorization` header; here, per launch.

**Branch**: a movable name for a line of Git commits.

**buffalo_l**: the InsightFace model pack (SCRFD-10GF + ArcFace R50) used for real recognition.

**Calibration**: making a score mean a probability. Here a policy is only called calibrated once its thresholds were measured and verified; none is yet.

**Capability (readiness)**: a named part of the backend (database, storage, index, recovery, scheduler...) whose state `/readiness` reports.

**CHECK constraint**: a database rule that refuses values outside a listed set.

**Checkpoint**: a saved progress marker of a run; `FINAL` holds the full decision evidence ([lesson](../03-backend/processing/04-checkpoints-and-acceptance.md)).

**CI**: continuous integration: automated checks on every pull request.

**Closure**: a function that remembers variables from where it was defined.

**Component / ComponentVersion**: a replaceable model role (detector, embedder) and a version of it.

**Content Security Policy (CSP)**: the list of places the web view may connect to and load from, set in `tauri.conf.json` ([lesson](../05-desktop-shell/04-library-folder-and-dialogs.md)).

**Conventional Commits**: the `type(scope): summary` commit header format.

**Cosine similarity**: how alike the directions of two vectors are, -1 to 1.

**CUDA / cuDNN / cuBLAS**: NVIDIA's GPU computing platform and its neural-network and matrix libraries.

**Cursor pagination**: paging by an opaque 'next' token instead of page numbers ([lesson](../03-backend/api/README.md)).

**Dataclass**: a Python class whose constructor and comparison are generated from its fields.

**DEGRADED**: the library is usable but something recoverable is outstanding; `/readiness` says what.

**Dependency injection**: passing in what a function needs (a clock, an id maker) instead of reaching for it.

**Derived**: can be rebuilt from authoritative data (the vector index, caches) ([lesson](../00-start-here/03-authoritative-and-derived.md)).

**Detection**: finding faces and their boxes in an image.

**DOM**: the browser's tree of page elements.

**Embedding**: a vector that represents something (here, a face) so that distance means difference.

**Enum**: a fixed set of named values.

**Event (API)**: a small notice over the WebSocket that something changed; it carries ids, never state, and means 'refetch' ([lesson](../03-backend/architecture/07-events.md)).

**Evidence**: an immutable record of why a decision was made ([lesson](../03-backend/domain/06-occurrences-and-evidence.md)).

**Execution provider**: an ONNX Runtime back-end for particular hardware (CPU, CUDA, ...).

**Execution segment**: a stretch of a run on one model variant; a new one starts after a real fallback ([lesson](../03-backend/processing/01-jobs-and-runs.md)).

**False accept / false reject**: wrongly saying "same person" / wrongly failing to.

**FastAPI**: the Python web framework used for the backend.

**Fixture (pytest)**: reusable test set-up.

**Foreign key**: a column referring to another table's primary key.

**Forget**: the operation that removes an identity's face vectors while the photographs and the person's name stay [built] ([lesson](../03-backend/lifecycle/03-forget.md)).

**Frozen (dataclass)**: cannot be changed after creation.

**Generator**: a function that `yield`s values one at a time.

**GIL**: Python's lock letting one thread run Python code at a time.

**Handshake**: the one JSON line the host prints so the shell knows its address ([lesson](../05-desktop-shell/03-sidecar-contract.md)).

**Hash (SHA-256)**: a fixed-size fingerprint of data.

**HNSW**: the graph algorithm behind the vector index.

**Hook (git)**: a script run at commit/push time; (React) a `use...` function.

**Idempotent**: doing it twice has the same effect as once.

**Identification (1:N)**: who among everyone known is this?

**Identity**: one visual subject, named or unnamed (vs Person: the named human) ([lesson](../03-backend/domain/04-identities-and-lineage.md)).

**Index (database)**: a structure that speeds lookups on a column.

**Index (vector)**: the USearch structure ([vector index](../02-data-and-storage/06-vector-index-and-outbox.md)).

**IndexOperation**: a queued ADD/REMOVE for the vector index (the outbox) ([lesson](../02-data-and-storage/06-vector-index-and-outbox.md)).

**Inference**: running a trained model. (Training is not done here.)

**Invariant**: something that must always be true.

**Job**: the scheduling record of work to do (vs ProcessingRun: its history) ([lesson](../03-backend/processing/01-jobs-and-runs.md)).

**JSON**: text format of nested dictionaries, lists, strings, numbers, booleans, null.

**Landmarks**: five face points (eyes, nose, mouth corners) used for alignment.

**Lease**: the time a claimed job belongs to one runner, so a dead worker cannot hold work forever ([lesson](../03-backend/architecture/05-scheduler-and-runner.md)).

**Library root**: the folder holding your database and files.

**Lifeline (stdin)**: the pipe the shell keeps open to the host; closing it asks the host to stop ([lesson](../05-desktop-shell/03-sidecar-contract.md)).

**Lifespan (FastAPI)**: code run at server start and stop.

**Lineage**: structural history of merges and splits between identities ([lesson](../03-backend/domain/04-identities-and-lineage.md)).

**Loopback**: `127.0.0.1`, your own machine.

**Margin**: the lead the best candidate must have over the runner-up ([lesson](../03-backend/recognition/03-decision-policy.md)).

**Metric learning**: training so that distance reflects identity.

**Migration**: a versioned script that changes the database schema ([lesson](../02-data-and-storage/04-migrations-alembic.md)).

**Mock / double / fake**: a stand-in used in tests.

**mypy**: the Python type checker ([lesson](../01-basics/tools/04-ruff-and-mypy.md)).

**ruff**: the Python linter and formatter ([lesson](../01-basics/tools/04-ruff-and-mypy.md)).

**NMS**: non-maximum suppression: removing duplicate overlapping boxes.

**Normalisation (L2)**: scaling a vector to length 1.

**Observation**: a detected face in a source ([lesson](../03-backend/domain/03-observations-and-representations.md)).

**Occurrence**: an appearance of an identity within a source ([lesson](../03-backend/domain/06-occurrences-and-evidence.md)).

**ONNX / ONNX Runtime**: model file format / the engine that runs it.

**Open-set**: strangers are possible; the system may say "nobody I know".

**Operating point**: the chosen threshold and margin, with the precision and recall measured at them ([lesson](../06-evaluation-and-operations/02-measure-operating-point.md)).

**Optimistic concurrency**: edit only if the row's revision is unchanged ([lesson](../03-backend/domain/07-states-revisions-provenance.md)).

**ORM**: object-relational mapper (SQLAlchemy).

**Outbox pattern**: record intent in the database, perform the side effect afterwards ([lesson](../02-data-and-storage/06-vector-index-and-outbox.md)).

**Pending (state)**: private, not yet accepted output; invisible to search and the screens.

**Person**: the named human, separate from the visual Identity ([lesson](../03-backend/domain/05-people-and-naming.md)).

**Policy (decision)**: the thresholds and margin that govern recognition.

**Precision / recall**: share of accepted that is right / share of rightable that was accepted ([lesson](../01-basics/recognition-ideas/05-thresholds-and-errors.md)).

**ProcessingRun**: one processing of a source with frozen settings ([lesson](../03-backend/processing/01-jobs-and-runs.md)).

**Profile (development / real)**: which catalog and perception the host runs with ([lesson](../03-backend/architecture/04-profiles.md)).

**Protocol (Python)**: a structural interface.

**Protocol (wire)**: the worker message contract ([lesson](../03-backend/runtime-and-worker/01-worker-and-messages.md)).

**Provenance**: the record of which model, variant and run produced a row.

**Pull request**: a request to merge a branch, with reviews and checks.

**Pydantic**: validated, typed data models used by FastAPI.

**Query-only**: a search that never stores what it searched with ([lesson](../03-backend/recognition/05-face-query.md)).

**Readiness**: the backend's own report of its state (`INITIALIZING`, `READY`, `DEGRADED`, `FAILED`, `SHUTTING_DOWN`) and capabilities ([lesson](../03-backend/architecture/03-host-and-startup.md)).

**Rebase**: replay a branch's commits on top of a newer base.

**Recall@1 / Recall@5 / MRR**: how often the right person is ranked first / in the top five / the average of 1 divided by the rank ([lesson](../06-evaluation-and-operations/03-assisted-gate-and-open-set.md)).

**Recycle**: hide a source but keep its bytes and memory (restorable) ([lesson](../03-backend/lifecycle/01-recycle-and-restore.md)).

**Repository (pattern)**: a class wrapping the queries of one kind of data.

**Representation**: the stored face vector with provenance ([lesson](../03-backend/domain/03-observations-and-representations.md)).

**RepresentationSpace**: a family of mutually comparable vectors ([lesson](../03-backend/domain/03-observations-and-representations.md)).

**Revision**: the version counter used for optimistic updates (also: an Alembic migration id).

**Runtime package**: an installed folder of model files and a manifest ([lesson](../03-backend/runtime-and-worker/04-packages-and-catalog.md)).

**Runtime variant**: an export on a specific provider and device.

**SCRFD**: the face detector model used.

**Sequence gap (events)**: a jump in event sequence numbers, meaning an event was dropped; the client refetches.

**Session (SQLAlchemy)**: a workspace for loading and saving rows.

**Shared memory**: a memory block two processes can both read.

**Sidecar**: a helper program started and owned by the main app (here, the Python backend) ([lesson](../05-desktop-shell/03-sidecar-contract.md)).

**Snapshot (configuration)**: the frozen settings a run executed under ([lesson](../03-backend/processing/02-configuration-snapshots.md)).

**Source**: an imported image (video later) ([lesson](../03-backend/domain/02-sources-and-artifacts.md)).

**Spawn**: start a fresh Python process that re-imports your code.

**State machine**: a thing that moves through a fixed set of states by guarded transitions.

**StrEnum**: an enum whose values are strings.

**Sub-protocol (WebSocket)**: the labels offered on connect; here `faceidentify.v1` and `fi.<token>`, the second carrying the credential ([lesson](../03-backend/architecture/08-security.md)).

**Supervisor**: the component that starts, watches, restarts and stops the worker ([lesson](../03-backend/runtime-and-worker/02-supervisor.md)).

**TanStack Query**: the library that caches and refetches server data in the front end ([lesson](../04-frontend/05-api-client-and-queries.md)).

**Tauri**: the toolkit for the desktop shell (Rust core + web view) ([lesson](../05-desktop-shell/02-tauri-commands.md)).

**Tensor**: an array of any number of dimensions.

**Threshold**: a cut-off number a score is compared with.

**Tombstone (source)**: what remains of a permanently deleted source: a row with no name or media facts, so retained evidence still resolves it ([lesson](../03-backend/lifecycle/02-permanent-delete.md)).

**Transaction**: a group of database changes that succeed or fail together.

**Type hint**: a note about a value's type, checked by mypy/tsc.

**Unit of work**: this project's wrapper for a read or write transaction with retry ([lesson](../02-data-and-storage/03-transactions-and-unit-of-work.md)).

**USearch**: the vector-index library.

**uv**: the Python package and environment manager.

**Vector**: an ordered list of numbers.

**Verification (1:1)**: are these two faces the same person?

**WAL (write-ahead log)**: SQLite's mode where changes go to a side log first ([lesson](../02-data-and-storage/02-sqlite-and-wal.md)).

**Wilson interval**: a confidence range for a proportion measured on few samples ([lesson](../06-evaluation-and-operations/02-measure-operating-point.md)).

**Worker (ML)**: the separate process that runs the models ([lesson](../03-backend/runtime-and-worker/01-worker-and-messages.md)).

**Worktree (git)**: an extra checkout of the repository in another folder.

**Zustand**: the small store for client-only UI state (the events connection status).

## 4. Try it

**Works with no models. Verified 2026-10-12.** Pick three terms from the last lesson you read and say each in your own words without looking; then check. A term
you cannot say is a lesson to re-read, not a word to memorise.

## 5. Change it

When a lesson introduces a term, add it here in alphabetical order with its link (see [keeping this true](05-further-reading-and-keeping-true.md)).

## 6. Break it on purpose

Look up **Identity** and **Person**, then read the domain vocabulary lesson's "three words people mix up" and try to explain, with the glossary closed, why a person
can have several identities.

## 7. Exercises

1. Which two terms are both called "index", and how do they differ?
2. What is the difference between a Job and a ProcessingRun?

**Answers**

1. A database index speeds up lookups on a column; the vector index (USearch) finds nearby vectors and is derived and rebuildable.
2. A job is schedulable work (priority, lease); a run is the history and frozen settings of one processing.

## 8. Related files

- Previous: [03](03-exercises.md) · Next: [05 Further reading and keeping this true](05-further-reading-and-keeping-true.md)
