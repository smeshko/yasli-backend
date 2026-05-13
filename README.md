# yasli (backend)

FastAPI HTTP API plus an ingest CLI for the `yasli` system. Reads scraper
snapshots from Cloudflare R2 and serves them out of Postgres.

This repo is the backend half of `yasli`. Specs live in the sibling
[`yasli/spec`](https://github.com/smeshko/yasli-spec) repo. The scraper that
produces the R2 snapshots lives in
[`yasli/scraper`](https://github.com/smeshko/yasli-scraper).

## Status

`v0.1.0` — bootstrap. The web service exposes `GET /api/health` (which pings
the DB), `GET /api/streets` (the bulk dump of every Varna street row),
`GET /api/addresses` (the bulk dump of every canonical address), and
`GET /api/match` (the address-to-institution lookup),
`GET /api/institutions` (the institution list), and
`GET /api/institutions/{institution_id}` (institution profile coverage). The
snapshot read endpoints carry strong content-derived `ETag` headers and
hour-long `Cache-Control`.
Alembic is at revision `0005` with the address-centric v2 schema
(`institutions`, `streets`, `addresses`, `address_institutions`,
`grao_addresses` + `pg_trgm` trigram index on `streets.search_norm`).
`institutions` carries the v2 physical address, district code, and
infant-group flag; `addresses` carries the ГРАО-stamped `district_code`;
`grao_addresses` holds the ГД ГРАО KADS reference rows loaded
quarterly out-of-band. The weekly ingest CLI pulls the latest scraper
snapshot from R2, upserts streets/addresses/institutions/coverage edges
into Postgres, and runs both gated district-stamping passes (addresses
then KG/PG institutions) after the upsert phase. An out-of-band CLI
subcommand `python -m yasli.ingest restamp-districts` propagates ГРАО
reassignments to previously-stamped rows after a quarterly KADS reload —
see [`docs/OPERATIONS.md`](docs/OPERATIONS.md).

## Quickstart (local, Python)

Requires Python 3.12+ and a reachable Postgres with the `pg_trgm` extension
available (the stock `postgres:16` image ships it — no extra setup).

```bash
# Install in editable mode with dev deps
pip install -e ".[dev]"

# Start a local Postgres (Docker is the easy path)
docker run --rm -e POSTGRES_PASSWORD=dev -p 5432:5432 postgres:16

# Point the backend at it
export DATABASE_URL=postgres://postgres:dev@localhost:5432/postgres

# Run the migrations — creates the pg_trgm extension, the four v2
# tables (institutions, streets, addresses, address_institutions) and
# their indexes, including institution metadata columns
alembic upgrade head

# Serve the API
uvicorn yasli.main:app --host 0.0.0.0 --port 8000

# Smoke-test
curl http://localhost:8000/api/health
# → {"status": "ok", "db": "ok"}

# Bulk-dump every street row (~2,272 after a real ingest, including the
# ~295 compound-locality rows whose `street_part` is empty). The response
# carries a strong `ETag`; revalidate with `If-None-Match` to get a 304.
curl -i http://localhost:8000/api/streets | head -5
# HTTP/1.1 200 OK
# etag: "v1-…"
# cache-control: public, max-age=3600, stale-while-revalidate=86400

# Bulk-dump every canonical address (~49,254 after a real ingest). This
# endpoint has the same ETag and Cache-Control behaviour as /api/streets.
curl -i http://localhost:8000/api/addresses | head -5
# HTTP/1.1 200 OK
# etag: "v1-…"
# cache-control: public, max-age=3600, stale-while-revalidate=86400

# Look up the institutions covering a known address id. Add kind=nursery,
# kind=kindergarten, or kind=preschool to filter the flat result list.
curl "http://localhost:8000/api/match?address_id=1"
# → [{"id":...,"external_id":"...","name":"...","kind":"...","source_url":"..."}]

# List all institutions in browse-display order. The response uses the
# same ETag and Cache-Control behaviour as the bulk dump endpoints.
curl -i http://localhost:8000/api/institutions | head -5
# HTTP/1.1 200 OK
# etag: "v1-…"
# cache-control: public, max-age=3600, stale-while-revalidate=86400

# Fetch one institution profile with served-address coverage grouped by
# street. Replay either institution route with If-None-Match: "<etag>"
# to get a 304 Not Modified response when the snapshot is unchanged.
curl -i http://localhost:8000/api/institutions/1 | head -20
# HTTP/1.1 200 OK
# etag: "v1-…"
# cache-control: public, max-age=3600, stale-while-revalidate=86400

# Run the ingest CLI: pulls snapshots/varna/latest.json from R2 and
# upserts into Postgres in one transaction. Set the four R2_* env vars
# alongside DATABASE_URL — a read-only Cloudflare R2 access key is
# enough.
export R2_ACCOUNT_ID=…
export R2_ACCESS_KEY_ID=…
export R2_SECRET_ACCESS_KEY=…
export R2_BUCKET=yasli-snapshots
python -m yasli.ingest
# → ingest done snapshot=… institutions={inserted:N,updated:0,…} \
#   streets={inserted:M,…} addresses={inserted:A,…} \
#   address_institutions={inserted:E,unchanged:0} \
#   address_null=K skipped_rows=0 elapsed_ms=…
# First run against a fresh DB is roughly 30–90 s for the production
# snapshot (12 nurseries, about 52 kindergartens, and 12 preschools).
# Subsequent runs are faster (mostly no-op upserts).

# Run tests. Migration and constraint tests need a Postgres URL —
# point YASLI_TEST_DATABASE_URL at a throwaway DB; otherwise they skip.
# Ingest integration tests need Docker (testcontainers spins up
# Postgres). Pure-Python tests (parser, normaliser, schema drift) run
# without either.
export YASLI_TEST_DATABASE_URL=postgres://postgres:dev@localhost:5432/postgres
pytest
```

The backend accepts both `postgres://...` (Railway's default) and
`postgresql+psycopg://...` URL forms; the `postgres://` prefix is normalised
internally.

## Required environment variables

The web service (`uvicorn yasli.main:app`) needs `DATABASE_URL`.
Browser clients also need `CORS_ALLOWED_ORIGINS` set to the exact frontend
origins allowed to call the API. The ingest CLI (`python -m yasli.ingest`)
additionally needs the four `R2_*` variables — they're validated at startup
before any network call.

| Variable                | Used by               | Purpose                                                        |
| ----------------------- | --------------------- | -------------------------------------------------------------- |
| `DATABASE_URL`          | web + ingest          | Postgres connection URL. Both `postgres://` and `postgresql+psycopg://` accepted. |
| `CORS_ALLOWED_ORIGINS`  | web                   | Comma-separated exact browser origins allowed to call the API, e.g. `http://localhost:4321,https://example.com`. |
| `R2_ACCOUNT_ID`         | ingest                | Cloudflare R2 account id (constructs the endpoint URL).        |
| `R2_ACCESS_KEY_ID`      | ingest                | Read-only R2 access key id.                                    |
| `R2_SECRET_ACCESS_KEY`  | ingest                | Read-only R2 access key secret.                                |
| `R2_BUCKET`             | ingest                | Snapshot bucket, typically `yasli-snapshots`.                  |

## Layout

```
src/yasli/
  __init__.py            # __version__
  config.py              # Settings (env-var parsing + URL normalisation)
  db.py                  # engine, SessionLocal, get_db
  main.py                # FastAPI app
  routes/health.py       # GET /api/health
  routes/streets.py      # GET /api/streets (bulk dump + ETag/Cache-Control)
  routes/addresses.py    # GET /api/addresses (bulk dump + ETag/Cache-Control)
  routes/match.py        # GET /api/match (address_id -> institutions)
  routes/institutions.py # GET /api/institutions + detail coverage
  models/                # Base + ORM classes (Institution, Street, Address) + address_institutions Table
  snapshot_contract/     # Vendored Pydantic Snapshot models (v2)
  ingest/                # python -m yasli.ingest pipeline
    __main__.py          # CLI entrypoint (argparse, exit-code mapping)
    pipeline.py          # fetch → validate → parse → upsert → log
    r2.py                # boto3 R2 client wrapper
    parser.py            # house-number string → (int, suffix, entrance)
    normalise.py         # raw street → (city, marker, part, search_norm)
migrations/              # Alembic
tests/                   # pytest suite
docs/DEPLOYMENT.md   # operator setup guide
Dockerfile           # python:3.12-slim image
pyproject.toml
```

## Cloud setup (Railway + Postgres)

See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for the step-by-step operator
guide covering the Railway Postgres plugin, the `backend-api` web service,
the `backend-ingest` cron service, migrations, verification, and
troubleshooting.
