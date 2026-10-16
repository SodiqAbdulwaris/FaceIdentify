# Switching agents: continuing with Codex

- **Date:** 2026-10-16
- **Milestone / tracker IDs:** none (process documentation)
- **Status:** done
- **Commits:** PR to be recorded when merged (`docs: add a guide for continuing work with Codex`)

## What changed

- `docs/guides/AGENT_HANDOFF.md` (new): how to start Codex in this repository and what to tell it
  first, where the state lives, the rules that matter most when switching (merges need the owner's
  own message, rebase merges only, independent review, CI on the exact head, data folders, the live
  recognition policy), the traps that cost time (the commit-msg hook's silent refusal, PowerShell
  versus Git Bash, CRLF files, shared doc lines that conflict, detached long runs, the worker's spawn
  guard, frontend formatting), the checks, and how to hand back.
- `AGENTS.md`: "Start here" item 4 points to the guide.
- `.agents/rules/branches.md`: who reviews a PR that Codex wrote (a fresh read-only Codex run in a
  disposable worktree counts; Claude Code when available), with a dated delegated decision.
- `.agents/CONTEXT.md` (Next steps) and the implementation index.

## Why

The owner (2026-10-16) wants to continue with Codex when Claude Code reaches its usage limit. Codex
reads `AGENTS.md` itself, so the repository's rules already reach it; what it could not see were the
lessons kept only in Claude Code's private memory (the commit-hook trap, the rebase-only merges, the
detached-run lesson, the review set-up). They now live in the repository, where both agents read
them.

## Decisions

- **Codex-authored PRs:** the review rule says the author is never the only reviewer. A separate
  `codex exec -s read-only` run, started fresh with only the review prompt in a disposable worktree,
  has no memory of the authoring conversation, so it counts as independent; Claude Code reviews when
  available. Decided by the agent under the owner's delegation of 2026-10-16 ("I'll leave all other
  decisions to your recommendations"); recorded in `.agents/rules/branches.md`.
- The owner's `~/.codex/config.toml` (full access, no approvals) is described, not changed.

## Verification

Documentation only. Codex CLI 0.159.3 is installed on the owner's machine and reads `AGENTS.md`; the
links in the new guide were checked to resolve.

## Follow-ups

- Keep the guide's trap list current; any agent that learns a new one adds it.
