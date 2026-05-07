# Deployment guide

This is the operator's step-by-step guide for getting the `yasli` backend
from a fresh GitHub repo to two working Railway services (`backend-api` web
+ `backend-ingest` cron) talking to a Railway-managed Postgres.

The implementer of `s04-bootstrap-backend-repo` does **not** log in to
Railway. Every web-UI step below is for you, the operator, to run once.

---

## Prerequisites

You should have already completed the Railway project setup from the
scraper repo —
[`yasli/scraper/docs/DEPLOYMENT.md`](../../scraper/docs/DEPLOYMENT.md). That
guide creates the `yasli` Railway project (and the Cloudflare R2 bucket
the scraper writes to and the backend will eventually read from). This
guide reuses that same Railway project — we add a Postgres plugin and two
services to it; we do not create a second project.

By this point you should have:

- The `yasli` Railway project, with the scraper running as a cron service.
- The Cloudflare R2 bucket `yasli-snapshots`. (The R2 vars are not needed
  yet for the backend in this change; they land in s06.)

---

## Postgres plugin

The backend persists data in a Railway-managed Postgres instance.

1. **Sign in** to <https://railway.app> and open the existing **`yasli`**
   project.
2. Click **+ New** → **Database** → **Add PostgreSQL**. Railway provisions
   a managed Postgres instance and attaches it to the project. Wait for
   the Postgres tile to go green (a few seconds).
3. Click the new Postgres tile. The **Variables** tab exposes
   `DATABASE_URL` (and a handful of derived `PG*` vars). The reference
   form for use in other services is `${{Postgres.DATABASE_URL}}` — we'll
   wire that into both backend services in the next two sections.

Note: Railway returns the URL with the `postgres://` scheme. The backend
normalises it internally to `postgresql+psycopg://` (SQLAlchemy 2's
expected form), so no manual rewriting is needed in the variable.

---

## `backend-api` service

The web service serving `GET /api/health` (and, in later changes, the real
endpoints).

1. From the `yasli` project view, click **+ New** → **Deploy from GitHub
   repo**. Authorise Railway against GitHub if you haven't already, and
   select the **`smeshko/yasli-backend`** repo. Railway will detect the
   `Dockerfile` at the repo root — confirm "Build with: Dockerfile" in
   the build settings; do not let it pick a buildpack.
2. Once the first build kicks off, open the new service tile → **Settings**:
   - **Service name:** `backend-api` (rename from the default).
   - **Service type:** **Web** (default; leave as-is).
   - **Start command:**
     `sh -c 'uvicorn yasli.main:app --host 0.0.0.0 --port ${PORT:-8080}'`
     (the `sh -c` wrapper is mandatory — Railway passes the start
     command through `exec` rather than a shell, so a bare `$PORT`
     would reach uvicorn as the literal string `$PORT`.)
   - **Public networking:** enable a public domain
     (`<service-name>-<project>.up.railway.app`). Railway sets `$PORT`
     automatically.
3. Open **Variables** → **+ New Variable**:
   - **Name:** `DATABASE_URL`
   - **Value:** `${{Postgres.DATABASE_URL}}` — Railway recognises this
     as a reference to the Postgres plugin you added above. The web UI
     shows the resolved value once you save.
4. **Redeploy** so the service picks up the start command and env var.
   Wait for the build + deploy to go green.

---

## `backend-ingest` service

A cron service that shares the same image as `backend-api` but runs
`python -m yasli.ingest`. As of s06 this is the real ingest pipeline:
on every cron firing it pulls `snapshots/varna/latest.json` from R2,
validates it against the v1 contract, and upserts institutions /
streets / address entries into Postgres in a single transaction.

1. From the `yasli` project view, click **+ New** → **Deploy from GitHub
   repo** and select the **same** `smeshko/yasli-backend` repo. Railway
   allows a single repo to back multiple services — this is how we get
   one image, two entrypoints.
2. In the new service tile → **Settings**:
   - **Service name:** `backend-ingest`.
   - **Service type:** **Cron**.
   - **Schedule:** `0 2 * * 0` — Sundays at 02:00 UTC, one hour after
     the scraper's 01:00 UTC run. (See `ARCHITECTURE.md`. Adjust later
     if the scraper's runtime drifts.)
   - **Start command:** `python -m yasli.ingest`
   - **Public networking:** **disabled**. Cron services don't accept
     traffic.
