# TASK-002: Ingest a snapshot from a committed local file

Depends on: None
Suggested commit: `feat(ingest): ingest a snapshot from a local file instead of R2`

## Goal

Let the ingest pipeline read its snapshot from a local gzipped file, and commit one
such snapshot, so a developer can populate institutions, streets, addresses and
catchment without holding a single R2 credential.

## Files

- `src/yasli/ingest/pipeline.py` — `run()` grows a `snapshot_path: Path | None = None`
  keyword. `_fetch_snapshot_bytes()` returns the file's bytes when a path is given
  (transparently gunzipping a `.gz`) and reads R2 otherwise. Everything downstream —
  `_validate_snapshot`, `_build_plan`, the upserts, the gated stamping — is untouched.
- `src/yasli/ingest/__main__.py` — `ingest` gains `--snapshot <path>`. When it is
  given, `_validate_startup_config(require_r2=False)`: the R2 vars must not be
  required for a path-based run. A missing/unreadable file exits 3, alongside the
  other snapshot-shaped failures.
- `data/seed/snapshot.json.gz` — new, ~760 KB. `snapshots/varna/latest.json` gzipped
  at `-9`.
- `data/seed/README.md` — new. What the file is, which `scraped_at` it carries, that
  it holds only data the source portal publishes publicly, and that
  `python -m yasli.seed freeze` (TASK-006) is what regenerates it.
- `tests/ingest/` — new cases below.

## Acceptance

- [ ] `python -m yasli.ingest --snapshot data/seed/snapshot.json.gz` succeeds with
      **no** `R2_*` variable set, and prints the usual ingest summary line
- [ ] Ingesting the committed snapshot into a fresh database yields 77 institutions,
      2,289 streets, 49,800 addresses and 205,674 `address_institutions` rows —
      the same counts a real R2 ingest produces
- [ ] Both a `.gz` and a plain `.json` path work
- [ ] A missing file, unreadable file or corrupt gzip exits 3 with a message naming
      the path — never a traceback
- [ ] With no `--snapshot`, behaviour is byte-identical to today: R2 is still
      required and still validated at startup
- [ ] The committed snapshot validates as schema v2

Evidence: the ingest summary line from a run with `env -u R2_ACCOUNT_ID …`, plus a
row-count query against the resulting database.

## Steps

### RED
- [ ] Test `run(snapshot_path=…)` against the existing
      `tests/ingest/fixtures/snapshot_v2_minimal.json`, and against a gzipped copy
      of it, asserting equal results
- [ ] Test that the CLI with `--snapshot` does not call `r2.validate_env()`
- [ ] Test the missing-file, corrupt-gzip and non-v2 exit codes
- [ ] Add a data test asserting the committed snapshot exists, gunzips, and
      validates against the `Snapshot` model

### GREEN
- [ ] Thread `snapshot_path` through `run()` and `_fetch_snapshot_bytes()`
- [ ] Add the CLI flag and relax the R2 startup check when it is present
- [ ] Freeze and commit `data/seed/snapshot.json.gz` and its README

### REFACTOR
- [ ] Keep R2 reachable from exactly one place; the file branch must not duplicate
      `LATEST_KEY` handling or the validation sequence

## Notes

The weekly Railway cron invokes the bare `python -m yasli.ingest` with no arguments.
That path must not change — the new flag is strictly additive, and the R2 startup
validation must still fire when it is absent.

`_validate_snapshot()` already raises `UnsupportedSnapshotVersion` for a
`schema_version` other than 2. Reuse it; do not add a second version check.
