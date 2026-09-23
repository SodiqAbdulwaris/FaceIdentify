# Identity & Memory Model v1.0

**Status:** Locked Product/Domain Baseline  
**Scope:** Identity, memory, evidence, reconciliation, Universal Search, human feedback, retraining, lifecycle, deletion, and historical events.  
**Implementation status:** Implementation-agnostic. Exact models, frameworks, databases, thresholds, ranking algorithms, and training methods remain open unless explicitly stated.

---

## 1. Purpose

This document defines how the system discovers, remembers, recognizes, organizes, corrects, searches, learns from, and forgets visual identities across managed images, videos, movies, and live cameras.

The central memory question is:

> **Have I seen this person before?**

The central retrieval question is:

> **Given this query, what are the most relevant people, media, and occurrences in my visual library?**

The system is a **local visual identity memory and retrieval system**. Face recognition is an important subsystem, but it is not the product by itself.

This specification builds on the locked Product Definition & Requirements v1.0 and does not replace it.

---

## 2. Core Principles

### 2.1 Local visual memory

Core biometric processing and identity memory remain local. The system identifies only against its locally learned visual library from user-provided media and configured cameras.

It does not scrape the internet or attempt to discover legal names, social profiles, or external identities.

### 2.2 Person and Identity are different concepts

A **Person** is the canonical, user-facing human entity.

An **Identity** is a machine-maintained visual grouping or belief that a collection of evidence represents the same visual subject.

A Person may own multiple Identities.

```text
Person: David
├── Identity I-18
├── Identity I-91
└── Identity I-182
```

This separation allows machine-discovered fragments to be reconciled without destroying provenance.

### 2.3 Names are semantic metadata, not visual evidence

A Person may have:

- a generated display label,
- a primary name,
- aliases.

Changing a name must not modify visual recognition evidence.

Two people sharing the same name must not be automatically merged.

### 2.4 Unknown identities are first-class

An Identity does not require a name.

```text
Identity I-481
Person: NULL
Display label: PERSON_0041
```

The system may remember and re-recognize this identity across sources before the user ever names it.

### 2.5 Recognition is open-set

Recognition must never assume every observation belongs to an existing identity.

Conceptually, recognition produces:

```text
Known candidate(s)
+
Unknown / no acceptable match
```

Unknown rejection is a core requirement.

### 2.6 Evidence and corrections are authoritative; optimized machine state is derived

Persistent evidence and explicit user corrections are the authoritative memory foundation.

Derived structures may include:

- machine representations,
- prototypes,
- recognition templates,
- indexes,
- clusters,
- calibrated scores,
- ranking features.

Where retained evidence permits, these structures should be rebuildable.

> **Persistent evidence and user corrections are authoritative memory records. Recognition representations, prototypes, indexes, and other optimized machine structures are derived state.**

### 2.7 Machine decisions are fallible

Automatic detection, tracking, matching, clustering, evidence promotion, reconciliation, and ranking may be wrong.

The system must therefore preserve sufficient provenance and support correction and reversal where the underlying data still exists.

### 2.8 High autonomy with uncertainty

The application should not constantly require user approval.

Conceptually:

```text
Strong evidence     → act autonomously
Ambiguous evidence  → retain uncertainty / Review Inbox
Weak evidence       → do not force a match
```

---

## 3. Conceptual Domain Model

The main conceptual hierarchy is:

```text
PERSON
│
├── semantic metadata
│   ├── generated display label
│   ├── primary name
│   └── aliases
│
├── IDENTITY
│   ├── memory maturity
│   ├── human validation
│   ├── identity health
│   ├── recognition memory
│   └── EVIDENCE
│       └── OBSERVATION
│
├── ENCOUNTER
│   └── APPEARANCE
│       └── TRACK
│           └── OBSERVATION
│
├── IDENTITY EVENTS
└── FEEDBACK EVENTS
```

An Observation can participate in both:

1. temporal/media history, and
2. identity evidence.

These are related but not identical roles.

---

## 4. Observation

An **Observation** is the atomic visual-memory unit.

It means:

> At this exact source/place/time, the system observed this face.

An Observation may conceptually contain or reference:

- source,
- timestamp/frame,
- bounding region,
- selected face crop when retained,
- detection information,
- quality information,
- machine representation(s),
- original identity hypothesis,
- current association,
- processing/model provenance.

### 4.1 Observation corrections

Observations should be immutable-ish.

If the system originally associates:

```text
O-71 → I-17
```

and the user later corrects it to:

```text
O-71 → I-42
```

the system should preserve the original machine decision and record the reassignment rather than pretending the original association never occurred.

---

## 5. Track

A **Track** is a continuous sequence of observations believed to represent the same visible subject.

Tracking answers:

> Which observations belong to the same continuously visible subject?

Tracking does **not** necessarily answer:

> Who is this person?

A Track may initially have no Identity.

### 5.1 Tracking is contextual evidence, not identity truth

Tracking continuity may strengthen identity reasoning, but trackers can switch subjects.

Strong identity contradiction must be able to trigger actions such as:

- track segmentation,
- identity conflict,
- re-evaluation,
- Review Inbox entry.

---

## 6. Appearance

An **Appearance** is a meaningful user-facing occurrence or interval.

