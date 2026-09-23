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

## Review: every PR, before it is reported ready

When you open a PR, get an **independent review**. The PR author must never be its only
reviewer. Use one of these reviewers:

| Reviewer | Command (run from the repository, on the PR branch) |
|---|---|
| Codex CLI | `codex review --base main "<instructions>"` |
| OpenCode CLI | `opencode run "<instructions>"` |
| Antigravity CLI | `agy -p "<instructions>"` |
| Cursor CLI | `agent -p "<instructions>"` (not installed on the current machine) |
| Subagent | A fresh-context subagent given the PR number and these instructions |

The instructions give the reviewer the PR number, tell it to read `gh pr diff <n>`, `AGENTS.md`,
`.agents/rules/` and the specs the change touches, and ask for findings on correctness, spec
conformance and rule compliance, ranked by severity. Reviewers only read and report: they
never edit, push, comment or merge.

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
