# M4 W7.4: the people and processing screens

- **Date:** 2026-10-07
- **Milestone / tracker IDs:** M4 W7 · TST-049, TST-050
- **Status:** done for the screens the plan names (`/identities`, `/identities/:id`, `/processing/:runId`); W7 is complete
- **Commits:** PR (this change): `feat(frontend): add the people and processing screens`

## What changed

- **`/identities` (People)**: each person with their face, how many times and in how many images
  they appear; paged; an invitation when nobody is known yet.
- **`/identities/:id` (a person)**: the same facts and every image they appear in (a face crop and
  the image's name, each a way to that image), paged; clear states for an unknown person, a load
  failure and no appearances. Nobody has a name yet, so the label is the start of the identity id
  ("Person 3F9A2C", `identities/label.ts`), the same on every screen; names and merging are M5.
  The source screen's boxes use the same label (replacing the per-image "Person 1" numbering).
- **`/processing/:runId`**: the run's state, when it was requested, started, finished or failed, its
  job (state and attempt), progress while under way, the earlier attempt it retries, the policy it
  ran under ("development-uncalibrated-v1 (uncalibrated)"), a plain explanation of a failure
  ("it stopped without a result ... nothing from this attempt was kept"), and **Cancel processing**
  or **Try again** only where they apply. It updates by itself through the events, and looks again every three seconds while the run is
  under way (the source screen's history does the same), for when the live connection is down.
- **`FaceCrop`**: the backend stores no face crops yet (`face_crop` is null), so a face is cut out of
  its original for display: the image is scaled uniformly and shifted so the box fills a square tile
  (centred on its shorter side); until the image's own size is known the plain image is shown, never
  a distorted one.
- A crop remembers which image it measured, so a tile reused for another image is not sized with the
  first one's dimensions.
- The placeholder screen is gone; every route in the plan is a real screen.

## Why

W7 of the completion plan. With the library and source screens, these complete the path a person
walks: images in, faces found, who they are, and what happened to each attempt.

## Decisions

None new. The "Person XXXXXX" label is a stand-in for names, which arrive with the M5 corrections.

> **Decision 2026-10-07 (owner):** confirmed. Until semantic naming exists (M5), an unnamed identity
> is shown as `Person {SHORT_ID}`, the uppercase first 6 hexadecimal characters of the identity
> UUID. It is a presentation-only derived label, never persisted as a name, derived the same way on
> every screen; first-seen timestamps are separate metadata and play no part in it.

## Verification

- `npm test` (113 across 16 files): the people list (empty, faces and counts with correct plurals,
  paging, failure), a person (counts and wording, appearances as links to their images, a face crop
  when there is a face and none when there is not, paging, no appearances, not found, other failure,
  the appearances failing, and that nothing is asked for when the person is unknown), a processing
  run (a finished run's facts and no actions, under way with progress, progress without a total,
  a failure with its earlier attempt and retry, a refused request's message, not found and other
  failure), the face crop (plain image first, scaled and centred in proportion for a wide and for a
  tall face, plain when no size is reported) and the label.
- Mutation probes (32 by hand on every rule above): all killed after tests were added for what
  survived (nothing requested for an unknown person, no "under way" for a finished run, centring
  of a narrow face, a reported size of zero).
- `npm run typecheck`, `npm run lint -- --deny-warnings` and `npm run build` pass.
