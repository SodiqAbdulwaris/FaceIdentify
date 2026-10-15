# Dataset sources recorded, `MyFaces/` ignored

- **Date:** 2026-10-13
- **Milestone / tracker IDs:** M5 track R (evaluation data hygiene); no tracker row changes
- **Status:** done; documentation and `.gitignore` only
- **Commits:** PR to be recorded when merged

## What changed

- `.gitignore` now lists `MyFaces/` beside `LFW/` and `CelebA/`, and ends with a newline. The owner's
  own photographs (11 files) are biometric data and are never committed.
- `docs/research/licensing-and-commercialization.md` records where the datasets came from (owner,
  2026-10-13): LFW from the Kaggle mirror `jessicali9530/lfw-dataset`, CelebA from the creators' page,
  and `MyFaces/` as the owner's own photographs.

## Why

The licensing record must say where each dataset came from, and a folder the owner created for
photographs of their own face must not be one `git add -A` away from being published.

## Verification

- `git check-ignore -v MyFaces` matches the new line. Nothing else changed.
- **Not verified:** the Kaggle mirror's licence and terms (the page could not be read from the agent's
  environment) and the original sites' terms: still issue 183.
  (2026-10-15: the Kaggle mirror's licence field was read and grants no licence of its own; see
  `docs/research/licensing-and-commercialization.md` section 10.3.)
