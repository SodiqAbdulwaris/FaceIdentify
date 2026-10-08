# M5 plan: corrections, search and memory

**Status:** scope and order approved by the owner 2026-10-07, with seven changes and then the real-model
track (section 2) made the same day. Built so far: R0 (issue #137). **Scope:** tracker milestone M5 (TST-054 to
TST-059, SEC-006) in [`TESTING_IMPLEMENTATION_TRACKER.md`](TESTING_IMPLEMENTATION_TRACKER.md), **plus the
real-model track: issue #69 (SCRFD and ArcFace), the runtime installation and provenance they need,
TST-038/039 on the real path, TST-044 (initial calibrated policy), issue #80's sweep, and issue #137.**
M5 is the first real recognition milestone. **Out of scope:** movies (M6), cameras and their GPU work
(M7), installer-level model packaging and distribution (M8), and **source reprocessing (Roadmap Phase
G), which stays outside M5** unless an M5 feature genuinely requires it.

The rule for what M5 absorbs: if M5 cannot truthfully meet its definition of done without it, it is in
M5; otherwise it stays in its own milestone.

This plan sequences work; it changes no spec. Where it records a decision the affected spec and
[`CONTEXT.md`](../../.agents/CONTEXT.md) carry the dated note.

> The remaining work, in order, with what needs the owner: [`M5_REMAINING_WORK.md`](M5_REMAINING_WORK.md).

## 1. Where things stand (2026-10-07)

M4's desktop workflow runs end to end on the development profile: import, process, see faces and the
people found, restart. People are shown as `Person {SHORT_ID}`; nothing can be named, corrected,
merged, split, recycled, deleted, forgotten or searched from the app. The domain use cases for naming,
reassignment, merge and split exist (M1, `backend/app/identities/use_cases.py`,
`backend/app/people/use_cases.py`) but have no routes or screens; representation erasure exists
(`backend/app/memory/erasure.py`); Source deletion and identity-level Forget do not.

## 2. Decisions recorded (owner, 2026-10-07)

> **Decision 2026-10-07:** **Order.** Naming, then corrections, then merge and split, then lifecycle
> (recycle, restore, permanent delete, forget), then retrieval (historical search, name and person
> search, face search, cross-source recognition).

> **Decision 2026-10-07:** **Q16, merge and split move Occurrences.** `merge_identities` and
> `split_identity` also reassign `Occurrence.identity_id` (Roadmap Phase D lists "Occurrence
> reassignment").

> **Decision 2026-10-07:** **A mixed-support Occurrence is an explicit conflict in a split.** If an
> Occurrence is supported by representations on both sides of the selection, the split is refused as a
> conflict that names those Occurrences; nothing is written, and neither side keeps it automatically.
> The user resolves it by selecting all or none of that Occurrence's representations (the API returns
> the closure so the UI can offer it).

> **Decision 2026-10-07:** **Naming creates and attaches the Person atomically.** Naming an unnamed
> Identity normally creates the Person and attaches it in one transaction. Standalone Person creation
> is not exposed unless the existing spec requires it (step 1 records what the spec says).

> **Decision 2026-10-07:** **Merge and split are atomic across entities** (the invariant in step 3).

> **Decision 2026-10-07:** **Forget's meaning is settled before it is implemented** (the gate in
> step 4).

> **Decision 2026-10-07:** **Q12, add `PERSON_RENAMED`.** A new `EvidenceKind` through a reviewed
> Alembic revision, so a Person rename leaves the historical semantic event the identity model
> requires (section 38).

> **Decision 2026-10-07:** **Q15, `IdentityState.SPLIT` is not assigned** and is to be removed in the M5
> schema cleanup unless a compatibility constraint needs it for now. A split is recorded by
> `IDENTITY_SPLIT` Evidence and lineage, not by a state.

> **Decision 2026-10-07:** **Recycled-source Occurrences stay eligible for historical views.**
> Recycling hides a Source from normal library browsing only. Its Occurrences remain in identity views,
> counts and historical search (marked as from a recycled source, and filterable); restore clears the
> mark. Permanent deletion is separate (step 4).

> **Decision 2026-10-07:** **TST-057 is split in two.** The cross-source *workflow* is `PASSING` on the
> development profile; the *recognition-quality* claim is `BLOCKED` on issue #69 and is never reported
> as met by the workflow test.