It may group multiple Tracks separated by short gaps, cuts, or other processing boundaries.

Example:

```text
David
00:14:01–00:14:18
Tracks: T-91, T-104, T-109
```

Exact grouping rules remain an implementation decision.

---

## 7. Encounter

An **Encounter** is a higher-level source event involving a Person or Identity.

Examples:

- Movie: David is encountered in Movie A through several appearances.
- Camera: David is present during a visit/session from 09:01–09:14.
- Image: the image represents a source encounter/appearance.

Conceptually:

```text
Person
└── Encounter
    └── Appearance
        └── Track
            └── Observation
```

---

## 8. Evidence

An Observation and Evidence are not synonymous.

Not every observation should strengthen persistent identity memory.

A blurry or heavily occluded observation may establish presence through track continuity while being poor reference material for future recognition.

### 8.1 Evidence levels

Conceptually, evidence may progress through:

```text
TENTATIVE
    ↓
SUPPORTING
    ↓
CORE
```

Evidence can also be demoted or rejected.

Exact promotion logic and thresholds remain open.

### 8.2 Evidence promotion signals

Promotion should not depend on one universal recognition score.

Relevant signals may include:

- recognition strength,
- observation quality,
- track consistency,
- repeated encounters,
- cross-source recurrence,
- evidence diversity,
- clustering coherence,
- contradictions,
- human feedback,
- existing identity maturity.

The final decision mechanism may later use rules, statistics, probabilistic reasoning, classifiers, learned fusion, ensembles, or other approaches.

### 8.3 Association certainty and recognition utility are separate

Two questions must remain distinct:

**Association certainty**

> How strongly do we believe this observation belongs to this identity/person?

**Recognition utility**

> How useful is this observation for recognizing the person in the future?

A user may confirm a blurry observation as David while that image remains poor recognition evidence.

Human confirmation establishes association truth; it does not automatically make poor imagery good reference material.

### 8.4 Evidence origin

Evidence/associations must preserve their provenance, including distinctions such as:

- SYSTEM,
- USER,
- DERIVED_FROM_CONFIRMED_CONTEXT.

A system inference derived from a user-confirmed track must never masquerade as an observation individually confirmed by the user.

### 8.5 Negative evidence

Explicit negative information is valuable.

Examples:

```text
O-88 != David
I-17 != I-42
```

Negative constraints should be stored when produced by meaningful evidence or user correction rather than constructing an enormous all-pairs negative matrix.

---

## 9. Identity State Is Multidimensional

Identity state is not one universal classification.

### 9.1 Memory maturity

Machine memory maturity is:

```text
EPHEMERAL
    ↓
CANDIDATE
    ↓
ESTABLISHED
```

It may also demote when supporting evidence is removed or invalidated.

#### EPHEMERAL

A weak, brief, or provisional possible identity.

EPHEMERAL may remain a processing/local-clustering concept rather than becoming a full persistent global Identity.

#### CANDIDATE

Enough useful evidence exists to believe a recurring visual identity may exist.

It may participate cautiously in recognition.

#### ESTABLISHED

The system autonomously has enough coherent evidence to remember and recognize the identity globally across sessions/media.

Promotion to ESTABLISHED does not require user approval.

### 9.2 Human validation

Human validation is independent:

```text
UNREVIEWED
CONFIRMED
```

`CONFIRMED` is human-only.

A confirmed identity does not need a name.

```text
Memory maturity: ESTABLISHED
Human validation: CONFIRMED
Primary name: NULL
```

is valid.

Human validation of an Identity does not imply that every underlying observation was individually reviewed.

### 9.3 Identity health

Identity health independently represents internal consistency:

```text
STABLE
UNCERTAIN
CONFLICTED
UNDER_REVIEW
```

A valid combination might be:

```text
Memory maturity: ESTABLISHED
Human validation: CONFIRMED
Identity health: CONFLICTED
```

This means the established/previously validated identity exists, but some associated evidence now appears inconsistent.

`DISPUTED` is deliberately not a Human Validation state; disagreement belongs to Identity Health and explicit correction/rejection events.

---

## 10. Identity Reasoning

Identity maturity and health should not be defined as a simple visual multiclass classification problem.

The same face image may belong to a CANDIDATE today and an ESTABLISHED identity tomorrow because the historical memory context changed.

Identity reasoning may consume multiple signals such as:

```text
Recognition evidence
Tracking consistency
Observation quality
Clustering
Cross-source recurrence
Cross-encounter recurrence
Contradictions
Co-occurrence
Human feedback
Historical memory
```

Whether these signals are ultimately combined through rules, classifiers, probabilistic methods, learned fusion, or other techniques remains open.

The system may use multiple specialized models/components rather than one monolithic model.

---

## 11. Recognition Hypotheses

Recognition should propose candidates rather than directly mutate identity truth.

Conceptually:

```text
Observation
    ↓
Recognizer
    ↓
MatchHypothesis candidates
```

Example:

```text
I-17 / David       strong
I-91 / PERSON_21   plausible
I-42 / Sarah       weak
UNKNOWN            possible
```

The Identity Reasoning layer then decides whether to:

- accept an association,
- retain a tentative association,
- reject all known candidates,
- create/promote a new identity,
- request review.

