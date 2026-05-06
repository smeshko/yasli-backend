# yasli (backend)

FastAPI HTTP API plus an ingest CLI for the `yasli` system. Reads scraper
snapshots from Cloudflare R2 and serves them out of Postgres.

This repo is the backend half of `yasli`. Specs live in the sibling
[`yasli/spec`](https://github.com/smeshko/yasli-spec) repo. The scraper that
produces the R2 snapshots lives in
[`yasli/scraper`](https://github.com/smeshko/yasli-scraper).

## Status

`v0.1.0` — bootstrap. The web service exposes `GET /api/health` (which pings
the DB), Alembic is at revision `0002` with the v1 data-model schema
(`institutions`, `streets`, `address_entries` + `pg_trgm` trigram index on
`streets.search_norm`), and the ingest CLI is a schema-presence stub that
logs the `institutions` row count. Real ingest and search endpoints land in
follow-up changes (s06–s09).

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

# Run the migrations — creates the pg_trgm extension, the three v1
# tables (institutions, streets, address_entries) and their indexes
alembic upgrade head

# Serve the API
uvicorn yasli.main:app --host 0.0.0.0 --port 8000

# Smoke-test
curl http://localhost:8000/api/health
# → {"status": "ok", "db": "ok"}

# Run the ingest CLI stub (logs institutions row count; 0 until s06)
python -m yasli.ingest

# Run tests. Migration and constraint tests need a Postgres URL —
# point YASLI_TEST_DATABASE_URL at a throwaway DB; otherwise they skip.
export YASLI_TEST_DATABASE_URL=postgres://postgres:dev@localhost:5432/postgres
pytest
```

The backend accepts both `postgres://...` (Railway's default) and
`postgresql+psycopg://...` URL forms; the `postgres://` prefix is normalised
internally.

## Required environment variables

| Variable        | Purpose                                                        |
| --------------- | -------------------------------------------------------------- |
| `DATABASE_URL`  | Postgres connection URL. Validated at startup; missing = fail. |

## Layout

```
src/yasli/
  __init__.py        # __version__
  config.py          # Settings (env-var parsing + URL normalisation)
  db.py              # engine, SessionLocal, get_db
  main.py            # FastAPI app
  routes/health.py   # GET /api/health
  models/            # Base + ORM classes (Institution, Street, AddressEntry)
  ingest/__main__.py # python -m yasli.ingest entry; logs row count, real ingest in s06
migrations/          # Alembic
tests/               # pytest suite
docs/DEPLOYMENT.md   # operator setup guide
Dockerfile           # python:3.12-slim image
pyproject.toml
```

## Cloud setup (Railway + Postgres)

See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for the step-by-step operator
guide covering the Railway Postgres plugin, the `backend-api` web service,
the `backend-ingest` cron service, migrations, verification, and
troubleshooting.
