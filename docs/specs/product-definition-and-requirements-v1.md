# Product Definition & Requirements v1.0

**Project:** Local Visual Identity System\
**Document:** Product Definition & Requirements\
**Version:** 1.0\
**Status:** Locked product baseline\
**Implementation status:** Technology choices remain open\
**Date:** 18 September 2026

------------------------------------------------------------------------

## 1. Purpose

This document defines the product requirements for a fully local visual
identity system capable of discovering, remembering, recognizing,
organizing, tracking, correcting, and retrieving human visual identities
across images, videos, movies, and live cameras.

This document defines **what the system must do and how the product
should behave**. It intentionally does not prescribe the exact
machine-learning model, recognition representation, tracking algorithm,
database, UI framework, inference runtime, or other implementation
technology.

Those choices will be made during subsequent architecture and
technical-design phases.

------------------------------------------------------------------------

## 2. Product Vision

The product is a **private, local-only visual identity and retrieval
system** whose central question is:

> **Have I seen this person before?**

The system does not require a person's real-world name in order to
remember them.

When it encounters a previously unknown person, it may create an
internal visual identity such as `PERSON_0042`. Future observations from
any supported source may then be associated with that identity. The user
may later rename the identity to a real name, nickname, alias, or any
arbitrary label.

The system shall maintain persistent visual memory across:

-   managed images;
-   managed videos;
-   managed movies;
-   configured cameras;
-   different application sessions; and
-   different source types.

Identity is therefore **source-independent**, while every observation
and encounter remains **source-aware**.

Example:

``` text
PERSON_0042
    |
    +-- Movie A @ 00:17:21
    +-- IMG_3821.jpg
    +-- Camera: Laptop Webcam @ 14:42
    +-- Video B @ 01:03:17

User renames PERSON_0042 -> "David"
```

The historical observations do not change; their identity label does.

------------------------------------------------------------------------

## 3. Product Principles

### 3.1 Local-only core operation

All core biometric and visual-identity functionality shall operate
locally.

The following shall not require a remote inference service:

-   face detection;
-   visual representation;
-   tracking;
-   recognition;
-   identity memory;
-   identity matching;
-   clustering/discovery;
-   search;
-   media processing;
-   user corrections;
-   storage; and
-   core querying.

The system should remain functionally useful when disconnected from the
Internet.

Internet access may eventually be used for optional non-core
functionality such as software updates, but core identity functionality
must not depend on it.

### 3.2 Source-independent identity

The system shall not create separate fundamental identities merely
because the same person was encountered through different media.

A person learned from a movie may later be recognized in:

-   another movie;
-   an uploaded image;
-   a normal video; or
-   a live camera.

The source shall be recorded as encounter metadata rather than treated
as part of the person's identity.

### 3.3 Autonomous, persistent, evidence-aware memory

The system should operate with high autonomy.

It should be capable of:

-   discovering unknown people;
-   creating candidate identities;
-   remembering sufficiently supported identities;
-   recognizing previously encountered people;
-   accumulating useful identity evidence;
-   reconciling likely duplicate identities;
-   recording encounters; and
-   maintaining its visual memory without requiring continuous user
    confirmation.

However, the system must distinguish between:

-   what it directly observed;
-   what it inferred;
-   what it strongly believes;
-   what the user confirmed; and
-   what the user rejected.

Autonomy must not mean blindly reinforcing every machine prediction.

### 3.4 Correctability

Machine-generated identity decisions shall be correctable.

The user shall be able to inspect and correct identity associations
without rebuilding the entire visual database.

### 3.5 Uncertainty is valid

The system shall be allowed to conclude that it does not know who a face
belongs to.

It must not be designed around forcing every observation into an
existing identity.

### 3.6 Evidence over labels

A person's display name is not the identity itself.

An identity may be well established while remaining unnamed.

Names and aliases are user-facing metadata layered over persistent
visual identities.

### 3.7 Hardware-aware performance

The system shall be designed to use available local hardware
efficiently.

It should be capable of using CPU, GPU, memory, and available hardware
media capabilities concurrently where this improves end-to-end
throughput.

No product requirement mandates that a particular stage must run on the
CPU or GPU.

The performance objective is **minimum useful end-to-end processing
time**, not maximum utilization of one specific device.

------------------------------------------------------------------------

## 4. Core Terminology

### 4.1 Person

A conceptual human entity represented within the product.

A person may have:

-   a persistent identifier;
-   a display name;
-   aliases;
-   one or more system identities or identity evidence groups;
-   historical encounters; and
-   user-defined metadata.

### 4.2 Identity

The system's persistent belief that a collection of visual evidence
represents the same person.

An identity may exist without a name.

Example:

``` text
Identity: 82ca...
Display label: PERSON_0041
Status: Established
```

Later:

``` text
Display name: David
```

Changing the display name shall not change the underlying identity.

### 4.3 Observation

A discrete visual measurement of a detected face.

An observation may contain or reference:

-   source;
-   frame or timestamp;
-   bounding box;
-   face imagery;
-   quality information;
-   derived machine-readable visual information;
-   recognition result;
-   confidence/certainty information;
-   model/version information; and
-   identity association.

### 4.4 Track

A continuous sequence of observations believed to represent the same
visible subject over a period of video or camera time.

Example:

``` text
00:18:31 -> 00:18:47
```

Tracks may cross internal processing chunk boundaries.

### 4.5 Appearance

A meaningful occurrence of an identity in a piece of media.

