# Branch workflow and main protection

- **Date:** 2026-09-23
- **Milestone / tracker IDs:** repository conventions (supports CI-001 to CI-005)
- **Status:** done; ruleset active on GitHub
- **Commits:** `887307c` chore: initialize repository with git conventions (bootstrap, on `main`); the rest arrive via the `chore/project-foundation` PR

## What changed

- `.agents/rules/branches.md`: all changes go through a branch and a PR. Branch names are
  `<type>/<short-kebab-description>`, using the commit types. It also covers PR expectations, the
  enforcement table and the first-commit bootstrap exception. Linked from `AGENTS.md` and
  `rules/commits.md`.
- `.githooks/check-branch-name`: the single definition of the naming pattern.
- `.githooks/pre-commit`: rejects commits on `main` unless the repository has no commits yet.
- `.githooks/pre-push`: rejects pushes to `main` and pushes of badly named branches. It ignores
  tags and remote-branch deletions.
- `.github/workflows/ci.yml`: new `Branch name` job (runs the same script on the PR head
  branch, passed through `env` rather than inline `${{ }}` to avoid script injection).
- `.github/rulesets/main.json`: default-branch ruleset that blocks deletion and force-pushes,
  requires a pull request (0 approvals, review threads resolved, stale reviews dismissed), and
  requires the five CI checks with up-to-date branches. No bypass actors, so admins cannot push
  directly either.

## Why

User request (2026-09-23): changes on meaningfully named branches with PRs, and a GitHub rule
that disallows pushing directly to `main`.

## Decisions

- **User decisions (2026-09-23):** public repository `SodiqAbdulwaris/FaceIdentify` (rulesets
  are enforced on public repositories on every plan); rebase merge only; bootstrap sequence
  approved: minimal first commit pushed to `main`, ruleset applied, then everything else via a PR.
- **Commit email:** the bootstrap commit was first pushed with the GitHub noreply address. The
  user then chose `sodiqabdulwaris@gmail.com`, so the commit was re-authored and force-pushed
  (`da65d03` → `887307c`) before the ruleset existed. The noreply override was removed from the
  repo-local config.

- **Required approvals = 0.** With one developer, GitHub does not let a PR author approve their
  own PR, so requiring 1 would block every merge. Raise it when a second reviewer exists.
- **No bypass actors**, so the rule also applies to the repository owner.
- **One `/` in branch names.** Deeper nesting is rejected to keep names flat and predictable.
- Branch-name enforcement uses hook + CI rather than a GitHub `branch_name_pattern` rule, which
  is not available on all plans.
- The ruleset is kept as versioned JSON so changes to it are reviewed like code.

## Verification

- `check-branch-name`: 13 cases (4 valid, 9 invalid incl. `main`, `feature/x`, uppercase,
  underscore, trailing or double hyphen, nested `/`). All correct.
- `pre-push` fed synthetic ref lines: 6 cases (push to main, good branch, bad branch, tag,
  remote deletion, multi-ref including main). All correct.
- Scratch-repository test with the real hooks and a bare remote: bootstrap commit on `main`
  allowed; second commit on `main` blocked; commit on `feat/something` allowed; bad message
  blocked; push of `feat/something` allowed; push to `main` blocked; push of `Bad_Branch`
  blocked.
- `ci.yml` parses.
- Repository settings: `allow_rebase_merge=true`, squash and merge commits disabled,
  `delete_branch_on_merge=true` (confirmed from the API response).
- Ruleset created (id `23894323`, enforcement `active`). `GET /repos/.../rules/branches/main`
  lists deletion, non_fast_forward, pull_request (`allowed_merge_methods: ["rebase"]`) and
  required_status_checks with all five contexts.
- **Not verified:** an actual rejected direct push to `main` (deliberately not attempted: if it
  succeeded, it could no longer be force-reverted). CI jobs have not run on GitHub yet.

## Open issues / follow-ups

1. ~~Create the repository and apply the ruleset~~ Done 2026-09-23. To change the ruleset, edit
   `main.json` in a PR, then run
   `gh api -X PUT repos/SodiqAbdulwaris/FaceIdentify/rulesets/23894323 --input .github/rulesets/main.json`.
2. Rulesets on **private** repositories require GitHub Pro/Team. On a free plan the repository
   must be public for the ruleset to be enforced.
3. ~~Choose a merge method~~ **Decided by the user (2026-09-23): rebase merge only.** It keeps
   the small commits and a linear history. It is set in the ruleset (`allowed_merge_methods`) and in
   the repository settings.

## Update 2026-09-23: independent PR review

The user asked that every PR opened by an agent is reviewed by a subagent or by the OpenCode,
Antigravity (`agy`), Codex or Cursor (`agent`) CLI, and that feedback is checked. The rule
applies to every PR an agent opens. Added a
*Review* section to `.agents/rules/branches.md`, covering the reviewer commands, read-only
reviewers, recording the review as a PR comment, checking all feedback channels and addressing
every finding. It is also summarised in `AGENTS.md` and the `CONTEXT.md` commands. Installed on
this machine: `codex` 0.154.0, `opencode` 1.18.31 and `agy` 1.2.7.

The first run, on PR #2, exposed two problems, both now fixed in the rule:
`codex review --base` rejects custom instructions (use `codex exec -s read-only`), and the
reviewer's sandbox may have no network (use local `git diff` rather than `gh pr diff`). The
Codex review then requested changes. Two of its findings led to reviewers running in a
disposable worktree in their read-only mode, and to one consistent scope (agent-opened PRs). The Cursor CLI is not installed. Shipped in PR #2 (`docs: require independent review of
every pull request`).
