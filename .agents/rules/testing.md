# Testing and verification rules

Full details: [`docs/guides/TESTING_GUIDE.md`](../../docs/guides/TESTING_GUIDE.md) and
[`docs/strategy/TESTING_STRATEGY.md`](../../docs/strategy/TESTING_STRATEGY.md).

## Before you say "done"

Run whatever applies to your change and report the actual output:

```bash
uv run ruff format --check . && uv run ruff check . && uv run mypy
uv run pytest
npm run typecheck && npm run lint -- --deny-warnings && npm test && npm run build
```

Changes under `desktop/` also need `npx tauri build --debug --no-bundle`.

## Rules

- New behaviour gets tests. Bug fixes get a test that fails without the fix.
- Test behaviour through public contracts, not private details.
- Use real SQLite, USearch and filesystem fixtures for persistence behaviour, never mocks.
- Tests are deterministic: use the `clock`, `new_id`, `rng` and `np_rng` fixtures, and never
  wall-clock time, global randomness or `sleep`-based coordination.
- Tests never touch real user data. All paths come from `tmp_path` / `app_dirs`.
- **Never** delete, skip, `xfail` or weaken an assertion to get a pass. If a test cannot pass
  because a dependency is missing, mark the tracker task `BLOCKED` and say why.
- Warnings are errors. Fix the cause instead of filtering it.
- Do not add numeric coverage or performance thresholds without measured baselines.
