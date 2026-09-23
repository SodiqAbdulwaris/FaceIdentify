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
only through a tested read-only invocation. "Only read" is then enforced rather than requested.
All scratch files live in one temporary directory:

```bash
# Author, before the review: refresh local refs. The reviewer itself never uses the network.
git fetch origin

tmp="$(mktemp -d)"
dir="$tmp/worktree"; prompt="$tmp/prompt.md"; result="$tmp/review.md"
git worktree add --detach "$dir" "origin/<branch>"
# Write the instructions (below) to "$prompt", then run an approved reviewer:
codex exec -s read-only -C "$dir" -o "$result" - < "$prompt"

git -C "$dir" status --short          # must print nothing: the reviewer changed no files
gh pr comment <n> --body-file "$result" # record the review (after resolving local paths)
git worktree remove --force "$dir" && rm -rf "$tmp"
```

| Reviewer | Status | Read-only invocation |
|---|---|---|
| Codex CLI | **Approved** (used on PR #2) | `codex exec -s read-only -C "$dir" -o "$result" - < "$prompt"` |
| Subagent | **Approved** | A fresh-context subagent whose tools cannot edit (e.g. a read-only explore type), pointed at `$dir` |
| Antigravity CLI (`agy`) | Not yet approved | Candidate: `agy --sandbox --mode plan -p …`, run in `$dir`. Test that it cannot write before approving |
| OpenCode CLI | Not yet approved | `--agent plan` only selects an agent and is not a sandbox. Needs a tested read-only configuration |
| Cursor CLI (`agent`) | Not yet approved | Not installed on the current machine. Identify and test its read-only flag first |

To approve a reviewer, run it in a disposable worktree, ask it to modify a file, confirm that
`git -C "$dir" status --short` stays empty, then update this table. `codex review --base` does
**not** accept custom instructions, so use `codex exec`.

The instructions in `$prompt` give the PR number and branch and tell the reviewer to:

- read the change with `git log --oneline origin/main..HEAD` and `git diff origin/main...HEAD`
  (local refs only; no network);
- read `AGENTS.md`, `.agents/rules/` and the specs the change touches;
- report findings on correctness, spec conformance and rule compliance, each with severity,
  `file:line` and a concrete fix;
- never edit, commit, push, comment or merge.

Then:

1. **Record the review** as a PR comment (as in the block above), naming the reviewer used.
   Replace local absolute paths with repository-relative ones before posting.
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
