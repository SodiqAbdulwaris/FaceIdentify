# Four small screen defects (issue 284)

- **Date:** 2026-11-14
- **Milestone / tracker IDs:** none (defects seen driving the web app against the real backend)
- **Status:** done
- **Commits:** PR (number added when opened): `fix(web): show a placeholder, not a broken image, for a video card`, `fix(web): count a person's appearances in images and videos`, `feat(web): the app's own screen for an unknown address or a failure`, `fix(web): name the chosen recognition mode in the uncalibrated notice`

## Why

Issue 284 listed four defects, none affecting stored data or decisions, seen on 2026-11-14 with real models on a scratch library.

## What changed

- **A video's card** (`SourceCard.tsx`): a source of type `VIDEO` no longer asks for its bytes as a picture; it shows a "Video" placeholder with an accessible name ("<name> (a video)"). No backend thumbnailing was added (a frame through the pinned FFmpeg would be a small change later; the placeholder is enough).
- **Counts** (`IdentitiesPage.tsx`, `IdentityPage.tsx`): "6 appearances in 6 images and videos", and "in 1 image or video" for one; the end-to-end test's expected strings follow.
- **Unknown address or a failing screen** (`RouteError.tsx`, `routes.tsx`): the app's own words ("That page does not exist" for a 404, "Something went wrong. Nothing in your library was changed." otherwise) and a link back to the library, in place of React Router's default screen.
- **The notice** (`PolicyNotice.tsx`): a result from `buffalo-l-verified-match-v1` says it came from "the Automatic recognition you chose", from `buffalo-l-abstain-only-v1` from "the Assisted recognition you chose", and anything else keeps "the development policy (version)". The text says what uncalibrated means for the person: a high score is a reason to look, not proof.

## Verification (this machine)

- `npm run typecheck`, `npm run lint` (strict: any warning fails), `npm test` (**249 passed**), `npm run build` exit 0; the end-to-end workflow test (`npm run test:e2e`, 2 passed) against the real backend with the new wording.
- New tests: a video card shows the placeholder and makes no media request; the unknown address shows the app's screen and a way back; the notice names Automatic and Assisted and no longer says "development policy" for them; the counts follow in the existing tests.
- Not verified: the screens by eye in the desktop window.

## Decisions (delegated, 2026-11-14; the owner may reverse any)

- A placeholder rather than a real video thumbnail: it removes the defect with no backend work.
- "image or video" / "images and videos" rather than "sources", which is internal wording.
