# Universal Search & Retrieval Architecture v1.0

**Status:** Locked  
**Version:** 1.0

## 1. Purpose and boundary

Universal Search is the query-time layer for finding and explaining relevant people, media, appearances, encounters, and analytical answers across the local library. It consumes the product's existing identity/memory and processing outputs; it does not replace their responsibilities.

This document preserves the established boundaries:

- The Identity & Memory architecture determines what an observation is associated with, how certain that association is, and how user feedback changes it.
- The Processing architecture creates and persists sources, observations, tracks, appearances, encounters, representations, provenance, and processing state.
- Universal Search interprets a request, retrieves eligible evidence-derived candidates, ranks and presents them, and records search feedback.

**Recognition is not Universal Search.** Recognition answers: *who might this face be?* Search answers: *what in the library is relevant to this request?* A face query can use Recognition, but the two outcomes remain distinct.

## 2. Query-time architecture

`Query != Ingest.` Importing and processing build durable evidence and derived indexes. Querying reads that state and must not silently turn a search-time guess into a new identity association or persistent evidence. Explicit user feedback follows the Identity & Memory feedback path.

```text
SearchQuery
  -> Query Understanding
  -> Search Planner
  -> Retrieval or Aggregation Plan
  -> Candidate Generation
  -> Constraint Filtering
  -> Type-specific Ranking
  -> Cross-type Fusion and Diversification
  -> Response + Ranking Provenance + Feedback Capture
```

### SearchQuery and query understanding

`SearchQuery` is the structured query-time representation produced from one or more inputs:

- **Text queries:** names, media terms, dates, and natural-language questions.
- **Face queries:** a supplied face image or crop.
- **Mixed queries:** text and face together, such as “find pictures of this person with David.”

Query Understanding identifies intended entities, result scope, requested source/media type, time constraints, co-occurrence intent, and whether the request is retrieval or aggregation. It distinguishes:

- **Hard constraints** — conditions a candidate must meet, such as “David in videos from last month.”
- **Soft preferences** — relevance signals, such as “recent videos of David.”

Hard constraints filter eligible candidates before ranking where possible. Soft preferences are query-conditioned ranking features, not filters.

### Search Planner

The Search Planner selects an appropriate plan rather than forcing every request through one retriever or one ranker.

- A **retrieval plan** returns library items or evidence-backed result cards.
- An **aggregation plan** computes a requested measure over eligible evidence, for example “Who appears most frequently with David?”

The planner may combine multiple retrieval paths for mixed queries. It must preserve the difference between a candidate-generation score and a final relevance decision.

## 3. Retrieval

Universal Search uses specialized retrievers whose scores are meaningful only within their own retrieval task:

- **People retriever:** names, aliases, stable person/identity references, and eligible face/identity candidates.
- **Media retriever:** images, videos, movies, and other processed sources.
- **Occurrence retriever:** appearances, observations, tracks, and time-specific evidence within media.
- **Co-occurrence retriever:** direct shared visibility and supported scene/encounter relationships.

Text, face, and mixed queries may use several retrievers. A face representation can retrieve visual candidates, but vector similarity is a candidate signal, not an identity verdict and not a universal relevance score.

**Qdrant is one derived retrieval backend** for vector/nearest-neighbor candidate generation and metadata-filtered search. It is not authoritative memory. The primary database and retained files/evidence remain authoritative; Qdrant entries are versioned derived index state and can be rebuilt from retained authoritative evidence when possible. Incompatible representation spaces must not be silently compared.

## 4. Face-query presentation

Face queries first use the established Recognition path for identity candidates, including `UNKNOWN` as a valid outcome.

If Recognition produces a strong accepted identity, Search shows that identity as a separate **Identity Answer**. It is not rank #1 in the ordinary result list. Under it, independently ranked search results can include relevant media, occurrences, and encounters.

If no candidate reaches recognition acceptance, no identity is pinned. Search may show clearly labeled **Possible People** and visually similar results, preserving their uncertainty. A nearest visual result must never be presented as a confirmed identity solely because it was retrieved first.

## 5. Ranking, fusion, and heterogeneous Top

Candidate generation answers “what could match?” Ranking answers “what is most useful for this query?” Retrieval scores such as face similarity, name-match type, appearance count, or recency are not directly comparable and must not be combined as a simplistic universal raw-score formula.

Candidates are normalized into type-appropriate features. Examples include query-name match, requested-person satisfaction, identity certainty, evidence quality, source completeness, appearance count or duration, recency, human confirmation, co-occurrence strength, and query-constraint match. Identity certainty establishes trust in an association; it is a ranking feature, not relevance itself.

Ranking occurs in two stages:

1. Rank candidates within their own result type: People, Media, Occurrences, and Encounters.
2. Fuse those lists into a heterogeneous **Top** result, then diversify it.

