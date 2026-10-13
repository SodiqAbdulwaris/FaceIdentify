# Tools 05 Git and pull requests

## 1. What this is and why it exists

**Git** records every version of every file as a chain of **commits**, each with a message, an author
and a parent. A **branch** is a movable name for a line of commits. `main` is the shared, protected
line. A **pull request** (PR) asks to merge a branch into `main`; GitHub shows the difference, runs the
checks and records the review. This project has an unusually strict version of that workflow because
it is built with an AI assistant and checked by independent reviewers. This lesson is the workflow, as
commands you can run.

## 2. Where it lives

| Rule or tool | Where |
|---|---|
| The non-negotiable rules | `AGENTS.md`; details in `.agents/rules/branches.md`, `commits.md`, `documentation.md` |
| The local hooks | `.githooks/commit-msg`, `pre-commit`, `pre-push`, `check-branch-name`; enabled by `git config core.hooksPath .githooks` |
| The server-side protection of `main` | `.github/rulesets/main.json` (a PR is required; rebase merge only; five required checks; no bypass) |
| CI | `.github/workflows/ci.yml` (see [CI](06-ci.md)) |

## 3. How it works

**Branch names** are `<type>/<short-kebab-description>` where the type is one of `feat fix docs chore
refactor test ci build perf style revert`: `feat/identity-merge-service`, `docs/guides/learning-guide-restructure`.
Only one `/`; lowercase words joined by single hyphens.

