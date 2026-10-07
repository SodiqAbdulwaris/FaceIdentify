# M5 schema cleanup: revision 0009 removes the `SPLIT` identity state

- **Date:** 2026-10-07
- **Milestone / tracker IDs:** M5 schema cleanup (CONTEXT question 15, owner decision 2026-10-07)
- **Status:** done
- **Commits:** PR to be recorded when merged

## What changed

- **Revision `0009`** recreates `identities` (batch mode, the `0002`/`0006`/`0008` pattern) with the
  state check no longer allowing `SPLIT`. `IdentityState.SPLIT` is removed from the model, so the
  model and the schema agree.
- A split stays recorded by `IDENTITY_SPLIT` Evidence and a `SPLIT_FROM` lineage edge: the source
  stays `ACTIVE` and the new identity is created `ACTIVE`. Nothing in production ever wrote `SPLIT`.
- Tests (`tests/integration/test_migration_0009.py`): a populated upgrade keeps every row and then
  refuses the removed state; an identity left in `SPLIT` (written raw, since head's own check refuses
  it) stops the upgrade and leaves the database and its version untouched; an empty library
  downgrades; a populated one is refused unless forced, and a forced downgrade restores the rows; the
  printed-SQL check. The head pins in the migration and lifecycle tests move to `0009`.
- The candidate-resolution test for a `SPLIT` identity is gone (the state can no longer exist); the
  spec's value-set table drops the state. `PERSISTENCE_IMPLEMENTATION.md` section 7 says so.

## Why

The owner decided on 2026-10-07 that `SPLIT` is dead enum space to remove in the M5 cleanup. A state
nothing assigns invites a reader to think a split identity exists.

## Verification

- Mutation: putting `SPLIT` back into the new check fails three of the five new tests; restored, all
  pass.
- Full gate results are in the PR.

## Open issues / follow-ups

None for this change.
