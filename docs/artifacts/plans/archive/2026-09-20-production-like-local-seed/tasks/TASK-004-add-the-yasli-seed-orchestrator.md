# TASK-004: Add the yasli.seed orchestrator

Depends on: TASK-001,TASK-002,TASK-003
Suggested commit: `feat(seed): add one command that seeds a production-like local database`

## Goal

`uv run python -m yasli.seed` takes a bare local Postgres through every step —
migrate, ingest, ГРАО, legacy institutions, locations, restamp — in the one order
that works, reporting each step as it goes.

## Files

- `src/yasli/seed/__init__.py` — new package.
- `src/yasli/seed/__main__.py` — new. `argparse` with the default (no-arg) action
  running the full seed; `verify` (TASK-005) and `freeze` (TASK-006) land as
  subcommands beside it.
- `src/yasli/seed/runner.py` — new. A `Step` record (name, callable) and a
  `run_seed(session_factory, …)` that executes them in order, timing each one and
  collecting a summary. Steps, in this order:
  1. `alembic upgrade head` via `alembic.command.upgrade` (no subprocess)
  2. ГРАО load from the committed archive — **before** ingest, so ingest's own
     gated stamping passes have something to join against
  3. ingest from `data/seed/snapshot.json.gz`
  4. legacy institutions load
  5. institution locations load (`--allow-incomplete`, local-only, as the loader's
     own help already prescribes)
  6. `restamp-districts` — the non-gated passes, which re-derive every kindergarten
     and preschool district against the freshly loaded ГРАО data. It does **not**
     stamp the legacy nurseries: both passes exclude `kind='nursery'`, so those rows
     carry the `district_code` TASK-003's fixture gives them.
     On a *clean* seed this step is close to a no-op — ingest already ended with the
     gated passes (`pipeline.py:673-674`), so nothing is left NULL. It earns its
     place on a re-seed, where it corrects districts that a previous ГРАО cycle
     stamped differently. Keep it, but do not expect a clean-database test to
     detect its absence; TASK-008 proves it over a dirty database instead
- `tests/seed/test_runner.py`, `tests/seed/test_cli.py` — new.

## Acceptance

- [ ] On a database freshly reset with `just db-reset`, one invocation with no R2
      variables set exits 0 and produces: 95 institutions, 2,289 streets, 49,800
      addresses, ~47,579 `grao_addresses`, 94 `institution_locations`
- [ ] The run prints one line per step with its name, row counts and elapsed time,
      and a closing line carrying the frozen snapshot's `scraped_at`
- [ ] It also works on an already-migrated, already-seeded database — no special
      casing, matching D6
- [ ] A failing step aborts the run immediately with a non-zero exit; later steps
      do not run
- [ ] Step order is asserted by a test, not just by reading the code — ГРАО before
      ingest, restamp last
- [ ] Exit codes follow the existing `yasli.ingest` convention (2 config, 3 data,
      4 fetch/precondition, 5 database)

Evidence: the full step-by-step console output of a real run against a
`just db-reset` database, plus the row-count query that follows it.

## Steps

### RED
- [ ] Test that `run_seed` invokes the steps in the documented order, using stubs
- [ ] Test that a raising step aborts and that subsequent steps are not called
- [ ] Test the CLI's exit-code mapping for each failure class
- [ ] Add an integration test (testcontainers, as the ingest tests already do) that
      runs the whole seed against a real empty Postgres and asserts the row counts

### GREEN
- [ ] Add the package, the step list and the CLI
- [ ] Wire each step to the loader it calls, passing the committed default paths

### REFACTOR
- [ ] Keep each step a thin call into its existing loader — the orchestrator holds
      ordering and reporting, never loading logic

## Notes

**Order is load-bearing and non-obvious.** ГРАО must precede ingest because
`pipeline.run()` ends with the *gated* `stamp_*_unmatched` passes, which can only
stamp what `grao_addresses` already contains. The final non-gated
`restamp-districts` then re-derives every kindergarten and preschool district
against the full ГРАО table. Getting this wrong produces a seed that exits 0 with
no districts — precisely the failure YAS-21 was filed about.

**Step 6 is not what makes the legacy nurseries route.** `district_stamp` excludes
nurseries in both passes (`kind <> 'nursery'`, `district_stamp.py:270,291`) because
nursery districts are API-sourced. The 18 rows route because TASK-003's fixture
carries `district_code` directly. Step 4 may therefore run after step 6 without
changing the outcome — it is placed before it only to keep the "load, then derive"
shape.

Call `alembic.command.upgrade` with a programmatically built `Config` pointed at
`alembic.ini`; do not shell out, and do not assume the process CWD is `backend/`.

Locations load with `--allow-incomplete` because the committed CSV can lag the
snapshot's institutions. That flag is documented as local-only and this is a local
seed, but TASK-005's verification must still surface what it let through.