Top must not be a single giant sort that repeats the same source or closely adjacent occurrences. Diversification considers result type, source, person, time proximity, and near-duplicate content while retaining relevance. Type-specific views may use their native rankings directly.

For multi-person requests, joint satisfaction and co-occurrence evidence are central features; a source containing people separately is not interchangeable with evidence that they are together.

Each response retains ranking provenance sufficient to reproduce a result: query interpretation, plan, participating retrievers and versions, candidate features, ranker version, representation version where relevant, applied constraints, and final ordering.

## 6. Co-occurrence and aggregation

Co-occurrence has an explicit evidence hierarchy:

```text
DIRECT_CO_VISIBILITY        strongest
SAME_SCENE / SAME_ENCOUNTER supported inference
TEMPORAL_PROXIMITY          supporting evidence only
```

People may be considered together when directly visible together, or when appearances belong to the same sufficiently supported scene/encounter—even if editing prevents same-frame visibility. Temporal closeness alone must not establish co-occurrence across a likely scene boundary.

Aggregation queries do not use the ordinary heterogeneous Top ranker. They resolve entities, retrieve eligible appearances/encounters, compute the requested relation or measure, group and rank the result, and return drill-down evidence. Analytical output is uncertainty-aware: tentative associations must not silently count as equivalent to confirmed or strong evidence. Results may separate strong evidence from additional possible evidence, with supporting occurrences available for inspection.

Unknown but persistent identities remain searchable; naming is metadata, not a prerequisite for retrieval.

## 7. Completeness, authority, and degraded operation

Search results must accurately reflect processing coverage. A source that is unprocessed, partially processed, failed, stale, or awaiting index work may yield incomplete results. Responses and aggregate answers should expose applicable completeness/coverage state rather than imply exhaustive library-wide results.

Authoritative resolution remains outside the retrieval index:

- Authoritative people, identities, associations, evidence state, feedback, and processing state come from the existing primary identity/memory and processing stores.
- Derived indexes accelerate discovery and may be stale, unavailable, or rebuilding.
- If an index is degraded, Search may use available authoritative metadata and healthy derived paths, return clearly degraded or partial results, and schedule/rely on rebuild or reconciliation. Loss of Qdrant must not mean people or identity memory are lost.

## 8. Feedback and evolution

Search captures enough context to improve safely: the query, interpretation, plan, candidate set, feature/ranker versions, presented ordering, and subsequent user interaction or explicit relevance feedback, subject to the product's privacy and storage rules.

Explicit feedback is stronger evidence than clicks or opens. Feedback can immediately correct identity/evidence through the established authoritative path, while model or ranker learning occurs later through evaluated candidate versions. A learned-ranker failure must be able to fall back to a rule/weighted ranker so Search remains operational.

## 9. Performance principles

- Keep normal local indexed search fast enough before introducing progressive results.
- Use metadata constraints early to reduce candidate work.
- Permit independent retrieval paths to run as needed, then bound and rank their candidates.
- Respect the existing scheduler: interactive search should receive responsive access to shared compute, especially when face representations are required.
- Treat rebuilding indexes and expensive reconciliation as derived/background work; they must not change authoritative identity truth.

Progressive initial/refined results remain an implementation option only if measurement shows normal query latency needs it.

## 10. Locked invariants

1. Universal Search consumes identity/memory and processing outputs; it does not redefine identity truth.
2. Query-time inference does not become durable identity evidence without the established feedback/processing path.
3. Recognition candidates, Identity Answers, visual similarity, and ranked Search Results are distinct concepts.
4. Hard constraints determine eligibility; soft preferences influence ranking.
5. Retrieval scores are local signals, not universal relevance scores.
6. Ranking is type-specific before cross-type fusion and diversification.
7. Aggregations are evidence-backed, drillable, and uncertainty-aware.
8. Direct co-visibility is stronger than scene/encounter inference; temporal proximity alone is only supporting evidence.
9. Derived retrieval indexes, including Qdrant, are rebuildable and never authoritative memory.
10. Partial processing and degraded indexes must not be represented as complete results.

## 11. Explicitly open decisions

The following remain intentionally open for implementation and evaluation; this document does not decide them:

- Exact `SearchQuery` schema, API, query grammar, and natural-language interpretation technology.
- Exact retriever implementations, Qdrant collection/layout strategy, and final vector-backend selection after benchmarking.
- Acceptance thresholds, feature definitions, normalization, ranker weights, learned-ranker design, and diversification algorithm.
- Exact result-card/UI wording, completeness indicators, and uncertainty presentation.
- Scene/encounter detection implementation and the thresholds required for supported inference.
- Aggregation measures, default evidence filters/weights, and reporting wording.
- Logging retention, privacy controls, feedback UX, and evaluation/promotion criteria.

---

**v1.0 is locked.** Changes require an explicit architecture revision rather than silent reinterpretation.