3. **Variables** → add the following:
   - `DATABASE_URL = ${{Postgres.DATABASE_URL}}` (same reference as
     `backend-api`).
   - `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`,
     `R2_BUCKET` — provision a **read-only** R2 access key in
     Cloudflare against the `yasli-snapshots` bucket and paste the
     four values here. The scraper service has Read+Write; the backend
     gets a separate Read-only key with the same account/bucket so a
     buggy backend deploy can never overwrite a snapshot.
4. **Redeploy**.

> **Web vs Cron mistakes are silent failures.** A web-typed
> `backend-ingest` would crash-loop after the stub exits 0 (Railway
> restarts any web process that exits). A cron-typed `backend-api` would
> never serve traffic. Double-check the service-type pill in each tile's
> header before moving on.

---

## Migrations

Convention: **run `alembic upgrade head` once before each deploy that
contains schema changes.**

For s04 there are no schema changes after the initial empty migration —
running it once during this rollout is enough. From s05 onwards, every
PR that adds an Alembic revision adds an entry to that PR's deploy
checklist.

**s05 deploy: revision `0002_data_model`.** Running `alembic upgrade
head` after the s05 deploy advances the production DB from `0001` to
`0002` and creates the three core tables (`institutions`, `streets`,
`address_entries`) plus the `pg_trgm` extension and two non-PK indexes.
The Railway-managed Postgres includes `pg_trgm` in its default contrib
set, so `CREATE EXTENSION IF NOT EXISTS pg_trgm` from the migration
runs without superuser intervention. If a future Postgres host strips
contrib, the operator can run the same `CREATE EXTENSION` statement
manually before the migration; the migration is idempotent on the
extension. The `0002` downgrade drops the tables and indexes but
intentionally leaves `pg_trgm` installed.

**Address-centric deploy: revision `0003_address_centric_schema`.**
Running `alembic upgrade head` after this change advances the DB from
`0002` to `0003`, **drops `address_entries`** and creates `addresses`
(one row per distinct physical address) plus `address_institutions`
(many-to-many coverage junction) with an `(address_id)` lookup index.
No production data exists at the time of this rollout — drop-and-
recreate is safe; the new tables are populated by re-running
`backend-ingest` after the migration. The downgrade drops the new
tables and recreates `address_entries` empty.

Two ways to run it on Railway:

1. **One-off run command (recommended for this change).** From the
   `backend-api` service → **Settings** → **Run command** (or the
   equivalent "exec into deployment" panel) → enter
   `alembic upgrade head` and hit run. Watch the logs for
   `Running upgrade 0002 -> 0003, address_centric_schema` (or, on a
   re-run, no-op output ending with exit 0).
2. **Release-phase command (preferred long-term).** Add a Railway
   pre-deploy hook to `backend-api` that runs `alembic upgrade head`
   before swapping the new container in. This keeps the deploy and
   migration atomic. We'll switch to this when the next table-creating
   migration lands; for now the one-off run is fine.

> **Single-head policy.** Alembic does not tolerate multiple heads. If
> two pull requests each add a migration in parallel, after both merge
> the chain has two heads and `alembic upgrade head` errors out. The
> rule for this repo: **rebase your migration onto `main` before
> merging** so its `down_revision` points at whatever just landed. A CI
> check is on the s15 list.

---

## One-off verification

Before relying on either service, prove the pipeline works.

1. **Web service.** Open the `backend-api` service → **Settings** →
   copy the public URL. Then:
   ```bash
   curl https://<backend-api>.up.railway.app/api/health
   ```
   Expected: `200 {"status": "ok", "db": "ok"}`.
