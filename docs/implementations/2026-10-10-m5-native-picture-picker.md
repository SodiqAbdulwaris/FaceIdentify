# M5 step 5b follow-up: native file picker for face search

- **Date:** 2026-10-10
- **Milestone / tracker IDs:** M5 step 5b (follow-up); TST-056
- **Status:** done
- **Commits:** PR to be recorded when merged

## What changed

- **Shell command** `choose_picture` (`desktop/src-tauri/src/lib.rs`): the native Windows file dialog, one
  picture, the same image-extension filter as `choose_images`, using the dialog plugin already in the
  project (no new dependency). Only the path crosses to the web view.
- **Search screen.** In the desktop app "Choose a picture" opens that dialog and searches with the path
  through the existing `POST /search/face` path form: the same query-only pipeline, no second backend path,
  and no image bytes or copy are kept. Drop and paste still send the picture's bytes, and the browser file
  input remains for the browser build (`inShell()` decides which "Choose" opens).
- A picture chosen by path has no preview in the web view (the backend reads the file; the web view never
  does), so its faces are listed without crops. Pictures dropped or pasted keep their crops.

## Changes after the independent review

The review also found issues in the face-search path this picker shares; fixed here:

- A dialog that cannot be opened is shown, not swallowed.
- An answer that was on its way when a forget, delete or merge event arrived is never kept: the screen asks
  again until no event overlapped the request (`staleTime: Infinity` no longer lets a late answer stand).
- Mixed-slash network paths (`/\\server`, `\\/server`) are refused like `\\server` and `//server`.
- At most three face searches are in flight (reading, waiting or perceiving); more get `429
  FACE_SEARCH_BUSY` (retryable) before their picture is read, which bounds the memory they hold together;
  the upload buffer is checked per chunk and only one copy is kept.
- A worker output lost between calls (a `ContractError`) is the retryable `503 PERCEPTION_UNAVAILABLE`.
- Still a follow-up in the supervisor: a lease covering execute, copy and release shared by processing and
  queries, so a processing crash cannot cost a query its output at all.

## Tests

- `FaceSearch.native.test.tsx` (3): the chosen path is sent as `{path}` and a cancelled dialog sends nothing;
  `backend.test.ts` covers the browser fallback. `cargo check` and `cargo fmt --check` pass locally; the
  dialog itself needs a human (a desktop run), as for `choose_images`.
