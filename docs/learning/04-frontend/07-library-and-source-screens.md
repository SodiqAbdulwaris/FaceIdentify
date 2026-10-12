# Front end 07 The library and source screens

## 1. What this is and why it exists

These two screens are the heart of the daily use: the **library** (a grid of your pictures, with import, process and the recycle
bin) and the **source** page (one picture with a box on each face, the people in it, processing controls and history). Reading them
shows every pattern in the front end in a real, working form.

## 2. Where it lives

| Screen | Files |
|---|---|
| Library | `features/library/LibraryPage.tsx` (136 lines), `SourceCard.tsx` (123), `messages.ts` |
| Source | `features/source/SourcePage.tsx` (222), `FaceOverlay.tsx`, `faces.ts`, `RecycleControl.tsx`, `PermanentDelete.tsx`, `UnresolvedFaces.tsx`, `FaceCorrection.tsx` |
| Shared | `features/status.ts`, `StatusBadge.tsx`, `useSourceImage.ts`, `processing/useRunActions.ts`, `PolicyNotice.tsx` |
| Processing run page | `features/processing/ProcessingPage.tsx` (route `processing/:runId`) |
| Tests | `LibraryPage.test.tsx` (23), `source/` (4 files, 40 tests), `processing/` (8) |

## 3. How it works

**Library** (`#/library`):

- Two views (`view` state): the library (`state=ACTIVE`) and the **recycle bin** (`RECYCLED`), each its own query key
  (`keys.sources`, `keys.recycledSources`, the second nested under the first so one invalidation covers both).
- `useInfiniteQuery` + "Load more" for cursor pages.
- **Import**: `chooseImages()` asks the shell for the picker (the page cannot read your disk); for each path it calls
  `importSource({path, storage_mode: 'MANAGED'})`; successes and failures are counted and summarised (`importSummary`); the sources
  list is invalidated.
- Each `SourceCard` has the image (fetched with the token, `useSourceImage`), a status badge, and buttons that appear by rule:
  *Process* only if `canProcess(status)` and the file is present; *Recycle* or *Restore* depending on the view; *PermanentDelete* in
  the bin. Each action is its own `useMutation`, so one click cannot make another button look idle.
- Empty, loading and error states are explicit (`No images yet`, `The recycle bin is empty`, `Your library could not be loaded: ...`).

**Source page** (`#/library/source/:sourceId`):

- Three queries: the source, its occurrences (the faces) and its runs. Runs refetch every 3 s **only while** the newest run is active.
- `FaceOverlay` positions a link over each face with CSS percentages from the bounding box (fractions of the image, so it scales).
- Buttons come from rules in `status.ts`: `canProcess`, `canCancel` (`PENDING` or `RUNNING`), `canRetry` (`FAILED`, `INTERRUPTED`, `NOT_RESUMABLE`).
- `labelFaces`/`personLabel` give every face a name, or "Person ABC123" from the start of the identity id (presentation only).
- Missing file, not found, error and "no faces" each have their own text.
- Corrections (`FaceCorrection`, `UnresolvedFaces`) call the corrections routes ([corrections](../03-backend/api/routes/corrections.md)); recycling and permanent
  deletion call the lifecycle routes ([lifecycle](../03-backend/lifecycle/README.md)); the permanent delete has a confirmation step.
- The **`PolicyNotice`** in the layout warns whenever the newest run was produced by an uncalibrated policy or with automatic matching off.

## 4. Try it

**Works with no models and no shell. Verified 2026-10-12.**

```bash
npm run test --workspace frontend -- src/features/library src/features/source src/features/processing
```

Expected: pass; the three groups gave `23`, `40` and `8` tests. Read test names to see behaviour as a list: `LibraryPage.test.tsx`
names every state above. To *see* the screen in a real run you need the desktop app (`npm run tauri dev`, Windows, unverified here). The nearest
thing runnable anywhere is the end-to-end test, which imports, processes, recycles and restarts through these very screens:

```bash
npm run test:e2e
```

Observed: `1 passed`, about 11 s.

## 5. Change it

Add a line under the source's details showing the media type: `detail` already has the field the backend sends (see
`SourceDetail` in `schema.d.ts`); add a `<dt>`/`<dd>` pair in `SourcePage.tsx`, then a test in `SourcePage.test.tsx` that the line
appears for a scripted source. Run `npm test`, `npm run typecheck`, `npm run lint`.

## 6. Break it on purpose

In `status.ts` make `canProcess` return `true` always (scratch edit): the library tests that say a running or finished source offers
no *Process* button fail. That is the rule that stops a double-queued run. Restore with `git restore`.

## 7. Exercises

1. Which hook fetches a source's runs, and when does it poll?
2. Why are face boxes in percentages?
3. Where is "may this be cancelled?" decided in the UI, and where in the backend?
4. What two things does `LibraryPage` do after an import?

**Answers**

1. `useQuery` with `refetchInterval` returning 3 s only when the newest run `isActive`.
2. The boxes are fractions of the picture, so they scale with the displayed size.
3. UI: `canCancel` in `status.ts` (only to show or hide the button); backend: the cancel use case (the authority; it may still refuse).
4. Shows a summary notice and invalidates the sources list.

## 8. Related files

- Previous: [06](06-events-and-routing.md) · Next: [08 People and search screens](08-people-and-search-screens.md)
- [`frontend/src/features/library/LibraryPage.tsx`](../../../frontend/src/features/library/LibraryPage.tsx), [`source/SourcePage.tsx`](../../../frontend/src/features/source/SourcePage.tsx)