2. **Cron service.** Open the `backend-ingest` service →
   **Deployments** → **Run now** (or whichever button currently
   triggers a one-shot run). Open the resulting deployment's logs.
   Expected:
   - A single structured summary line, e.g.
     `ingest done snapshot=2026-05-04T01:00:00Z institutions={inserted:N,updated:0,unchanged:0,disappeared:0} streets={inserted:M,updated:0,unchanged:0} addresses={inserted:A,updated:0,unchanged:0} address_institutions={inserted:E,unchanged:0} skipped_rows=0 elapsed_ms=…`
     For Varna's snapshot, expect roughly `~70` institutions, `~2.3k`
     streets, `~49k` addresses, and `~236k` coverage edges on the first
     run; second-run counts move to the `unchanged` columns.
   - Exit code 0 ("Exited with code 0" in the dashboard).
   - Re-running immediately should report `inserted:0` for every
     table and a non-zero `unchanged` count — that's the idempotency
     guarantee in action.
3. **Postgres.** Open the Postgres plugin → **Data** tab → confirm an
   `alembic_version` table exists with a single row whose `version_num`
   matches the current head (`0001` after s04, `0002` after s05,
   `0003` after the address-centric restructure). After `0003`,
   `institutions`, `streets`, `addresses`, and `address_institutions`
   exist and `address_entries` is gone; the four tables are empty
   until `backend-ingest` runs.

If all three are green, the backend is wired end-to-end. Subsequent
changes (s05–s09) will only add behaviour — no further Railway setup.

---

## Backend ingest (s06)

`backend-ingest` reads `snapshots/varna/latest.json` from R2 and writes
the contents into Postgres. The cron service was set up earlier in this
document; this section is the operator runbook for the ingest pipeline
itself.

### Required env vars

| Variable                | Purpose                                      |
| ----------------------- | -------------------------------------------- |
| `DATABASE_URL`          | Postgres connection (already wired from s04). |
| `R2_ACCOUNT_ID`         | Cloudflare R2 account id.                     |
| `R2_ACCESS_KEY_ID`      | Read-only R2 access key id.                   |
| `R2_SECRET_ACCESS_KEY`  | Read-only R2 access key secret.               |
| `R2_BUCKET`             | `yasli-snapshots`.                            |

The four `R2_*` vars share the bucket with the scraper but **must** be
a separate read-only key — provision in the Cloudflare dashboard, not
by reusing the scraper's read+write key.

### Cron schedule

`0 2 * * 0` (UTC) — every Sunday at 02:00 UTC, one hour after the
scraper writes the new `latest.json` at 01:00 UTC.

### Manual run procedure

1. **Railway dashboard** → `backend-ingest` service → **Deployments** →
   **Run now**.
2. **Logs** tab on the resulting deployment.
3. Expect a single line beginning with `ingest done snapshot=…` and an
   exit code of 0. The line includes counts per table (inserted /
   updated / unchanged / disappeared) and `elapsed_ms`.

If the run exits non-zero, the most common causes are:

- **Missing R2 var** → first line of stderr names the variable; add it
  in Variables and redeploy.
- **R2 returned 403** → the access key isn't scoped to
  `yasli-snapshots`; reissue from Cloudflare with the right scope.
- **`pydantic.ValidationError`** → the snapshot violates the v1
  contract. Compare with `yasli/scraper/schemas/snapshot.v1.schema.json`
  and check the scraper's most recent run.
- **`SQLAlchemyError` / DB connection refused** → Postgres plugin is
  unhealthy or the `DATABASE_URL` reference broke. Verify in the
  Postgres tile.

The transaction is atomic: a failed run leaves the DB at the previous
snapshot's state. Re-run the cron job after fixing the root cause.

---

## Local Docker run

Useful for reproducing the production code-path before pushing to
Railway.

```bash
# 1. Run a local Postgres in the background.
docker run --rm -d --name yasli-pg \
    -e POSTGRES_PASSWORD=dev \
    -p 5432:5432 \
    postgres:16

# 2. Build the backend image.
docker build -t yasli-backend:local .

# 3. Run migrations against the local Postgres.
docker run --rm \
    -e DATABASE_URL=postgres://postgres:dev@host.docker.internal:5432/postgres \
    yasli-backend:local \
    alembic upgrade head

# 4. Serve the API.
docker run --rm \
    -e DATABASE_URL=postgres://postgres:dev@host.docker.internal:5432/postgres \
    -p 8000:8000 \
    yasli-backend:local \
    uvicorn yasli.main:app --host 0.0.0.0 --port 8000

# 5. Smoke-test from another shell.
curl http://localhost:8000/api/health
# → {"status": "ok", "db": "ok"}

# 6. Tidy up.
docker stop yasli-pg
```

