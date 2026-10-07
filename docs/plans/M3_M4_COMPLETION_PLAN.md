# M3 and M4 completion plan

**Status:** approved by the owner 2026-10-06. **Scope:** the remainder of M3 and all of M4 as
defined in [`TESTING_IMPLEMENTATION_TRACKER.md`](TESTING_IMPLEMENTATION_TRACKER.md). M5 onward
(corrections, search, merge/split UI, `ResolveUnresolvedRepresentation` #79, movies, cameras,
packaging) is **out of scope** for this plan.

This plan sequences work; it does not change a spec. Where it records a decision it says so, and
the affected specs and `CONTEXT.md` carry the dated note.

## 1. Where things stand (2026-10-06)

M3's pipeline is built and tested with planted perception: request, claim, private execution, FINAL
checkpoint, atomic acceptance, index convergence, startup recovery of `FINALIZING` and pre-FINAL
runs, retry lineage, and an end-to-end recognise, restart and rebuilt-index story (PR #110).
M4 has only the authenticated in-memory FastAPI bootstrap (PR #103). The frontend and the Tauri
shell are placeholders, and there is no production host, lifespan, scheduler loop or route.

## 2. Decisions recorded (owner, 2026-10-06)

> **Decision 2026-10-06:** **1. Development policy profile.** M4 uses a clearly named
> development/evaluation decision-policy profile so the vertical slice can run before calibration.
> It is marked uncalibrated and non-release in provenance (the frozen snapshot) and surfaced as such
> in the UI. Its numbers are not shipped production defaults. TST-044 remains the gate for promoting
> calibrated values into a release/default policy.

> **Decision 2026-10-06:** **2. Weights (issue #69).** The real-model path stays blocked until the
> exact SCRFD and ArcFace artifacts are selected and their licensing and provenance are verified and
> recorded: source, exact artifact and version, hash, licence, redistribution status and verifier.
> M4 infrastructure continues with fakes and test providers. M4 does not select or download weights.

> **Decision 2026-10-06:** **3. Job priority (CONTEXT question 14).** Add an integer priority rank
> in revision `0007` before the scheduler is implemented. Alphabetical string order is never
> scheduling semantics.

> **Decision 2026-10-06:** **4. Startup handshake.** The sidecar writes one JSON line on stdout with
> the startup handshake and protocol information. The per-launch capability (token) is passed
> through an inherited environment variable, never argv.

> **Decision 2026-10-06:** **5. Frontend data layer.** TanStack Query for server state, a small
> Zustand store only for client and UI state, `openapi-typescript` for generated API types. Server
> state is not duplicated in Zustand.

> **Decision 2026-10-06:** **6. Development runtime packages.** A documented local `runtime/`
> development installation through the existing headless installer, until M8 owns final packaging.

> **Decision 2026-10-06 (constraint on W1 and W2):** startup recovery completes, or establishes
> ownership of every in-flight job and run, before the scheduler claims any new work. Recovery and
> normal scheduling must never race over the same job or run (Persistence section 28 and the
> 2026-10-06 notes in sections 15 and 28).

## 3. Remaining M3 work

| # | Work | Tracker | Blocker |
|---|---|---|---|
| 3.1 | Move `RepresentationEraser` and the recovery writes onto `UnitOfWork` (issue #66) | TST-023, TST-030 | none |
| 3.2 | Real-process kill tests of the pipeline (after observations, after FINAL, during acceptance), then restart and verify, with planted perception | TST-043 | none |
| 3.3 | Provenance persistence and the installation-`MISSING` sweep (issue #80) | TST-038, TST-039 | the sweep waits for real weights (issue #69) |
| 3.4 | Weights selection, licence and provenance record (issue #69), then a local-only real-weights integration run | TST-038, TST-039 | owner and licence verification (decision 2) |
| 3.5 | Initial ML evaluation baseline | TST-044 | licensed datasets and weights; post-M3 per the owner |

**M3 status (2026-10-06): 3.1 and 3.2 are done (PRs #113 and #114); 3.3's sweep, 3.4 and 3.5 stay
blocked on weights and datasets. The exit gate below is met: see the M3 status block in the tracker.**

**M3 exit gate.** Every M3 tracker row from TST-033 to TST-043 is `PASSING`, or `BLOCKED` with the
reason and the issue that unblocks it (3.4 is expected to remain `BLOCKED` on weights). TST-044
(3.5) is deferred past M3 and is not part of this gate. The full backend gate passes with 100% coverage, CI is green on `main`, and
`CONTEXT.md`, the implementation log and the tracker agree. TST-044 does not gate M4; it gates
promoting calibrated values to a release policy (decision 1).

## 4. M4 workstreams

| W | Workstream | Content | Tracker |
|---|---|---|---|
| W1 | Host | FastAPI lifespan wrapping `open_library`; loopback bind on a dynamic port; the stdout JSON handshake; token from the inherited environment; parent-PID watch and graceful shutdown; capability-based readiness (`DEGRADED` when ML or the index is unavailable) | TST-048 |
| W2 | Services | Revision `0007` (integer priority rank); the scheduler loop (claim, execute, accept, index wake); the ML supervisor and `PerceptionClient` wired from the catalog plan; runtime package registration at startup from the dev `runtime/` install; the command boundary that sets `CANCELLING`; the development policy profile (decision 1) | TST-060 (the claim and transition rules M4 exercises; the full state machine stays M6) |
| W3 | REST | Import, list/get sources, media delivery, process, runs, jobs, identities, occurrences, system status; error contract, pagination and response conventions; thin routes over use cases; read models for list and detail queries | TST-045 |
| W4 | Events | WebSocket envelope, namespaces and reliability; REST stays authoritative, so a client resyncs from REST after reconnect | TST-051 |
| W5 | Contracts | Generated OpenAPI, generated TypeScript types (`openapi-typescript`), CI sync check | TST-046 |
| W6 | Tauri shell | Spawn the sidecar, read the handshake, single instance, library-root selection (the shell owns it), shutdown, native file picker | TST-047 |
| W7 | Frontend | Routes `/library`, `/library/source/:id`, `/identities/:id`, `/processing/:runId`; API and WebSocket clients; import flow; results view (faces to identity); observability before polish; the uncalibrated-policy notice | TST-049, TST-050 |
| W8 | End to end | Complete image workflow, then restart | TST-052, TST-053 |

> **Decision 2026-10-07 (agent's, for the owner to confirm; W3.6):** W3 builds no separate "system
> status" route. `/health` and `/readiness` already report the lifecycle and every capability, and
> the spec's `/runtime/status` is about runtime packages (M8). The development-policy notice is
> carried by each processing run's `policy` field instead. Pause/resume and observation reads stay
> out of M4; see the implementation entries for W3.4 and W3.5.

**Ordering.** W1, then W2 and the read side of W3 in parallel, then the write side of W3, then W4
and W5, then W6 and W7 in parallel, then W8. Within W2, revision `0007` comes first, then the
scheduler, and the scheduler starts only after startup recovery has completed (the constraint in
section 2). Each PR is small, review-gated and keeps backend coverage at 100%.

## 5. Dependencies and blockers

- **Weights and licence (issue #69):** blocks 3.3's sweep, 3.4, 3.5 and any real-model claim in M4.
  M4 proceeds on fakes and test providers.
- **Policy numbers:** blocked on TST-044 for release; M4 uses the labelled development profile only.
- **Revision `0007`:** blocks the scheduler loop (W2).
- **Recovery before scheduling:** W1 must run recovery to completion before W2 starts claiming.
- **Handshake and token:** W1 defines them; W6 consumes them.
- **OpenAPI:** W3 produces the schema; W5 and W7 depend on it.
- **Specs not yet decided** (CONTEXT questions 11 and 24) are settled only when a use case needs
  them, with an owner decision, never silently.

## 6. M4 definition of done

The complete desktop image workflow passes end to end: the user launches the desktop application,
which starts the backend; imports an image; processing runs through the real scheduler, worker
boundary, acceptance and index; the faces and their identities are displayed from authoritative
results with the uncalibrated-policy notice; and after the application is closed and reopened the
previously committed results are still displayed and recognition still works (the restart story of
TST-053). TST-045 to TST-053 are `PASSING` (TST-051 is P1), with real weights not required.
