# API 03 OpenAPI and the generated contract

## 1. What this is and why it exists

The front end and the back end are written in different languages (TypeScript and Python) and could easily drift:
a field renamed on one side, a status code changed on the other. The project closes that gap with a **generated
contract**. **OpenAPI** is a machine-readable description of every route, its inputs and its answers. FastAPI
produces it from the Python type hints; a tool turns it into TypeScript types; and tests plus a CI step fail if
any of the three disagrees. The result: if you change a route's shape and forget the front end, a compiler or a
test tells you before a person does.

## 2. Where it lives

| Link in the chain | File |
|---|---|
| The routes and their Pydantic models | `backend/api/routes/*.py` |
| The OpenAPI builder and exporter | `backend/api/openapi.py` (`openapi_document`, `render`, `main`) |
| The committed document | `frontend/src/api/openapi.json` (never edit by hand) |
| The generated TypeScript | `frontend/src/api/schema.d.ts` (never edit by hand) |
| Friendly names for the generated types | `frontend/src/api/types.ts` |
| One typed function per operation | `frontend/src/api/endpoints.ts` |
| The generating command | `npm run generate:api` (= `uv run python -m backend.api.openapi && npm run generate:types --workspace frontend`) |
| The tests | `tests/contracts/test_openapi_contract.py` (6 tests); CI "Frontend" job step "Generated API types are up to date" |

## 3. How it works

1. `openapi_document()` builds the real application (`create_backend_app`, with placeholder settings, because
   building the app opens nothing and touches no path) and asks FastAPI for `app.openapi()`.
2. `render()` writes it as stable text: sorted keys, two-space indent, LF line endings, one trailing newline, so a
   diff shows only real changes.
3. `openapi-typescript` turns `openapi.json` into `schema.d.ts`: a `paths` type, an `operations` type and
   `components["schemas"][...]` for every model.
4. `types.ts` gives the schemas friendly names (`export type SourceSummary = Schemas['SourceSummary']`);
   `endpoints.ts` has one function per operation, typed with them. Screens call `endpoints(api).listSources(...)`.

The tests that keep it honest (`test_openapi_contract.py`):

- the committed document **equals** what the application produces (`...is_what_the_application_produces`);
- **every** `/api/v1` operation declares the one error shape (`ErrorEnvelope`) as its default response;
- operation ids are the **unique function names** (`import_source`, `list_identities`), not FastAPI's long
  path-derived defaults;
- the document names **no launch secret and no filesystem path**;
- the exporter writes the rendered document, and running the module rewrites the committed path.

## 4. Try it

**Works with no models. Verified 2026-10-12.**

1. **Regenerate and prove nothing changes.** From a clean checkout:

   ```bash
   npm run generate:api
   git status --short
   ```

   Expected: `wrote frontend/src/api/openapi.json`, the `openapi-typescript` lines, and an **empty** `git status`
   (the committed files already match the routes).
2. **List every operation** (this is how the 39 in the [API README](README.md) were counted):

   ```python
   import json
   d = json.load(open("frontend/src/api/openapi.json"))
   ops = [(m.upper(), p, o["operationId"]) for p, v in d["paths"].items() for m, o in v.items()]
   print(len(d["paths"]), "paths,", len(ops), "operations")
   for op in ops[:5]: print(op)
   ```

   Expected: `36 paths, 39 operations`, then rows such as `('GET', '/api/v1/identities', 'list_identities')`.
3. **Read one generated type** next to the model it came from:

   ```bash
   grep -n "SourceSummary: {" -A14 frontend/src/api/schema.d.ts
   ```

   You will see fields `availability`, `created_at`, `display_name`, `id`, `processing_status`, ... with their
   types: exactly the Pydantic `SourceSummary` in `backend/api/routes/sources.py`.
4. Run the contract tests: `uv run pytest tests/contracts/test_openapi_contract.py -q`. Expected: `6 passed`.
5. See the chain break (this was run in the add-a-route dry run): add a route, run step 4, and read
   `frontend/src/api/openapi.json is stale: run npm run generate:api and commit the result`.

## 5. Change it

Rename a field of a response model **in a scratch branch** (say `display_name` to `name` in `SourceSummary`) and
follow the compiler:

1. `uv run pytest tests/contracts/test_openapi_contract.py -q` fails (stale document);
2. `npm run generate:api` regenerates both files;
3. `npm run typecheck` now fails in every place the front end reads `display_name`, and `uv run pytest` fails in
   the tests that assert it.

That list is your to-do list for a real rename. (Not performed by hand in this guide: the add-a-route dry run
exercised the same chain.) The generated files and the change that caused them go in **one commit**.

## 6. Break it on purpose

Edit `frontend/src/api/schema.d.ts` by hand and run CI's check locally:
`npm run generate:types --workspace frontend && git status --porcelain -- frontend/src/api`. The generator
overwrites your edit and the status shows the file changed back: hand edits are pointless by design. Edit
`openapi.json` by hand instead and the backend test fails ("stale"). The header comment of `types.ts` says it:
"schema.d.ts is generated from the backend; never edit it".

## 7. Exercises

1. Which command regenerates both the document and the TypeScript types?
2. Which two things must be committed together with a route change?
3. What does the "Generated API types are up to date" CI step do?
4. Why does `openapi.py` build the app with placeholder paths and a placeholder token?
5. Where do you look to find the function the front end calls for `POST /sources/{id}/process`?

**Answers**

1. `npm run generate:api`.
2. The route/model change and the regenerated `openapi.json` and `schema.d.ts`.
3. It regenerates `schema.d.ts` from the committed `openapi.json` and fails if the working tree differs.
4. Building the app opens nothing, so no real library or secret is needed; the document never contains the token.
5. `processSource` in `frontend/src/api/endpoints.ts`.

## 8. Related files

- Previous: [02 Add a route](02-add-a-route.md) · [API README](README.md)
- [`backend/api/openapi.py`](../../../../backend/api/openapi.py), [`frontend/src/api/endpoints.ts`](../../../../frontend/src/api/endpoints.ts)
- [API client and queries](../../04-frontend/05-api-client-and-queries.md), [CI](../../01-basics/tools/06-ci.md)