This preserves the boundary:

> **Recognizer proposes; Identity Reasoning decides what becomes memory.**

---

## 12. Memory Consolidation

An identity should not simply accumulate every observation forever as active recognition memory.

The system retains rich history while maintaining a smaller curated active memory.

```text
All meaningful observations/history
            │
            ▼
     Evidence candidates
            │
            ▼
    Curated active memory
```

### 12.1 Active recognition memory

Active memory should favor useful and diverse evidence rather than raw quantity.

Diversity may include differences in:

- orientation,
- lighting,
- occlusion,
- expression,
- appearance conditions,
- time/age where applicable,

without requiring these categories to be hard-coded.

### 12.2 Corroboration

Evidence should be evaluated at multiple levels:

```text
Observation
    ↓
Track
    ↓
Appearance
    ↓
Encounter
    ↓
Cross-encounter history
```

Multiple coherent moderate observations can collectively be stronger than an isolated result.

### 12.3 Self-reinforcing contamination protection

A machine-generated match must not automatically become equally authoritative evidence merely because it matched an established identity.

Otherwise:

```text
Wrong match
   ↓
Active memory updated
   ↓
Future wrong matches become easier
   ↓
Identity contamination
```

New automatic associations should be quarantined/promoted according to evidence policy before becoming trusted active memory.

### 12.4 Incremental and deeper consolidation

Memory consolidation should normally be incremental.

A new observation should primarily require re-evaluating affected identities and nearby candidates rather than rebuilding the entire library.

Heavier reconciliation may occur after:

- media processing,
- encounter completion,
- idle periods,
- explicit maintenance actions.

Exact scheduling remains open.

---

## 13. Co-occurrence and Temporal Constraints

Simultaneous independent faces are strong evidence that two identities differ.

However, co-occurrence is not an absolute invariant because of:

- mirrors,
- screens,
- photographs inside scenes,
- split-screen footage,
- edited duplication effects.

Similarly, tracking continuity is strong contextual evidence but not unquestionable identity truth.

Both should be used as signals by Identity Reasoning.

---

## 14. Person Creation and Identity Attachment

A machine Identity may initially exist without a Person.

A Person may be created when semantic/user-facing canonicalization becomes appropriate.

Machine-discovered identities may later attach to the same Person.

Example:

```text
Movie A → I-101
Movie B → I-827

Later reconciliation:

Person David
├── I-101
└── I-827
```

Names alone must never cause this reconciliation.

---

## 15. Movie Identity Reconciliation

Chunk boundaries are processing boundaries, not identity boundaries.

Movie processing may use temporary/local identity clusters before committing them to global memory.

Conceptually:

```text
Movie processing
      ↓
Resolve tracks
      ↓
Build appearances
      ↓
Cluster unknown observations
      ↓
Movie-local reconciliation
      ↓
Global identity reconciliation
      ↓
Attach strong matches
Create/promote candidates
Queue ambiguous cases for review
      ↓
People Found
```

This avoids creating a persistent global identity for every temporary chunk-level artifact.

---

## 16. Camera Identity Consolidation

Live processing must remain responsive while memory updates can be consolidated more deliberately.

Conceptually:

```text
Camera
  ↓
Detect
  ↓
Track
  ↓
Selected observations
  ↓
Recognize
  ↓
Identity Reasoning
  ↓
Encounter
```

When an encounter closes, the system may:

- evaluate collected observations,
- select useful evidence,
- reconsider the identity,
- update active memory.

The system should not independently treat every camera frame as a permanent learning event.

---

## 17. Duplicate Identity Detection and Reconciliation

The system should be capable of detecting likely duplicate identities.

Signals may include:

- visual similarity,
- complementary evidence,
- repeated cross-source matching,
- temporal/contextual patterns,
- lack of strong contradictions,
- human feedback.

Outcomes:

```text
Very strong evidence → autonomous reconciliation may be allowed
Ambiguous evidence   → Review Inbox
Weak evidence        → no action
```

Automatic reconciliation involving established identities should be substantially more conservative than ordinary observation-to-identity matching.

False temporary fragmentation is generally safer than contaminating two different people into one canonical Person.

---

## 18. Merge Semantics

Merging should normally preserve underlying Identities.

Before:

```text
Person P-10: David
└── Identity I-10

Person P-27: PERSON_0027
└── Identity I-27
```

After:

```text
Person P-10: David
├── Identity I-10
└── Identity I-27
```

The superseded Person should not need to be physically erased.

Conceptually:

```text
P-27
status: MERGED
canonical_person: P-10
```

This preserves historical resolution and allows reversal.

### 18.1 Undo merge

Undo/reversal should generate a compensating historical event rather than deleting the original merge history.

---

## 19. Split Semantics

There are two distinct split operations.

### 19.1 Person-level split

Detach an entire Identity from the wrong Person.

```text
David
├── I-10
├── I-27
└── I-83  ← incorrect
```

becomes:

```text
David
├── I-10
└── I-27

New/other Person
└── I-83
```

### 19.2 Identity-level split

Separate mixed evidence within one machine Identity.

```text
I-10
├── Evidence cluster A
├── Evidence cluster B
└── Evidence cluster C ← another person
```

