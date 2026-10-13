# Front end 02 TypeScript and tooling

## 1. What this is and why it exists

**TypeScript** is JavaScript with types: the compiler checks, before anything runs, that you pass the right kind of value
everywhere. In this project it earns its keep in one place above all: the types of every API answer are **generated from the
backend**, so if a backend route changes shape and the screen is not updated, `npm run typecheck` fails instead of the screen
quietly showing `undefined`.

## 2. Where it lives

| Thing | Where |
|---|---|
| The generated types (never edit) | `frontend/src/api/schema.d.ts` (2564 lines), from `frontend/src/api/openapi.json` |
| Friendly names for them | `frontend/src/api/types.ts` (`SourceSummary`, `ProcessingRun`, `Page<T>`...) |
| Compiler settings | `frontend/tsconfig.app.json` (`strict`, `noUnusedLocals`, `verbatimModuleSyntax`, `erasableSyntaxOnly`, path alias) |
| Dev server, build and test settings | `frontend/vite.config.ts` (React and Tailwind plugins, alias, port 5173, jsdom for tests) |
| Lint | `oxlint` (`npm run lint`; CI adds `--deny-warnings`) |
| Scripts | root `package.json` (workspace `frontend`): `dev`, `build`, `test`, `typecheck`, `lint`, `generate:api`, `test:e2e` |

## 3. How it works

- **Types**: `interface`/`type` declarations describe shapes; `T[]` an array; `string | null` "either"; `Promise<T>` a future
  value; generics like `Page<T>` (items plus a cursor page) are templates.
- **The generation chain**: backend routes → `uv run python -m backend.api.openapi` writes `openapi.json` → `openapi-typescript`
  writes `schema.d.ts` → `types.ts` re-exports friendly names → `endpoints.ts` uses them. One command does it all:
  `npm run generate:api` ([the contract lesson](../03-backend/api/03-openapi-and-contract.md)).
- **Strictness**: `strict` forbids implicit `any`; `noUnusedLocals` forbids dead variables; `erasableSyntaxOnly` bans TypeScript
  features that need more than deleting the types (so the code is also valid JavaScript after type erasure).
- **`tsc -b`** (`npm run typecheck`) only checks; **Vite** compiles and bundles (`npm run build` runs both and writes `dist/`,
  which git ignores). In development Vite serves modules directly.
- **The editor** (VS Code) shows these types as you hover; it uses the same `tsconfig`.

## 4. Try it

**Works with no models. Verified 2026-10-12.**

```bash
npm run typecheck     # prints the header and nothing else when clean
npm run lint
npm run build         # tsc -b, then vite build: ends with "built in ~0.6s"; dist/ is git-ignored
```

Then see the generation chain protect you (a **scratch** edit, reverted at once): in `frontend/src/api/types.ts` change
`Schemas['SourceSummary']` to `Schemas['SourceSummaryX']` and run `npm run typecheck`. Observed:
`src/api/types.ts(7,37): error TS2339: Property 'SourceSummaryX' does not exist on type '{ BoundingBox: ...`. Restore with
`git restore frontend/src/api/types.ts`.

## 5. Change it

Add a friendly alias for a schema you will use: a line in `types.ts` such as `export type Foo = Schemas['Foo']` (the name must
exist in `schema.d.ts`); run `npm run typecheck`. Never edit `schema.d.ts`; regenerate it.

## 6. Break it on purpose

Edit a backend response model without running `npm run generate:api`: the **backend** test that compares the committed
`openapi.json` fails first ("run `npm run generate:api`"), and CI's frontend job regenerates the types and fails if they differ
([CI lesson](../01-basics/tools/06-ci.md)).

## 7. Exercises

1. Which file would you open to see what fields a `SourceSummary` has?
2. Why must `schema.d.ts` never be edited?
3. What does `tsc -b` not do that `vite build` does?

**Answers**

1. `frontend/src/api/schema.d.ts` (search `SourceSummary:`), or hover the type in the editor.
2. It is regenerated from the backend; edits would be lost and would lie about the API.
3. It does not produce the runnable bundle; it only checks types.

## 8. Related files

- Previous: [01](01-web-and-javascript.md) · Next: [03 React](03-react.md)
- [`frontend/tsconfig.app.json`](../../../../frontend/tsconfig.app.json), [`frontend/vite.config.ts`](../../../../frontend/vite.config.ts), [JavaScript and Rust tools](../01-basics/tools/07-javascript-and-rust-tools.md)