An appearance may contain one or more nearby tracks and multiple
observations.

Example:

``` text
David
Appearance #3
00:23:14 -> 00:25:09
```

### 4.6 Encounter

A higher-level record that a person was encountered through a particular
source.

Examples:

-   David in `movie.mkv`;
-   David in `graduation.jpg`;
-   David on `Laptop Webcam` between 09:01 and 09:14.

An encounter answers **where, when, and how** an identity was seen.

------------------------------------------------------------------------

## 5. Supported Sources

### 5.1 Images

The system shall support images containing:

-   no detectable faces;
-   one face; or
-   multiple faces.

Each useful face may generate observations and may be associated with a
new or existing identity.

### 5.2 Videos

The system shall process uploaded video files and discover, track,
recognize, and index people appearing within them.

Exact supported container and codec formats are an implementation
decision, but common consumer video formats are expected.

### 5.3 Movies

Movies are technically videos but receive richer product-level
treatment.

A processed movie shall support:

-   people discovery;
-   known/unknown identity counts;
-   appearances;
-   tracks;
-   timestamps;
-   representative face snapshots;
-   screen-presence/frequency information;
-   searchable identity indexes;
-   correction workflows; and
-   navigation from an appearance to the corresponding point in the
    movie.

### 5.4 Cameras

A configured camera shall be represented as a source of type `CAMERA`.

A camera may:

-   detect multiple people;
-   track people while visible;
-   recognize previously remembered identities;
-   create new candidate identities;
-   create encounter records;
-   retain selected face observations; and
-   contribute evidence to global visual memory.

Continuous full-camera video recording shall be **off by default**.

Camera encounter history and selected face snapshots shall be retained
by default and remain user-deletable.

------------------------------------------------------------------------

## 6. Identity and Memory Model --- Product Requirements

### 6.1 Automatic identity discovery

When a useful face does not sufficiently correspond to an existing
identity, the system may autonomously create a new candidate identity.

The user shall not be required to approve every new identity during
normal processing.

### 6.2 Identity maturity

The product shall conceptually support different levels of identity
maturity so that one weak detection does not automatically become a
permanent high-confidence identity.

The exact names and thresholds are implementation decisions, but the
model should support concepts equivalent to:

1.  **Ephemeral** --- insufficient evidence for durable memory.
2.  **Candidate** --- evidence suggests a recurring visual identity.
3.  **Established** --- sufficient evidence exists for persistent
    autonomous remembrance.
4.  **Confirmed** --- the user has explicitly confirmed or meaningfully
    labeled the identity.

### 6.3 Evidence certainty

Evidence shall not all carry identical authority.

The system must be capable of distinguishing concepts equivalent to:

-   observed;
-   predicted;
-   strongly associated;
-   user-confirmed;
-   user-rejected; and
-   uncertain.

User-confirmed evidence should be eligible to carry greater authority
than ordinary machine-generated associations.

### 6.4 Autonomous evidence accumulation

When an existing identity is recognized with sufficiently strong
evidence, the system may autonomously retain useful new observations as
identity evidence.

Weak or uncertain observations may be associated tentatively without
being allowed to immediately strengthen the identity's trusted core
evidence.

### 6.5 Feedback

Recognition confirmation shall be optional.

Where useful, the interface may ask:

``` text
Was this identification correct?

[Yes] [No] [Unsure]
```

A positive response may strengthen identity evidence.

A negative response shall remove or invalidate the incorrect association
and should preserve useful negative relationship information where
appropriate.

### 6.6 Cross-media recognition

An identity learned through one source shall be eligible for recognition
through every other supported source.

The system shall not require separate enrollment for each media type.

### 6.7 Rename

Users shall be able to rename an identity without affecting its
underlying visual evidence or encounter history.

### 6.8 Merge

Users shall be able to merge identities believed to represent the same
person.

The operation should preserve enough provenance to support auditing and,
where practical, reversal.

### 6.9 Split

Users shall be able to separate observations, appearances, tracks, or
evidence that were incorrectly grouped into one identity.

### 6.10 Forget identity

The product shall provide an explicit concept of **forgetting an
identity**.

Forgetting a person is different from deleting source media.

A user must not need to delete every movie, image, or camera encounter
merely to remove a persistent identity from visual memory.

Exact destructive semantics will be formalized in the Identity & Memory
design.

### 6.11 Identity event history

Important identity operations should be represented as auditable events,
including concepts such as:

-   automatic creation;
-   automatic association;
-   confirmation;
-   rejection;
-   rename;
-   merge;
-   split;
-   deletion; and
-   forgetting.

This history should make identity evolution explainable and make
undo/recovery possible where feasible.

------------------------------------------------------------------------

## 7. Visual Evidence and Retention

### 7.1 Initial retention policy

V1 shall favor inspectability and recoverability over aggressive storage
optimization.

The system may retain:

-   original managed media;
-   selected original face crops;
-   processed/aligned crops where applicable;
-   representative face imagery;
-   timestamps;
-   bounding boxes;
-   tracks;
-   appearances;
-   encounter records;
-   recognition outputs;
-   quality information;
-   derived visual identity information;
-   user corrections; and
-   model/version metadata.

### 7.2 Meaningful observations rather than every frame

"Keep everything" does **not** require persisting a face crop for every
face in every decoded frame.

For long tracks, the system should be capable of retaining:

-   full presence/timing information; and
-   selected useful observations.

The original managed media remains the lossless source from which
additional frames or crops may be reconstructed.

### 7.3 Core evidence versus cache

