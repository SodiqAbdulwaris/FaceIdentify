# AGENTS.md

FaceIdentify is a local Windows desktop application for visual identity recognition and
persistent face memory. Tauri → FastAPI → one persistent Python ML worker; SQLite (WAL) is
authoritative, USearch is a rebuildable index, ONNX Runtime runs inference.

## Start here

1. Read [`.agents/CONTEXT.md`](.agents/CONTEXT.md): current milestone, repository map, commands,
   known conflicts and what to do next.
2. Read every file in [`.agents/rules/`](.agents/rules/) before changing anything. They are
   mandatory.
3. Read the specs in [`docs/specs/`](docs/specs/) that cover the area you are touching. They are
   authoritative. If code, tests or a request conflicts with a spec, stop and ask.

## Non-negotiable rules

- **Document everything you do.** Every change gets an entry in
  [`docs/implementations/`](docs/implementations/), and `.agents/CONTEXT.md` is updated before you
  finish. See [`rules/documentation.md`](.agents/rules/documentation.md).
- **Never commit to `main`.** Work on a `<type>/<short-kebab-description>` branch and open a pull
  request. Every PR gets an independent review (subagent or `codex`/`opencode`/`agy`/`agent`
  CLI), and all feedback is addressed before it is reported ready. See
  [`rules/branches.md`](.agents/rules/branches.md).
- **Small, meaningfully scoped commits** in Conventional Commits format (`feat:`, `fix:`,
  `docs:`, `chore:` …). See [`rules/commits.md`](.agents/rules/commits.md).
- **Stay in scope.** Do not add features, models, dependencies or abstractions the task does not
  need, and never change the locked stack. See [`rules/scope.md`](.agents/rules/scope.md).
- **Verify before claiming.** Run the checks, report real results, and never weaken a test to
  get a pass. See [`rules/testing.md`](.agents/rules/testing.md).
- **Ask when unsure.** A question is cheaper than a wrong assumption baked into the codebase.
