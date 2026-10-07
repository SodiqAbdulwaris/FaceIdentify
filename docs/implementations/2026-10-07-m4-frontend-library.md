# M4 W7.2: the library screen, import, and the uncalibrated-policy notice

- **Date:** 2026-10-07
- **Milestone / tracker IDs:** M4 W7 · TST-049, TST-050 (screens); plan decision 1 (the notice)
- **Status:** partial; the source, people and processing screens follow (W7.3, W7.4)
- **Commits:** PR (this change): `feat(frontend): add the library screen and import`

## What changed

- **`/library`**: an infinite list of sources, newest first, as a grid of cards. Each card shows the
  image (the original, fetched with the launch token and shown through an object URL that is
  revoked when the screen goes away; an `<img src>` cannot send the token), the name, a status badge
  and, where processing can start, a **Process** button (each card has its own request, so the button stays disabled while *its*
  request is out, whatever is clicked next, and the newest run is refreshed afterwards). A source whose file is missing says so and fetches nothing. **Import images** opens the
  shell's native picker, imports each chosen file (`MANAGED`), keeps going past a failure, and
  reports "Imported N images." plus the first failure's own message; cancelling the dialog does
  nothing. An empty library invites the first import; a long one pages with **Load more**.
- **The uncalibrated-policy notice** (plan decision 1) is in the layout, above every screen: it
  asks for the newest processing run and, when that run's frozen policy is not calibrated, shows
  "Uncalibrated results ... for evaluation only, not for real decisions", naming the policy version.
  It comes from the run's own provenance, never a constant, and a calibrated policy shows nothing.
- `features/status.ts` holds the wording, tone and the rules for which action is offered in which
  state (process, cancel, retry); `StatusBadge` and `PolicyNotice` are the shared pieces.
- Test harness (`test/harness.tsx`): renders the real app (routes, layout, query cache) against a
  scripted `fetch`; anything the app asks that the script does not expect answers 599, so a stray
  request cannot pass unnoticed.

## Why

W7 of the completion plan: the first screen a person sees, and the notice the owner asked for.

## Decisions

None new.

## Verification

- `npm test` (70): the library (empty, listed with statuses and authenticated images, what is
  offered per state and the missing-file case, processing and its refresh, the backend's own message
  when processing cannot start, the button disabled only for the image in flight, paging, a library
  that cannot load, image addresses released on leaving), importing (a partial failure reported with
  its reason, a clean import, a cancelled dialog), the layout (the notice for an uncalibrated run,
  none for a calibrated one or before any run, only the newest run requested, navigation, the live
  indicator, the root redirect) and the state rules and badges.
- Mutation probes (24 by hand on the state rules, the card, the page, the messages, the notice, the
  layout and the image hook): all killed after tests were added for the badge colours, the busy
  button, a clean import's wording and releasing image addresses.
- `npm run typecheck`, `npm run lint -- --deny-warnings` and `npm run build` pass.
