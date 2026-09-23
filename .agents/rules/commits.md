# Commit rules

## Format

Every commit header follows [Conventional Commits](https://www.conventionalcommits.org/):

```text
<type>(<optional scope>)<optional !>: <subject>
```

| Type | Use for |
|---|---|
| `feat` | New behaviour |
| `fix` | Bug fix |
| `docs` | Documentation only |
| `test` | Adding or changing tests only |
| `refactor` | Restructuring with no behaviour change |
| `perf` | Performance improvement |
| `build` | Dependencies, packaging, build configuration |
| `ci` | CI workflows |
| `chore` | Maintenance that fits nothing above |
| `style` | Formatting only |
| `revert` | Reverting an earlier commit |

- Scope is lowercase and names the area: `feat(identities): …`, `fix(db): …`, `ci(frontend): …`.
- `!` marks a breaking change. Explain it in the body.
- Header ≤ 72 characters, imperative mood ("add", not "added"), no trailing period.
- The body explains **why**, not what. The diff shows what.

This is enforced by [`.githooks/commit-msg`](../../.githooks/commit-msg) locally
(`git config core.hooksPath .githooks`) and by the `commit-messages` CI job on every pull request.

## Size and scope

- **One logical change per commit.** If the subject needs "and", it is probably two commits.
- Keep commits small enough to review in one sitting. As a guide, aim for under ~400 changed
  lines, not counting lockfiles and generated files. A larger commit must explain in its body
  why it cannot be split.
- Do not mix kinds of change: refactors, formatting, dependency bumps and behaviour changes go in
  separate commits.
- Lockfile and generated-file changes go in the same commit as the change that caused them.
- Every commit should leave the repository building and its tests passing.
- The implementation entry and `CONTEXT.md` update for a change go in that change's commit, or in
  an immediately following `docs:` commit.

## Process

- Commit on a correctly named branch, never on `main` (see [`branches.md`](branches.md)).
- Do not commit, push or open pull requests unless the user asked for it.
- Never bypass hooks (`--no-verify`) or rewrite published history without explicit permission.
- Never commit secrets, real biometric data, user media, databases (`*.db`) or index files
  (`*.usearch`).
