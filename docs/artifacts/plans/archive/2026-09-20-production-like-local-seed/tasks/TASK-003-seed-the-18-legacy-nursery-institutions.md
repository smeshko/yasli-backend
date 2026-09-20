# TASK-003: Seed the 18 legacy nursery institutions

Depends on: None
Suggested commit: `feat(ingest): seed the legacy nursery institutions production still carries`

## Goal

Add the 18 `ДГ№X … / с яслена група/` nursery rows that production has carried since
before 2026-05-10 but that no current snapshot creates, so a local database serves
95 institutions and every slug in the frontend's manifest resolves.

## Files

- `data/seed/legacy_institutions.json` — new, ~4 KB. One object per row:
  `kind`, `external_id`, `name`, `source_url`, `address`, `has_infant_group`,
  **`district_code`**, and the `last_seen_at` the row carries in production. All 18
  are `kind=nursery`, external ids 39–83.
  `district_code` is **not optional and not derivable** — see the Notes; it is
  copied from production, where it is API-sourced, and must be one of `01`–`05`.
- `src/yasli/ingest/legacy_institutions_loader.py` — new. Modelled on
  `institution_locations_loader.py`: a parser that validates each row and reports
  the offending index on a bad one, plus
  `load(path, session)` which **upserts** on `(kind, external_id)` and leaves every
  other institution untouched. A `DEFAULT_PATH` and a `main()` CLI with
  `--dry-run`, matching the sibling loaders' exit codes (2 file/config, 3 parse,
  5 database).
- `tests/test_legacy_institutions_loader.py` — new.
- `tests/test_legacy_institutions_data.py` — new; a data test over the committed
  JSON, in the spirit of `tests/test_institution_locations_data.py`.

## Acceptance

- [ ] Loading the fixture into a database that already holds the snapshot's 77
      institutions brings it to 95, and touches none of the original 77
- [ ] Running the loader twice leaves the table in the same state
- [ ] Every one of the 18 rows lands with a non-null `district_code` in `01`–`05`,
      written by **this** loader — no stamping pass touches nurseries
- [ ] Each fixture row's `district_code` equals the value the same `(kind,
      external_id)` carries in production; a row missing `district_code`, or
      carrying one outside `01`–`05`, is rejected by the parser
- [ ] `python -m yasli.ingest validate-match-data` reports
      `nursery_without_district:0` after the fixture is loaded — the hard-failure
      counter in `match_data_validation.py` stays at zero
- [ ] The 18 are returned by `/api/match` for an address in their район
- [ ] Every `(kind, external_id)` in the fixture is absent from
      `data/seed/snapshot.json.gz` — the fixture never shadows a live row
- [ ] Every entry in the frontend's `institutions-manifest.json` resolves against a
      database seeded with snapshot + fixture
- [ ] A malformed row is rejected with its index and the field at fault, and nothing
      is written

Evidence: `SELECT count(*) FROM institutions` before and after (77 → 95), and the
`/api/match` payload for an address whose район contains one of the 18.

## Steps

### RED
- [ ] Test that loading into a 77-row table gives 95 and that a second run is a no-op
- [ ] Test that an existing non-legacy institution is not modified
- [ ] Test the malformed-row error path
- [ ] Add the data test: the committed fixture parses, holds exactly 18 rows, all
      `kind=nursery`, every one carrying a `district_code` in `01`–`05`, and none
      of its keys appear in the committed snapshot
- [ ] Test that a row with a missing or out-of-range `district_code` is rejected

### GREEN
- [ ] Extract the 18 rows from production into the fixture
- [ ] Write the loader and its CLI

### REFACTOR
- [ ] Factor anything genuinely shared with `institution_locations_loader` rather
      than copying it; leave it alone if the overlap is only superficial

## Notes

These rows are **not** a workaround for a data bug — they are stale entries that
production has never retired, and the fixture's README should say so in a sentence.
Retiring them is explicitly another ticket.

Extracting the fixture needs one-off read access to the production database
(`railway run`). TASK-006 turns that into a repeatable command; here it is a manual
extraction, and the extracted file is the artifact under review.

Nurseries route on `Institution.district_code` alone
(`yasli.services.matching._district_rows_for_kind`), never through
`address_institutions` — which is why these rows need no catchment edges.

**The district stamp will not come from `restamp-districts`.** Both stamping
passes exclude nurseries on purpose — `kind <> 'nursery'` appears in the candidate
query (`district_stamp.py:270`), in the UPDATE (`:291`) and in the module docstring
(`:11`, "kindergartens + preschools only — nurseries are API-sourced"). So the
fixture has to carry `district_code` itself, exactly as the snapshot carries it for
the 77 live nurseries. Leaving it NULL would trip
`match_data_validation`'s `nursery_without_district` hard-failure counter
(`match_data_validation.py:119`) and the 18 rows would route nowhere.

Do **not** add nursery support to `district_stamp` to work around this. The
exclusion is deliberate and the ingest upsert already preserves an API-sourced
district (`pipeline.py:442`, `preserve_old_on_null_columns=("district_code",)`).
