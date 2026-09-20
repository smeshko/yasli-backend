# yasli-backend

FastAPI service that serves Varna's kindergarten/nursery catchment data from Postgres, plus an ingest CLI that pulls weekly snapshots from Cloudflare R2 (produced by [`yasli-scraper`](https://github.com/smeshko/yasli-scraper)) and upserts them. Consumed by [`yasli-frontend`](https://github.com/smeshko/yasli-frontend).

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for how the pieces fit together.

## Quickstart

Requires Python 3.12+ and Postgres 16 (uses `pg_trgm`). No credentials —
the seed data is committed to this repository.

```bash
pip install -e ".[dev]"

# 1. Start Postgres
docker run --rm -e POSTGRES_PASSWORD=dev -p 5432:5432 postgres:16
export DATABASE_URL=postgres://postgres:dev@localhost:5432/postgres

# 2. Seed. Migrates, then loads districts, institutions, catchment and
#    locations from data/ — and verifies its own work before exiting 0.
python -m yasli.seed

# 3. Serve
uvicorn yasli.main:app --port 8000
# → http://localhost:8000/api/health
```

The seed takes about half a minute on an empty database and prints one
line per step:

```
seeding a production-like local database
  migrate                head (252 ms)
  grao                   rows=47579 streets=2071 (1152 ms)
  ingest                 institutions=77 streets=2289 addresses=49800 address_institutions=205674 ...
  legacy-institutions    inserted=18 updated=0 unchanged=0 (26 ms)
  institution-locations  rows=94 missing_main=18 address_drift=0 (21 ms)
  restamp-districts      addresses_stamped=43459 institutions_district_unstamped=4 (2373 ms)
seed done steps=6 snapshot=2026-09-19T07:01:51+00:00 elapsed_ms=23569
verifying the local database against the committed artifacts
  [ok  ] institution-set        95 institutions = snapshot 77 + fixture 18
  ...
verify passed checks=10 failures=0 warnings=0
```

It is safe to re-run over an existing database. `python -m yasli.seed
verify` re-checks a database on its own and exits non-zero naming
everything that is missing, so a half-seeded database never passes for a
good one. From the repo root, `just be-seed` and `just be-verify-seed` are
aliases for the two.

### What your local database contains

Everything the `/api` endpoints serve, matching production on every count
but one:

| | local, after the seed | production | why |
| --- | --- | --- | --- |
| `institutions` | 95 | 95 | 77 from the frozen snapshot, plus 18 committed separately |
| — of which stale | 18 | 18 | `ДГ№X … / с яслена група/` rows that stopped appearing in snapshots after 2026-05-10 and were never retired. They carry no район in production either, so they route nowhere on both sides. Retiring them is a separate ticket |
| `streets` | 2,289 | 2,289 | |
| `addresses` | 49,800 | 49,800 | |
| in-city addresses without a район | 685 / 46,149 | 685 / 46,149 | ГРАО's classifier does not cover every building; >2% is the staleness signal |
| `grao_addresses` | 47,579 | 47,579 | the committed 2026-02 ГРАО cycle |
| `address_institutions` | 205,674 | 241,723 | production additionally carries ~36k catchment edges on the 18 stale rows; nursery routing ignores them, so `/api/match` answers identically |
| `institution_locations` | 94 | — | the table is newer than the current production deploy |

Two things a local database does **not** have:

- **Fresh data.** The snapshot is frozen at a moment in time and does not
  move on its own; `verify` prints its `scraped_at` and warns once it is
  more than 90 days old. Refreshing it is a maintainer action — see
  [`data/seed/README.md`](data/seed/README.md).
- **Free places.** The free-places API (epic 02) is not implemented, so
  there is nothing local or remote to seed.

Because ingest never deletes, re-running the seed over a database that
already holds older data accumulates stale rows. `verify` fails on
anything outside the committed artifacts rather than letting it pass, and
`just db-reset && just be-seed` gives a clean one.

### Maintainer: ingest from R2 directly

Not needed for local work. The weekly cron runs this, and it is how a
snapshot reaches R2 in the first place:

```bash
export R2_ACCOUNT_ID=… R2_ACCESS_KEY_ID=… R2_SECRET_ACCESS_KEY=… R2_BUCKET=yasli-snapshots
python -m yasli.ingest
```

## Tests

```bash
export YASLI_TEST_DATABASE_URL=postgres://postgres:dev@localhost:5432/postgres
pytest
```

Pure-Python tests (parser, normaliser) run without Postgres. Migration/constraint tests need `YASLI_TEST_DATABASE_URL`. Ingest integration tests need Docker (testcontainers spins up Postgres).

## Environment variables

`python -m yasli.seed` and `python -m yasli.seed verify` need **only**
`DATABASE_URL`. The `R2_*` variables are for the weekly ingest and for
`python -m yasli.seed freeze`, neither of which is part of getting
started.

| Variable | Used by | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | web + ingest + **seed** | Postgres URL. Both `postgres://` and `postgresql+psycopg://` accepted. |
| `CORS_ALLOWED_ORIGINS` | web | Comma-separated browser origins, e.g. `https://yasli-frontend.pages.dev`. |
| `R2_ACCOUNT_ID` | ingest, `seed freeze` | Cloudflare R2 account id. |
| `R2_ACCESS_KEY_ID` | ingest, `seed freeze` | R2 access key. |
| `R2_SECRET_ACCESS_KEY` | ingest, `seed freeze` | R2 secret. |
| `R2_BUCKET` | ingest, `seed freeze` | Snapshot bucket (usually `yasli-snapshots`). |

## Deployment

Deployed on Railway as two services (web + ingest cron) plus the managed Postgres plugin. See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) and [`docs/OPERATIONS.md`](docs/OPERATIONS.md).