The storage design should distinguish between:

**Durable knowledge** - identity decisions; - corrections; - encounter
history; - tracks; - appearances; - timestamps; - derived identity
information; - trusted face evidence.

**Regenerable/cacheable artifacts** - some thumbnails; - preview
frames; - some face crops; - other artifacts reproducible from managed
source media.

Exact caching policy is deferred to technical design.

------------------------------------------------------------------------

## 8. Media Ownership and Lifecycle

### 8.1 System-managed media

Imported images, videos, and movies shall become managed by the
application.

The system shall maintain its own managed copy or otherwise guarantee
that moving the user's original external file does not silently break
the visual identity database.

### 8.2 Recycle Bin

Normal media deletion shall be soft deletion.

Deleted managed media shall enter a Recycle Bin or equivalent temporary
state.

While in the Recycle Bin:

-   media shall disappear from normal library views and searches;
-   its data shall remain recoverable;
-   identity evidence shall not be destructively removed merely because
    of soft deletion; and
-   the user shall be able to restore the media.

### 8.3 Permanent deletion

Permanent deletion shall be explicit and destructive.

Permanently deleting a media source should remove source-owned data
including, as applicable:

-   original managed media;
-   source metadata;
-   source tracks;
-   source appearances;
-   source observations;
-   source face crops;
-   source-derived processing artifacts; and
-   source-specific associations.

An identity supported by other sources shall remain.

### 8.4 Orphaned identities

If permanently deleting a source removes the only remaining evidence
supporting an identity, the system shall detect the resulting
unsupported/orphaned identity.

The final policy for automatically retaining, prompting about, or
removing such identities will be formalized in the Identity & Memory
design.

### 8.5 Delete media is not forget person

The product shall preserve the semantic distinction:

``` text
DELETE MEDIA != FORGET IDENTITY
```

------------------------------------------------------------------------

## 9. Camera History

By default, camera operation should retain:

-   encounter history;
-   timestamps;
-   selected face observations/snapshots;
-   identity associations; and
-   relevant derived identity information.

Continuous full-camera footage shall not be recorded by default.

Future settings may support explicit camera recording and configurable
retention.

Users shall be able to delete:

-   individual camera encounters;
-   selected history;
-   a time range/day of history;
-   all history for a camera; or
-   relevant identities through the separate identity-forgetting
    workflow.

------------------------------------------------------------------------

## 10. Search and Retrieval

### 10.1 Unified Search experience

The user-facing product shall present search and query as a unified
capability.

Internally, interpretation and retrieval may remain separate subsystems.

### 10.2 Search by name

Users shall be able to search by:

-   display name;
-   system-generated identity label; and
-   aliases where supported.

### 10.3 Search by uploaded face

A user shall be able to upload an image containing a face and ask the
system to find matching or potentially matching remembered identities.

### 10.4 Search by camera

A user shall be able to present a face through a configured camera and
search the local visual identity database.

### 10.5 Search within media

Users shall be able to constrain retrieval to a particular:

-   movie;
-   video;
-   image collection;
-   camera; or
-   relevant source scope.

### 10.6 Natural-language queries

The product should support natural-language retrieval questions such as:

-   "When does David appear in this movie?"
-   "Who appears most frequently?"
-   "Show every scene containing David."
-   "Who appears between 35:00 and 42:00?"
-   "Which unidentified person appears most often?"
-   "Show pictures containing David and Mike."
-   "When was this person last seen?"
-   "Who appears most often with David?"

A large language model is **not required** to implement these queries.
Deterministic or structured query interpretation is acceptable.

### 10.7 Retrieval results

Results may include:

-   identities;
-   images;
-   videos;
-   movies;
-   encounters;
-   appearances;
-   tracks;
-   timestamps;
-   face snapshots; and
-   derived statistics.

------------------------------------------------------------------------

## 11. People Discovery Experience

After media processing, the system shall provide a people-discovery view
showing the people found in the source.

A person entry should expose representative face imagery and summary
information such as appearances.

Opening a person shall allow the user to inspect:

-   every meaningful appearance;
-   appearance start/end timestamps;
-   representative face snapshots;
-   underlying selected observations where useful;
-   recognition status;
-   confidence/certainty information where appropriate; and
-   the corresponding source location.

For video/movie appearances, the user shall be able to navigate directly
to the relevant timestamp.

The user should be able to mark an observation as:

-   correct;
-   incorrect;
-   unsure; or
-   belonging to another identity.

The interface shall support identity rename, merge, split, and related
correction workflows.

------------------------------------------------------------------------

## 12. Review Inbox

V1 should provide a non-blocking review area for uncertain or suspicious
identity decisions.

Examples include:

-   possible duplicate identities;
-   possible matches to an existing identity;
-   low-quality candidate identities;
-   potentially incorrect groupings; and
-   unresolved observations.

Review shall generally be optional.

The processing pipeline should not stop repeatedly to request user
confirmation.

------------------------------------------------------------------------

## 13. Movie and Long-Video Processing

### 13.1 Incremental processing

Long media shall be processable incrementally rather than requiring the
entire file to remain in memory or complete one monolithic operation.

### 13.2 Processing chunks

The processing engine may divide media into bounded chunks.

A **media chunk** is an internal processing subdivision and is distinct
from a face track or inference batch.

Tracks and identities must not be artificially fragmented merely because
they cross a chunk boundary.

### 13.3 Frame batches

Frames or observations may be processed in batches where doing so
improves hardware utilization.

