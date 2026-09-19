# Research: Expose the enriched institution profile

Curated findings only — no raw conversation transcripts.

## Key Files & Directories

- `src/yasli/routes/institutions.py` — both handlers and everything this plan
  touches. Serialisation is by hand: `_json_bytes` (`jsonable_encoder` →
  compact `json.dumps`, `ensure_ascii=False`), `_etag` (sha256, 16 hex,
  `"v1-…"`), `_headers`, `_not_modified_response`, `_json_response`.
  `list_institutions` selects six columns with a `kind_order` CASE;
  `get_institution` runs a row query and a coverage query, then folds
  coverage by street. Pydantic models: `InstitutionListItem`,
  `InstitutionDetail`, `CoverageGroup`, `StreetSummary`, `InstitutionAddress`.
- `src/yasli/models/institution.py` — columns already present: `address`
  (256), `phone` (128), `email` (256), `director` (256), `website` (256),
  `district_code` (2, CHECK `01..05`), `has_infant_group` (bool NOT NULL,
  default false). Natural key `UniqueConstraint("external_id", "kind")`.
- `src/yasli/models/institution_location.py` — `InstitutionLocation`:
  `kind`, `external_id`, `role`, `label`, `address`, `lat`, `lon`,
  `precision`, `source`, `verification`, `verified_at`. Constraints that
  matter here: partial unique index `uq_institution_locations_main` on
  `(kind, external_id) WHERE role = 'main'`; `(lat IS NULL) = (lon IS NULL)`;
  `(precision = 'none') = (lat IS NULL)`; FK `(external_id, kind)` →
  `institutions` with `ON UPDATE CASCADE`.
- `src/yasli/models/types.py` — `Kind`, `DistrictCode`, `LocationPrecision`
  (`building | approximate | none`) and their `*_VALUES` tuples.
- `src/yasli/routes/match.py` — precedent for a `Kind`-typed parameter
  (`kind: Kind | None = Query(...)`) and for `DistrictCode | None` in a
  response model.
- `tests/test_institutions.py` — the SQLite in-memory `client` fixture
  (`create_engine("sqlite+pysqlite:///:memory:")`, `StaticPool`,
  `Base.metadata.create_all`, `db.set_engine`); seed helpers
  `_seed_institutions` (passes extra kwargs straight to `Institution(**payload)`),
  `_seed_streets`, `_seed_addresses`, `_link_addresses`, `_seed_detail_fixture`;
  `LIST_KEYS` / `DETAIL_KEYS` exact-key assertions; the `_BrokenSession`
  503 pattern.
- `tests/test_institutions_openapi.py` — `_resolve_schema` and `_enum_values`
  helpers over `/openapi.json`; exact-key assertions on component schemas.
- `tests/test_match_openapi.py` — asserts the `kind` query parameter's enum
  values; the same `_enum_values` approach works for a path parameter.
- `tests/test_institution_locations_loader.py` — `sqlite_engine` /
  `sqlite_session` fixtures prove `InstitutionLocation` round-trips on SQLite.
- `data/institution_locations.csv` — 94 rows: 53 kindergarten `main`,
  12 nursery `main`, 12 preschool `main`, 17 kindergarten `branch`. Lines
  23–27 are `kindergarten,46` (4 branches + 1 auto-accepted main at
  43.209589, 27.926883).
- `docs/ARCHITECTURE.md` §Public API — the route table to update.
- `src/yasli/main.py` — routers mounted under `/api`; `SQLAlchemyError` →
  503 `{"status": "degraded", "error": "database unreachable"}`.
- `../frontend/scripts/generate-api-types.mjs` — runs `openapi-typescript`
  against `YASLI_OPENAPI_URL` or `http://localhost:8000/openapi.json` and
  writes `src/lib/api/types.ts`. `just fe-api-types` wraps it.
- `../frontend/src/lib/api/client.ts`, `../frontend/src/lib/search/results.ts`
  — today's only consumers of `InstitutionListItem`; `newestFreshnessDate`
  reads `last_seen_at` only.

## Architecture Facts

- `response_model` on both routes feeds OpenAPI only; the body bytes come from
  `_json_bytes(model)`. Field declaration order is therefore JSON key order,
  and the ETag is a hash of exactly those bytes — any shape change changes
  every ETag automatically.
- Pydantic v2 + FastAPI: a field typed `X | None` **without** a default is
  required. OpenAPI lists it in `required` with `anyOf: [{X}, {"type":
  "null"}]`; `openapi-typescript` emits `X | null`. With `= None` it leaves
  `required` and the frontend sees `X?: ...`. The epic's "null, not omitted"
  is satisfied only by the no-default form.
- `jsonable_encoder` maps `Decimal` to `float` (or `int` when integral). The
  plan converts with `float()` explicitly so an integral coordinate cannot
  serialise as an integer.
- FastAPI path matching: `/institutions/{institution_id}` matches exactly one
  path segment, so `/institutions/by-source/{kind}/{external_id}` cannot
  collide with it regardless of registration order. `/api/institutions/by-source`
  with nothing after it falls into the id route and returns 422.
