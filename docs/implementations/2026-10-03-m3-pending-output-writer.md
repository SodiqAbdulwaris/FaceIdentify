# M3: the writer of a run's PENDING output (step 7, last part)

- **Date:** 2026-10-03
- **Milestone / tracker IDs:** M3 (step 7) · TST-038, TST-039; GitHub issue 88 (the writer half)
- **Status:** done. Step 7 is complete: contracts, ONNX handlers, catalog registration, the plan, the client and this writer.
- **Commits:** PR (this branch): `feat(processing): write pending observations and representations`

## What changed
- `backend/app/processing/pending_output.py`: `write_observation(session, *, source_id, processing_run_id, execution_segment_id, sequence_in_run, detection, detector, new_id, now) -> WrittenObservation` persists detector output first. `write_representation(session, *, observation_id, detection_index, vector, embedder, representation_space_id, new_id, now) -> WrittenRepresentation` later persists the embedder output. Neither commits. The representation writer reloads the PENDING observation, proves its run and segment are still running, and checks the vector against the caller's transient detector-index-to-observation mapping. This matches Persistence 5 and 30: an embedding failure leaves its PENDING observation rather than discarding detector output.
- **Provenance (decision 2026-10-03, issue 88):** the observation's `runtime_variant_id` is the detector variant that actually executed and the representation's the embedder variant, taken from the `PlannedVariant`s the client returned (`Detected.ran`, `Represented.ran`), which the client checked against the worker's own provenance. The writer checks the catalog agrees: each variant is in the catalog, of the right kind, and its export belongs to the component version the output names (so `observations.detector_component_version_id` cannot disagree with the variant); the embedder variant is `DECLARED` or `VALIDATED` for the space (a vector from a variant the library never said could produce the space does not enter it).
- **Validation before storing (Persistence 6.2; ML Components 6.1):** the vector is a contiguous, little-endian `float32` NumPy array, has the space's dimension, is finite, has the space's normalisation, and, for `L2_NORMALIZED`, unit length within `UNIT_LENGTH_TOLERANCE` (1e-3). It is stored without dtype coercion as its exact canonical bytes. A bad detection writes nothing; a bad embedding writes no representation and retains its already-settled PENDING observation (`PendingOutputError`).
- A face's geometry is the detector's normalised box (`x, y, width, height`) and landmarks; an observation has no frame or time (an image).

## Decisions (the agent's)
- **The contents of the three JSON columns** (Persistence 5 left them undefined): `landmarks_json` `{"schema_version": 1, "points": [[x, y], ...]}`, the observation's `quality_json` `{"schema_version": 1, "detection_score": s}`, the representation's `{"schema_version": 1, "l2_norm": n}`; approved by the owner on 2026-10-03 and recorded in Persistence 5.
- `sequence_in_run` is the caller's; the schema makes it unique within a run, so a replayed write refuses instead of duplicating.
- No guard for `x + width <= 1` (a first version clamped the width; no input could make it observable: with the worker's boxes inside the image the float sum never exceeds 1, checked over millions of random boxes).

## Verification
- `tests/integration/test_pending_output.py` (37, real SQLite and a real registered catalog), including catalog-kind spoofing, source/run/segment mismatches and terminal states, noncanonical vectors, a mismatched detection index, and a failed embedding that leaves its observation PENDING. The focused migration/writer suite passed: `uv run pytest tests/integration/test_migration_0005.py tests/integration/test_pending_output.py -q -p no:cacheprovider` — 50 passed (2026-10-03). The writer has 100% coverage in that run.
- Mutation checks: the earlier 22 mutations remain caught. I first inverted the catalog-kind comparison, but that was a poor mutant: the later role check rejected the normal embedder too, so its regression still passed. I restored it byte-identically and used a deletion mutant instead. Eleven meaningful review-fix guard mutations (catalog kind; array type, dtype and contiguity; absent run/segment; source/run and segment/run mismatch; run/segment writability; detection-index match) each failed their focused regression test. The new unknown-observation, PENDING-observation, and transient detector-index mapping guards also each failed their focused regression tests. `pending_output.py` was restored byte-identically after every mutation.
- Full backend suite: `HYPOTHESIS_PROFILE=ci uv run pytest --cov -q -p no:cacheprovider` — 2102 passed, 100% coverage (2026-10-03).
- Independent review found and the follow-up commit corrected an obsolete `write_face` summary in `.agents/CONTEXT.md`; the context now states the detector-first boundary directly rather than relying on a correction note beside contradictory history.

## Open issues / follow-ups
- Step 10 (orchestration) persists every detection first, then calls the representation writer with the retained detector-index-to-observation mapping and the variants the client says ran.
- Issue 88 closes with this change (the schema half was revision 0005) when PR #96 merges.