Batch sizing is an implementation decision.

### 13.4 Tracking to reduce redundant recognition

The system should avoid unnecessarily performing full identity analysis
independently on every frame.

Once a subject is being tracked, the system may use selected
observations and periodic verification rather than repeatedly performing
expensive recognition on every frame.

### 13.5 Best-face selection

The system should be capable of evaluating observations within a track
and selecting stronger identity evidence based on useful quality
criteria.

Poor observations may still remain valid evidence of presence even when
they are weak evidence of identity.

### 13.6 Adaptive processing

Processing intensity should be allowed to vary according to scene and
tracking conditions.

Examples that may justify increased analysis include:

-   scene changes;
-   new faces;
-   lost tracks;
-   uncertain identity;
-   difficult visibility; and
-   crowded scenes.

Stable known tracks may permit reduced expensive inference.

The exact strategy is deferred.

### 13.7 Chunk reconciliation

Identities and tracks produced near chunk boundaries shall be
reconcilable so that the same person is not treated as a different
person solely because processing crossed an internal chunk boundary.

### 13.8 Resume

Long-running media processing shall support recovery/resumption without
restarting the entire media item wherever practical.

### 13.9 Pause and cancel

V1 shall support pausing/resuming and cancelling long-running processing
jobs.

### 13.10 Reusable processing stages

The processing architecture should support retaining useful intermediate
results so that future model improvements do not necessarily require
repeating every earlier stage.

For example, a future recognition change may be able to reuse previously
produced observations rather than fully decoding and reprocessing the
original movie.

Exact reusable artifacts depend on the chosen technical architecture.

------------------------------------------------------------------------

## 14. Heterogeneous CPU/GPU Processing

### 14.1 Requirement

The system shall support a processing architecture capable of using CPU
and GPU concurrently where appropriate.

Potential workloads include:

-   media decoding;
-   metadata extraction;
-   preprocessing;
-   scene analysis;
-   inference;
-   tracking;
-   post-processing;
-   identity reasoning;
-   indexing; and
-   storage.

This document does not assign those tasks to specific hardware.

### 14.2 Pipeline concurrency

The processing engine should support overlapped stages.

Conceptually:

``` text
CPU: decode/preprocess batch N+1
GPU: process batch N
CPU: post-process/index batch N-1
```

The exact pipeline will be determined by benchmarking.

### 14.3 Performance objective

The primary performance metric for long media should be useful
end-to-end processing throughput.

A useful user-facing metric is processing speed relative to realtime,
for example:

``` text
4.7x realtime
```

### 14.4 Processing profiles

The architecture should permit future resource profiles such as:

-   Fast;
-   Balanced; and
-   Background.

These profiles are not required to use a particular implementation in
V1.

------------------------------------------------------------------------

## 15. V1 Processing Status UI

Detailed processing status is a V1 product requirement.

For long-running media jobs, the UI shall expose, where measurable:

-   file/source name;
-   media duration;
-   overall progress;
-   current processing stage;
-   current media position;
-   elapsed time;
-   estimated remaining time where estimable;
-   faces detected;
-   tracks created;
-   people discovered;
-   known identities;
-   new/unknown identities;
-   CPU utilization;
-   GPU utilization;
-   RAM utilization;
-   VRAM utilization;
-   processing throughput;
-   pause control;
-   resume control; and
-   cancel control.

The UI should avoid pretending to know an accurate ETA when insufficient
information exists.

------------------------------------------------------------------------

## 16. Storage Management

Because the system manages local media and retained identity evidence,
V1 shall include basic storage visibility and management.

The UI should be capable of showing storage categories such as:

-   original media;
-   face observations;
-   derived model/identity data;
-   thumbnails/cache;
-   database;
-   Recycle Bin; and
-   total application storage.

Exact categories may evolve with implementation.

Storage optimization may be improved after real usage data is available.

------------------------------------------------------------------------

## 17. Model and Processing Traceability

Machine-generated identity information should be traceable to the
processing configuration that produced it.

Where relevant, derived data should be able to record:

-   detector/model identifier;
-   model version;
-   representation/recognition model identifier;
-   algorithm/version;
-   processing configuration/profile; and
-   creation time.

This supports:

-   debugging;
-   selective reprocessing;
-   model upgrades;
-   comparison of processing versions; and
-   auditing identity decisions.

------------------------------------------------------------------------

