# M3: the writer of a run's PENDING output (step 7, last part)

- **Date:** 2026-10-03
- **Milestone / tracker IDs:** M3 (step 7) · TST-038, TST-039; GitHub issue 88 (the writer half)
- **Status:** done. Step 7 is complete: contracts, ONNX handlers, catalog registration, the plan, the client and this writer.
- **Commits:** PR (this branch): `feat(processing): write pending observations and representations`

## What changed
- `backend/app/processing/pending_output.py`: `write_face(session, *, source_id, processing_run_id, execution_segment_id, sequence_in_run, detection, detector, vector, embedder, representation_space_id, new_id, now) -> WrittenFace`. It writes one `PENDING` `Observation` and its `PENDING` `Representation` in the caller's transaction (never commits).
- **Provenance (decision 2026-10-03, issue 88):** the observation's `runtime_variant_id` is the detector variant that actually executed and the representation's the embedder variant, taken from the `PlannedVariant`s the client returned (`Detected.ran`, `Represented.ran`), which the client checked against the worker's own provenance. The writer checks the catalog agrees: each variant is in the catalog, of the right kind, and its export belongs to the component version the output names (so `observations.detector_component_version_id` cannot disagree with the variant); the embedder variant is `DECLARED` or `VALIDATED` for the space (a vector from a variant the library never said could produce the space does not enter it).
- **Validation before storing (Persistence 6.2):** the vector has the space's dimension, is finite, has the space's normalisation, and, for `L2_NORMALIZED`, unit length within `UNIT_LENGTH_TOLERANCE` (1e-3). The vector is stored as the exact little-endian float32 bytes. Nothing is written if anything fails (`PendingOutputError`).
- A face's geometry is the detector's normalised box (`x, y, width, height`) and landmarks; an observation has no frame or time (an image).

## Decisions (the agent's)
- **The contents of the three JSON columns** (Persistence 5 left them undefined): `landmarks_json` `{"schema_version": 1, "points": [[x, y], ...]}`, the observation's `quality_json` `{"schema_version": 1, "detection_score": s}`, the representation's `{"schema_version": 1, "l2_norm": n}`; recorded as a dated note in Persistence 5 for the owner to confirm.
- `sequence_in_run` is the caller's; the schema makes it unique within a run, so a replayed write refuses instead of duplicating.
- No guard for `x + width <= 1` (a first version clamped the width; no input could make it observable: with the worker's boxes inside the image the float sum never exceeds 1, checked over millions of random boxes).

## Verification
- `tests/integration/test_pending_output.py` (21, real SQLite and a real registered catalog), 100% coverage: see the tracker row. Mutation pass: 22 mutations (every refusal, the compatible states, the geometry, both variants, the component version, the stored fields and bytes, the tolerance); the first run left four (a boundary with a clamp that cannot matter, a recorded value hidden by approximate comparison, and the tolerance read from the same constant the test used), which led to the deletion of the clamp and to tests with literal values; none survive.
- Full gate: see the PR.

## Open issues / follow-ups
- Step 10 (orchestration) calls the writer once per face per segment, with the variants the client says ran.
- Issue 88 closes with this change (the schema half was revision 0005).
