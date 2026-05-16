# Backend architecture

## Role in the yasli system

```
┌────────────────────┐       weekly         ┌──────────────────┐
│  yasli-scraper     │ ─────snapshot──────▶ │  Cloudflare R2   │
│  (Railway cron)    │   v2 JSON upload     │ yasli-snapshots/ │
└────────────────────┘                      └────────┬─────────┘
                                                     │ pull latest.json
                                                     ▼
                  ┌──────────────────────────────────────────┐
                  │            yasli-backend                 │
                  │  ┌────────────────┐  ┌────────────────┐  │
                  │  │ ingest CLI     │─▶│   Postgres     │  │
                  │  │ (Railway cron) │  │  (Railway)     │  │
                  │  └────────────────┘  └───────┬────────┘  │
                  │                              │           │
                  │              ┌───────────────▼────────┐  │
                  │              │ FastAPI web (Railway)  │  │
                  │              │ /api/* JSON endpoints  │  │
                  │              └───────────┬────────────┘  │
                  └──────────────────────────┼───────────────┘
                                             │ HTTPS + CORS
                                             ▼
                                  ┌────────────────────────┐
                                  │     yasli-frontend     │
                                  │   (Cloudflare Pages)   │
                                  └────────────────────────┘
```

The backend is the only writer to Postgres and the only reader of R2. The frontend never talks to R2 directly.

## Stack

- Python 3.12, FastAPI, SQLAlchemy 2, Alembic.
- Postgres 16 with `pg_trgm` (trigram fuzzy search on street names).
- boto3 against the R2 S3-compatible API.
- pytest + testcontainers for integration tests.

## Components

### `src/yasli/`

| Module | Purpose |
| --- | --- |
| `main.py` | FastAPI app factory, CORS middleware wiring. |
| `config.py` | Env-var settings (DB URL normalisation, CORS origin parsing). |
| `db.py` | SQLAlchemy engine, session factory, `get_db` dependency. |
| `routes/` | One module per resource: `health`, `streets`, `addresses`, `match`, `institutions`. |
| `models/` | ORM classes — `Institution`, `Street`, `Address`, `GraoAddress`, + `address_institutions` junction. |
| `snapshot_contract/` | Vendored Pydantic v2 models matching the scraper's snapshot schema. Source of truth for ingest validation. |
| `ingest/` | CLI entrypoint, R2 client, pipeline orchestrator, house-number parser, street normaliser, district-stamping passes. |

### `migrations/`

Alembic, currently at revision `0005`. The schema is address-centric: catchments are edges between addresses and institutions, not free-text matching.

### `docs/`

- `ARCHITECTURE.md` (this file)
- `DEPLOYMENT.md` — Railway setup, services, plugins, migrations
- `OPERATIONS.md` — quarterly GRAO restamp procedure

## Data model

| Table | Holds |
| --- | --- |
| `institutions` | One row per (external_id, kind). Name, source URL, physical address, district code, infant-group flag. |
| `streets` | Verbatim street strings + `search_norm` (normalised search form). Trigram index for fuzzy lookup. |
| `addresses` | Physical address rows: `(street_id, number_int, number_suffix, entrance)`, stamped with `district_code`. |
| `address_institutions` | Junction table — street-level catchment edges (mostly kindergartens). |
| `grao_addresses` | ГД ГРАО KADS reference rows loaded quarterly. Ground truth for `(street, number, entrance) → район`. |

Catchments split into two kinds:
- **Street-level** (kindergartens): explicit edges in `address_institutions`.
- **District-level** (nurseries, preschools): no edges; matched by stamping `addresses.district_code` and looking up institutions in that district.

## Public API

All routes under `/api`, JSON responses, GETs only.

| Route | Purpose |
| --- | --- |
| `GET /api/health` | DB-backed liveness probe. |
| `GET /api/streets` | Bulk dump of all streets (~2,272 rows). ETag + 1h Cache-Control. |
| `GET /api/addresses` | Bulk dump of all addresses (~49,254 rows). ETag + 1h Cache-Control. |
| `GET /api/institutions` | All institutions in browse order. ETag + 1h Cache-Control. |
| `GET /api/institutions/{id}` | One institution profile + served addresses grouped by street. |
| `GET /api/match?address_id={id}&kind={…}` | Institutions covering an address (street edges + district routing). |

ETags are content-derived strong tags; clients revalidate with `If-None-Match` for 304s.

## Ingest pipeline

`python -m yasli.ingest` (run weekly on Railway, separate from the web service):

1. Fetch `snapshots/varna/latest.json` from R2 via boto3.
2. Validate against the vendored Pydantic snapshot contract.
3. Parse house numbers (`ingest/parser.py`), normalise streets (`ingest/normalise.py`).
4. Upsert streets → addresses → institutions → catchment edges in a single transaction.
5. Run two gated district-stamping passes: addresses first (`grao_addresses` ground truth), then nursery/preschool institutions.
6. Log structured stats: inserted/updated counts, elapsed ms.

Subcommand `python -m yasli.ingest restamp-districts` propagates GRAO reassignments after a quarterly KADS reload — no R2 fetch needed. See `docs/OPERATIONS.md`.

## Frontend contract

The frontend consumes the OpenAPI schema served at `/openapi.json` and generates TS types from it at dev time (`scripts/generate-api-types.mjs` on the frontend side). Any schema-affecting change here is a coordinated change with the frontend.

CORS is the only runtime coupling — the frontend's Pages origin must be in `CORS_ALLOWED_ORIGINS`.

## Scraper contract

The backend depends on the scraper writing two files to R2:

- `snapshots/varna/<UTC-ISO-timestamp>.json` — immutable audit trail.
- `snapshots/varna/latest.json` — what ingest reads.

The scraper writes timestamped first, `latest.json` second, so a partial failure leaves `latest.json` pointing at the previous good snapshot. The vendored `snapshot_contract/models.py` here must match the scraper's `models.py` at the same schema version (currently v2).
