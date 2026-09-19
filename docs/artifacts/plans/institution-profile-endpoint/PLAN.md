# Plan: Expose the enriched institution profile

Status: done
Branch: feature/yas-8-institution-profile-endpoint
Risk: medium
Epic: 01 — Institution data foundation ([epic](../../epics/01-institution-data-foundation.md))
Phase: 1.3 — Expose the enriched institution profile
Linear: YAS-8
Created: 2026-09-16

## Goal

One API call returns everything a detail page needs for any of the 77
institutions — address, contacts, district, infant-group flag, the main
building's coordinates and every branch building — and the page can be
addressed by the stable `(kind, external_id)` key instead of a database
serial that changes on re-ingest.

## Scope

- Extend `InstitutionDetail` in `src/yasli/routes/institutions.py` with
  `address`, `phone`, `email`, `director`, `website`, `district_code`,
  `has_infant_group`, `location` and `branches`, all present as `null` (or
  `[]` for `branches`) when absent.
- Extend `InstitutionListItem` with `has_infant_group` and `location`; the
  list's ordering, row count and cache behaviour stay as they are.
- Add `GET /api/institutions/by-source/{kind}/{external_id}` returning the
  detail payload with the same ETag, cache headers and 404 body as the id
  route; both routes share one builder.
- Update the exact-key assertions in `tests/test_institutions.py` and
  `tests/test_institutions_openapi.py` — that is where the new contract gets
  pinned, including "required and nullable" at the schema level.
- Update the Public API table in `docs/ARCHITECTURE.md`.
- Validate against the local Postgres (77 institutions with contacts, 94
  location rows reloaded from the committed CSV by `just be-load-locations`,
  alembic head `0010`) and prove the OpenAPI document is consumable by the
  frontend's `openapi-typescript` step.

## Out of Scope

- Any frontend work, including committing a regenerated
  `frontend/src/lib/api/types.ts` — frontend epic 01 owns that. The final
  task regenerates the file as evidence and restores it.
- Backfilling `openspec/specs/institutions-endpoint/spec.md` (in the `yasli/`
  parent). The epic rules this out (the project is moving off OpenSpec); the response contract lives
  in this plan's acceptance criteria and its tests.
- Exposing location provenance — `source`, `verification`, `verified_at` and
  `role` stay internal to the reference dataset.
- Schema or migration changes. Every column this plan reads already exists
  (revisions `0009` contact fields, `0010` `institution_locations`).
- Changing the ETag scheme, the cache headers, or the coverage grouping and
  ordering.
- A slug-form route (`/institutions/kindergarten-46`). The frontend builds its
  slug from the two path segments.
- Free places — backend epic 02.

## Research Summary

See [RESEARCH.md](./RESEARCH.md). The short version:

- **All the data is already in the database.** `institutions` has the four
  contact columns, `district_code` and `has_infant_group`;
  `institution_locations` has exactly one `main` row per institution (a
  partial unique index enforces it) plus 17 kindergarten `branch` rows.
  Scraper epic 01 has shipped, so the local snapshot's 77 institutions all
  carry phone, e-mail and director, and the 12 preschools a website.
- **The routes serialise by hand**, not through FastAPI's `response_model`
  path: `jsonable_encoder` → compact `json.dumps` → sha256 → `"v1-…"`. The
  Pydantic models exist for OpenAPI and shape only, and field declaration
  order is JSON key order.
- **"null, not omitted" is a declaration detail.** A Pydantic field typed
  `str | None` *without* a default is required-nullable: in the body it is
  always present, in OpenAPI it sits in `required` with `anyOf [string,
  null]`, and `openapi-typescript` emits `string | null`. With `= None` it
  becomes optional and the frontend would see `string?`.
- **`institution_locations` stores `label` and `address` as `""` when
  absent** (so the UNIQUE tuple constrains), `lat`/`lon` are `Numeric(9,6)`
  (Python `Decimal`), and CHECK constraints guarantee `(lat IS NULL) = (lon
  IS NULL)` and `precision = 'none' ⇔ lat IS NULL`.
- **Route tests run on SQLite in-memory** via `Base.metadata.create_all`;
  seeding `InstitutionLocation` there works (the loader tests already do it)
  with a harmless `SAWarning` about `Decimal`.
- **Locally, kindergartens have `district_code = NULL`** — their value comes
  from the catchment-majority stamp, which needs ГРАО rows that are not
  loaded locally. Nurseries carry their source district. The endpoint exposes
  what is stored; the null is data, not a bug.

## Decisions

The choices that had real alternatives are in [DECISIONS.md](./DECISIONS.md):
the ETag prefix stays `v1-`; the list's `location` comes from a LEFT OUTER
JOIN on the `main` row; the empty-string storage sentinel becomes `null` at
the API boundary; `external_id` is validated by lookup, not by length.