## 18. Functional Requirements

  -----------------------------------------------------------------------
  ID                                  Requirement
  ----------------------------------- -----------------------------------
  FR-001                              Detect multiple faces in an image.

  FR-002                              Detect multiple faces in uploaded
                                      video/movie media.

  FR-003                              Detect multiple faces from a
                                      configured live camera.

  FR-004                              Create candidate identities for
                                      previously unknown people without
                                      mandatory user intervention.

  FR-005                              Recognize sufficiently supported
                                      previously encountered identities.

  FR-006                              Persist identities across
                                      application sessions.

  FR-007                              Persist and recognize identities
                                      across different source types.

  FR-008                              Track visible people through video
                                      and camera streams.

  FR-009                              Record source-aware encounter
                                      history.

  FR-010                              Record meaningful appearance
                                      timestamps/ranges.

  FR-011                              Retain selected face observations
                                      and representative imagery.

  FR-012                              Maintain source-independent
                                      identity records.

  FR-013                              Allow identities to remain unnamed.

  FR-014                              Allow identities to be renamed.

  FR-015                              Support identity aliases where
                                      applicable.

  FR-016                              Merge identities.

  FR-017                              Split incorrectly grouped identity
                                      evidence.

  FR-018                              Confirm recognition results.

  FR-019                              Reject incorrect recognition
                                      results.

  FR-020                              Record uncertainty without forcing
                                      an identity match.

  FR-021                              Learn from trusted user feedback
                                      without requiring model retraining
                                      for every correction.

  FR-022                              Accumulate useful identity evidence
                                      autonomously when confidence is
                                      sufficient.

  FR-023                              Distinguish machine-inferred
                                      evidence from user-confirmed
                                      evidence.

  FR-024                              Search identities by name/label.

  FR-025                              Search the identity memory using an
                                      uploaded face.

  FR-026                              Search the identity memory using a
                                      camera-observed face.

  FR-027                              Search within a selected
                                      media/source scope.

  FR-028                              Support
                                      higher-level/natural-language
                                      identity and appearance queries.

  FR-029                              Show every meaningful appearance of
                                      a selected identity in processed
                                      media.

  FR-030                              Show representative face
                                      snapshot(s) for appearances.

  FR-031                              Navigate from a video/movie
                                      appearance to its source timestamp.

  FR-032                              Calculate appearance/frequency
                                      statistics.

  FR-033                              Identify frequently appearing
                                      unnamed identities.

  FR-034                              Provide a people-discovery view
                                      after processing.

  FR-035                              Provide an optional Review Inbox
                                      for uncertain identity decisions.

  FR-036                              Process long videos incrementally.

  FR-037                              Support internal media chunking
                                      without making identity
                                      source/chunk-dependent.

  FR-038                              Reconcile tracks/identities across
                                      chunk boundaries.

  FR-039                              Support batching where useful.

  FR-040                              Use tracking to reduce redundant
                                      identity processing.

  FR-041                              Select useful/high-quality
                                      observations from tracks.

  FR-042                              Support adaptive processing
                                      intensity.

  FR-043                              Resume interrupted long-running
                                      processing where practical.

  FR-044                              Pause and resume active
                                      long-running processing.

  FR-045                              Cancel active processing.

  FR-046                              Expose detailed V1 processing
                                      status and hardware utilization.

  FR-047                              Support concurrent/overlapped
                                      processing stages where beneficial.

  FR-048                              Use suitable available CPU and GPU
                                      resources without prescribing a
                                      fixed division of work.

  FR-049                              Manage imported
                                      images/videos/movies within
                                      application-owned storage.

  FR-050                              Soft-delete managed media into a
                                      Recycle Bin.

  FR-051                              Restore media from the Recycle Bin.

  FR-052                              Permanently delete managed media
                                      and its source-owned derived data.

  FR-053                              Preserve identities supported by
                                      other sources when one source is
                                      permanently deleted.

  FR-054                              Distinguish deleting media from
                                      forgetting an identity.

  FR-055                              Provide an explicit
                                      identity-forgetting workflow.

  FR-056                              Retain camera encounter history by
                                      default.

  FR-057                              Retain selected camera face
                                      snapshots by default.

  FR-058                              Keep continuous full-camera
                                      recording disabled by default.

  FR-059                              Allow camera history to be deleted
                                      by the user.

  FR-060                              Provide basic V1 storage
                                      visibility/management.

  FR-061                              Preserve identity correction/audit
                                      history where appropriate.

  FR-062                              Record model/processing version
                                      information for relevant derived
                                      results.

  FR-063                              Support reprocessing/re-evaluation
                                      strategies that can reuse retained
                                      intermediate information where
                                      possible.

  FR-064                              Operate core visual-identity
                                      functionality without Internet
                                      access.
  -----------------------------------------------------------------------

------------------------------------------------------------------------

## 19. Non-Functional Requirements

### NFR-001 --- Privacy

Biometric and visual identity processing shall remain local for core
operation.

### NFR-002 --- Data ownership

Managed identity data and managed media shall remain under the user's
local control.

### NFR-003 --- Explainability

The system should expose enough evidence and provenance for users to
understand and inspect why observations are associated with identities.

### NFR-004 --- Correctability

Automatic identity decisions must be correctable.

### NFR-005 --- Recoverability

Long-running processing should survive ordinary interruption without
unnecessary full restart.

### NFR-006 --- Uncertainty handling

The system shall support unknown and uncertain states.

### NFR-007 --- Scalability

The architecture shall not assume only a handful of identities. It
should be designed to remain practical with at least thousands of local
identities, subject to benchmarking.

### NFR-008 --- Hardware acceleration

The architecture shall support local hardware acceleration and efficient
CPU/GPU cooperation where beneficial.

### NFR-009 --- Responsiveness

Live-camera operation should prioritize bounded latency and responsive
recognition/tracking.

### NFR-010 --- Offline media throughput

Offline media processing should prioritize useful accuracy while
minimizing end-to-end processing time.

### NFR-011 --- Auditability

Important identity mutations and model-generated associations should
preserve sufficient provenance for debugging and review.

### NFR-012 --- Storage transparency

The user should be able to understand how much local storage the
application consumes and what categories are responsible.

### NFR-013 --- Deletion integrity

Permanent deletion operations shall clearly distinguish recoverable soft
deletion from irreversible deletion.

### NFR-014 --- Extensibility

The product architecture shall not depend on one fixed recognition
technique, model family, or identity representation.

### NFR-015 --- Reprocessability

The architecture should permit model evolution and selective
re-evaluation of retained data without always requiring full
source-media processing.

