# Research: Production-like local seed

Curated findings only — no raw conversation transcripts.

## Key Files & Directories

- `src/yasli/ingest/__main__.py` — the `python -m yasli.ingest` CLI. Three
  subcommands today (`ingest` default, `restamp-districts`, `validate-match-data`),
  each with its own exit-code contract (2 config, 3 snapshot, 4 R2, 5 database).
  The seed reuses these codes.
- `src/yasli/ingest/pipeline.py` — `run(*, r2_client=None)` is the whole ingest.
  `_fetch_snapshot_bytes()` (line 302) is the single place R2 is read, and
  `LATEST_KEY = "snapshots/varna/latest.json"` (line 58) the only key. Ingest is
  upsert-based and never deletes; `_count_disappeared()` only counts.
- `src/yasli/ingest/r2.py` — the four required vars, validated lazily. `validate_env()`
  is what the CLI calls at startup only when the subcommand actually fetches.
- `src/yasli/ingest/grao_loader.py` — `parse_file(path)` decodes windows-1251 and
  yields row dicts; `load(path, session)` does TRUNCATE + bulk INSERT. The CLI
  (`main`) takes one positional `path` and exits 2 on a missing file, 3 on a decode
  failure. Adding `.zip` support means one branch in `parse_file`.
- `src/yasli/ingest/institution_locations_loader.py` — same shape; already defaults
  its path to `DEFAULT_CSV` and already has `--dry-run` and `--allow-incomplete`.
  This is the closest existing model for the new loaders.
- `src/yasli/ingest/district_stamp.py` — `stamp_*_unmatched` (gated, run inside
  ingest) versus `restamp_*_all` (non-gated, run by `restamp-districts`).
- `src/yasli/services/matching.py` — the routing rules the seed has to satisfy.
- `src/yasli/models/institution.py` — the columns a legacy-institution row must fill.
- `data/` — precedent for committed reference data: `institution_locations.csv`,
  `institution_locations.provenance.json`, `varna_municipality.geojson`.
