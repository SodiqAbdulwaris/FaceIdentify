# The model family leaves the representation-space identity

- **Date:** 2026-10-02
- **Milestone / tracker IDs:** M3 (step 7); TST-038, TST-039 (in progress)
- **Status:** done; the provenance question it raised is GitHub issue 88
- **Commits:** PR (this branch): `fix(runtime): leave the model family out of the space identity`, `docs: record the contract-key decision and the identity amendment`

## What changed
Owner decision 2026-10-02 (CONTEXT open question 31, part 2): the manifest component `contract` keys are approved with one change.
- `registration.space_identity` no longer contains `family`; a space is identified by the weights digest, dimension, preprocessing contract, normalization, normalization contract version and `compatibility_version`. `family` stays a required key of an embedder's contract (descriptive provenance) and is validated, but does not change the space or its `semantic_key`.
- `compatibility_version` stays its own field (the owner's reasoning: preprocessing says how input becomes model input, normalization says how output becomes the stored vector, compatibility is the explicit boundary for semantic changes those mechanical contracts do not capture; bumping it creates a new space and needs a documented reason).
- Dated notes: Architecture 12.2 (the keys and the identity, in the owner's wording) and ML 18.1 (the two earlier decisions listed the family; the amendment follows them). CONTEXT question 31 is fully decided; the registration entry, the tracker and CONTEXT's step-7 text no longer say the family is part of the identity.
- The fingerprint scheme stays `rs1`. Nothing outside the tests has stored an `rs1` key (no released library exists), so this is a correction before first use, not a migration; the pinned test key changed accordingly.

## Why
`family` is a human-controlled label (`arcface`, `ArcFace`, `arc-face`, `insightface-arcface`): equivalent exports would have been split into several spaces by spelling alone, and it adds no compatibility information once the exact weights digest and the explicit contracts are in the identity.

## Verification
- `tests/integration/test_runtime_registration.py` (56 tests): five spellings of the family give the same key and an identity without it; the same weights announced under another family spelling in a new component version are one space whose `contract_json` has no family (the family stays on the component versions); each remaining part still changes the key; the literal key is re-pinned; a manifest without a family is still refused (it is required). 100% coverage of the module.
- Mutation pass: 51 mutations (the earlier ones, family put back into the identity at two places, family no longer required); none survive. One run of the pass reported no survivors over an empty list because a spec-file write had failed; it was noticed, the spec rewritten and the pass redone.
- Full gate: see the PR.

## The provenance check the owner asked for (before the PENDING-output writer)
There is no unambiguous durable path from a Representation to the embedder's actual component version, export and runtime variant: `RepresentationSpace.component_version_id` is origin only; the snapshot records intent; an `ExecutionSegment` has one nullable `runtime_variant_id` while a run executes a detector and an embedder; `runtime_details_json` is untyped; an Observation records only the detector's component version. GitHub issue 88 has the table, the gap and four options (A: JSON convention, B: per-stage segments, C: variant FK on the representation and the observation, recommended, fits migration 0005, D: a provenance table). No column is designed here. The writer is held until the owner chooses.

## Open issues / follow-ups
- Issue 88 (the owner's choice), then the PENDING-output writer.
- The backend client (run the plan against the supervisor) is not blocked by it.