becomes:

```text
I-10
├── A
└── B

I-104
└── C
```

### 19.3 Rebuilding derived state

Merge/split operations may invalidate:

- recognition memory,
- prototypes,
- machine representations,
- search indexes,
- clustering state,
- ranking features.

Affected derived state should be rebuilt from valid retained evidence.

Original observations, source history, feedback, and event provenance remain.

---

## 20. Human Feedback

Human feedback is first-class structured data.

It should be stored in its original semantic form rather than prematurely converting every interaction into a training label.

Feedback may include:

- correct,
- incorrect,
- unsure,
- selected candidate,
- same person,
- different people,
- merge,
- split,
- rename,
- observation reassignment,
- occurrence correction,
- result not relevant.

### 20.1 Explicit vs implicit feedback

Feedback strength differs.

**Strong explicit feedback** may include:

- "This is the correct person."
- "These are the same person."
- "These are different people."
- explicit reject,
- merge,
- split.

**Medium signals** may include:

- selecting a correct candidate,
- correcting an occurrence,
- renaming after a recognition workflow.

**Weak implicit behavior** may include:

- clicking a search result,
- opening a Person,
- repeatedly viewing an occurrence.

Weak behavioral signals must not automatically become biometric recognition ground truth.

### 20.2 Feedback provenance

Feedback should retain context such as:

- query,
- presented candidates,
- original ordering,
- relevant scores/signals,
- selected/rejected result,
- component/model/ranker version,
- timestamp,
- actor.

### 20.3 Multiple-result feedback

If a face query returns:

```text
1. David
2. Mike
3. PERSON_31
4. John
```

and the user selects Mike, the raw semantic fact is:

> Mike is the correct result for this query.

The system should preserve that fact.

Training logic may later derive useful positive, negative, preference, or hard-negative examples, but the raw feedback should not be overwritten by those derived interpretations.

---

## 21. Learning Model

The system does **not** require actual RLHF.

Human feedback forms a structured local corpus that may improve several layers over time.

Learning is divided into three conceptual levels.

### 21.1 Level 1 — Memory Learning

Immediate.

May update:

- identity associations,
- evidence promotion/demotion,
- negative constraints,
- active recognition memory,
- Person/Identity relationships.

No neural retraining is required.

### 21.2 Level 2 — Decision, Calibration, and Search Learning

Periodic.

May improve:

- when to accept a match,
- when to reject,
- when to request review,
- signal combination,
- candidate ranking,
- heterogeneous search ranking,
- calibration.

### 21.3 Level 3 — Representation / Model Learning

Controlled and more expensive.

Potential techniques may later include:

- fine-tuning,
- metric learning,
- contrastive learning,
- hard-negative training,
- custom model training,
- other representation-learning methods.

No specific method is locked.

---

## 22. Training Readiness

Feedback is stored continuously for future use.

Periodic retraining may be manually or automatically initiated when enough useful feedback has accumulated.

Training readiness must not be based only on raw feedback count.

Relevant factors may include:

- quantity,
- reliability,
- diversity,
- novelty,
- identity coverage,
- cross-source coverage,
- useful corrections,
- hard negatives,
- sample quality,
- contradictions,
- redundancy.

The exact formula is not locked.

Internally, readiness may be numeric. The UI need not expose false precision and may instead use states such as:

```text
LOW
BUILDING
READY
STRONGLY READY
```

Training readiness may be component-specific.

Example:

```text
Recognition calibration   BUILDING
Search ranking            READY
Representation learning   BUILDING
```

---

## 23. Retraining Controls

Users should be able to manually trigger improvement/retraining from Settings or another appropriate control.

Potential modes:

- Manual only,
- Ask when ready,
- Automatic when idle,
- Scheduled.

The safest initial default is expected to be user-controlled or ask-first behavior.

A high readiness state should not necessarily start expensive training immediately if the machine is busy with media processing or other workloads.

---

## 24. Candidate Model Evaluation and Rollback

Retraining must not blindly replace the active component.

Conceptually:

```text
Feedback
   ↓
Training
   ↓
Candidate version
   ↓
Evaluation
   ↓
Compare with current version
   ↓
Promote or reject
```

Previous promoted versions should remain rollback-capable where practical.

Evaluation should use appropriate trusted held-out evidence rather than measuring only on the training set.

Relevant metrics depend on the component and may include:

- Top-1 identification,
- Top-K retrieval,
- unknown rejection,
- false-match behavior,
- hard-negative performance,
- cross-media performance,
- ranking quality.

Retraining should account for severe identity imbalance, redundant observations, and overrepresentation of frequently encountered people.

---

## 25. Component Versioning

The system is conceptually multi-model/multi-component.

Different capabilities may evolve independently, for example:

```text
Detection
Tracking
Visual representation
Recognition
Recognition calibration
Identity reasoning
Search retrieval
Search ranking
Query understanding
```

The product must not assume one global "AI Model Version" is sufficient.

Important automated decisions should retain enough component/version provenance to support useful explanation and debugging.

---

# Universal Search

## 26. Search Is Not Recognition

Recognition asks:

> Does this observation correspond to something already remembered?

Search asks:

> Given this query, what are the most relevant things in my visual library?