> **Decision 2026-10-07:** **Correction to the note above.** The tracker records no passing TST-057
> result. The verified development-profile workflow evidence is TST-052 and TST-053 (the end-to-end
> run and the restart). TST-057 stays unpassed until real-model evidence exists.

> **Decision 2026-10-07:** **Source reprocessing stays outside M5** and gets its own plan.

> **Decision 2026-10-07:** **M5 is the first real recognition milestone.** M4 proved the application
> and its workflow work; M5 must prove the application remembers, recognises, corrects and retrieves
> real people with a real SCRFD/ArcFace runtime. The real-model track (issue #69, runtime installation
> and provenance, real-inference tests, TST-044) and issue #137 move into M5 and run **in parallel**
> with the identity-management track, joining before face search and cross-source recognition and
> before M5 closes. Not being able to obtain the final ArcFace weights must not stop naming, correction,
> merge, split or lifecycle work. This **supersedes** the TST-057 note above: the fake-profile workflow
> stays as a CI test but is no longer evidence that recognition works; TST-057 is closed on real
> models. M8 packaging and M6/M7 work are not absorbed.

> **Decision 2026-10-07:** **Corrections need no new schema.** Confirm is a `USER_CORRECTION` Evidence row
> with no recognition effect yet; reject and reassign move a face (its representation and occurrence)
> to a new unknown identity or to a chosen existing one, with Evidence. There is no cannot-link
> constraint in M5 (owner, answering step 2's question).

> **Decision 2026-10-07:** **"Calibrated" means measured thresholds in the same mode.** TST-044's policy is
> the decision thresholds measured at the owner's 99%-precision rule and frozen in the snapshot; scores
> stay raw cosine, so the mode stays `UNCALIBRATED` and the UI notice says what was measured and its
> limits. No `CALIBRATED` mode is built.

> **Decision 2026-10-08 (owner): assisted and automatic recognition are separate capabilities.**
> 1. *Cross-source recognition now is assisted:* ranked possible matches plus manual confirmation
>    (option 1 of `M5_REMAINING_WORK.md`). Option 2, earning automatic matching with verified evidence,
>    is pursued in parallel. Automatic identity assignment stays disabled until a verified evaluation
>    shows the conservative precision requirement is met.
> 2. *TST-057 is split.* **TST-057A (assisted cross-source recognition)** is validated by ranked
>    retrieval metrics (Recall@1, Recall@5, MRR) over real images from independent sources, plus manual
>    confirmation, including persistence after a restart. **TST-057B (automatic cross-source
>    recognition)** is `BLOCKED pending calibration` and is never claimed as passed while automatic
>    matching is disabled. The original requirement is not weakened: it is kept as TST-057B.
> 3. *Evaluation labels:* a lightweight local review utility for doubtful same-person/different-person
>    pairs is built (track R, step R5). It preserves reviewed labels, reviewer decisions and evaluation
>    provenance. Reviewed calibration examples are never reused as an untouched final test set. The
>    agent asks the owner for the dataset requirements when that work begins.
> 4. Steps 1 to 7 proceed as planned and do not wait on calibration.
> 5. *Permanent deletion:* retained Evidence must not expose deleted biometric material or weaken the
>    erasure guarantees; tests assert retained provenance against removed biometric payloads.
> 6. *Face search:* ranking and retrieval settings are independent of the automatic-matching
>    thresholds; a query-only search never persists biometric observations or identities.
> 7. *M5 completion:* the assisted-recognition workflow may pass its own acceptance gate while
>    automatic recognition remains explicitly disabled and unverified (TST-057B blocked).

> **Decision 2026-10-08:** **Owner confirmations of the abstain-only agent designs** (recorded; the
> policy choices stay versioned and their provenance is kept):
>
> **Final 2026-10-08:** items 1 to 3 below are settled without reopening: ABSTAIN does not mean NEW
> IDENTITY (abstain-first once identities exist; no identity for every unmatched face), scores are
> bounded to [-1, 1] so a threshold above 1.0 disables matching, and the eleven routes are approved
> as listed. The paragraph that follows records the earlier agent reading, now the owner's rule.
>
> 1. *First face.* An abstain-only policy disables automatic matching to **existing** identities, not
>    automatic identity creation: the first face creates a persistent unnamed identity. No automatic
>    merging and no assignment to an existing identity happens under the disabled policy. *Agent
>    reading, flagged for the owner:* a later face that has candidates but is not matched **abstains**
>    (reason `UNCERTAIN_SIMILARITY`) and waits for manual resolution, where "this is someone new" makes
>    its own identity; the disabled policy's new-identity ceiling is -1.0, so a weak score never creates
>    an identity by itself (the R4 text: scores below the threshold abstain). Creating an identity for
>    every unmatched face would fragment one person into many; say if that is wanted instead.
> 2. *Disabled matching* (conditionally approved): `match_threshold` above 1.0 stays the representation
>    of "automatic matching disabled", on these conditions, now met: similarities are bounded centrally
>    (`RetrievedCandidate.similarity` holds a cosine to -1..1, so nothing can reach a threshold above 1;
>    the bound is the cosine's own range, -1 to 1, not 0 to 1, because a negative cosine is meaningful);
>    enforcement is central (`DecisionPolicy` validation and `DecisionPolicy.automatic_matching`); the
>    run's policy provenance reports `automatic_matching` and the interface shows "Automatic matching
>    disabled". A separate `auto_match_enabled` setting is preferable long-term and is **not** built now.
> 3. *REST routes:* approved in principle. The paths exist and are in the generated contract
>    (`frontend/src/api/openapi.json`): corrections `POST /occurrences/{id}/confirm` and
>    `/reassign`; unplaced faces `GET /sources/{id}/unresolved-faces` and `POST
>    /representations/{id}/resolve`; `POST /identities/merge`; `POST /identities/{id}/split`; people
>    `POST/GET /people`, `PATCH /people/{id}`, `POST /people/{id}/assign-identity` and
>    `/remove-identity`. They are listed again for final confirmation in the pull request.
> 4. *Rename events* carry the stable entity id and the new revision, never the name; REST stays
>    authoritative (`person.updated` now has `data.revision`).
> 5. *`--minimum-recall 0.5`* is a configurable evaluation usefulness target (it replaces the
>    conservative rule's predeclared 0.25). Precision and false-accept safety outrank it, and missing
>    it never relaxes a threshold: it only disables automatic acceptance.
> 6. *Wording:* embedding similarity is never described as "% alike". The interface says "Similarity
>    score", states that it is not a probability of identity, and shows ranked possible matches
>    (highest score first) rather than implying certainty.
>
> Regression tests for the abstain-only behavior (first-face creation, later observations, restart
> persistence) are in `tests/integration/test_api_development_profile.py`.

> **Decision 2026-10-07:** **R4's operating point is conservative and provisional.** After the
> first measurement (the point chosen on the selection half reached 100% precision there and 78.4% on
> the held-out half), the owner decided: choose the threshold above the observed different-person tail
> (above 0.326), put false accepts before recall, re-evaluate on held-out data, label the policy
> provisional and conservative until a larger verified set can certify 99% precision, record its
> precision, recall, false accepts, abstention rate, counts, intervals and provenance, and let scores
> below the threshold ABSTAIN. If the higher threshold still produces false accepts, disable automatic
> acceptance (ABSTAIN and manual resolution only) until the evaluation set improves. Result: it did
> (5 false accepts of 40 on the held-out half), so the evaluated policy is ABSTAIN-only
> (`docs/research/measured-operating-point.md`); it takes effect when the real host reads it.
> **Agent design awaiting the owner's confirmation:** a `match_threshold` above 1.0 (up to 2.0) is
> accepted by the validators and means no automatic matching; the first face of an empty gallery still
> creates an identity (`NO_CANDIDATE`); say if that should wait for manual resolution too.

> **Decision 2026-10-07:** **Forget is confirmed as proposed in step 4:** `ForgetIdentity` is the only
> operation that removes biometric memory; "forget person" runs it on each of a Person's identities; the
> Person record and name stay.

> **Decision 2026-10-07:** **Deleting a Source keeps Evidence and named people.** Its observations,
> representations (erased), Occurrences and runs go; Evidence rows stay (they hold scores, not faces); a
> named person's identity stays with zero appearances; an unnamed identity left with none becomes
> `DELETED`.

> **Decision 2026-10-07:** **Weights are chosen by the owner.** The earlier rule stands: I select and
> download nothing without the owner's approval. Track R1 produces a candidates report; the owner picks;
> only then is anything downloaded, and no weights are committed to Git unless the licence expressly
> permits that distribution.

> **Decision 2026-10-07:** **Superseded later the same day by the owner's answers to the R-item
> questions:** use is personal and local only; downloading the official candidates ("all you need") is
> approved, from official sources, Git-ignored and never committed; and the final selection is
> delegated to the agent by documented criteria, overridable on return.

Other owner decisions from the same day (routing, status route, development catalog guard, label
derivation, `.npmrc`) are dated notes in the M4 implementation entries and in `CONTEXT.md`.

## 3. Steps

Each step is one or more small PRs under the repository rules (branch, docs entry, independent review,
mutation-tested guards, 100% backend coverage). Every route stays thin and calls a use case; every
use case runs inside one `UnitOfWork`; the ML worker never touches SQLite.

The work runs as two tracks that converge:

```text
                 .-- Track R: real models ------------.
                 |  R0 #137 -> R1 #69 -> R2 -> R3 -> R4 |
M5 starts -------+                                     +-- Step 5 retrieval -> M5 gate
                 |  Track I: identity management       |
                 '-- Step 1 -> 2 -> 3 -> 4 -------------'
```

### Track R. Real models (parallel to steps 1 to 4)

Each item is its own PR (or more). Nothing in track R blocks steps 1 to 4.

- **R0. Issue #137, the development-profile guard (entry cleanup). Built 2026-10-07** ([entry](../implementations/2026-10-07-m5-r0-library-profile-guard.md)). Built first, because every later
  step may touch a library worth keeping. Its history stays an M4 follow-up; M5 refuses to go on to
  real-library use without it.
- **R1. Issue #69, select and verify the weights. Selected and verified on CPU 2026-10-07** ([record](../research/reference-model-selection.md), [entry](../implementations/2026-10-07-m5-r1-reference-models.md)); the owner delegated the final choice. Done only when all of this is recorded: the exact
  SCRFD and ArcFace models; the authoritative source; the hashes; the licences, reviewed, and the
  redistribution status; and, in the existing runtime and catalog architecture, the model and version
  provenance. **Gate:** the owner approves the selection from my candidates report before any download.
- **R2. Runtime installation and compatibility.** The runtime packages for the chosen models installed
  through the existing installer (a documented local `runtime/`, plan decision 6 of the M3/M4 plan;
  M8 owns distribution); ONNX Runtime provider compatibility verified, the CUDA path tested on the
  RTX 4070 development machine and the CPU fallback smoke-tested; preprocessing and postprocessing
  matched to what those exact models expect; embedding dimension and normalisation verified; restart
  and runtime registration tested. Issue #80's installation-`MISSING` sweep is built here (it was
  waiting for real weights). TST-038 and TST-039 are closed on the real path.
- **R3. Real inference smoke tests.** Real image, then detection, then crop and alignment, then
  embedding, through the production perception client, local-only (no weights in CI; CI keeps the
  fake-profile tests).
- **R4. Evaluation and TST-044, the initial calibrated policy.** A real evaluation dataset (licensed,
  Git-ignored under `evaluation/datasets/`, never committed) and enough evaluation to set a defensible
  initial application policy and document its limits; this is not a research-grade benchmark. The
  development profile's "uncalibrated" label is replaced only by this policy. **Ask before building:**
  the dataset, its licence and the acceptance numbers; per the testing rules no threshold is invented
  without a measured baseline.

### Step 1. Naming and Person semantics (TST-054, first part). Built 2026-10-07 ([entry](../implementations/2026-10-07-m5-naming.md))

- Revision `0008`: add `PERSON_RENAMED` to the Evidence kinds (Q12). Revision `0009`
  (built 2026-10-07): remove the `SPLIT` identity state (Q15).
- **Naming an unnamed Identity** is one use case and one route: it creates the Person with the given
  name and attaches the Identity to it in one `UnitOfWork`, writing the attach Evidence
  (`IDENTITY_ASSIGNED_TO_PERSON`). Attaching an Identity to an *existing* Person (reconciliation,
  Identity model section 14) and detaching stay separate, as the API spec lists (`assign-identity`,
  `remove-identity`).
- **Standalone Person creation is not exposed in this step.** The API spec's Person list
  (`POST /api/v1/people`) does name it, so this is a spec point for the owner: I recommend deferring it
  until a screen needs a Person with no Identity, and noting the deferral beside the spec entry. Say if
  the spec's route must be built now.
- `rename_person` writes `PERSON_RENAMED` Evidence in the same transaction (today it writes none).
- Routes for reading and renaming a Person follow the spec's shapes; ask where it is silent.
- UI: name an unnamed identity from the person screen; the derived label `Person {SHORT_ID}` shows
  only while no Person is attached, and a Person's name replaces it everywhere.
- Event: publish a Person/identity change so open screens refresh (existing event client).

### Step 2. Corrections (TST-054). built 2026-10-07: 2a confirm, move, separate ([entry](../implementations/2026-10-07-m5-corrections.md)) and 2b, placing unplaced faces, issue #79 ([entry](../implementations/2026-10-07-m5-unresolved-faces.md))

- Use cases and routes: confirm a match, reject a match, reassign an occurrence or representation to
  another identity, each writing `USER_CORRECTION` Evidence and an index intent where eligibility
  changes.
- Build `ResolveUnresolvedRepresentation` for accepted ABSTAIN representations (issue #79), which
  gives the user a way to resolve an identity-less representation.
- UI: confirm, reject and reassign controls on the source and person screens.
- **Ask before building:** what "reject" does to future recognition (negative evidence that blocks the
  same pairing, or a one-off unlink). The identity model and decision-engine plan describe it; I will
  quote them and recommend rather than choose.

### Step 3. Merge and split (TST-058). Built 2026-10-07 ([entry](../implementations/2026-10-07-m5-merge-split.md)); the `SPLIT` removal (revision `0009`) is a separate small PR

- Routes and UI for `merge_identities` (merge one identity into another) and `split_identity`
  (move selected representations to a new identity).
- **Atomicity invariant (cross-entity).** A merge or a split is one write `UnitOfWork`: the Identity
  states and `identity_lineage` edge, the Representation reassignment, the Occurrence reassignment
  (Q16), the Person-link handling, the Evidence rows and the durable `IndexOperation` intents commit
  together or not at all. No reader can see an Identity moved without its Occurrences and
  Representations, or a change without its Evidence. Optimistic-lock revisions cover every row
  changed, and a stale one aborts the whole operation. The USearch index changes only afterwards, from
  the durable `IndexOperation`s, never inside the transaction, and needs no change for ownership alone
  (Roadmap Phase D). No ML work happens inside the transaction. A test forces a failure after each
  write in the sequence and checks that nothing is left half done.
- **Moving Occurrences (Q16):** merge moves all of the source's Occurrences to the survivor. Split
  moves the Occurrences whose supporting representations are all selected. **A mixed-support
  Occurrence is a conflict** (section 2): the split refuses, names the Occurrences and writes nothing;
  the API returns the closure that would make the selection consistent. To verify before building: how
  an Occurrence relates to its supporting representations in the schema, since the closure depends on
  it.
- Person conflict on merge (two identities attached to different Persons): **to verify** how
  `merge_identities` treats it today and what Identity model section 19 requires, then expose it
  through the existing error shape; the UI asks the user to detach one first if the rule refuses.
- Revision `0009` (cleanup): remove `IdentityState.SPLIT` (Q15) from the model, the persistence
  document and any check, if no constraint needs it; if one does, keep it and record why.
- Tests include the existing Hypothesis invariants extended to Occurrences (TST-020) and an
  end-to-end merge, split and restart.

### Step 4. Lifecycle: recycle, restore, permanent delete, forget (TST-059, SEC-006)

**4a (recycle and restore) built 2026-10-08** ([entry](../implementations/2026-10-08-m5-recycle-restore.md)): `DELETE /sources/{id}` and `POST /sources/{id}/restore`, the recycle bin view, and the recycled marker on occurrences. 4b (permanent delete) and 4c (forget) follow.

- Recycle and restore routes over `recycle_source` and `restore_source` (built). Normal library
  browsing hides a recycled Source; identity views, counts and historical search keep its Occurrences,
  marked as recycled.
- Permanent delete of a Source: deletes its runs and then their now-unreferenced snapshots (CONTEXT
  question 29), deletes managed artifacts through the Storage Manager's conservative cleanup, and
  defines what happens to the Source's observations, representations (erasure, built), Occurrences and
  Evidence. **Ask before building:** the fate of Evidence and of an identity that loses its last
  Source; I will propose from Identity model section 60 ("Delete Media vs Forget Person").
- **Forget: the meaning is fixed before any code (gate; confirmed by the owner 2026-10-07).** The API spec's operation is
  `POST /identities/{identity_id}/forget` (section 8.3), an Identity-level memory operation, while the
  Identity model speaks of "Forget Person" and says user-authored Person metadata survives. Proposed
  definitions, for the owner to decide:
  - **`ForgetIdentity`** is the internal operation and the only one that removes biometric memory: the
    Identity becomes `FORGOTTEN`, its Person link ends, its representations are erased through
    `RepresentationEraser`, and `IDENTITY_FORGOTTEN` Evidence is kept.
  - **"Forget person"** is the user-facing phrase for running `ForgetIdentity` on each Identity of a
    Person. It never deletes the Person record or its user-authored name and notes, which stay in
    People without visual support. A Person with several Identities can have one forgotten and keep
    the others.
  - Nothing is built for Forget until the owner decides, and the decision then goes into this plan and
    the specs as dated notes.
- Tests: a forgotten or deleted memory cannot be resurrected by later processing or index rebuild,
  checked after a restart (TST-059) and by the byte-level erasure policy tests (SEC-006).

### Step 5. Retrieval (TST-055, TST-056, TST-057), after tracks R and I converge

Face search and cross-source recognition start only when track R has reached R4 (real models, initial
calibrated policy). Historical and name search need only track I and can land earlier.

- Historical search by Person or name, Identity, Source and Occurrence over authoritative (ACTIVE)
  data only (TST-055), per the search architecture spec; I will cite its sections and ask where it is
  silent. Occurrences of recycled Sources are included, marked and filterable (section 2).
- Face search: upload a query image, perceive it with the real runtime, search, return identities with
  context, and persist nothing (the query-only guard is built; TST-056 proves it end to end, including
  after a restart).
- Cross-source recognition (TST-057): real images of the same person from independent sources are
  recognised under the initial calibrated policy, with the repeat appearances shown. This is closed on
  real models; the fake-profile version stays as a CI test only and is not evidence for this row.
- UI: a search screen and result views.

### M5 real-world gate

The complete identity-memory workflow runs with the selected real SCRFD/ArcFace runtime: import real
images containing the same person across independent sources; detect and embed faces; recognise and
retrieve the identity across sources under the initial calibrated policy; name and correct identities;
merge and split; exercise recycle, restore, delete and forget; run historical and face search; restart
the application; and verify that authoritative identity state, Evidence, indexes and retrieval remain
consistent. It is a local run (the weights are not in CI), recorded in the tracker with its evidence.

## 4. Dependencies and blockers

- Track R depends on the owner's choice of weights (R1) and, for R4, on a licensed evaluation dataset.
  If a model cannot be obtained, track I continues and only step 5's face search, TST-057 and the M5
  gate wait.
- Step 4 needs R0 (issue #137) built before a kept library is used in practice.
- Step 3 depends on step 2 only for the UI; the use cases are independent.

## 5. Tracker IDs and definition of done

TST-054 (steps 1, 2), TST-058 (step 3), TST-059 and SEC-006 (step 4), TST-055, TST-056 and TST-057
(step 5), and from track R: TST-038, TST-039 on the real path, TST-044, and issues #69, #80 and #137.
**Done** when the TST and SEC rows named are `PASSING` (TST-057 on real models), issues #69, #80 and
#137 are closed with their stated evidence, the real-world gate above has been run and recorded, the milestone gate holds ("identity-management workflows preserve current state and
historical evidence"), the full backend gate passes with 100% coverage, the desktop end-to-end test
still passes on the development profile in CI, CI is green on `main`, and `CONTEXT.md`,
`PROJECT_STATUS.md`, the implementation log and the tracker agree. Fake-profile tests stay valuable CI
tests; they are not evidence that recognition works.

## 6. Not in this plan

- Source reprocessing (Roadmap Phase G): outside M5 by the owner's decision of 2026-10-07.
- Installer-level model packaging and distribution (M8), camera GPU and runtime work (M7), movies (M6).
- Cleanup or migration of development-profile data (deliberately unsolved; #137 builds none).
