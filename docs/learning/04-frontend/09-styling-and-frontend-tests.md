# Front end 09 Styling and front-end tests

## 1. What this is and why it exists

Two quiet systems carry most of the front end's quality: **Tailwind** and **shadcn** make it look consistent without writing
CSS files, and a **scripted-backend test harness** lets every screen be tested in a fake browser against a pretend backend, fast
and with no network. This lesson shows how to read the classes and how to write a test in the house style.

## 2. Where it lives

| Thing | Where |
|---|---|
| Tailwind setup and theme variables (light and dark colours) | `frontend/src/index.css`; plugin in `frontend/vite.config.ts` |
| shadcn components (copied into the repo, owned by it) | `frontend/src/components/ui/button.tsx`; settings in `frontend/components.json` |
| Class merging helper | `frontend/src/lib/utils.ts` |
| Test setup | `frontend/src/test/setup.ts` |
| The harness | `frontend/src/test/harness.tsx` (`renderApp`, `renderWithBackend`, `page`, `apiError`, `failure`, `source`, `run`) |
| Shared fixtures | `frontend/src/test/fixtures.ts` |
| End-to-end | `frontend/e2e/` (`backend.ts` starts the real backend like the shell does; `workflow.e2e.tsx`) |

## 3. How it works

**Tailwind**: styles are small classes on elements: `flex` (row layout), `gap-4` (space between), `p-4` (padding), `rounded-lg`,
`border`, `text-sm`, `text-muted-foreground` (a theme colour), `grid-cols-[repeat(auto-fill,minmax(12rem,1fr))]` (an automatic
grid). `lg:grid-cols-...` applies from the large breakpoint. `dark:` variants apply in dark mode. Colours are theme variables
(`--primary`, `--muted`...) defined once in `index.css`, so changing the theme is one file. **shadcn** `Button` is a function with
variants (`default`, `outline`, `secondary`, `ghost`, `destructive`, `link`) and sizes built by `class-variance-authority`.

**Tests** (Vitest + Testing Library + jsdom, a browser stand-in):

- `renderApp('/library', handlers)` renders the **real routes, layout and query cache** at an address. `fetch` is replaced by a
  scripted backend: a list of `{ method?, path (string or regex), respond, status? }`; the test's own handlers win over defaults. The
  event socket is a quiet stub.
- **Any request with no handler is recorded as `unexpected`** (and answered with status 599); tests assert `unexpected` is empty,
  so a screen cannot silently ask for something the test did not plan.
- `calls` records every request (method, path, query, body, whether the token header was sent) for assertions.
- Tests find things the way a person would: `screen.findByRole('button', { name: 'Process beach.png' })`, `getByText`, labels. They avoid
  CSS classes except when the class *is* the behaviour (status colours).
- `userEvent` types and clicks; `await screen.findBy...` waits for the screen to settle.
- **The pyramid**: unit tests of rules (`status.ts`, `staleBecauseOf`), component and screen tests with the harness, and one end-to-end
  workflow against the real backend.

## 4. Try it

**Works with no models and no shell. Verified 2026-10-12.**

```bash
npm test                                    # everything: 24 files, 193 tests, ~17 s
npm run test --workspace frontend -- src/features/StatusBadge.test.tsx     # one file
npm run test:e2e                            # the real backend, ~11 s
```

(`npm run test --workspace frontend -- <path>` is the way to run one file from the repository folder; the part after `--` goes to Vitest.)
Open `StatusBadge.test.tsx` (54 lines): `it.each` runs one rule over a table of states. Then open `LibraryPage.test.tsx` and find a
`renderApp('/library', [...])` call: the array is the pretend backend.

## 5. Change it

Write a test for something that exists: in `StatusBadge.test.tsx` add `['PAUSED', 'Paused', 'bg-blue-100']` to the `it.each` table
and run the file. It passes, which proves a table row is a whole test. For a new screen test see [add a screen](10-add-a-screen.md).

## 6. Break it on purpose

In `Layout.tsx` change the `People` link text to `Everyone` and run `npm test`: observed `1 failed`, in `Layout.test.tsx`
(`names the places to go, and says whether live updates are on`), because it looks for a link named `People` (the `Search` link is
not checked there, so renaming it passes: a test only protects what it names). Tests that name the visible words are the front end's contract with the person using it. Restore with `git restore`.

## 7. Exercises

1. What does an `unexpected` request in the harness mean?
2. Why do tests find buttons by role and name?
3. Where do you change the app's colours?

**Answers**

1. The screen asked the backend for something the test did not script, so the test is incomplete or the screen is doing something new.
2. It mirrors how people (and assistive technology) find controls, and survives restyling.
3. The theme variables in `frontend/src/index.css`.

## 8. Related files

- Previous: [08](08-people-and-search-screens.md) · Next: [10 Add a screen](10-add-a-screen.md)
- [`frontend/src/test/harness.tsx`](../../../frontend/src/test/harness.tsx), [pytest and tests in general](../01-basics/tools/03-pytest.md)
