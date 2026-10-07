# A licensing and commercialisation record

- **Date:** 2026-10-07
- **Milestone / tracker IDs:** none (project governance)
- **Status:** done
- **Commits:** PR to be recorded when merged

## What changed

- `docs/research/licensing-and-commercialization.md`: every third-party thing whose terms would matter
  if the application were ever commercialised, with what is verified and what is not: the face models
  and their training data (the one real blocker today), our own code (no `LICENSE` yet), the runtime
  libraries including NVIDIA's, the Python and front-end dependencies (licences read from installed
  metadata), the Rust crates and future build tools (not verified), biometric-privacy law, the
  evaluation data, and a release checklist and the commands to regenerate the inventory.
- `.agents/rules/documentation.md`: a new item: whoever adds a dependency, model, dataset, font, icon
  set or build tool records it in that file in the same change.

## Why

Owner request, 2026-10-07: note or document all licensable things in a document in case the system is
commercialised; for now it is fully for personal use.

## Decisions

> **Decision 2026-10-07:** Owner: the application is for personal use only for now; this record exists
> so that a later commercial decision starts from a list. The agent added the rule that keeps it true.

## Verification

Documentation only. The Python and JavaScript licences were read from installed package metadata on
2026-10-07 and the model terms from the InsightFace model-zoo page; the Rust crates, NVIDIA's terms,
the training-data terms and transitive dependencies were **not** verified and are marked so.

## Open issues / follow-ups

- Choose a licence for the repository's own code (the owner's decision).
- Run `cargo license` and review transitive dependencies before any release.