Recognition may be one input into Search, but the systems are distinct.

---

## 27. Universal Ranked Retrieval

Search is modeled as heterogeneous ranked retrieval similar to modern social/content search.

A query may return multiple top results rather than one singular answer.

Possible result categories include:

- People,
- Images,
- Videos,
- Movies,
- Occurrences,
- Appearances,
- Encounters.

Internal concepts such as raw Tracks and Observations do not need to be ordinary user-facing search result types.

### 27.1 Search interface

A default result experience may conceptually expose:

```text
Top
People
Photos
Videos / Media
Occurrences
```

`Top` is heterogeneous.

Specialized tabs may apply their own type-specific ranking.

---

## 28. Search Modalities

Universal Search should support:

### Text

```text
David
```

### Face

An uploaded or camera-captured face.

### Natural-language/contextual queries

```text
Show where David and Mike appear together.
Who appears most frequently with David?
Who appears between 35:00 and 42:00?
When was this person last seen?
```

### Mixed/multimodal queries

Future/appropriate queries may combine modalities:

```text
Find pictures of [this face] with David.
Show this person between 2025 and 2026.
Find this person and Mike together.
```

The system may use different specialized components for text, visual, structured, and contextual understanding rather than requiring one giant multimodal model.

---

## 29. Face Search

Searching with a face should return ranked relevant results.

Example:

```text
Query: [face]

Top People
1. S.A.
2. PERSON_0042
3. PERSON_0108

Relevant Photos
1. graduation.jpg
2. IMG_2181.jpg

Relevant Videos
1. Birthday.mp4
2. Campus.mp4

Relevant Occurrences
1. Birthday.mp4   00:18:31
2. Campus.mp4     00:07:12
3. Camera         Sep 17, 14:32
```

Search is not required to collapse this into one identity answer.

---

## 30. Name Search

A name search is also ranked retrieval.

```text
Query: David
```

may return:

- exact/alias-matching People,
- relevant images,
- relevant movies/videos,
- occurrences,
- co-occurrences,
- other strongly related results.

An exact Person-name match normally ranks highly but is not necessarily the only result.

Names remain semantic/retrieval metadata rather than biometric evidence.

---

## 31. Natural-Language Query as Search

Natural-language querying should be integrated with Universal Search rather than treated as a completely separate user-facing subsystem.

Example:

```text
Who appears most frequently with David?
```

may produce ranked People with shared-appearance information.

```text
Show David and Mike together.
```

may produce ranked occurrences, images, and media containing both.

Ranked retrieval helps handle partially ambiguous queries without constantly forcing clarification.

---

## 32. Search Architecture

Universal Search may conceptually use specialized retrievers followed by fusion/ranking:

```text
People Retriever ────────┐
Media Retriever ─────────┤
Occurrence Retriever ────┼──→ Rank/Fusion ──→ Top Results
Visual Retriever ────────┤
Metadata Retriever ──────┘
```

Raw scores from different retrievers must not be assumed directly comparable.

Cross-type ranking/fusion is a separate concern.

### 32.1 Recognition score vs search relevance

These are not equivalent.

Recognition asks:

> How strongly does this face correspond to David?

Search relevance asks:

> How useful/relevant is this result to the user's query?

A movie containing David for forty minutes may rank above a movie containing a single high-confidence two-second appearance even if both contain strongly recognized David.

---

## 33. Search Indexing

Search should not require re-running expensive inference across all original media on every query.

Media ingestion/processing should produce appropriate searchable indexes and metadata.

Conceptually:

```text
Media Processing
      ↓
People / Identity Index
Media Index
Occurrence Index
Visual Retrieval Index
Metadata Index
      ↓
Universal Search
```

Exact index technology remains open.

---

## 34. Query vs Ingest

A temporary search-by-face operation is `QUERY`, not `INGEST`.

```text
QUERY
```

performs temporary analysis and retrieval.

```text
INGEST
```

may create observations, identities, and persistent memory.

A face uploaded only for Search must not automatically become a remembered identity unless the user explicitly imports/adds it.

---

# Lifecycle and Deletion

## 35. Identity Creation

Media processing may first create temporary/local clusters.

A provisional cluster does not necessarily become persistent global memory.

Conceptually:

```text
Local/provisional cluster
       ↓
Enough useful evidence?
       ├── No  → remain local/ephemeral
       └── Yes → persistent CANDIDATE Identity
```

This helps prevent poor/background detections from polluting global memory.

---

## 36. Candidate to Established

The system may autonomously promote a Candidate to Established based on sufficiently strong, coherent evidence.

Relevant evidence may include repeated encounters, cross-source recurrence, quality, diversity, and lack of strong contradiction.

No user approval is required.

---

## 37. Established Identities Can Become Conflicted

A contradiction does not automatically destroy an Established identity.

Example:

```text
Memory maturity: ESTABLISHED
Identity health: UNCERTAIN
```

Further conflict may produce:

```text
Identity health: CONFLICTED
```

Reconciliation then determines whether:

- bad evidence should be removed,
- an association was wrong,
- the identity should split,
- the contradiction was noise.

After correction, health may return to STABLE.

---

## 38. Naming Lifecycle

Generated labels and semantic names are separate.

