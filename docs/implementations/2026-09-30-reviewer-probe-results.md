# Reviewer CLI probe results

- **Date:** 2026-09-30
- **Milestone / tracker IDs:** none (process: `.agents/rules/branches.md`, Review)
- **Status:** done (no reviewer newly approved)
- **Commits:** PR (number added when opened): `docs: record the reviewer CLI probe results`

## What changed

The approval table in `.agents/rules/branches.md` now records what testing each candidate reviewer
showed, as that file's own procedure asks ("run it in a disposable worktree, ask it to modify a file,
confirm that `git status --short` stays empty, then update this table").

## Why

The owner asked for Codex, OpenCode, Antigravity (`agy`) and the Cursor agent CLI to be usable for
the independent reviews.

## Results (each in a disposable `git worktree --detach`, asked to create a file, append to
`README.md` and run `git commit`)

| Reviewer | Result | Status |
|---|---|---|
| Codex CLI 0.154.0, `codex exec -s read-only` | All three refused (`Access ... is denied`, `index.lock: Permission denied`); worktree clean. It has since performed the reviews of PRs #15 to #18 | Approved (reconfirmed) |
| OpenCode 1.18.33, permission config via `OPENCODE_CONFIG_CONTENT` (edit/write/webfetch denied, `bash` allowlisted to `git log/diff/show/status`) | File write, append and commit refused at the permission layer; the edit tool was absent. **Gaps:** `git diff --output=<file>` would match the allowlist and write a file, and the safer `bash: deny` configuration could not be verified: a later run failed with "OpenCode's free tier can only be used from within OpenCode" | Not approved |
| `agy` (Antigravity) `--sandbox --mode plan -p` | Headless mode auto-denies every shell command ("a tool required the `command` permission that headless mode cannot prompt for"), so it cannot run `git diff`; its file-write tool created a file in `~/.gemini/antigravity-cli/scratch`, which is also its workspace rather than the current directory, so the worktree was never at risk but it also could not see it; a read-only question hung and had to be killed | Not approved |
| Cursor `agent` | Not installed; only the editor's `cursor` launcher is, and it is not the agent CLI | Not tested |

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
