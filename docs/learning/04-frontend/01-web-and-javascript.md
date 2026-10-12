# Front end 01 The web and JavaScript

## 1. What this is and why it exists

A "web view" is a window that shows a web page. The desktop shell opens one and loads the front end into it, so the screens are
HTML, CSS and JavaScript like any website, except that the "website" talks to a private server on your own computer. This lesson
gives you the minimum of the web and of JavaScript that the code assumes, using this repository's own files.

## 2. Where it lives

| Thing | Where |
|---|---|
| The one HTML page | `frontend/index.html` (an empty `<div id="root">` and a script tag) |
| The entry point | `frontend/src/main.tsx` |
| Everything else | `frontend/src/` |

## 3. How it works

- **HTML** describes structure, **CSS** appearance, **JavaScript** behaviour. React builds the HTML for you from components,
  so you rarely write HTML by hand, but the elements (`<ul>`, `<li>`, `<button>`, `<img>`, `<form>`) are plain HTML.
- **The DOM** is the browser's live tree of elements. Changing it changes the screen. React changes it for you.
- **Modules**: `import { x } from './file'` and `export` split code across files. `@/` is a shortcut for `frontend/src/`
  (set in `vite.config.ts` and `tsconfig.app.json`).
- **Values you will meet**: `const` and `let`; arrow functions `(a) => a + 1`; objects `{ a: 1 }` and arrays `[1, 2]`;
  destructuring `const { endpoints } = useBackend()`; spread `{ ...old, x: 1 }`; template strings `` `${base}/path` ``;
  optional chaining `a?.b` and `??` ("if null or undefined, use this").
- **Asynchrony**: network calls take time, so they return a **Promise**. `await` waits for one inside an `async` function;
  `try/catch` handles failure. `fetch` is the browser's built-in HTTP call.
- **A page is not trusted**: it runs in a sandbox. It cannot read your files or start programs; that is why the *shell* offers
  the file picker (`chooseImages`) and why pictures are fetched with a token header and shown through an object URL
  ([API client](05-api-client-and-queries.md)).
- **The Content Security Policy** (CSP) in `desktop/src-tauri/tauri.conf.json` limits where the page may connect; the shell
  chapter shows it ([library folder and dialogs](../05-desktop-shell/04-library-folder-and-dialogs.md)).

## 4. Try it

**Works with no models. Verified 2026-10-12.** Read three small files in this order and name each import: `frontend/src/main.tsx`
(6 lines), `frontend/src/app/App.tsx` (22 lines), `frontend/src/features/StatusBadge.tsx` (18 lines). Then run the smallest test, which
renders a component in a fake browser (jsdom):

```bash
npm run test --workspace frontend -- src/features/StatusBadge.test.tsx
```

Expected: `Tests  13 passed (13)` (it renders each processing state and checks its wording).

*Browser-only tip:* in any browser, open the developer tools (F12) and try `await fetch('https://example.com').then(r => r.status)`
in the console to meet `await`. Do **not** paste your launch token anywhere.

## 5. Change it

Change the wording of one state in `frontend/src/features/status.ts` (for example `COMPLETED: 'Done'` to `'Finished'`), then run
`npm test` and see which test names that wording; update the test with it. Revert with `git restore`.

## 6. Break it on purpose

Delete a closing `)` in `StatusBadge.tsx` and run `npm run typecheck`: the compiler points at the line. Restore with `git restore`.

## 7. Exercises

1. What does `a?.b ?? 'x'` do when `a` is `undefined`?
2. Why does a picture need special handling instead of `<img src="...">`?
3. What does `@/api/client` mean?

**Answers**

1. It evaluates to `'x'`.
2. The server needs the token header, and an `<img>` cannot send one, so the bytes are fetched and shown from an object URL.
3. `frontend/src/api/client`, by the alias.

## 8. Related files

- Next: [02 TypeScript and tooling](02-typescript-and-tooling.md)
- [`frontend/index.html`](../../../frontend/index.html), [JavaScript and Rust tools](../01-basics/tools/07-javascript-and-rust-tools.md)
