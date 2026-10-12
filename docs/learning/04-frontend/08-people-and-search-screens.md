# Front end 08 The people and search screens

## 1. What this is and why it exists

Four screens answer "who is in my pictures?": the **people** list (`#/identities`), one **person** (`#/identities/:id`) where you
name, merge, split and forget, **search** by word (`#/search?q=`), and **face search**, where you ask "who is this?" with a
picture that is not saved. They show how the front end turns the domain vocabulary ([domain](../03-backend/domain/README.md)) into
words and buttons.

## 2. Where it lives

| Screen | Files |
|---|---|
| People list | `features/identities/IdentitiesPage.tsx`, `label.ts` |
| One person | `IdentityPage.tsx`, `NameForm.tsx`, `MergeControl.tsx`, `SplitControl.tsx`, `ForgetControl.tsx` |
| Search | `features/search/SearchPage.tsx` |
| Face search | `features/search/FaceSearch.tsx`, `FaceCrop.tsx` |
| Tests | `identities/` (6 files, 37 tests), `search/` (3 files, 21 tests) |

## 3. How it works

- **Identity versus person in the UI.** The list is of *identities* (a face group); each card shows the person's name if one has been given,
  otherwise `Person ABC123` (six characters of the id; never stored as a name). Below it, "Known by name only" lists people who have a
  name but no remembered face (all forgotten), fetched page by page until the short list is whole.
- **The face on a card** is a crop made *in the browser*: the backend stores no crops yet, so `FaceCrop` shows the original scaled
  and shifted so the bounding box fills a square tile.
- **One person**: name form (creates a person through `nameIdentity`, or renames with the person's `revision`); `MergeControl`
  sends both identities' revisions; `SplitControl` takes chosen appearances out into a new person; `ForgetControl` asks first (an `asking` state that opens a confirmation) and
  handles `204` versus `202` (work still owed: it passes a notice to the people list). A changed record is never overwritten: the server's
  codes `IDENTITY_CHANGED` (merge: "One of these people changed since you looked. The page has been refreshed; try again."),
  `PERSON_REVISION_CONFLICT` (rename) and `SPLIT_CONFLICT` each get their own message.
- **Search**: the word lives in the address (`useSearchParams`), so reload and Back work; an empty result says how much of the library
  the search could see (an unprocessed image has no faces); "recycled" can be included. Results are people, identities, sources and
  appearances.
- **Face search**: the picture can be chosen (native dialog gives a *path*; the backend reads it once), dropped, or pasted; it is
  held in component state only, never in the cache, so leaving the screen drops it. Each face found gets its own list of possible
  people with a similarity, labelled as **not a probability**. A subscription to cache invalidations hides and re-asks the answer
  when an event changes a name, face or image, so a forgotten person is never left on screen.
- Every destructive control explains what it does and what stays (forget keeps the pictures and the name).

## 4. Try it

**Works with no models and no shell. Verified 2026-10-12.**

```bash
npm run test --workspace frontend -- src/features/identities src/features/search
```

Observed: `37 passed` for `identities/` and `21 passed` for `search/`. Read `NameForm.test.tsx`, `MergeSplit.test.tsx`,
`ForgetControl.test.tsx` and `FaceSearch.test.tsx` names: they are the behaviours listed above, one sentence each. The
scripted backend they use is the [test harness](09-styling-and-frontend-tests.md).

## 5. Change it

To change how an unnamed person is labelled, edit `personLabel` in `identities/label.ts` (one place; every screen uses it) and run
`npm test`: `label.test.ts` and several screen tests mention the label and must change with it.

## 6. Break it on purpose

In `endpoints.ts`, in `mergeIdentities`, send the loser's revision for the survivor too (scratch edit): observed `1 failed | 36 passed`,
the failing test being `says what will happen, then merges and goes to the person they were merged into` (it asserts the request
body). That test keeps the front end honest about optimistic concurrency. Restore with `git restore frontend/src/api/endpoints.ts`.

## 7. Exercises

1. Why does the face search keep its picture in `useState` and not in the query cache?
2. What is shown for an identity nobody has named?
3. How does a forgotten person disappear from an open search result?

**Answers**

1. So leaving the screen drops it: the app must remember neither the picture nor the answer.
2. `Person` plus six characters of the id; it is presentation only.
3. A cache event for the `search` key invalidates and re-asks, and the old answer is hidden meanwhile.

## 8. Related files

- Previous: [07](07-library-and-source-screens.md) · Next: [09 Styling and front-end tests](09-styling-and-frontend-tests.md)
- [`frontend/src/features/identities/IdentityPage.tsx`](../../../frontend/src/features/identities/IdentityPage.tsx), [face search route](../03-backend/api/routes/face-search.md)
