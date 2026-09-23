# Branch and pull request rules

## All changes go through a branch and a pull request

- **Never commit or push directly to `main`.** Every change is made on its own branch and merged
  through a pull request.
- Start each branch from an up-to-date `main`, with one branch per task. Do not stack unrelated
  work on an existing branch.
- Merge only when every CI check is green. Do not merge your own PR unless the user asked you to.
- PRs are merged with **rebase merge** (the only method enabled), so every small commit lands on
  `main` unchanged, in a linear history. Each commit must therefore stand on its own.
- Delete the branch after merging.

## Branch names

```text
<type>/<short-kebab-description>
```

- `<type>` is one of the commit types: `feat fix docs chore refactor test ci build perf style
  revert`. Use the type of the branch's main change.
- The description is lowercase words joined by single hyphens, describing the job rather than
  the person or date: `feat/identity-merge-service`, `fix/sqlite-busy-retry`,
  `docs/testing-guide`, `test/m1-identity-invariants`.
- Only one `/`. No uppercase letters, underscores, spaces, or leading, trailing or double hyphens.

## Pull requests

- Title in Conventional Commits format, like a commit header.
- The description says what changed and why, how it was verified (commands and results), and
  links the `docs/implementations/` entry.
- Keep PRs small and focused, following the same size guidance as commits
  ([`commits.md`](commits.md)).

## Review: every PR an agent opens, before it is reported ready

When an agent opens a PR, it gets an **independent review**. The authoring agent must never be
its only reviewer. PRs opened by humans may use the same process but are not required to.

**Isolation.** Run the reviewer in a disposable worktree, never in the author's checkout, and
always in the tool's read-only mode. "Only read" is then enforced rather than merely requested:

```bash
git fetch origin
dir="$(mktemp -d)/review-pr-<n>"
git worktree add --detach "$dir" "origin/<branch>"
# … run one reviewer below with $dir as its working directory …
git worktree remove --force "$dir"
```

| Reviewer | Command (read-only mode) |
|---|---|
| Codex CLI | `codex exec -s read-only -C "$dir" -o review.md - < prompt.txt` |
| OpenCode CLI | `cd "$dir" && opencode run --agent plan "<instructions>"` |
| Antigravity CLI | `cd "$dir" && agy --mode plan -p "<instructions>"` |
| Cursor CLI | `cd "$dir" && agent -p "<instructions>"` in its read-only mode (not installed on the current machine; check its flags before first use) |
| Subagent | A fresh-context, read-only subagent (no edit tools) pointed at `$dir` |

Only the Codex command has been exercised so far (PR #2). Verify the others on first use and
correct this table if needed. `codex review --base` does **not** accept custom instructions, so
use `codex exec`.

The instructions (`prompt.txt`) give the PR number and branch and tell the reviewer to:

- read the change with `git log --oneline origin/main..HEAD` and `git diff origin/main...HEAD`
  (local git, because sandboxed reviewers may have no network);
- read `AGENTS.md`, `.agents/rules/` and the specs the change touches;
- report findings on correctness, spec conformance and rule compliance, each with severity,
  `file:line` and a concrete fix;
- never edit, commit, push, comment or merge.

Then:

1. **Record the review** as a PR comment (`gh pr comment <n> --body-file …`), naming the reviewer
   used.
2. **Check for all feedback:** the review, other PR comments (`gh pr view <n> --comments`), line
   comments (`gh api repos/{owner}/{repo}/pulls/<n>/comments`) and CI status.
3. **Address every finding.** Fix it in a new commit, or reply on the PR explaining why it
   stands. Do not silently ignore any finding.
4. Re-review after substantial changes. Report the PR as ready only when the findings are
   resolved and CI is green.

## Enforcement

| Where | What |
|---|---|
| `.githooks/pre-commit` (local) | Rejects commits on `main` (except the repository's first commit) |
| `.githooks/pre-push` (local) | Rejects pushes to `main` and badly named branches |
| `.githooks/check-branch-name` | The single definition of the naming pattern, used by the hook and CI |
| CI `Branch name` job | Rejects PRs from badly named branches |
| GitHub ruleset (`.github/rulesets/main.json`) | Server side: no direct pushes, force-pushes or deletion of `main`; merges need a PR with all required checks passing. No bypass actors. |

Enable the local hooks once per clone with `git config core.hooksPath .githooks`. Never bypass
them with `--no-verify`.

**Only exception:** the repository's very first commit, which creates `main` before any PR is
possible. `pre-commit` allows it automatically, because `HEAD` does not exist yet. Pushing it
needs the user's explicit permission and a one-off `--no-verify` to get past `pre-push`, and it
happens before the ruleset is applied. After that, `main` changes only through pull requests.