### NFR-016 --- Security

Stored biometric and identity information shall be treated as sensitive
local data. Technical design shall consider appropriate access control,
local data protection, encryption where appropriate, and safe
destructive deletion semantics.

------------------------------------------------------------------------

## 20. V1 User-Facing Capabilities

V1 is expected to include the following primary product areas.

### 20.1 People

A visual identity library containing:

-   named identities;
-   unnamed identities;
-   representative imagery;
-   encounter history;
-   appearances;
-   corrections;
-   rename/merge/split controls; and
-   identity forgetting.

### 20.2 Media

A managed library for:

-   images;
-   videos;
-   movies;
-   processing state;
-   people found;
-   appearances;
-   source navigation; and
-   deletion/recycle lifecycle.

### 20.3 Live

A camera experience capable of:

-   detecting multiple faces;
-   tracking visible people;
-   recognizing remembered identities;
-   creating candidate identities;
-   recording encounters; and
-   optionally contributing evidence to identity memory.

### 20.4 Search

One unified interface supporting:

-   name/label search;
-   face upload;
-   camera face search;
-   source-scoped search; and
-   natural-language-style retrieval.

### 20.5 Review

A non-blocking inbox for uncertain or suspicious identity associations.

### 20.6 Processing

A detailed processing-status experience for long-running media jobs.

### 20.7 Storage / Recycle Bin

Basic local storage visibility, media recovery, and permanent deletion
controls.

------------------------------------------------------------------------

## 21. Out of Scope / Non-Goals for V1

The following are not required by this product definition:

-   emotion detection;
-   personality inference;
-   age estimation;
-   gender inference;
-   race or ethnicity inference;
-   Internet identity discovery;
-   scraping social networks to identify people;
-   celebrity-database lookup;
-   automatic discovery of legal names;
-   body-only recognition;
-   gait recognition;
-   voice recognition;
-   general object recognition;
-   automatic movie plot understanding;
-   cloud-hosted biometric processing; or
-   mandatory continuous camera recording.

The product is intended to answer:

> "Have I encountered this visual identity in my local visual memory?"

It is not intended to identify arbitrary strangers using external
databases.

------------------------------------------------------------------------

## 22. Technology and Implementation Choices Intentionally Left Open

The following are **not locked by Product Definition v1.0**:

### 22.1 Identity representation

The system is not required to use embeddings.

Possible approaches may include:

-   learned feature representations;
-   embeddings;
-   CNN-derived representations;
-   transformer-derived representations;
-   Siamese/metric-learning systems;
-   classifiers;
-   prototypes/templates;
-   hybrid systems;
-   ensembles; or
-   future/custom approaches.

The requirement is simply that the system can maintain machine-usable
visual identity information sufficient for recognition and memory.

### 22.2 Model sourcing

Components may use:

-   pretrained models;
-   fine-tuned/adapted models;
-   models trained specifically for the application; or
-   models trained from scratch.

The decision will be based on evidence including:

-   accuracy;
-   generalization;
-   dataset requirements;
-   training cost;
-   inference speed;
-   local hardware requirements;
-   maintainability;
-   licensing; and
-   control.

### 22.3 Algorithms and frameworks

Not yet locked:

-   face detector;
-   recognition algorithm;
-   representation architecture;
-   tracking algorithm;
-   clustering algorithm;
-   similarity/search method;
-   vector indexing strategy;
-   database;
-   local media framework;
-   desktop framework;
-   backend framework;
-   inference runtime;
-   GPU runtime;
-   natural-language query mechanism;
-   storage format; and
-   exact CPU/GPU workload allocation.

These belong to later research and architecture decisions.

------------------------------------------------------------------------

## 23. Technology Research Areas

Before technical architecture is locked, research should cover:

### Computer vision

-   face detection;
-   face alignment;
-   face verification;
-   face identification;
-   open-set recognition;
-   closed-set recognition;
-   face re-identification;
-   metric learning;
-   contrastive learning;
-   self-supervised visual learning;
-   face quality assessment;
-   occlusion and pose handling.

### Architectures

-   CNNs;
-   Vision Transformers;
-   hybrid CNN/Transformer systems;
-   Siamese networks;
-   triplet networks;
-   metric-learning architectures.

### Identity memory

-   embeddings and other feature descriptors;
-   identity prototypes;
-   multi-template recognition;
-   template aggregation;
-   prototype learning;
-   continual/incremental identity learning.

### Tracking

-   multi-object tracking;
-   tracking-by-detection;
-   re-identification;
-   tracklets;
-   track association;
-   track stitching.

### Unknown-person discovery

-   clustering;
-   online clustering;
-   DBSCAN;
-   HDBSCAN;
-   agglomerative clustering.

### Video processing

-   FFmpeg;
-   PyAV;
-   OpenCV;
-   hardware decoding;
-   NVDEC or equivalent acceleration;
-   frame sampling;
-   seeking;
-   scene-change detection;
-   keyframes.

### Hardware optimization

-   heterogeneous CPU/GPU pipelines;
-   CUDA;
-   cuDNN;
-   TensorRT;
-   ONNX Runtime;
-   OpenVINO;
-   CPU SIMD;
-   multithreading;
-   multiprocessing;
-   asynchronous pipelines;
-   GPU batching;
-   pinned memory;
-   zero-copy concepts;
-   hardware video decoding.

------------------------------------------------------------------------

## 24. Performance Philosophy

Performance shall be measured primarily by useful end-to-end behavior.

For long media, relevant measurements include:

-   time to process;
-   processing speed relative to realtime;
-   identity accuracy;
-   unknown rejection quality;
-   track continuity;
-   resource utilization;
-   storage growth; and
-   ability to resume/reprocess.

The system should not maximize GPU utilization at the expense of total
throughput.

The preferred architecture will be determined through benchmarks on
target hardware.

------------------------------------------------------------------------

## 25. Privacy and Security Expectations

The system stores biometric information and shall treat it accordingly.

The technical design shall address:

-   local-only biometric inference;
-   protection of managed identity data;
-   clear deletion semantics;
-   access to managed media;
-   encryption where appropriate;
-   separation of soft deletion and permanent deletion;
-   identity forgetting;
-   auditability of corrections;
-   retention settings; and
-   safe handling of camera history.

The system shall not silently send face imagery or derived biometric
identity information to remote services.

------------------------------------------------------------------------

## 26. V1 Acceptance Criteria

Product Definition v1.0 will be considered successfully represented by
an implementation when the following high-level behaviors are
demonstrable.

1.  A user can import an image containing multiple people and the system
    can discover individual faces.
2.  A user can process a video/movie and receive a people-found index.
3.  Opening a discovered person shows meaningful appearances,
    timestamps, and representative face imagery.
4.  The user can jump from an appearance to the corresponding
    video/movie timestamp.
5.  The system can create unnamed identities and remember them across
    application sessions.
6.  A person discovered in one source can later be recognized from a
    different supported source without manual re-enrollment.
7.  A live camera can detect and track multiple faces and attempt
    recognition against local visual memory.
8.  Camera encounters can contribute to local identity history.
9.  Users can rename, confirm, reject, merge, and split identity
    information.
10. The system supports an explicit distinction between deleting source
    media and forgetting a person.
11. Search works by identity name/label.
12. Search can use an uploaded face.
13. Search can use a camera-observed face.
14. The product can answer supported source/appearance queries such as
    when a person appears and who appears most frequently.
15. Long-video processing exposes detailed V1 progress and hardware
    status.
16. Long-video processing can be paused/cancelled and resumed where
    applicable.
17. Internal processing boundaries do not make identity fundamentally
    chunk-dependent.
18. Managed media can be moved to a Recycle Bin and restored.
19. Permanent deletion removes the selected source and its source-owned
    data while preserving identities supported elsewhere.
20. The product provides basic visibility into local storage
    consumption.
21. Core recognition, memory, media processing, and search remain
    operational without Internet access.
22. Machine uncertainty can remain unresolved instead of being forcibly
    assigned to an existing person.
23. User-confirmed and machine-inferred identity evidence can be
    distinguished.
24. Relevant derived decisions retain sufficient processing/model
    provenance for later inspection or reprocessing.

------------------------------------------------------------------------

# 27. Pre-Lock Review Record

This section records the assumptions, concerns, inferences, and
decisions identified during planning. Product-level decisions listed
here are now part of the v1.0 baseline unless explicitly reopened in a
later revision.

## 27.1 Assumptions

The following remain assumptions to validate through prototyping and
benchmarking:

1.  A consumer workstation can provide acceptable local processing
    performance for long movies.
2.  Concurrent CPU/GPU processing will improve end-to-end throughput for
    at least some stages.
3.  Chunked/incremental processing can improve manageability,
    resumability, and potentially throughput without materially harming
    identity continuity.
4.  Tracking can substantially reduce the amount of redundant expensive
    recognition required.
5.  A limited set of selected face observations can provide sufficient
    identity evidence while the original media preserves
    reconstructability.
6.  Cross-media visual recognition can reach useful reliability under
    realistic variations in lighting, pose, quality, age, makeup,
    occlusion, and compression.
7.  User feedback can improve identity memory without requiring frequent
    full neural-network retraining.
8.  Thousands of identities can be managed practically on local hardware
    with an appropriate search/indexing strategy.
9.  Natural-language-style queries can initially be mapped to structured
    retrieval without requiring a large local language model.
10. Retaining rich processing artifacts during early versions will
    provide enough debugging and model-development value to justify the
    storage cost.

## 27.2 Concerns

The following risks require explicit technical attention:

### Identity contamination

A false match that is automatically accepted as trusted evidence could
reinforce itself and damage future recognition.

Mitigation must include evidence certainty, uncertainty states,
conservative promotion of evidence, correction, and auditability.

### Cross-media false matches

Faces may vary significantly across movies, cameras, photographs,
lighting conditions, ages, makeup, hairstyles, glasses, occlusion,
compression, and pose.

### Identity fragmentation

The same person may be incorrectly created as several identities.

Merge/reconciliation is therefore a core capability rather than an
optional administrative feature.

### Incorrect merging

Different people---especially visually similar people---may be grouped
into one identity.

Split and provenance-preserving reconciliation are required.

### Storage growth

Managed source media plus observations, crops, representations, indexes,
and history can consume substantial disk space.

Storage visibility is therefore required in V1, with deeper optimization
deferred until real usage can be measured.

### Camera-history growth

Long-running cameras can generate large amounts of history. Continuous
recording is therefore disabled by default, while encounter/snapshot
retention remains user-controlled.

### Processing time

High-resolution, high-frame-rate, crowded, or long video may be
expensive to process locally.

### Thermal and resource pressure

Aggressive local CPU/GPU processing may affect laptop temperature, power
consumption, fan noise, and foreground usability.

### Training-from-scratch ambition