`host.docker.internal` is the Docker-for-Mac/Windows hostname that
resolves to the host machine. On Linux, replace it with the host's IP
or run with `--network=host`.

---

## Troubleshooting

### `Invalid value for '--port': '$PORT' is not a valid integer`

**Symptom:** Logs from `backend-api` show repeated:
```
Error: Invalid value for '--port': '$PORT' is not a valid integer.
Usage: uvicorn [OPTIONS] APP
```
…and the public domain returns nothing.

**Fix:** Railway runs the start command via `exec`, not through a
shell, so a bare `$PORT` is passed to uvicorn as a literal string.
Wrap the command in `sh -c`:

```
sh -c 'uvicorn yasli.main:app --host 0.0.0.0 --port ${PORT:-8080}'
```

The `${PORT:-8080}` form also falls back to 8080 if Railway ever
forgets to inject the variable.

### `DATABASE_URL` mishandled by SQLAlchemy

**Symptom:** Container exits with
`sqlalchemy.exc.NoSuchModuleError: Can't load plugin: sqlalchemy.dialects:postgres`
or similar.

**Fix:** SQLAlchemy 2 doesn't accept the bare `postgres://` scheme; it
wants `postgresql+psycopg://`. The backend's `Settings` loader
normalises both Railway's `postgres://` and the legacy `postgresql://`
forms, so this error means something circumvented `Settings()`. Common
causes: a custom Alembic `env.py` reading the URL straight from
`os.environ`, or a script that built its own engine from
`os.getenv("DATABASE_URL")`. Funnel everything through
`yasli.config.Settings()`.

### Service typed as Web instead of Cron (or vice versa)

**Symptom (Web instead of Cron for ingest):** `backend-ingest` runs
once, exits 0, then Railway restarts it indefinitely with
`RestartLoopBackoff` or similar.

**Symptom (Cron instead of Web for api):** `/api/health` returns
nothing; the public domain shows "no deployment". The cron service
ran once and exited because the FastAPI process expects to keep
running.

**Fix:** In each service's **Settings**, the **Service type** pill at
the top is the source of truth. `backend-api` must be **Web**;
`backend-ingest` must be **Cron**.

### `psycopg` missing system libs in the slim image

**Symptom:** Build succeeds, but at runtime
`ImportError: libpq.so.5: cannot open shared object file` or similar.

**Fix:** `psycopg[binary]` ships its own libpq, so this should not
happen with the pinned dependency. If it does, you've likely switched
to plain `psycopg` (without `[binary]`) somewhere; revert to
`psycopg[binary]>=3` in `pyproject.toml`. As an escape hatch, install
`libpq5` in the Dockerfile (`apt-get install -y --no-install-recommends
libpq5`) before `pip install`.

### Alembic single-head violation from parallel branches

**Symptom:** `alembic upgrade head` errors with
`Multiple head revisions are present for given argument 'head'`. Two
migrations have the same `down_revision` because they were authored
on parallel branches.

**Fix:**
- `alembic heads` lists the heads.
- Pick the migration that was merged second; rebase it onto `main` by
  changing its `down_revision` to the other head's revision id, then
  run `alembic upgrade head` again.
- Going forward: **rebase migrations before merging.** A CI gate is on
  the s15 hardening list.

### `/api/health` returns 503 immediately after deploy

**Symptom:** First few probes after a deploy are 503 with
`db: unreachable`, then it goes 200.

**Fix:** Usually transient — Railway routes traffic to the new
container before Postgres has accepted the first connection, or the
connection pool's first checkout is slow. The engine has
`pool_pre_ping=True` so this self-corrects in seconds. If 503s persist
beyond a minute, check:
- The `DATABASE_URL` env var is the right reference
  (`${{Postgres.DATABASE_URL}}`, not a stale literal from before the
  Postgres plugin was re-provisioned).
- The Postgres tile is green and not in a failure state.
- Logs include the exception body returned by `/api/health` — it
  surfaces the underlying psycopg/SQLAlchemy error.
