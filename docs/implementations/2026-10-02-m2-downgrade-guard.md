# M2: refuse a destructive downgrade of a populated library

- **Date:** 2026-10-02
- **Milestone / tracker IDs:** M2 · TST-032; GitHub issue #35 (open question 19)
- **Status:** done
- **Commits:** PR #62: `feat(db): refuse to downgrade a populated library`, `docs: record the downgrade guard`

## What changed

- `backend/infrastructure/db/downgrade_guard.py`: `require_destructive_downgrade_allowed(connection)` raises
  `DestructiveDowngradeRefused` when any table other than the internal ones has a row, unless
  `FACEIDENTIFY_ALLOW_DESTRUCTIVE_DOWNGRADE` is exactly `1`. `populated_tables` lists the offenders; the message names them,
  the override (development only) and the forward-only alternative.
- Every revision (`0001` to `0004`) starts its `downgrade()` with the guard, so the refusal comes before any statement of
  that revision and, each revision being its own transaction, leaves the database exactly as it was.
- `tests/fixtures/migrations.py` `downgrade()` opts in to the override by default (`allow_destructive=False` for the guard's
  own tests); the existing downgrade tests are otherwise unchanged.
- `tests/integration/test_downgrade_guard.py` (27), spec note on persistence section 27, `backend/alembic/README`, CONTEXT.

## Why

The owner decided (2026-10-01) to refuse destructive downgrades on a populated library by default, with an explicit
development-only override that the application never sets; recovery goes forward with corrective revisions.

## Decisions

- **Populated = user/domain data.** The internal tables are the migration stamp, `app_state`, the settings singletons, the
  runtime/model catalog, `representation_spaces` and `ann_key_sequences`: a fresh library has rows there. This list is my
  reading of the owner's definition (recorded in the spec note and CONTEXT); a table that is not on it counts as data, so
  forgetting one errs on the side of refusing. Revisit if a catalog row should count as data.
- **An offline run is let through.** `alembic downgrade ... --sql` only prints a script, and its connection is a mock with
  no database to inspect (the first version of the guard crashed there; a review caught it and a test now pins it).
- **Artifacts:** installed models and packages keep their bytes as `artifacts` rows, so a fresh library has some; an artifact
  is internal only if a catalog table references it and no source (original or thumbnail) or observation (face crop) does
  (a re-review found that a shared artifact could hide a user's data; each of the three references is tested alone; `NOT EXISTS`
  rather than `NOT IN`, which a NULL would silently defeat). `ann_key_sequences` is *not* internal (the never-reused allocator).
- **A guard in each revision, not in `env.py`:** `env.py` runs after a step (`on_version_apply`) or cannot tell the direction
  reliably, while the revision's own first statement runs before anything changes. The risk, a future revision forgetting it,
  is closed by an AST test over every revision file.
- Any downgrade of a populated library is refused, including ones that would lose nothing (`0002` and `0003` keep every row).
  Classifying revisions by how destructive they are would be a judgement per revision; the rule stays simple.
- The override must be exactly `1` (`true`, `yes`, an empty or padded value do not count).

## Verification

- `ruff format --check`, `ruff check`, `mypy`, `mypy --platform linux` clean; `HYPOTHESIS_PROFILE=ci pytest --cov -q`: 1084 passed, backend coverage 100%.
  19 mutations (the exact override, the override ignored, the refusal removed, two internal tables removed from the list, an
  unknown table, the guard missing from one revision, the guard not first in another): each broken, shown to fail a test and
  restored byte-identical.
- **Review** (Explore subagent; Codex over its limit until 2026-10-03), posted on PR 62: one major, fixed (the offline crash).
  Fixed: `ann_key_sequences` and artifacts as above, a test that seeds every internal table and compares with the list, a test
  that a setting column added later forces a review of the guard, the revision list derived from the files, the AST test also
  checks the argument, the test helper is safe by default, quoting of table names. Answered: the first commit's size.
- **Not verified:** a downgrade through the `alembic` command line (the tests call `command.downgrade`).

## Open issues / follow-ups

- Revisit the internal-table list when the first-run seeding exists.
