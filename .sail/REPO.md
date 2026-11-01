# yasli-backend

The FastAPI service, Postgres schema and ingest behind Yasli. `docs/ARCHITECTURE.md` has the layout. The frontend and
scraper are separate repositories, and the API and the snapshot format are contracts with them.

## Commands

- Lint: `uv run ruff check .`. One test file: `uv run pytest <file>`. There is no type checker in CI.
- `uv` is the package manager; a new dependency is `uv add <package>`.

## Tests

pytest under `tests/`, one `test_<module>.py` per module, async by default. `tests/conftest.py` patches `DATABASE_URL` per
test. `tests/ingest/` spawns its own Postgres through testcontainers, and `tests/test_migrations.py` needs
`YASLI_TEST_DATABASE_URL`: run those only through the gate, which provides both. `*_openapi.py` tests pin the API contract.

## Migrations and generated files

- A schema change is an Alembic migration under `migrations/`, single head, rebased onto the latest one on `staging`
  (`docs/DEPLOYMENT.md`).
- An API change must stay compatible with what the deployed frontend reads: it generates its types from `/openapi.json`.
  Add fields; don't rename or remove them. A breaking change ends the step **blocked**.
- `data/` is committed seed data. Change it only when the ticket says so, and keep `python -m yasli.seed verify` passing.

## Demonstration

The surfaces are `api` (an endpoint) and `db` (what a load or migration leaves in the tables).

`.sail/lib/demo.sh <command> [args…]` starts a throwaway Postgres, seeds it from the committed data with
`python -m yasli.seed`, serves the API, runs the command with `$API_URL` and `$DATABASE_URL` set, then stops both. Seeding
takes a while, so make one call per scenario do everything it needs. Single-quote the command, so the variables expand
inside it:

```
.sail/lib/demo.sh bash -c 'curl -si "$API_URL/api/health" | tee -a "$STAGE_OUT/demo/transcript.txt"'
```

Run nothing against R2, Railway or any database but the one `demo.sh` starts: `python -m yasli.ingest` reads the production
bucket, so demonstrate an ingest through its tests' fixtures or `yasli.seed`, never that command.
