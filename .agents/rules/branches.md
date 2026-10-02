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
# Write the instructions (below) to "$prompt", then run an approved reviewer (Codex shown):
codex exec -s read-only -C "$dir" -o "$result" - < "$prompt" > "$tmp/reviewer.log" 2>&1
rc=$?
if [ "$rc" -ne 0 ] || [ ! -s "$result" ]; then
  echo "REVIEW FAILED (exit $rc): read $tmp/reviewer.log; do not post or clean up yet"
fi
git -C "$dir" status --short   # must print nothing: the reviewer changed no files
git status --short             # the author's checkout must be unchanged too
```

Only after a successful run, and after replacing local absolute paths in `$result` with
repository-relative ones:

```bash
gh pr comment <n> --body-file "$result"
git worktree remove --force "$dir" && rm -rf "$tmp"
```

With a **subagent** reviewer, skip the `codex exec` line: give the subagent the instructions
and `$dir`, save its report to `$result`, then continue from the two `git status` checks.

| Reviewer | Status | Read-only invocation |
|---|---|---|
| Codex CLI | **Approved** (used on PR #2 and PRs #15 to #18) | `codex exec -s read-only -C "$dir" -o "$result" - < "$prompt"`. Re-probed 2026-09-30: asked to create a file, append to `README.md` and run `git commit`, all three were refused (access denied, `index.lock` permission denied) and the worktree stayed clean |
| Subagent | **Approved, but the owner prefers a CLI reviewer to save tokens (2026-10-02); use it only if no CLI reviewer works** (used on PR #2, final review) | A fresh-context subagent without edit tools, told to work only in `$dir`. It may still have a shell, so this is *detected*, not sandboxed: check `git -C "$dir" status --short` **and** the author's own `git status` afterwards |
| Antigravity CLI (`agy`) | **Approved by the owner 2026-10-02** ("use a CLI agent for reviews, not a subagent, to conserve tokens"); the 2026-09-30 probe below still applies, so put the diff in the prompt and treat its output as advice from a reviewer that cannot be shown read-only (the disposable worktree is the safety). Probed 2026-09-30: | `agy --sandbox --mode plan -p` does not make a usable read-only reviewer: headless, it auto-denies every shell command (so it cannot run `git diff`); its file-write tool created a file in its own scratch directory (`~/.gemini/antigravity-cli/scratch`), which is also its workspace rather than the current directory, so it could neither see the worktree nor be shown unable to write to it; and a read-only question hung. Retest if a release documents a workspace flag and a real read-only mode. **Re-probed 2026-10-02 with Antigravity CLI 1.2.14 (`--add-dir`, `--mode plan`): headless `agy -p` produced no output even for a trivial prompt ("a tool required the `command` permission that headless mode cannot prompt for"); the only remedy offered is `--dangerously-skip-permissions`, which approves every tool including writes, so it was not used. Not usable as a reviewer unless the owner allows that flag or a read-only allow-rule is found** |
| OpenCode CLI | **Approved by the owner 2026-10-02** (same instruction); use the strict configuration (`bash` of `deny`, edit/write/webfetch denied) and supply the diff in the prompt, in a disposable worktree. Probed 2026-09-30: | `--agent plan` only selects an agent and is not a sandbox. With `OPENCODE_CONFIG_CONTENT='{"permission":{"edit":"deny","write":"deny","webfetch":"deny","bash":{"*":"deny","git log*":"allow","git diff*":"allow","git show*":"allow","git status*":"allow"}}}'` it refused a file write, an append and a commit and had no edit tool. Two gaps stop approval: a `git diff --output=<file>` would match the allowlist and writes a file (a `bash` of `deny` is the safer configuration, with the diff supplied in the prompt), and that stricter configuration could not be verified because its free tier began refusing non-interactive use ("can only be used from within OpenCode") |
| Cursor CLI (`agent`) | Not yet approved | Not installed on the current machine (only the editor's `cursor` launcher is, and it is not the agent CLI). Identify and test its read-only flag first |

**A failed run is not a review.** If the reviewer exits non-zero or `$result` is empty, read
`$tmp/reviewer.log` *before* cleaning up, fix the cause or switch to another approved reviewer,
and never report the PR as reviewed. For example, on 2026-09-23 Codex stopped with a usage-limit
error, and the review was redone with a subagent.

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
