# M3: plan the exact frozen model exports

- **Date:** 2026-10-04
- **Milestone / tracker IDs:** M3 step 10; TST-038/TST-039
- **Status:** done
- **Commits:** pending PR

## What changed

`plan_perception` can now receive the detector and embedder `model_export_id` values frozen in a
processing configuration snapshot. When supplied, each value is an exact selection: the planner
offers variants of that export only, and refuses an export that does not belong to the detector
component version or is not declared for the requested representation space. Its existing callers
may omit those arguments while the executor wiring is still being built.

The regression test registers two component versions and proves that an exact plan contains only
the selected export's variants, while cross-version detector and incompatible embedder selections
are refused.

## Why

The owner-approved M3 `ProcessingRequestV1` freezes explicit detector and embedder exports. The
old planner accepted the detector component version and representation space only, so a later
executor could have selected another export under either durable object. That would turn frozen
intent into an implicit mutable selection and violate the no-substitution rule.

## Decisions

No new product decision. Optional parameters preserve the catalog-planning contract for existing
callers; the processing executor will always pass the snapshot's exact exports.

## Verification

- RED: the new exact-export test failed against the old planner with an unsupported keyword
  argument.
- `uv run pytest tests/integration/test_runtime_worker_config.py -q -p no:cacheprovider` — 38
  passed after the implementation.
- `$env:HYPOTHESIS_PROFILE='ci'; uv run pytest --cov -q -p no:cacheprovider` — 2147 passed,
  backend coverage 100%. The first attempt exposed a stale Windows shared-memory object from an
  interrupted worker test; it cleared when that pytest process exited, and the clean retry passed.
- Mutation: changing the detector export-membership `or` guard to `and` made the focused test fail;
  `worker_config.py` was restored byte-identically (SHA-256
  `1C5C489F34CADAD0C92B9D6EDCB9FEA10624F8B80C0B539950FC6B35C2B58DCE`).

## Open issues / follow-ups

This is the prerequisite for the remaining step-10 executor: decode source bytes, make the
perception calls outside database transactions, persist private output, evaluate recognition, and
write checkpoints/FINAL. Acceptance remains step 11.
