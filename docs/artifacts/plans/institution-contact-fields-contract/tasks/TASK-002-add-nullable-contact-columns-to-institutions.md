# TASK-002: Add nullable contact columns to institutions

Depends on: TASK-001
Suggested commit: `feat(db): add contact columns to institutions`

## Files

- `src/yasli/models/institution.py` — four nullable columns after `address`:
  `phone String(128)`, `email String(256)`, `director String(256)`,
  `website String(256)`
- `migrations/versions/0009_institution_contact_fields.py` — new revision,
  `down_revision = "0008"`, four `op.add_column` calls and a symmetrical
  `downgrade()`
- `tests/test_models.py` — construct an `Institution` with and without contacts
- `tests/test_migrations.py` — `test_round_trip_upgrade_downgrade_upgrade`
  hard-codes the head as `"0008"` (both after `upgrade head` calls) and asserts
  the `downgrade -2` target is `"0006"` with the 0006 table/column shape.
  Adding 0009 breaks both: bump the head assertions to `"0009"`, and either
  change `-2` to `-3` (keeping the 0006 assertions) or retarget the assertions
  to 0007 — then add assertions that the four contact columns exist at head and
  are gone after the downgrade. `test_institutions_metadata_columns_and_constraint`
  is the natural home for the at-head column check

## Acceptance

- [ ] `alembic upgrade head` adds all four columns as nullable with no default
- [ ] `alembic downgrade -1` drops exactly those four and leaves `address`,
      `district_code` and `has_infant_group` intact
- [ ] Existing rows are unaffected — the columns read back `NULL`
- [ ] `Base.metadata.create_all` on SQLite produces the same columns, so the
      route and matching tests keep running
- [ ] `uv run alembic check` against the local DB reports no **new** drift:
      run it once before the change (at 0008) to record the baseline, and once
      after (at 0009); the outputs match. `alembic check` needs a live
      `DATABASE_URL`, so run it after `just db-reset`
- [ ] `tests/test_migrations.py` runs (not skipped — it needs Docker) and passes

Evidence: before/after `uv run alembic check` output, `uv run pytest tests/test_migrations.py -v`
showing `PASSED` (not `SKIPPED`), `just be-migrate` output, then
`just db-psql -c "\d institutions"` showing the four nullable columns, and a
`just db-psql -c "SELECT count(*) FROM institutions WHERE phone IS NOT NULL"`
returning `0`.

## Steps

### RED
- [ ] Add a model test asserting the four attributes exist and default to `None`
- [ ] Update the migration round-trip test's hard-coded `"0008"` head and
      `downgrade -2` target (see Files), and assert the contact columns appear
      at head and vanish on downgrade

### GREEN
- [ ] Add the columns to the ORM model
- [ ] Write `0009_institution_contact_fields.py` modelled on
      `0004_nursery_metadata.py` — same docstring shape, same revision-id style

### REFACTOR
- [ ] Confirm no CHECK constraint is warranted: these are free-form source
      strings with no enumerable domain, unlike `district_code`

## Notes

`phone` gets `String(128)` rather than `String(256)`: the source packs several
slash- or tab-separated numbers into one `TEL` cell, but 128 characters is far
beyond the longest observed value. If a real value ever overflows, the insert
fails loudly instead of truncating — which is the behaviour we want, and phase
1.2's live `sc-refresh` will surface it long before production.

No backfill: every existing row legitimately has no contact data until the
scraper starts emitting it in phase 1.2.