**Commit messages** are [Conventional Commits](https://www.conventionalcommits.org/):
`type(scope): subject`. The header is at most **72 characters**, in the imperative ("add", not "added"),
with no trailing period; the body explains **why**, not what. Small commits, one logical change each,
every commit leaving the tests passing. Lockfiles and generated files go in the same commit as the
change that caused them.

**The daily loop**:

```bash
git switch main && git pull                   # start from an up-to-date main
git switch -c docs/short-description          # one branch per task
# ... edit files ...
git status                                    # what changed?
git diff                                      # exactly how?
git add path/to/file                          # stage it for the next commit
git commit -m "docs(learning): explain X"     # the commit-msg hook checks the header
git push -u origin docs/short-description     # the pre-push hook checks the branch name
gh pr create ...                              # open the pull request
```

**The pull request**: a title in the same Conventional Commits form; a description saying what changed
and why, how it was verified (commands *and* results), and a link to the `docs/implementations/` entry.
`main` takes only **rebase merges** (a rebase replays the branch's commits on top of the current `main`,
keeping the history a straight line), after all required checks pass **on the exact head commit**.

**Rebase conflicts** happen when two branches edited the same lines (often `PROJECT_STATUS.md` or
`.agents/CONTEXT.md`). You resolve them by keeping both sides' meaning. Never `git push --force` to
`main`; `--force-with-lease` on your own branch is the safe form.

**Review**: every PR an agent opens gets an *independent, read-only* review (Codex CLI, or a read-only
subagent) run in a disposable `git worktree` so the reviewer never touches your files. The full
procedure is in `.agents/rules/branches.md` and is summarised in
[rules, branches and reviews](../../06-evaluation-and-operations/06-rules-branches-reviews.md).

## 4. Try it

**Works with no models. Verified 2026-10-12** (the hooks and git commands; opening a real PR needs a
GitHub login and was done through the GitHub tools, not repeated here).

1. Enable the hooks and see which are active: `git config core.hooksPath .githooks`, then
   `git config core.hooksPath` prints `.githooks`.
2. **Test the commit-message hook without committing anything.** Put a message in a file and run the hook
   on it:

   ```bash
   echo "added stuff" > /tmp/m1.txt
   sh .githooks/commit-msg /tmp/m1.txt; echo "exit=$?"
   ```

   Expected: `commit-msg: header does not follow Conventional Commits`, the header it saw, the expected
   form, the type list, and `exit=1`. Now `echo "docs(learning): add the thing" > /tmp/m3.txt` and run it
   on that: no output, `exit=0`. A header of 86 characters says `header is 86 chars; keep it <= 72`.
3. **Test the branch-name rule:**

   ```bash
   sh .githooks/check-branch-name "Feature/Bad_Name"            # exit 1, shows the pattern
   sh .githooks/check-branch-name "docs/guides/learning-guide-restructure"   # exit 0, silent
   ```

4. See what your branch adds compared with `main` (works once `origin/main` is fetched):

   ```bash
   git log --oneline origin/main..HEAD
   git diff --stat origin/main...HEAD | tail -3
   ```

5. A disposable second checkout, as the review procedure uses (safe: it changes nothing in your files):

   ```bash
   T="$(mktemp -d)"; git worktree add --detach "$T/worktree" HEAD
   git -C "$T/worktree" status --short          # prints nothing: a clean copy
   git worktree list                            # shows both checkouts
   git worktree remove --force "$T/worktree"; rm -rf "$T"
   ```

   PowerShell uses `New-TemporaryFile`-style paths instead of `mktemp` (*unverified here*).
6. **Try a commit on `main` and see it refused** (safe: the hook stops it, so nothing is created).
   Switch to `main`, run `git commit --allow-empty -m "docs: test"`, and expect:

   ```text
   pre-commit: do not commit on main; create a branch first:
     git switch -c <type>/<short-kebab-description>
   ```

   `git log --oneline -1` is unchanged. Switch back with `git switch -`.

## 5. Change it

Practise the loop on a throwaway branch with a trivial documentation change:

1. `git switch -c docs/practice-branch`
2. Make a trivial change to a scratch copy of any markdown file (not tracked), or to a throwaway file,
   and `git add` it.
3. Try a bad message: `git commit -m "added stuff"`. Expected: `commit-msg: header does not follow
   Conventional Commits` and no commit is made (`git log --oneline -1` is unchanged).
4. Commit properly: `git commit -m "docs: practise"`. Expected: it succeeds.
5. Clean up: `git switch -` then `git branch -D docs/practice-branch`.

Never practise on a branch you intend to push; never use `--no-verify` to get past a hook (the rules
forbid it).

## 6. Break it on purpose

Name a branch `Feature/New_Thing` and push it: `pre-push` runs `check-branch-name` and prints the
pattern. Push to `main`: `pre-push: direct pushes to main are not allowed; push a branch and open a
PR`. And even if you disabled the local hooks, the CI jobs "Branch name" and "Commit messages" run the
same two scripts on the pull request, and the GitHub ruleset blocks pushing to `main` at all. Three
layers of the same rule is deliberate.

## 7. Exercises

1. Is `feat/Add-Merge` a valid branch name? Is `fix/sqlite-busy-retry`?
2. A commit header is `fix(db): retry the whole transaction when SQLite reports the database is busy`.
   Is it valid?
3. Why rebase merge only?
4. What must be true of the head commit before a PR can be merged?
5. Why is the reviewer run in a separate worktree?

**Answers**

1. No (uppercase); yes.
2. It has the right shape but is 80 characters, over the 72 limit: shorten it ("retry the whole
   transaction on a busy database").
3. It keeps `main` a straight line where every small commit lands unchanged and stands on its own.
4. All five required checks pass on that exact commit (a later push means waiting again), and review
   threads are resolved.
5. So "read-only" is enforced rather than requested: the reviewer cannot touch your files.

## 8. Related files

- Previous: [04 ruff and mypy](04-ruff-and-mypy.md) · Next: [06 CI](06-ci.md)
- [`.agents/rules/branches.md`](../../../../../.agents/rules/branches.md), [`.agents/rules/commits.md`](../../../../../.agents/rules/commits.md)
- [Rules, branches and reviews](../../06-evaluation-and-operations/06-rules-branches-reviews.md)