Settled by the epic or by the user on 2026-09-16, with no alternative weighed:

- New nullable fields are declared with **no default** so they are
  required-nullable in the body, in OpenAPI and in the generated TypeScript.
- `location` is `{lat: float, lon: float, precision: "building" |
  "approximate"}`. A `main` row with `precision = 'none'`, or no row at all,
  gives `location: null`. `Decimal` → `float` conversion is explicit in
  Python.
- `branches` is every `role = 'branch'` row for the institution as
  `{label, address, location}`, ordered by `label, address` — the UNIQUE
  tuple makes that deterministic, and the surrogate `id` is reassigned on
  every loader run so it must not be used for ordering. Addressed buildings
  (`label = ""`) therefore sort before name-only ones.
- JSON key order on the detail: the existing six keys, then `address`,
  `phone`, `email`, `director`, `website`, `district_code`,
  `has_infant_group`, `location`, `branches`, and `coverage` last.
- The list gains `has_infant_group` and `location` and nothing else;
  `address` and the contacts stay detail-only.
- `has_infant_group` goes on both payloads: research §2 lists the infant
  marker as header content and frontend epic 02's directory wants it without
  parsing names.
- The by-source route reuses the id route's builder, 404 body
  (`{"error": "institution_not_found"}`), ETag and cache headers. `kind` is
  typed `Kind`, so an invalid value is FastAPI's default 422 — the same
  mechanism `/api/match`'s `kind` query parameter already uses.
- Coverage: query, grouping and ordering untouched.

## Risks

- **Collation differs between SQLite and Postgres for Cyrillic**, so branch
  order could differ between the test database and production. The
  guarantee is determinism within one database, as for coverage today; the
  fixtures use values whose order is the same under both collations.
- **The list now joins.** A second `main` row would duplicate a list item —
  prevented by `uq_institution_locations_main`; a test seeds an institution
  with a `main` and four `branch` rows and asserts it appears once, and one
  with no location row at all to prove the join is outer.
- **A missing path segment** (`/api/institutions/by-source`) falls into the
  `{institution_id}` route and returns 422. Documented in TASK-003, not a
  bug.
- **The frontend's committed `types.ts` lags the API** until frontend phase
  1.1 regenerates it. Harmless — every change is additive and today's only
  consumer of `InstitutionListItem` reads `last_seen_at` — and the final task
  proves the regeneration works.
- **A `main` row nobody could pin** shows as `location: null`; the frontend
  epic already renders that page without a map. The committed CSV currently
  has zero such rows.
- **A stale local `institution_locations` load** would make the final task's
  curls validate old coordinates or branches, and a row count cannot tell the
  difference. TASK-005 runs the idempotent loader before any curl and keeps
  its summary line as evidence.

## Acceptance Criteria

- [x] The detail response carries `address`, `phone`, `email`, `director`,
      `website`, `district_code`, `has_infant_group`, `location` and
      `branches`, with `null` (not omitted) wherever data is absent, and the
      OpenAPI schema marks each nullable field as required
- [x] `GET /api/institutions/by-source/kindergarten/46` returns ДГ№13 "Мир"
      with a building-precision `location` and its 4 `branches`, each with a
      location
- [x] For the same institution the id route and the by-source route return
      byte-identical bodies and ETags
- [x] An unknown `(kind, external_id)` returns 404
      `{"error": "institution_not_found"}`; an invalid `kind` returns 422
- [x] List items carry `has_infant_group` and `location` (`null` when there
      is no `main` row or no pin); the list's order and row count are
      unchanged
- [x] Coverage grouping and ordering are unchanged; ETags are stable across
      requests and change when a contact value, a coordinate or a branch
      changes
- [x] `search_norm`, junction-table columns, `source`, `verification`,
      `verified_at` and `role` never appear in any response or OpenAPI schema
- [x] `openapi-typescript` consumes the running backend's `/openapi.json`
      (`just fe-api-types` succeeds; the diff is captured and the file
      restored)
- [x] `just be-test` and `just be-lint` pass

## Tasks

Task state lives here. Tasks are appended by `scripts/add_task.py` and
`scripts/add_final_task.py`. Update the checkboxes as work progresses.

- [x] TASK-001: Add address, contacts, district and the infant flag to the detail response
- [x] TASK-002: Add location and branches to the detail response (depends on TASK-001)
- [x] TASK-003: Add the by-source detail route (depends on TASK-002)
- [x] TASK-004: Add the infant flag and location to the list response (depends on TASK-002)
- [x] TASK-005: Final Validation
