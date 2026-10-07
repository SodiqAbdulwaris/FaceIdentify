# M5 plan: corrections, search and memory

**Status:** draft for the owner's approval, 2026-10-07. Nothing here is built. **Scope:** tracker
milestone M5 (TST-054 to TST-059, SEC-006) in
[`TESTING_IMPLEMENTATION_TRACKER.md`](TESTING_IMPLEMENTATION_TRACKER.md), sequenced as the owner
asked on 2026-10-07. **Out of scope:** movies (M6), cameras (M7), packaging (M8), source reprocessing
(Roadmap Phase G; not in the tracker's M5, so it needs the owner's word before it joins), and the real
SCRFD/ArcFace models (issue #69).

This plan sequences work; it changes no spec. Where it records a decision the affected spec and
[`CONTEXT.md`](../../.agents/CONTEXT.md) carry the dated note.

## 1. Where things stand (2026-10-07)

M4's desktop workflow runs end to end on the development profile: import, process, see faces and the
people found, restart. People are shown as `Person {SHORT_ID}`; nothing can be named, corrected,
merged, split, recycled, deleted, forgotten or searched from the app. The domain use cases for naming,
reassignment, merge and split exist (M1, `backend/app/identities/use_cases.py`,
`backend/app/people/use_cases.py`) but have no routes or screens; representation erasure exists
(`backend/app/memory/erasure.py`); Source deletion and identity-level Forget do not.

## 2. Decisions recorded (owner, 2026-10-07)

> **Decision 2026-10-07:** **Order.** Naming, then corrections, then merge and split, then lifecycle
> (recycle, restore, permanent delete, forget person), then retrieval (historical search, name and
> person search, face search, cross-source recognition).

> **Decision 2026-10-07:** **Q16, merge and split move Occurrences.** `merge_identities` and
> `split_identity` also reassign `Occurrence.identity_id` (Roadmap Phase D lists "Occurrence
> reassignment"). The rule for an Occurrence supported by representations that go to both sides of a
> split is proposed in step 3 and needs the owner's decision.

> **Decision 2026-10-07:** **Q12, add `PERSON_RENAMED`.** A new `EvidenceKind` through a reviewed
> Alembic revision, so a Person rename leaves the historical semantic event the identity model
> requires (section 38).

> **Decision 2026-10-07:** **Q15, `IdentityState.SPLIT` is not assigned** and is to be removed in the M5
> schema cleanup unless a compatibility constraint needs it for now. A split is recorded by
> `IDENTITY_SPLIT` Evidence and lineage, not by a state.

> **Decision 2026-10-07:** **Recycled sources keep their identity history.** Recycling hides a Source
> from normal library browsing; its Occurrences stay in identity views and counts, marked as from a
> recycled source; restore clears the mark. Permanent deletion is separate (step 4).

Other owner decisions from the same day (routing, status route, development catalog guard, label
derivation, `.npmrc`) are dated notes in the M4 implementation entries and in `CONTEXT.md`.

## 3. Steps

Each step is one or more small PRs under the repository rules (branch, docs entry, independent review,
mutation-tested guards, 100% backend coverage). Every route stays thin and calls a use case; every
use case runs inside one `UnitOfWork`; the ML worker never touches SQLite.

### Step 1. Naming and Person semantics (TST-054, first part)

- Revision `0008`: add `PERSON_RENAMED` to the Evidence kinds (Q12).
- `rename_person` writes `PERSON_RENAMED` Evidence in the same transaction (today it writes none).
- Routes: create a Person, rename, attach an identity to a Person, detach, read a Person (API spec
  section on Person; follow the spec's shapes, and ask where it is silent).
- UI: name an unnamed identity from the person screen; the derived label `Person {SHORT_ID}` shows
  only while no Person is attached, and a Person's name replaces it everywhere.
- Event: publish a Person/identity change so open screens refresh (existing event client).
- **Ask before building:** whether naming creates a Person automatically on first name, or a Person
  can exist unattached (Persistence section 8 and Identity model sections 14, 38 decide; I will cite
  them and recommend).

### Step 2. Corrections (TST-054)

- Use cases and routes: confirm a match, reject a match, reassign an occurrence or representation to
  another identity, each writing `USER_CORRECTION` Evidence and an index intent where eligibility
  changes.
- Build `ResolveUnresolvedRepresentation` for accepted ABSTAIN representations (issue #79), which
  gives the user a way to resolve an identity-less representation.
- UI: confirm, reject and reassign controls on the source and person screens.
- **Ask before building:** what "reject" does to future recognition (negative evidence that blocks the
  same pairing, or a one-off unlink). The identity model and decision-engine plan describe it; I will
  quote them and recommend rather than choose.

### Step 3. Merge and split (TST-058)

- Routes and UI for `merge_identities` (merge one identity into another) and `split_identity`
  (move selected representations to a new identity).
- Moving Occurrences (Q16): merge moves all of the source's Occurrences to the survivor; split moves
  the Occurrences whose supporting representations are all selected. **Proposed, needs a decision:**
  an Occurrence supported by selected and unselected representations stays with the source and the
  new identity gets no copy (never duplicate an Occurrence), with the mixed case reported in the
  split result so the UI can say so. Recognition's index needs no mutation for identity ownership
  changes (Roadmap Phase D).
- Person conflict on merge (two identities attached to different Persons): **to verify** how
  `merge_identities` treats it today and what Identity model section 19 requires, then expose it
  through the existing error shape; the UI asks the user to detach one first if the rule refuses.
- Revision `0009` (cleanup): remove `IdentityState.SPLIT` (Q15) from the model, the persistence
  document and any check, if no constraint needs it; if one does, keep it and record why.
- Tests include the existing Hypothesis invariants extended to Occurrences (TST-020) and an
  end-to-end merge, split and restart.

### Step 4. Lifecycle: recycle, restore, permanent delete, forget (TST-059, SEC-006)

- Recycle and restore routes over `recycle_source` and `restore_source` (built). Identity views mark
  Occurrences from a recycled source and keep counting them; the library hides the Source.
- Permanent delete of a Source: deletes its runs and then their now-unreferenced snapshots (CONTEXT
  question 29), deletes managed artifacts through the Storage Manager's conservative cleanup, and
  defines what happens to the Source's observations, representations (erasure, built), Occurrences and
  Evidence. **Ask before building:** the fate of Evidence and of an identity that loses its last
  Source; I will propose from Identity model section 60 ("Delete Media vs Forget Person").
- Forget person (identity level): state to `FORGOTTEN`, Person association ended, representations
  erased through `RepresentationEraser`, `IDENTITY_FORGOTTEN` Evidence kept, user-authored Person
  metadata kept (Identity model section 60 and the invariant list).
- Tests: a forgotten or deleted memory cannot be resurrected by later processing or index rebuild,
  checked after a restart (TST-059) and by the byte-level erasure policy tests (SEC-006).

### Step 5. Retrieval (TST-055, TST-056, TST-057)

- Historical search by Person or name, Identity, Source and Occurrence over authoritative (ACTIVE)
  data only (TST-055), per the search architecture spec; I will cite its sections and ask where it is
  silent.
- Face search: upload a query image, perceive it, search, return identities with context, and persist
  nothing (the query-only guard is built; TST-056 proves it end to end, including after a restart).
- Cross-source recognition (TST-057): the same person recognised across different sources, evaluated.
  On the development profile this proves the plumbing only; meaningful quality needs real models.
- UI: a search screen and result views.

## 4. Dependencies and blockers

- Real SCRFD/ArcFace weights (issue #69) block any claim about recognition quality: TST-057 and the
  calibrated policy (TST-044) cannot be met on fakes. Plumbing is built and tested on the development
  profile.
- Step 4 needs the development-profile guard (below) decided and built before a kept library is used
  in practice; it is independent of step 4's code.
- Step 3 depends on step 2 only for the UI; the use cases are independent.

## 5. Tracker IDs and definition of done

TST-054 (steps 1, 2), TST-058 (step 3), TST-059 and SEC-006 (step 4), TST-055, TST-056 and TST-057
(step 5). **Done** when those rows are `PASSING` (TST-057 `PASSING` on the development profile with the
quality claim recorded as blocked on issue #69), the milestone gate holds ("identity-management
workflows preserve current state and historical evidence"), the full backend gate passes with 100%
coverage, the desktop end-to-end test covers name, correct, merge, split, recycle, search and a
restart, CI is green on `main`, and `CONTEXT.md`, `PROJECT_STATUS.md`, the implementation log and the
tracker agree.

## 6. Not in this plan, to be scheduled separately

- The development-profile guard the owner required on 2026-10-07 (refuse a kept or real library with
  `--development-profile` and the reverse; record development provenance on the catalog and runtime
  records; mark the library). It is M4 follow-up work, tracked in the GitHub issue linked from
  `CONTEXT.md`, and builds no migration machinery for cleanup.
- Source reprocessing (Roadmap Phase G).