- A `Literal` path parameter renders as an enum in OpenAPI and rejects other
  values with 422, the same way the `Kind` query parameter on `/api/match`
  does.
- `institution_locations.label` and `.address` are `""` when absent (the
  `grao_addresses` convention, needed for the UNIQUE tuple). The surrogate
  `id` is reassigned by every loader run, so nothing may order by it.
- CI (`.github/workflows/ci.yml`) runs `ruff check .` and `pytest` with a
  Postgres service; the route tests need only SQLite.
- Local state, verified 2026-09-16 against `yasli-postgres` (docker compose
  in the `yasli/` parent): alembic head `0010`; 77 institutions, all with
  `phone`; 12 with `website` (the preschools); 12 with `district_code` (the
  nurseries — kindergartens are stamped by catchment majority, which needs
  ГРАО rows not loaded locally); 94 `institution_locations` rows (a bare count cannot
  tell a fresh load of the committed CSV from an older one, so TASK-005
  reloads before any curl); `kindergarten/46`
  was `institutions.id = 13` with 5 location rows and `nursery/1` was
  `id = 66` with `district_code = '01'` — serials as observed that day, not
  a contract: a rebuilt database reassigns them, so every task resolves ids
  by `(kind, external_id)` at run time.
- Scraper epic 01 (contact metadata) is done, so real snapshots carry the
  contact fields — the end-to-end validation the epic asks for is possible.
- Frontend epic 01 phase 1.1 hydrates from `GET
  /api/institutions/by-source/{kind}/{external_id}` with
  a slug shaped like `kindergarten-46`; phase 1.2 reads `location` and `branches[].location`;
  phase 1.3 reads `district_code`. Frontend epic 02 phase 2.1 reads the list
  for name, kind and the infant marker.

## Constraints

- Ruff, line length 100, `py312`. `just be-lint` and `just be-test` must pass.
- No migrations, no ingest changes, no new dependencies.
- ETag/cache header behaviour and coverage grouping/ordering must not change.
- The frontend working tree must be left as it was found.
- Epics live in this repo under `docs/artifacts/epics/`, so `link_plan.py`
  works from here.

## Useful Commands

```bash
# from yasli/
just be-lint
just be-test
just be-api                       # uvicorn on :8000 with --reload
just db-up                        # docker compose postgres
just be-load-locations            # idempotent TRUNCATE + INSERT — the only proof the table holds the committed CSV
just be-load-locations --dry-run  # runs the three guards (CSV vs. institutions) only; never compares the table to the CSV

# from yasli/backend
uv run pytest tests/test_institutions.py tests/test_institutions_openapi.py -v
# full suite with the Postgres-backed tests — yasli_test only: test_migrations.py downgrades to base
YASLI_TEST_DATABASE_URL=postgresql+psycopg://yasli:yasli@localhost:5432/yasli_test uv run pytest

# evidence
curl -s localhost:8000/api/institutions/by-source/kindergarten/46 | python3 -m json.tool
ID=$(docker compose exec -T postgres psql -U yasli -d yasli -tAc \
  "SELECT id FROM institutions WHERE kind='kindergarten' AND external_id='46'")   # never hard-code a serial
curl -s -D - -o /dev/null localhost:8000/api/institutions/$ID
curl -s -o /dev/null -w '%{http_code}\n' localhost:8000/api/institutions/by-source/school/46
docker compose exec -T postgres psql -U yasli -d yasli -c \
  "SELECT id, kind, external_id, name, district_code FROM institutions WHERE kind='kindergarten' AND external_id='46'"

# frontend types round trip (from yasli/)
git -C frontend status --short src/lib/api/types.ts      # must be empty first
just fe-api-types
git -C frontend diff --stat src/lib/api/types.ts
git -C frontend checkout -- src/lib/api/types.ts
```

## Uncertainty

- Cyrillic collation differs between SQLite (binary) and Postgres, so branch
  order could differ between environments — resolved: the guarantee is
  determinism within one database, as for coverage; fixtures use values that
  sort the same under both.
- Whether `openapi-typescript` 7 handles `anyOf [$ref, null]` cleanly — it
  emits `components["schemas"]["Location"] | null`; TASK-005 proves it by
  running the real generator.
- Whether the `SAWarning` about `Decimal` on SQLite becomes noisy in the route
  tests — the loader tests already emit it without a filter; left as is
  unless it turns into an error.

## References

- [Epic 01, phase 1.3](../../epics/01-institution-data-foundation.md)
- `../openspec/docs/INSTITUTION_DETAIL_MAP_RESEARCH.md` (the `yasli/` parent,
  not this repo) §1 (field coverage), §1.3 (branch inventory), §2 (page
  content), §8 (impact surface)
- `../openspec/specs/institutions-endpoint/spec.md` (the `yasli/` parent) —
  the historic "exactly these keys" contract this plan supersedes (not
  backfilled, per the epic)
- `frontend/docs/artifacts/epics/01-institution-detail-page.md`,
  `frontend/docs/artifacts/epics/02-*.md` phase 2.1 — the consumers
- `docs/OPERATIONS.md` §Institution locations refresh — how the location rows
  get into the database
