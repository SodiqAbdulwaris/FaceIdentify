# Evaluation 06 Rules, branches and reviews

## 1. What this is and why it exists

This repository is changed by people *and* by AI agents, and a mistake in a face-memory product is costly. So the way changes happen is itself
specified: a branch per task, small Conventional Commits, a pull request, an independent review and checks that must pass. This lesson is the
workflow as a checklist, with the parts you can try locally. The rules themselves are in `AGENTS.md` and `.agents/rules/`; they are mandatory
and this lesson only explains them.

## 2. Where it lives

| Thing | Where |
|---|---|
| Entry rules | `AGENTS.md`, `CLAUDE.md` (which imports `AGENTS.md`) |
| The rules | `.agents/rules/branches.md`, `commits.md`, `documentation.md`, `scope.md`, `testing.md` |
| Local enforcement | `.githooks/` (`pre-commit`, `commit-msg`, `pre-push`, `check-branch-name`); enable with `git config core.hooksPath .githooks` |
| CI | `.github/workflows/ci.yml` (jobs: branch name, commit messages, static validation, backend tests, frontend, desktop shell) |
| Server side | `.github/rulesets/main.json` (no direct pushes to `main`, merges need a PR with required checks) |
| Where work is recorded | `docs/implementations/`, `.agents/CONTEXT.md`, `docs/plans/` |

## 3. How it works

**The workflow**

1. Read `AGENTS.md`, then `.agents/CONTEXT.md`, then every file in `.agents/rules/`, then the specs for your area. If code and a spec disagree, stop and ask.
2. **Branch** from an up-to-date `main`: `git switch main && git pull` then `git switch -c <type>/<short-kebab-description>`. Types: `feat fix docs chore refactor test ci build perf style revert`. Never commit to `main`.
3. **Commit small**: one logical change per commit, header `<type>(<scope>): <imperative subject>`, at most 72 characters, no trailing period, body explaining *why*; under about 400 changed lines unless the body says why it cannot be split. Lockfile or generated changes go in the commit that caused them. Never `--no-verify`; never commit secrets, real photographs, `*.db` or `*.usearch`.
4. **Check before you say done** (from `testing.md`): `uv run ruff format --check . && uv run ruff check . && uv run mypy`, `uv run pytest`, and `npm run typecheck && npm run lint -- --deny-warnings && npm test && npm run build`; changes under `desktop/` also `npx tauri build --debug --no-bundle`. Report the real output. Never delete, skip or weaken a test to get green.
5. **Document**: an entry in `docs/implementations/` (the folder's template), `.agents/CONTEXT.md` updated and kept true, `docs/plans/PROJECT_STATUS.md` if what is built changed, the tracker with *verified* status only.
6. **Push and open a PR** with a Conventional Commits title; the description says what changed and why, how it was verified (commands and results) and links the entry. PRs merge by **rebase merge** (one method), so every commit lands unchanged.
7. **Independent review**: an agent-opened PR gets a read-only review (Codex CLI preferred; a read-only subagent if no CLI works) in a *disposable worktree*, posted as a PR comment; every finding is fixed in a new commit or answered; the PR is "ready" only when findings are resolved and CI is green.
8. **The owner merges.** Agents do not merge unless asked. Delete the branch after merging.

## 4. Try it

**Works with no models. Verified 2026-10-12.** The two local checks are small shell scripts you can call yourself:

```bash
for b in docs/learning-guide-restructure Feat/Bad main fix/ok-name feat/two/slashes; do
  .githooks/check-branch-name "$b" >/dev/null 2>&1 && echo "OK  $b" || echo "BAD $b"
done
printf 'added stuff.\n' > /tmp/m1.txt; printf 'docs(learning): add the thing\n\nwhy\n' > /tmp/m2.txt
for f in /tmp/m1.txt /tmp/m2.txt; do .githooks/commit-msg "$f" >/dev/null 2>&1 && echo "msg OK  $(head -1 $f)" || echo "msg BAD $(head -1 $f)"; done
rm -f /tmp/m1.txt /tmp/m2.txt
```

Observed: `OK` for `docs/learning-guide-restructure` and `fix/ok-name`; `BAD` for `Feat/Bad` (uppercase), `main` (no type) and `feat/two/slashes`; `msg BAD added stuff.`
and `msg OK docs(learning): add the thing`. These are the same scripts CI runs. Then, in a scratch clone or on a throwaway branch, try
the whole loop once: `git switch -c docs/practice-note`, edit a file, `git commit` with a bad header (the hook refuses), then a good one,
then `git switch -` and `git branch -D docs/practice-note`. (Pushing and the PR need the remote; not rehearsed here.)

## 5. Change it

A rule change is itself a documented change: edit the rule file, the enforcing hook or CI job if there is one, and record it in an implementation
entry. Rules in `.agents/rules/` are mandatory; do not "interpret" them away in a PR.

## 6. Break it on purpose

Try `git commit -m "Added stuff."` with hooks enabled: `commit-msg: header does not follow Conventional Commits` (the first check above exercises the same script).
Try `git push origin main`: `pre-push` refuses, and the server ruleset would too.

## 7. Exercises

1. Which branch name is valid: `Docs/Fix`, `docs/fix-links`, `docs/fix_links`?
2. Why does each commit have to stand on its own?
3. Who may merge a pull request an agent opened?
4. What must you do with a reviewer's finding you disagree with?

**Answers**

1. `docs/fix-links`.
2. Rebase merging lands every commit on `main` unchanged.
3. The owner (the user); agents merge only when asked.
4. Reply on the PR explaining why it stands; never ignore it silently.

## 8. Related files

- Previous: [05](05-real-model-run.md) · Next: [07 Milestones, the tracker and decisions](07-milestones-tracker-decisions.md)
- [`AGENTS.md`](../../../AGENTS.md), [`.agents/rules/branches.md`](../../../.agents/rules/branches.md), [git and pull requests](../01-basics/tools/05-git-and-pull-requests.md)
