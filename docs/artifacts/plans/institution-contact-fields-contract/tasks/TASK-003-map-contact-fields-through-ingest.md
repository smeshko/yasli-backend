# TASK-003: Map contact fields through ingest

Depends on: TASK-002
Suggested commit: `feat(ingest): persist institution contact fields`

## Goal

A snapshot carrying contacts stores them; a snapshot without them leaves the
columns NULL; re-ingesting either one is idempotent and reports `unchanged`.

## Files

- `src/yasli/ingest/pipeline.py` — three edits:
  - `_build_plan`, the `inst_rows[inst_key]` dict (~line 342): add the four
    fields alongside `"address": inst.address`
  - `_upsert_institutions.on_conflict_set` (~line 422): plain
    `stmt.excluded.<field>` for each — **not** wrapped in `func.coalesce`
  - `value_columns_for_unchanged` (~line 447): append the four names
- `tests/ingest/test_pipeline.py` — the behavioural coverage below

## Acceptance

- [ ] Ingesting a snapshot with contacts writes all four verbatim
- [ ] Ingesting a snapshot **without** them leaves all four columns NULL — the
      test asserts each of `phone`, `email`, `director`, `website` — and the run
      succeeds; this is the "current production snapshot still works" case
- [ ] Ingesting with-contacts and then without-contacts **clears** the columns
      (no `coalesce` preservation), and the row is counted as `updated`
- [ ] Ingesting the same with-contacts snapshot twice counts the row as
      `unchanged` on the second run
- [ ] `district_code`'s existing preserve-on-NULL behaviour is unchanged — the
      test that covers it still passes untouched
- [ ] A mixed snapshot (some institutions with contacts, some without) stores
      each correctly and does not cross-contaminate

Evidence: `uv run pytest tests/ingest/test_pipeline.py -v` output showing the
new tests `PASSED` — **not** `SKIPPED` (the ingest suite skips silently without
Docker/testcontainers) — plus a real `just be-ingest` against the production R2
snapshot showing its summary line and
`SELECT count(phone), count(email), count(director), count(website) FROM institutions`
returning `0 | 0 | 0 | 0`.

## Steps

### RED
- [ ] Add the six pipeline tests above in `tests/ingest/test_pipeline.py`,
      following the existing pattern there: load
      `fixtures/snapshot_v2_minimal.json`, add/strip the contact keys on the
      payload dict, `_put_snapshot(s3, payload)` into the moto-backed R2, then
      call `pipeline.run(...)` against the testcontainers Postgres `engine`
      from `tests/ingest/conftest.py` (model on `test_idempotent_second_run`
      and `test_updated_institution_metadata_counts_updated`)

### GREEN
- [ ] Make the three edits in `pipeline.py`

### REFACTOR
- [ ] Check whether the `IngestSummary` operator line is worth extending with a
      contacts counter. Decide against unless the field list is already crowded —
      the `updated` count already tells the operator something changed

## Notes

The `unchanged` comparison is the subtle one. `_pg_upsert` only compares the
columns named in `value_columns_for_unchanged`; a field written but not listed
would make a corrected phone number report as `unchanged`, which is exactly the
kind of silent no-signal the ingest summary exists to prevent.

Resist adding the contact fields to `preserve_old_on_null_columns`. That tuple
means "NULL from the snapshot means backend-derived, keep what we have", which
is true for `district_code` and false here: a NULL contact means the source
dropped the value, and the database should follow.

This task's evidence is also the phase's first acceptance criterion. The
second criterion — a snapshot that *carries* the fields ingesting for real — is
only fully demonstrable once phase 1.2 emits them, so demonstrate it here with a
hand-edited local snapshot file, and note it as such.

There is **no local-file ingest path**: `just be-ingest` → `pipeline.run()` only
reads `snapshots/varna/latest.json` via `r2.get_object`. Do **not** upload the
edited file to R2 — that overwrites the production snapshot. Instead, fetch the
current snapshot (read-only) or run `just sc-snapshot-local FILE`, hand-edit it,
and call `pipeline.run(r2_client=<stub>)` from a one-off `uv run python -c`
against the local `DATABASE_URL`. `r2.get_object(key, client=...)` uses the
passed client as-is and reads `client.get_object(Bucket=..., Key=...)["Body"].read()`,
so the stub's `get_object(Bucket, Key)` returns `{"Body": io.BytesIO(file_bytes)}`.
`R2_BUCKET` must still be set (the helper loads it from the repo `.env`), but no
network call is made. The script is
throwaway demo scaffolding — do not commit it.
