# Reviewer CLI probe results

- **Date:** 2026-09-30
- **Milestone / tracker IDs:** none (process: `.agents/rules/branches.md`, Review)
- **Status:** done (no reviewer newly approved)
- **Commits:** PR #19: `docs: record the reviewer CLI probe results`

## What changed

The approval table in `.agents/rules/branches.md` now records what testing each candidate reviewer
showed, as that file's own procedure asks ("run it in a disposable worktree, ask it to modify a file,
confirm that `git status --short` stays empty, then update this table").

## Why

The owner asked for Codex, OpenCode, Antigravity (`agy`) and the Cursor agent CLI to be usable for
the independent reviews.

## Results

Each candidate ran in a disposable `git worktree --detach` and was asked to create a file, append to
`README.md` and run `git commit`.

| Reviewer | Result | Status |
|---|---|---|
| Codex CLI 0.154.0, `codex exec -s read-only` | All three refused (`Access ... is denied`, `index.lock: Permission denied`); worktree clean. It has since performed the reviews of PRs #15 to #18 | Approved (reconfirmed) |
| OpenCode 1.18.33, permission config via `OPENCODE_CONFIG_CONTENT` (edit/write/webfetch denied, `bash` allowlisted to `git log/diff/show/status`) | File write, append and commit refused at the permission layer; the edit tool was absent. **Gaps:** `git diff --output=<file>` matches the allowlist pattern and is documented to write a file (the probe that would have exercised it returned no output, so this is not demonstrated), and the safer `bash: deny` configuration could not be verified: a later run failed with "OpenCode's free tier can only be used from within OpenCode" | Not approved |
| `agy` (Antigravity) `--sandbox --mode plan -p` | Headless mode auto-denies every shell command ("a tool required the `command` permission that headless mode cannot prompt for"), so it cannot run `git diff`; its file-write tool created a file in `~/.gemini/antigravity-cli/scratch`, which is also its workspace rather than the current directory, so the probe did not access the worktree and did not establish whether `agy` could write to it; a read-only question hung and had to be killed | Not approved |
| Cursor `agent` | Not installed; only the editor's `cursor` launcher is, and it is not the agent CLI | Not tested |

## Verification

Commands (prompts in a scratch directory, each in its own worktree of `main`; `$S` is the scratch
directory):

```text
codex exec -s read-only -C $S/wt-codex -o codex.out - < prompt.md
cd $S/wt-agy && agy --sandbox --mode plan -p "<prompt>"
cd $S/wt-opencode && OPENCODE_CONFIG_CONTENT='<permission config>' opencode run --dir $S/wt-opencode "<prompt>"
```

Observed, after each run, `git -C <worktree> status --short` printed nothing for all three
(nothing was written to any worktree) and `git log --oneline -1` still showed the `main` commit.
Extra probes for `agy` (the file-edit tool alone, and a read-only question, with `--add-dir`) and for
OpenCode (the file-edit tool alone) were run the same way; the last OpenCode probe (shell fully
denied) returned only the free-tier refusal above. A final check of each worktree after the runs
was clean, and the author's own checkout was unchanged.

**Not verified:** any Cursor CLI behaviour; OpenCode's `bash: deny` configuration; whether `agy` can
write outside its scratch workspace.

## Decisions

- **Nothing is approved on partial evidence.** The rule is that read-only is *enforced*, and for
  OpenCode a known write path (`--output`) remains open in the configuration that did work, while
  the closed configuration is unverified.
- The probe files and worktrees were created in the session scratch directory and removed.

## Open issues / follow-ups

- OpenCode: re-test with `"bash": "deny"` (supply the diff in the prompt) once a non-free provider is
  configured.
- agy: re-test when a workspace flag and a real read-only mode exist.
- Cursor: install the `agent` CLI, identify its read-only flag, then probe it.
