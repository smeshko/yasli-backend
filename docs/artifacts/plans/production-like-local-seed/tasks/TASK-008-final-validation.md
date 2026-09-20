# TASK-008: Final Validation

Depends on: all prior tasks
Suggested commit: `chore: final validation for production-like-local-seed`

## Goal

Confirm the plan is fully implemented and that the seed does, end to end and on a
genuinely clean machine, what YAS-21 asked for.

## Steps

- [ ] All task checkboxes in `PLAN.md` are ticked
- [ ] `just be-lint` passes with no issues
- [ ] `just be-test` passes in full
- [ ] Module boundaries respected: `yasli.seed` orchestrates and reports; it holds
      no parsing or loading logic of its own
- [ ] `PLAN.md` acceptance criteria all met. Walk them **one at a time, in order**,
      and record against each the command that was run and the output it produced —
      no criterion ticked on "the code looks right", and none ticked by a blanket
      statement covering several at once
- [ ] The 18 legacy nurseries carry a non-null `district_code` that came from the
      committed fixture, and `python -m yasli.ingest validate-match-data` reports
      `nursery_without_district:0` and `nursery_coverage_edges:0`

## The end-to-end run

- [ ] `just db-reset`, then `env -u R2_ACCOUNT_ID -u R2_ACCESS_KEY_ID
      -u R2_SECRET_ACCESS_KEY -u R2_BUCKET uv run python -m yasli.seed` — capture
      the whole transcript; it must exit 0 with no R2 variable in the environment
- [ ] Row counts after it: 95 institutions, 2,289 streets, 49,800 addresses,
      ~47,579 `grao_addresses`, 94 `institution_locations`
- [ ] Resolve `ул. Н.Й.Вапцаров 007 вх.Г` to its `addresses.id` by natural key
      (street name + number + entrance) — `/api/match` takes `address_id`
      (`routes/match.py:80`), never an address string
- [ ] `GET /api/match?address_id=<that id>` — district `02`, with nurseries,
      kindergartens and preschools all non-empty. Show it beside the ticket's
      `null / 0 / 4 / 0` "local" row so the fix is legible
- [ ] Compare against production by resolving the **same natural key** in the
      production database to *its* `address_id` and calling the same endpoint
      there. Surrogate ids do not correspond across databases, so compare a
      normalised projection — `district_code` plus the sorted set of
      `(institution_kind, external_id, reception_kind)` — not the raw payloads,
      whose `id` fields will legitimately differ
- [ ] `addresses.district_code` non-null share is measured and recorded, and meets
      the threshold TASK-005 fixed — the number goes in the completion note
- [ ] `GET /api/institutions/by-source/kindergarten/46` — ДГ№13 "Мир" with 4
      branches, each carrying coordinates
- [ ] Every `(kind, external_id)` in the frontend's `institutions-manifest.json`
      resolves against the seeded database — all 95, none missing

## The half-done guard

**Every case below starts from `just db-reset`.** Skipping a step on an
already-seeded database proves nothing: the ГРАО and locations loaders
TRUNCATE-and-reload, so omitting one leaves the *previous* run's 47,579 and 94 rows
in place and `verify` passes on stale evidence. Reset, seed with the one step
disabled, then verify — and record the reset in the transcript so the evidence is
checkable.

- [ ] `db-reset` → seed with the ГРАО step skipped: `python -m yasli.seed verify`
      exits non-zero and names the district checks
- [ ] `db-reset` → seed with the locations step skipped: verify exits non-zero and
      names the branch check
- [ ] `db-reset` → seed with the legacy-institutions step skipped: verify exits
      non-zero and names the 18 missing `(kind, external_id)` keys
- [ ] `db-reset` → seed with the snapshot ingest skipped: verify exits non-zero on
      the institution/street/address checks
- [ ] `db-reset` and nothing else — `python -m yasli.seed verify` on a
      never-seeded (but migrated) database exits non-zero and names every failing
      check, not just the first
- [ ] `db-reset` but **skip the migration step** — point the seed at an unmigrated
      database with the `alembic upgrade head` step disabled: it exits non-zero on
      the migration/precondition class, not with a raw SQLAlchemy error
- [ ] `TRUNCATE grao_addresses` on a fully seeded database, then `verify`: non-zero,
      naming the step that would fix it
- [ ] Insert a nursery that no committed artifact accounts for, then `verify`: it
      exits non-zero and names that row — a database wrong in the *over*-seeded
      direction is caught too (round-2 finding 2)
- [ ] Insert an `address_institutions` edge the snapshot does not describe, then
      `verify`: non-zero, naming the edge. Confirm the same edge changes
      `/api/match` for that address, so the check is demonstrably load-bearing
      (round-3 finding 1)
- [ ] Each failure message names the seed step that repairs it, not only the symptom

### Why `restamp-districts` is not in the list

Ingest ends with the **gated** `stamp_*_unmatched` passes (`pipeline.py:673-674`),
so on a clean seed every district is already stamped by the time step 6 runs and
skipping it changes nothing observable. Its job is on a *dirty* database, so prove
it there instead:

- [ ] Record the expected district of **named rows** first: the Вапцаров address
      (`02`, per the KADS archive) and one named kindergarten whose district is
      known independently. The sabotage must be detectable by value, not by
      coverage — a valid-but-wrong district passes every non-null and
      code-membership check
- [ ] Corrupt exactly those rows to a different *valid* code
      (`UPDATE addresses SET district_code='05' WHERE id=<вапцаров id>`, likewise
      the kindergarten), then run the seed again
- [ ] `restamp-districts` restores both to their recorded expected values, and
      `verify` passes. With step 6 disabled over the same corruption, `verify`
      fails on the named-address checks and names the rows. This is what makes the
      non-gated pass load-bearing — and it only works because TASK-005 compares
      named rows against known values rather than counting non-nulls

## The refresh loop

- [ ] `python -m yasli.seed freeze --dry-run` against the committed artifacts
      reports no drift
- [ ] A real `freeze` over an unchanged snapshot leaves `git status` clean
- [ ] Seeding from freshly frozen artifacts reproduces the same row counts
- [ ] A fixture row deliberately duplicated into the snapshot makes `freeze` abort
      with exit 3 and write neither file — including under `--snapshot-only`
- [ ] A deliberately truncated legacy derivation is refused without
      `--allow-shrink`
- [ ] A forced failure of the *second* `os.replace` exits non-zero and reports both
      files as possibly mismatched, naming `git checkout -- data/seed/` — the
      publish is near-atomic, not atomic, and must not claim otherwise

## Documentation

- [ ] Follow the README quickstart verbatim on a clean database — every command as
      written, no improvisation — and it works
- [ ] The local-vs-production table's numbers match what the run actually produced