Training custom models from scratch may require more curated data and
compute than is justified. This remains an option, not a product
requirement.

### Open-set recognition

Correctly rejecting unknown people may be as important as correctly
matching known people. Thresholds and confidence policies must be
validated rather than guessed.

### Reprocessing compatibility

Model changes may invalidate old derived information. Versioning and
reusable processing stages must be designed carefully.

### Biometric sensitivity

The application maintains sensitive local biometric identity
information. Local-only processing reduces remote exposure but does not
eliminate local security and deletion risks.

## 27.3 Inferences

The locked requirements imply several architectural consequences even
though they do not yet dictate specific technologies.

1.  The identity system must be global across sources rather than scoped
    to one movie.
2.  Source and encounter information must be modeled separately from
    persistent identity.
3.  A single `IdentityManager` should not become an unrestricted God
    object; persistence will likely require domain-specific
    repository/storage boundaries.
4.  The system needs a job-processing model for long-running media.
5.  Processing jobs need persistent state if pause/resume and crash
    recovery are to work reliably.
6.  Identity corrections need provenance/history rather than simple
    destructive database edits.
7.  The system needs some mechanism for machine-comparable identity
    information, even though its exact form is intentionally open.
8.  Unknown-person discovery requires a method for grouping recurring
    observations.
9.  Cross-source recognition requires a global search/matching
    capability.
10. Movie appearance navigation requires reliable
    timestamp/frame-to-source mapping.
11. Keeping original managed media makes some derived visual artifacts
    regenerable and therefore suitable for caching.
12. Permanent source deletion requires dependency-aware cleanup.
13. Identity forgetting requires semantics independent of media
    deletion.
14. Detailed processing status requires system telemetry for CPU, GPU,
    RAM, VRAM, job stages, and throughput.
15. Local-only natural-language querying may eventually justify a local
    language model, but the initial query layer does not require one.
16. Model evolution requires processing/model version metadata.
17. High autonomy requires stronger internal uncertainty and
    evidence-state modeling than a purely manual enrollment system.
18. The Review Inbox is a natural consequence of autonomous processing
    plus non-blocking human correction.

## 27.4 Decisions

The following product decisions are locked for v1.0:

1.  The product is a **local visual identity system**, not merely a
    face-recognition demo.
2.  Core identity functionality is **local-only** and must not depend on
    cloud biometric inference.
3.  Identities are **source-independent**.
4.  Encounters and observations are **source-aware** and shall record
    where/when a person was seen.
5.  The system supports managed images, videos, movies, and configured
    cameras.
6.  Imported image/video/movie media is managed by the application.
7.  Cameras are represented as camera sources rather than imported media
    files.
8.  The system should operate with high autonomy.
9.  Unknown people may be discovered and remembered without constant
    user approval.
10. Autonomous memory shall be evidence-aware rather than blindly
    self-reinforcing.
11. The system shall distinguish machine inference from
    user-confirmed/rejected evidence.
12. User feedback is optional during ordinary recognition.
13. Identity name and visual identity are separate concepts.
14. Identities may remain unnamed indefinitely.
15. The user may assign any desired name/label.
16. Cross-media remembrance is required.
17. The system shall retain encounter history.
18. People-discovery results shall expose all meaningful appearances and
    associated timestamps/snapshots.
19. User correction of observations is a core feature.
20. Rename, merge, split, and forget are core identity operations.
21. Search and query are unified as one user-facing feature.
22. Search shall support name, uploaded face, camera face, source scope,
    and higher-level queries.
23. Long media shall support incremental/chunked processing.
24. Internal chunks shall not define identity.
25. Tracking should be used to avoid unnecessary repeated identity
    analysis.
26. The system may adapt processing intensity according to
    scene/tracking conditions.
27. CPU and GPU should both be available to the processing architecture.
28. No fixed CPU/GPU task allocation is locked before benchmarking.
29. Detailed processing status is part of the V1 UI.
30. V1 processing status includes progress, stage, media position,
    elapsed time, ETA where possible, identity/detection statistics,
    hardware utilization, throughput, pause/resume, and cancel.
31. Original managed media and useful face imagery/derived identity
    information are retained initially.
32. Storage optimization is intentionally deferred until real usage can
    inform it.
33. Continuous camera video recording is off by default.
34. Camera encounter history and selected face snapshots are retained by
    default and are user-deletable.
35. Media deletion first moves content to a Recycle Bin.
36. Recycle Bin deletion is recoverable until permanent deletion.
37. Permanent media deletion removes source-owned media and derived
    data.
38. Deleting media is not equivalent to forgetting a person.
39. Storage visibility/management is part of V1.
40. Model/algorithm/processing traceability is required where relevant.
41. The system is **not locked to embeddings, CNNs, transformers, or any
    other specific identity technique**.
42. Pretrained, fine-tuned, custom, and from-scratch models are all
    valid research options.
43. Exact models, frameworks, databases, algorithms, runtimes, and
    storage formats remain open implementation decisions.

------------------------------------------------------------------------

## 28. Lock Status

**Product Definition & Requirements v1.0 is locked as the product
baseline.**

Future work may clarify or amend this specification through explicitly
versioned revisions, but implementation work should not silently change
the product decisions recorded here.

The next design phase should define:

> **Identity & Memory Model**

That phase should formalize the lifecycle and relationships among
Person, Identity, Observation, Track, Appearance, Encounter, Evidence,
Match, Confirmation, Rejection, Merge, Split, Forget, and related
persistence behavior before implementation architecture is finalized.
