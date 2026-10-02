# M3: planning and the decisions it rests on

Date: 2026-10-02. Documentation only; no code.

## What was done
- Surveyed M3 (tracker TST-033 to TST-044, Roadmap phases 3 to 9, Persistence sections 12 to 16, 23, 28, 30, the API contract, the ML spec) and wrote a 14-step plan, approved by the owner after review.
- Recorded four owner decisions as dated notes: the reference models and what identifies a representation space (ML spec 18.1); the headless runtime installer (ML spec 18.1); the three recognition outcomes (Roadmap phase 6); and accepted `ABSTAIN` representations being `ACTIVE` without an identity (Persistence 6.2).
- Updated CONTEXT (M3 started) and the tracker status line.

## Consequences for the code (not built here)
- Migration `0005` relaxes the ACTIVE CHECK to `state != 'ACTIVE' OR ann_key IS NOT NULL`. `ACTIVE` without an `ann_key` stays rejected; tests must prove both halves (including `ACTIVE + identity NULL + ann_key NULL` rejected), the populated-library upgrade, and the downgrade guard.
- Candidate retrieval treats an identity-less candidate as evidence only. A run-local candidate of a PENDING identity must stay distinguishable from an ACTIVE identity's.

## Documents that disagree (resolved)
Persistence wins over the API contract for `previous_job_id` (not `retry_of_job_id`) and for the index returning `ann_key`; the Qdrant text in `processing-architecture-v1.md` is superseded by USearch; Run `COMPLETED` does not wait for index operations to be `APPLIED` (Persistence section 12).