- `docs/OPERATIONS.md` — the ГРАО refresh runbook (§ "ГРАО quarterly reference-data
  refresh") and the institution-locations runbook the new seed section sits beside.

## Architecture Facts

- **The local database has no district data at all.** Measured on the running dev
  Postgres: `grao_addresses` = 0 rows, against `addresses` = 49,800,
  `address_institutions` = 205,674, `institutions` = 77, `streets` = 2,289,
  `institution_locations` = 94, `settlements` = 6.
- **The ГРАО archive is small.** `initial/data/grao/kads-03-06.zip` is 92 KB;
  extracted, `kads-03-06.txt` is 688 KB. Parsed through
  `grao_loader.parse_file()` it yields **47,579 rows across 2,071 streets** and
  districts `01`–`05`.
- **That file resolves the ticket's verification case.** `УЛ.Н.Й.ВАПЦАРОВ` number 7,
  entrances А/Б/Г/Д all carry `district_code='02'` (ПРИМОРСКИ), section 156 —
  matching the production row the ticket quotes.
- **A snapshot compresses ~32×.** `/tmp/yasli-latest.json` is 24,087,331 bytes raw
  and 759,639 bytes gzipped at `-9`. Per-table gzipped CSV dumps of the same data
  total ~768 KB, so a dump buys nothing over the snapshot and skips the real
  ingest path.
- **Nurseries route by district, not by address.** `matching.py` sends
  `kindergarten` through `_address_rows` (the `address_institutions` junction) but
  `nursery` through `_district_rows_for_kind(session, address.district_code,
  "nursery")`, and `preschool` through address rows with a district fallback. So
  an institution row with a `district_code` and no catchment edges routes correctly
  for nurseries.
- **Nothing stamps a nursery's district — it is API-sourced.** Both district-stamping
  passes filter `kind <> 'nursery'`, in the candidate query
  (`district_stamp.py:270`), in the UPDATE (`:291`) and by explicit contract in the
  module docstring (`:11`) and `restamp_institutions_all`'s docstring (`:477-482`).
  The value reaches the table from the snapshot, and `pipeline.py:442` preserves an
  existing one when the incoming value is NULL. `match_data_validation.py:119`
  counts `nursery_without_district` as a **hard failure**. Consequence: the legacy
  fixture has to carry `district_code` itself — found during round-1 validation,
  which invalidated the plan's original "restamp will stamp them" assumption. See
  DECISIONS.md D7.
- **`/api/match` takes `address_id`, not an address string.**
  `routes/match.py:80` declares `address_id: int = Query(..., ge=1)`. Any
  acceptance check phrased around `ул. Н.Й.Вапцаров 007 вх.Г` has to resolve that
  address to its surrogate id first, per database — and surrogate ids do not
  correspond between local and production, so cross-database parity must be judged
  on a normalised projection rather than on raw payload equality.
- **All 18 missing institutions are nurseries.** Diffing the frontend's
  95-entry `institutions-manifest.json` against the local `institutions` table
  gives exactly 18 misses, every one `kind=nursery`, external ids 39–83, every name
  of the form `ДГ№X "…"/ с яслена група/`. Combined with the routing fact above,
  this is why a ~4 KB fixture is enough.
- **R2 keeps timestamped snapshots.** `yasli_scraper.r2.snapshot_keys()` writes both
  `snapshots/varna/<timestamp>.json` and `snapshots/varna/latest.json`, so an older
  snapshot probably still exists — but relying on it would mean relying on retention
  *and* on it still validating as schema v2.
- **Ingest only accepts schema v2.** `pipeline._validate_snapshot()` raises
  `UnsupportedSnapshotVersion` for any explicit `schema_version` other than 2.

## Constraints

- **The `yasli` root is not a git repository.** Only `backend/`, `scraper/` and
  `frontend/` are. The root `justfile`, `docker-compose.yml` and `initial/` are
  untracked local files. A `just` recipe therefore cannot be the primary
  entrypoint — it does not survive a fresh clone of this repo — so the real command
  must be a module inside `src/yasli/` with the recipe as a convenience alias.
- **The ГРАО archive is currently only on this machine**, at
  `initial/data/grao/kads-03-06.zip`, outside any repository. Committing it into
  `backend/data/grao/` is what makes it reproducible.
- Tests: migration/constraint tests need `YASLI_TEST_DATABASE_URL` pointed at
  `yasli_test`, never the ingested `yasli` database. Ingest integration tests use
  testcontainers and need Docker.
- `just be-test` runs from `backend/`, so any committed data path the code resolves
  must be anchored off the package or repo root, not the process CWD — the existing
  `DEFAULT_CSV` in `institution_locations_loader.py` is the pattern to match.

## Useful Commands

```bash
# Row counts on the running dev database
docker compose exec -T postgres psql -U yasli -d yasli -c "
  SELECT 'institutions' t, count(*) FROM institutions
  UNION ALL SELECT 'grao_addresses', count(*) FROM grao_addresses
  UNION ALL SELECT 'addresses', count(*) FROM addresses"

# Parse the KADS file without touching the database
uv run python -c "
from pathlib import Path
from yasli.ingest import grao_loader
rows = list(grao_loader.parse_file(Path('…/kads-03-06.txt')))
print(len(rows), len({r['street_code'] for r in rows}))"

# Which manifest entries a local database cannot resolve
docker compose exec -T postgres psql -U yasli -d yasli -tAc \
  "SELECT kind||'|'||external_id FROM institutions"
```

## Uncertainty

- **Would an older R2 snapshot have reproduced the 18 rows more faithfully?**
  Probably, but it depends on R2 retention and on a pre-2026-05-10 snapshot still
  validating as schema v2 — two unknowns for a ~760 KB cost. Resolved in favour of
  the small explicit fixture; see DECISIONS.md D4.
- **Exactly how many nurseries production returns for the Вапцаров address.** The
  ticket says 4. Local-with-the-18 should match it exactly, since production reaches
  95 the same way; the final-validation task compares the two sides rather than
  asserting a hard-coded 4 — on a normalised projection, resolving the address by
  natural key in each database, because `/api/match` is keyed by `address_id` and
  surrogate ids differ across databases.
- **Whether `addresses.district_code` reaches 100 % after stamping.** It will not —
  `docs/OPERATIONS.md` treats `addresses_district_unstamped` above ~2 % of in-city
  addresses as the staleness signal, so `verify` asserts a threshold, not zero.
  The threshold is fixed at the first real seed run in TASK-005.

## References

- [YAS-21](https://linear.app/ivo-tsonev/issue/YAS-21) — the originating ticket,
  including the production-vs-local comparison table for `ул. Н.Й.Вапцаров 007 вх.Г`
- [YAS-11](https://linear.app/ivo-tsonev/issue/YAS-11) — the detail-page work that
  surfaced the problem
- `docs/OPERATIONS.md` § ГРАО quarterly reference-data refresh
- `docs/artifacts/epics/01-institution-data-foundation.md` — phases 1.2/1.3 built
  the locations dataset and the detail endpoint this seed has to reproduce locally
