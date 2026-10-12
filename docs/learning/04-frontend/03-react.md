# Front end 03 React

## 1. What this is and why it exists

React turns **data into screens**. You write a *component*, a function that returns what the screen should look like for the
current data; when the data changes React calls it again and updates only what differs. You never edit the page by hand. This
lesson teaches the five ideas the codebase uses, each with a real file.

## 2. Where it lives

| Idea | Example in this repository |
|---|---|
| A component is a function returning JSX | `StatusBadge` in `frontend/src/features/StatusBadge.tsx` |
| Props are its inputs | `{ state }` in `StatusBadge`; `{ source, recycled, onNotice }` in `SourceCard.tsx` |
| State is memory that triggers a redraw | `useState` for `view` in `LibraryPage.tsx` |
| Effects synchronise with the outside world | `useEffect` in `EventsBridge.tsx` (open and close the socket) |
| Context shares a value without passing props | `BackendContext` in `app/useBackend.ts` |

## 3. How it works

- **JSX** is HTML-looking syntax inside TypeScript: `<Button onClick={() => ...}>Import</Button>`. `{ }` embeds an expression;
  `{cond ? <A/> : null}` shows or hides; `items.map(i => <li key={i.id}>...</li>)` repeats (a stable `key` is required).
- **Hooks** are functions starting with `use`: `useState`, `useEffect`, `useMemo`, `useContext` (React); `useQuery`, `useMutation`
  (TanStack Query); `useParams`, `useSearchParams` (router); `useUi` (zustand). Rules: call them at the top level of a component,
  never inside a condition or loop.
- **Server data is not state.** `useQuery` owns data that lives on the backend (cached, refetched, with loading and error
  flags). `useState` is only for the screen's own memory (which tab, what is typed). The one global client-only store is
  `state/ui.ts` (zustand): just the events connection status.
- **An effect with cleanup**: `EventsBridge` opens the socket in `useEffect` and returns `() => client.stop()` to close it. Without
  the cleanup, every re-render would leave another socket open. The linter (`oxlint`) warns about patterns like setting state
  in an effect; the two places that must do it carry an `oxlint-disable-next-line` comment with the reason (`useSourceImage.ts`).
- **Strict mode** (`main.tsx`) runs effects twice in development to expose missing cleanup; that is expected.
- **Accessibility is testable**: components carry `role`, `aria-label` and real `<button>`/`<form>` elements, and the tests find
  things by those (`screen.getByRole('button', { name: ... })`), not by CSS classes.

## 4. Try it

**Works with no models. Verified 2026-10-12.** Read `frontend/src/features/library/LibraryPage.tsx` top to bottom (136 lines) and
write down, for each hook call, what it owns:

| Line | Hook | Owns |
|---|---|---|
| `useBackend()` | context | the typed endpoints |
| `useQueryClient()` | TanStack | the cache, to invalidate it |
| `useState(arrived)` | React | the notice text |
| `useState('library')` | React | which tab |
| `useInfiniteQuery(...)` | TanStack | the pages of sources |
| `useMutation(...)` | TanStack | the import action |

Then run its tests (`584` lines of them show every state: loading, empty, bin, errors, import):

```bash
npm run test --workspace frontend -- src/features/library/LibraryPage.test.tsx
```

Expected: `Tests  23 passed (23)` (observed).

## 5. Change it

Change the empty-state sentence in `LibraryPage.tsx` ("No images yet" / "Import images to find and group the people in them.").
Run the library test: the test that asserts that text fails; update it in the same change. That is the normal rhythm: change, red
test, change the test deliberately.

## 6. Break it on purpose

Remove the `key={source.id}` on the card list: React warns about missing keys in the console (*not run here; React's documented
behaviour*), and the list may reorder wrongly when items change. Restore with `git restore`.

## 7. Exercises

1. Which hook would you use for a value that comes from the backend, and which for "is this panel open"?
2. Why does `EventsBridge` return a function from its effect?
3. What does `{items.length > 0 ? <ul>...</ul> : null}` do when the list is empty?

**Answers**

1. `useQuery` for the backend value; `useState` for the panel.
2. To close the socket when the component goes away or the connection changes.
3. Renders nothing.

## 8. Related files

- Previous: [02](02-typescript-and-tooling.md) · Next: [04 App structure and the gate](04-app-structure-and-gate.md)
- [`frontend/src/features/library/LibraryPage.tsx`](../../../frontend/src/features/library/LibraryPage.tsx)
