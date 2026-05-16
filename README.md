# yasli-backend

FastAPI service that serves Varna's kindergarten/nursery catchment data from Postgres, plus an ingest CLI that pulls weekly snapshots from Cloudflare R2 (produced by [`yasli-scraper`](https://github.com/smeshko/yasli-scraper)) and upserts them. Consumed by [`yasli-frontend`](https://github.com/smeshko/yasli-frontend).

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for how the pieces fit together.

## Quickstart

Requires Python 3.12+ and Postgres 16 (uses `pg_trgm`).

```bash
pip install -e ".[dev]"

# 1. Start Postgres
docker run --rm -e POSTGRES_PASSWORD=dev -p 5432:5432 postgres:16
export DATABASE_URL=postgres://postgres:dev@localhost:5432/postgres

# 2. Migrate
alembic upgrade head

# 3. Serve
uvicorn yasli.main:app --port 8000
# → http://localhost:8000/api/health

# 4. (optional) Pull a real snapshot from R2 into your local DB
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

| Variable | Used by | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | web + ingest | Postgres URL. Both `postgres://` and `postgresql+psycopg://` accepted. |
| `CORS_ALLOWED_ORIGINS` | web | Comma-separated browser origins, e.g. `https://yasli-frontend.pages.dev`. |
| `R2_ACCOUNT_ID` | ingest | Cloudflare R2 account id. |
| `R2_ACCESS_KEY_ID` | ingest | R2 access key. |
| `R2_SECRET_ACCESS_KEY` | ingest | R2 secret. |
| `R2_BUCKET` | ingest | Snapshot bucket (usually `yasli-snapshots`). |

## Deployment

Deployed on Railway as two services (web + ingest cron) plus the managed Postgres plugin. See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) and [`docs/OPERATIONS.md`](docs/OPERATIONS.md).
