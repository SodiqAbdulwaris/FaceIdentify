# Decision: output-level execution provenance (issue 88, option C)

- **Date:** 2026-10-03
- **Milestone / tracker IDs:** M3 (step 7, step 11); TST-038/039
- **Status:** decided and recorded; to be built with migration 0005 (not yet built)
- **Commits:** PR (this branch): `docs: record the output provenance decision`

## Decision (owner, 2026-10-03)
Option C of issue 88. A nullable `runtime_variant_id` FK (`RESTRICT`) on `representations` (the embedder variant that actually executed) and on `observations` (the detector variant that actually executed). Provenance chain: output -> `runtime_variants` -> `model_exports` -> `component_versions`. Rules, all in Persistence 5, 6.2 and 14:
1. The FK is the variant actually used, never the configured one (a CUDA to CPU fallback stores the CPU variant).
2. Export and component ids are not duplicated on the output row.
3. Catalog metadata an output references stays durable: uninstalling files never deletes provenance rows.
4. Nullable for migrated rows and non-ML fixtures; required by the application for newly produced ML output.
5. `observations.detector_component_version_id` is kept in 0005 and must agree with the variant's component version when both are present; cleanup later.
6. `execution_segment_id` stays (when, under which interval).
Rejected by the owner: A (untyped), B (segments per stage distort the segment abstraction and the one-running-segment rule), D (a provenance table is for outputs that depend on many executions; M3 has one producing variant per stage per output).

## Agent's: ordering
The columns arrive with revision 0005, which the plan already ties to the acceptance use case (step 11). So the PENDING-output writer is built after 0005; the backend client, the run-local index, retrieval and the recognition service (steps 7 client, 8, 9) need no output rows and go first.

## Docs touched
Persistence 5, 6.2 and 14 (dated notes), CONTEXT question 31, the M3 decisions entry (the changes 0005 will require), this entry.
