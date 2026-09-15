# TASK-003: Load the reference file idempotently via a CLI

Depends on: TASK-002
Suggested commit: `feat(ingest): load institution locations via CLI`

## Goal

`python -m yasli.ingest.institution_locations_loader` truncates and reloads
`institution_locations` in one transaction, and fails loudly — before it
truncates anything — on a row it cannot attribute, an institution with no
`main` row, and a `main` row whose address no longer matches the
institution's.

## Files

- `src/yasli/ingest/institution_locations_loader.py` — the loading half:
  `load(path, session) -> LoaderSummary`, `main(argv)`, and a
  `UnmatchedInstitution` exception
- `tests/test_institution_locations_loader.py` — loader tests against a SQLite
  in-memory session fixture defined in this module, copied from
  `tests/test_grao_loader.py`'s `sqlite_session` (`tests/conftest.py` has no
  shared one)
- `Dockerfile` — add `COPY data ./data` next to `COPY migrations`; today the
  image has only `src/`, `alembic.ini` and `migrations/`, so neither the CSV
  nor the polygon would exist in a Railway exec shell

## Acceptance

- [ ] `load()` truncates then bulk-inserts inside the caller's transaction;
      running it twice leaves identical business columns — every column
      except the surrogate `id`, which plain `TRUNCATE` does not reset (the
      `grao_loader` precedent; PLAN.md's "same observable state")
- [ ] A row whose `(kind, external_id)` matches no institution **aborts the
      whole load** with an error naming the pair — no partial state
- [ ] A load whose file leaves any current institution without a `main` row
      **aborts before TRUNCATE**, naming the institutions — a half-finished
      review or a CSV predating a newly ingested institution never replaces a
      complete table. `--allow-incomplete` skips that abort for local partial
      loads; an explicit `no_pin` row (`precision=none`) counts as present
- [ ] A load with a `main` row whose `address` differs from
      `institutions.address` after `normalise_address` on both sides (NULL
      institution addresses are skipped) **aborts before TRUNCATE**, naming
      the institution and both addresses — ingest overwrites addresses, so
      this is how a moved institution's stale pin gets caught. Covered by the
      same `--allow-incomplete` flag ("the CSV lags the institutions table");
      the summary lists drifted rows by name either way
- [ ] `--dry-run` runs all three guards and prints the full summary without
      TRUNCATE or INSERT, exit codes as for a real run — the operator's
      "is the CSV still current?" check
- [ ] A failed load rolls back to the previous contents, not to an empty table;
      a partial or drifted CSV without the flag leaves the previous table intact
- [ ] The summary reports rows loaded, counts by `role` and by `verification`,
      the number of institutions with **no** `main` row (non-zero only under
      `--allow-incomplete`), and **lists by name** every `main` row with
      `precision=none` (unresolved, shipped without a pin)
- [ ] The CLI defaults to `REPO_ROOT / "data" / "institution_locations.csv"`
      (the same `Path(__file__)`-anchored root as `municipality.py`, never the
      CWD) and accepts a path override; a subprocess run from a temp cwd, in
      `tests/ingest/test_cli.py`'s style, still resolves the default
- [ ] The deployed image contains `data/`, so the loader runs from a Railway
      exec shell exactly like the ГРАО loader, or from a checkout against a
      tunnelled `DATABASE_URL`
- [ ] Exit codes extend `grao_loader`'s convention: `0` success, `2` file not
      found, `3` parse/validation failure, `4` referential abort (unmatched
      pair or missing `main`)
- [ ] A `LocationRowError` from the parser surfaces with its line number intact,
      not wrapped into something vaguer
- [ ] Postgres uses `TRUNCATE TABLE`; SQLite falls back to `delete()`, as
      `grao_loader` already does

Evidence: `uv run pytest tests/test_institution_locations_loader.py -v`, plus a
real run of a small hand-made sample file (the committed CSV does not exist
until TASK-006) against a migrated local database showing the summary line,
then a second run showing identical `SELECT role, precision, count(*)` output.

## Steps

### RED
- [ ] Loader tests: idempotency across two runs (compared without `id`);
      unmatched-pair abort; missing-`main` abort with the previous contents
      preserved; address-drift abort after an `UPDATE institutions SET address`
      in the fixture session, and no abort when the change is only quote
      style; the same partial and drifted files loading under
      `--allow-incomplete` with the counts in the summary; `--dry-run`
      leaving the table untouched
- [ ] A CLI test per exit code, following `tests/ingest/test_cli.py`'s style,
      plus one that runs with no path argument from a temp cwd and shows the
      default resolved to the in-repo file

### GREEN
- [ ] Implement `load(path, session, *, allow_incomplete=False, dry_run=False)`
      — resolve every `(kind, external_id)` and address against `institutions`
      in one query, run the three guards (file pairs not in the table;
      institutions with no `main` row; `main` rows whose normalised address
      differs), raise unless `allow_incomplete` covers the second and third,
      then — unless `dry_run` — TRUNCATE + `session.execute(insert(...), rows)`
- [ ] Implement `main()` mirroring `grao_loader.main`

### REFACTOR
- [ ] Check whether the TRUNCATE-vs-delete dialect branch is now duplicated
      between the two loaders; extract a shared helper only if it reads better
      than the four-line branch

## Notes

The unmatched check must run **before** the TRUNCATE, or a bad file empties the
table and then fails — technically rolled back, but it makes the failure look
like a database problem instead of a data problem.

The missing-`main` check is the other direction of the same referential guard:
the unmatched check catches locations without institutions, the missing-`main`
check catches institutions without locations, and the drift check catches a
location whose institution moved (ingest overwrites `institutions.address`
on every run). All three run before TRUNCATE. An institution added or
re-addressed by a later ingest therefore makes the next load abort until the
CSV is refreshed — the loud failure the plan wants — and the runbook
(TASK-007) tells the operator what to do. The counts and names are still
reported so that under `--allow-incomplete` they are the visible signal.

The unresolved-`main` list exists because unresolved rows are allowed to ship
(plan Decisions). If a blank is allowed, it has to be listed where an operator
will see it.

`just be-ingest` must not call this. Coordinates change roughly never;
coupling a reference load to the weekly cron means a third-party outage during
the seed script's data collection could break routing refreshes.

There is no `just` recipe in this PR. The root `justfile` lives in the `yasli/`
parent, outside this repo — see the plan's Decisions. The CLI invocation in
TASK-007's runbook is the committed interface.
