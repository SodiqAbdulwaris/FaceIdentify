# M4 W7.3: the source screen

- **Date:** 2026-10-07
- **Milestone / tracker IDs:** M4 W7 · TST-049, TST-050
- **Status:** partial; the people and processing screens follow (W7.4)
- **Commits:** PR (this change): `feat(frontend): add the source screen`

## What changed

- **`/library/source/:sourceId`**: the image (the original, fetched with the token) with a box on
  each face found, drawn from the backend's normalized bounding boxes as percentages so they scale
  with the image. Each box is a link to that person (`/identities/:id`); people are labelled
  "Person 1, 2, ..." in the order they first appear on that image (the same identity always gets the
  same label there, `faces.ts`). Beside it: **Process** (only where processing can start and the
  file exists), **Cancel processing** (only while a run is queued or running), **Try again** (only
  for a run that failed, was interrupted or could not be accepted, and only while the file exists),
  a note while processing is under way ("this page updates by itself"), the people in the image
  ("No faces were found" for a processed image, "Nobody yet" before), the processing history (each
  run's state and a link to its page), and the facts (size, file name, where it is kept).
- A missing file says so and fetches no image; an unknown source says it is not in the library with a
  way back; any other failure shows the backend's own message.
- `features/processing/useRunActions.ts`: process, cancel and retry in one place (reused by the
  processing screen next); each tells the person the backend's message when it fails and refreshes
  the run, its source, the library list, the people and the newest run.
- `test/fixtures.ts`: more API shapes for tests (a source detail, an occurrence, an identity).

## Why

W7 of the completion plan: where a person sees the result of processing an image, which is the
point of the whole workflow.

## Decisions

None new. The label "Person N" is local to one image; names and merging are M5.

## Verification

- `npm test` (87): the image and its facts, boxes placed from the bounding box (position and size),
  links to the right identity, a person with no drawable box, processed-without-faces wording,
  processing and the backend's refusal message, cancelling while running (and no retry offered then),
  retry for a failure (with the history links and no cancel), no retry or process for a missing
  file, a referenced image's wording, refreshing the image, the library and the people after a
  request, the missing-file, not-found, other-failure and image-failed states; the labelling.
- Mutation probes (26 by hand on every rule above): all killed after tests were added for the
  button rules, the storage wording and the refresh. One probe was a no-op by construction.
- `npm run typecheck`, `npm run lint -- --deny-warnings` and `npm run build` pass.