```text
System display label: PERSON_0041
Primary name: David
Aliases: Dave, David Smith
```

Renaming produces a historical semantic event but does not modify visual evidence.

Internal stable IDs do not change when labels/names change.

---

## 39. Recycle Bin

Deleting managed media first moves it to Recycle Bin.

While recycled:

- original media remains,
- observations remain,
- face crops remain,
- tracks remain,
- appearances remain,
- encounters remain,
- derived processing data remains,
- recognition evidence may remain active while the source is recoverable.

Normal Universal Search should exclude recycled media.

Restoring the source should normally not require reprocessing.

---

## 40. Permanent Source Deletion

Permanent deletion removes source-owned content including, as applicable:

- original media,
- source metadata,
- source tracks,
- source appearances,
- source encounters,
- source observations,
- source face crops,
- source processing artifacts.

Derived state dependent on deleted observations must be invalidated/rebuilt, including relevant:

- recognition memory,
- representations,
- indexes,
- training eligibility,
- ranking features.

---

## 41. Feedback and Permanent Deletion

Historical audit metadata may record that a confirmation/correction occurred, but permanent deletion must not be defeated by retaining copies of deleted biometric payload.

For example, history may preserve:

```text
SOURCE_PERMANENTLY_DELETED
Affected historical identity references: ...
```

but must not preserve the deleted face crop or recoverable visual representation merely as "audit history."

---

## 42. Training Provenance and Deletion

Training examples must retain provenance back to the evidence/source from which they were derived.

If a source is permanently deleted:

- future training datasets must exclude invalidated visual examples,
- derived training eligibility must be invalidated,
- rebuilds should use currently valid evidence only.

### 42.1 Machine-unlearning limitation

V1 does not promise exact removal of a deleted sample's influence from a neural model that was already trained using it.

Model provenance should record relevant dataset/training versions.

Future retraining can exclude deleted evidence.

Exact machine unlearning is a separate future research problem.

---

## 43. Deletion Can Weaken Identity Maturity

If permanent source deletion removes substantial evidence, affected identity maturity and health should be recalculated.

An identity may demote:

```text
ESTABLISHED
    ↓
CANDIDATE
```

if the remaining evidence no longer supports establishment.

---

## 44. Person With No Surviving Visual Evidence

Deleting the final visual source does **not** automatically delete a user-created Person.

This is a locked semantic rule:

> **Delete Media removes media/evidence. Forget Person removes persistent person memory.**

Example:

```text
David

Visual evidence: NONE
Recognition: UNAVAILABLE
Known occurrences: NONE
Human validation: CONFIRMED
Name/aliases: PRESERVED
```

The Person remains in active People because user-authored semantic information survives.

The UI should make clear that recognition is unavailable.

The user may explicitly choose `Forget Person`.

A newly discovered identity must not be attached to this unsupported Person purely because a name matches. User confirmation or valid visual evidence is required.

---

## 45. Unsupported Unnamed Identities

If permanent source deletion removes all evidence for an unnamed machine-generated identity and no meaningful user-authored semantic information remains, it may be removed from active identity memory.

A minimal non-biometric historical tombstone may remain for audit/reference resolution.

`ORPHANED` does not need to be a normal user-facing lifecycle state.

---

## 46. Forget Person

`Forget Person` means:

> Stop maintaining this individual as a persistent remembered identity.

It is different from deleting media.

Forget should remove/inactivate, as appropriate:

- active Person/Identity recognition associations,
- active recognition memory,
- identity-specific derived representations,
- global recognition eligibility,
- active name/alias search mapping for that remembered Person,
- Person-level occurrence resolution.

Underlying source media remains.

Tracks, timestamps, and source-level visual observations remain valid media-analysis data but no longer resolve to the forgotten Person.

---

## 47. Rediscovery After Forget

Forget does **not** mean:

> Never learn this visual pattern again.

If the person appears later:

```text
No remembered match
      ↓
new unknown/candidate
      ↓
PERSON_0192
```

This is correct.

The system must not secretly use forgotten biometric state to reconnect the new identity to the forgotten Person.

Existing evidence detached by Forget should not automatically resurrect the forgotten Person merely because background consolidation runs.

Deliberate reprocessing or genuinely new encounters may produce new unknown identities.

A future "Do Not Remember" or biometric suppression feature would be a separate product capability and is not part of this model.

---

## 48. Forget and Training Eligibility

After Forget, biometric identity-training examples specifically tied to that remembered Person should not continue to be newly used as if the Person remained active memory.

Historical non-biometric audit events may remain.

Exact handling must preserve the distinction between:

- source media that still exists,
- persistent identity memory that the user explicitly removed,
- future rediscovery as a new unknown identity.

---

## 49. Search Index Effects of Forget

Forget should invalidate appropriate:

- Person search entries,
- face-recognition index entries,
- Person occurrence mappings,
- aliases,
- derived Person-level ranking features.

Underlying media remains searchable through its own metadata and through other active identities.

---

# Historical Events

## 50. Historical Event Principle

Identity history should be append-oriented under normal operation.

Corrections and reversals should create new events rather than silently deleting the previous history.

Examples:

```text
MERGE
  ↓
MERGE_REVERSED
```

or:

```text
ASSOCIATION_CONFIRMED
  ↓
ASSOCIATION_REJECTED / REASSIGNED
```

This does not require the entire database to use full Event Sourcing.

Ordinary current-state entities may coexist with dedicated event histories.

---

## 51. Event Granularity

Identity Events represent meaningful state changes.

They should not duplicate frame-level inference logs.

Frame/observation-level processing belongs primarily in Observation/provenance data.

Identity Events include meaningful transitions such as:

### Discovery

- IDENTITY_CREATED
- IDENTITY_PROMOTED
- IDENTITY_DEMOTED
- PERSON_CREATED
- IDENTITY_ATTACHED_TO_PERSON

### Correction

- ASSOCIATION_CONFIRMED
- ASSOCIATION_REJECTED
- ASSOCIATION_REASSIGNED
- IDENTITY_HEALTH_CHANGED

### Reconciliation

- PERSON_MERGED
- MERGE_REVERSED
- PERSON_SPLIT
- IDENTITY_SPLIT
- IDENTITY_RECONCILED

### Semantic

- PERSON_RENAMED
- ALIAS_ADDED
- ALIAS_REMOVED

### Lifecycle / Privacy

- PERSON_FORGOTTEN
- SOURCE_RECYCLED
- SOURCE_RESTORED
- SOURCE_PERMANENTLY_DELETED
- EVIDENCE_INVALIDATED

Training/model history may use a related but separate event stream:

- TRAINING_STARTED
- TRAINING_COMPLETED
- MODEL_EVALUATED
- MODEL_PROMOTED
- MODEL_REJECTED
- MODEL_ROLLED_BACK

Exact event names are conceptual and may change during implementation.

---

## 52. Event Actors and Provenance

Events should identify the actor where meaningful:

- SYSTEM,
- USER,
- potentially REPROCESSING/IMPORT or other explicit system actors later.

Automated identity-changing events should retain enough provenance to answer:

> Why did this happen?

Where appropriate, provenance may include:

- component/model versions,
- decision/reasoning version,
- relevant scores/signals,
- source,
- timestamp,
- affected IDs,
- previous/new state.

Events should not store unnecessary copies of biometric payload.

---

## 53. Stable IDs, Tombstones, and Redirection

Internal IDs should remain stable and should not be casually reused.

Names and canonical relationships may change.

Merged entities may retain tombstones/redirection:

```text
P-27 → canonical P-10
```

Historical references can therefore still be interpreted after reconciliation.

If source content is permanently deleted, historical IDs may remain as non-biometric references while the deleted content itself becomes unavailable.

---

## 54. History Must Not Defeat Deletion

Auditability must not become a loophole for retaining data the user explicitly deleted or forgot.

Historical records should retain the fact and semantics of meaningful events where appropriate, not deleted face crops, recoverable biometric representations, or other payload solely for historical convenience.

---

# Search Feedback and History

## 55. Search Feedback Events

Search feedback should preserve the context in which the feedback occurred.

A feedback record may reference:

```text
Query
Candidate/result set
Original ranking
Result types
Relevant scores/features
Selected result
Rejected result
Ranker/model versions
Timestamp
Actor
```

If a result later merges into another Person, historical references should remain resolvable through stable IDs/tombstones.

If the underlying source is permanently deleted, historical feedback may retain a non-biometric reference while the deleted thumbnail/visual content remains unavailable.

---

# Invariants

## 56. Stable Identity Invariant

Names, labels, maturity, validation, health, and canonical relationships may change.

Stable internal identifiers are not casually recycled.

---

## 57. Destructive Propagation Invariant

Permanent deletion must propagate to dependent derived data.

A source deletion may invalidate:

```text
Source
→ Observations
→ Evidence
→ Representations
→ Indexes
→ Training eligibility
→ Derived recognition/search state
```

No hidden derived copy should silently keep supposedly deleted biometric source data alive.

---

## 58. Evidence Authority Invariant

Historical evidence and explicit corrections are authoritative memory records.

Optimized recognition/search structures are derived and should be rebuildable where valid retained evidence permits.

---

## 59. Human Feedback Integrity Invariant

The system must preserve what the user actually said/did.

Derived labels, preferences, or training examples must not overwrite the original semantic feedback.

Inferred-from-confirmation data must not masquerade as directly user-confirmed data.

---

## 60. Delete Media vs Forget Person Invariant

These operations have different meanings:

```text
Delete Media
→ remove media/source-derived evidence

Forget Person
→ remove persistent person/identity memory
```

Deleting the final visual source does not automatically erase user-authored Person metadata.

---

## 61. Query vs Ingest Invariant

Temporary Search analysis must not silently become persistent memory.

```text
QUERY != INGEST
```

---

## 62. Search Relevance Invariant

Recognition confidence and Search relevance are different quantities.

Search ranking may use recognition signals, but must not equate them.

---

# Locked Decisions Summary

The following decisions are locked for Identity & Memory Model v1.0:

1. Person and machine Identity are separate concepts.
2. A Person may contain multiple visual Identities.
3. Unknown identities can persist and be recognized without names.
4. Recognition is open-set and supports unknown rejection.
5. Observations and explicit feedback form the authoritative historical foundation.
6. Optimized recognition/search structures are derived state.
7. Identity maturity is not assumed to be a single visual multiclass classifier.
8. Machine maturity is EPHEMERAL → CANDIDATE → ESTABLISHED and may demote.
9. EPHEMERAL may remain provisional/local rather than globally persistent.
10. Human Validation is independent and is UNREVIEWED / CONFIRMED.
11. CONFIRMED is human-only and does not require a name.
12. Identity Health independently represents STABLE / UNCERTAIN / CONFLICTED / UNDER_REVIEW.
13. `DISPUTED` is not a Human Validation state.
14. Association certainty and recognition utility are separate.
15. Evidence provenance distinguishes explicit user confirmation from machine inference and derived confirmation context.
16. Evidence can be promoted, demoted, rejected, and negatively constrained.
17. Machine associations must not automatically contaminate trusted active memory.
18. Tracking continuity and co-occurrence are contextual signals, not absolute identity truth.
19. Recognition proposes hypotheses; Identity Reasoning decides what becomes memory.
20. Identity reasoning may combine multiple models/components/signals.
21. Memory retains rich history while active recognition uses curated evidence.
22. Automatic reconciliation is allowed but is conservative, especially for established identities.
23. Person-level merge preserves underlying Identity provenance.
24. Merge and split operations are reversible where data permits and trigger affected derived-state rebuilds.
25. Movie processing may use temporary/local clusters before global identity commitment.
26. Camera memory should consolidate useful evidence rather than learning independently from every frame.
27. Universal Search is heterogeneous ranked retrieval rather than singular identification.
28. Search and Recognition are distinct systems.
29. Search supports text, face, natural-language/contextual, and eventually mixed queries.
30. Search returns People, Images, Videos/Movies, Occurrences/Appearances/Encounters as appropriate.
31. `Top` results may mix result types; specialized tabs may rank independently.
32. Search may use specialized retrievers plus cross-type ranking/fusion.
33. Face Search is temporary QUERY behavior unless explicitly ingested.
34. Human feedback is stored in its original semantic form.
35. Explicit and implicit feedback are distinguished.
36. Weak search behavior does not automatically become biometric ground truth.
37. Actual RLHF is not required.
38. Learning is divided into immediate Memory Learning, periodic Decision/Search/Calibration Learning, and controlled Model/Representation Learning.
39. Training Readiness depends on reliability, diversity, usefulness, novelty, coverage, and related signals—not raw count alone.
40. Training Readiness may be component-specific.
41. Users can manually trigger retraining/improvement.
42. Ask-first, automatic-when-idle, and scheduled modes may be supported.
43. Retraining creates a candidate component/model that must be evaluated before promotion.
44. Previous promoted versions should support rollback where practical.
45. Retraining must account for identity imbalance and redundant evidence.
46. Recycle Bin hides media from normal Search while recoverable evidence may remain active.
47. Permanent deletion invalidates source-owned data and dependent derived state.
48. Future training datasets must exclude permanently deleted source evidence.
49. V1 does not promise exact machine unlearning from already-trained neural models.
50. Deleting the final visual source does not automatically delete a user-created Person.
51. A Person with no surviving visual evidence remains as a semantic Person shell with recognition unavailable.
52. Unsupported unnamed machine identities may be removed from active memory when all evidence disappears.
53. Forget Person removes persistent identity memory but not underlying source media.
54. Forget does not mean permanent biometric suppression.
55. Forgotten biometric state must not secretly reconnect future rediscoveries.
56. Historical events are append-oriented records of meaningful state changes.
57. Historical event storage must not retain deleted biometric payload merely for auditability.
58. Stable IDs/tombstones preserve historical interpretation across merge, split, and deletion.
59. Automated important identity decisions retain sufficient component/decision provenance.
60. Search feedback history preserves original result context and model/ranker provenance.

---

## 63. Deliberately Open Implementation Questions

This specification does **not** lock:

- face detector,
- face representation technique,
- CNN vs transformer vs other architecture,
- recognition algorithm,
- clustering algorithm,
- tracking algorithm,
- evidence thresholds,
- maturity thresholds,
- exact confidence/calibration formula,
- identity-reasoning implementation,
- database technology,
- vector index technology,
- search ranking algorithm,
- query-understanding implementation,
- training-readiness formula,
- fine-tuning strategy,
- retraining cadence,
- model evaluation thresholds,
- exact storage schema,
- exact API shape,
- exact desktop/web application framework,
- CPU/GPU task allocation.

These belong to subsequent architecture/research phases.

---

## 64. Next Planning Domain

With Product Definition & Requirements v1.0 and Identity & Memory Model v1.0 established, the next planning domain is the **Processing Architecture**.

That phase should define, without prematurely selecting concrete models:

```text
Images / Movies / Cameras
        ↓
Decode / Ingest
        ↓
Detection
        ↓
Tracking / Observation Selection
        ↓
Representation / Recognition
        ↓
Identity Reasoning
        ↓
Memory Consolidation
        ↓
Storage / Indexing
        ↓
Universal Search
```

It should also define CPU/GPU concurrency, long-media chunking, checkpointing, live-vs-offline behavior, queues, backpressure, failure recovery, and how derived artifacts move through the system.

---

**End of Identity & Memory Model v1.0**
