# Epic 01 — Institution data foundation

Status: in progress
Created: 2026-08-17
Depends on: none
Project: none
Linear: none
Milestone: none

## Overview

Make the API able to fully describe a single institution — where it is, how to
reach it, and which buildings it occupies — so a detail page has something to
render. Nothing here is user-visible on its own. Two of the phases are plumbing
for data we already touch and throw away: the source portal's
`/lv/api/childhood` response carries phone, e-mail, director and website for all
95 rows and the scraper keeps only `ADDRESS`. The locations phase adds the one
thing no source gives us — coordinates — as a curated reference dataset, because
geocoding measurably cannot be trusted here: strict rules auto-accept the safe
rows and a review tool puts the rest in front of a person.

Cross-repo ordering is load-bearing: both the scraper and the backend validate
the snapshot with `extra="forbid"`, so the backend must accept the new fields
(phase 1.1) **before** the scraper starts emitting them
([scraper epic 01](../../../../scraper/docs/artifacts/epics/01-contact-metadata.md),
phase 1.1), or ingest rejects the snapshot outright.

## Architecture references

- [INSTITUTION_DETAIL_MAP_RESEARCH.md](../../../../openspec/docs/INSTITUTION_DETAIL_MAP_RESEARCH.md) — the measurements this epic is built on: field coverage per reception (§1), the branch inventory (§1.3), why coordinates must be curated (§3), and the impact surface (§8)
- [ARCHITECTURE.md](../../../../openspec/docs/ARCHITECTURE.md) — the scraper → R2 → ingest → API pipeline these phases extend
- [PRD.md](../../../../openspec/docs/PRD.md) — FR-11/FR-12 describe the profile-page data contract this epic serves
- [NURSERY_RESEARCH.md](../../../../openspec/docs/NURSERY_RESEARCH.md) — the `jasla` source shape and the `RAJON_ID` → district mapping
- [institutions-endpoint spec](../../../../openspec/specs/institutions-endpoint/spec.md) — the current response contract, including the "exactly these keys" guarantees that phase 1.3 changes

## Dependencies

- none within this repo
- Phase 1.3 validates end to end only once scraper epic 01 (phase 1.1) has shipped real contact data

## Out of scope

- Emitting the contact fields from the scraper — [scraper epic 01](../../../../scraper/docs/artifacts/epics/01-contact-metadata.md).
- Any frontend work — [frontend epic 01](../../../../frontend/docs/artifacts/epics/01-institution-detail-page.md).
- The free-places live read — [backend epic 02](./02-free-places-api.md).
- Publishing anything derived from `/lv/api/new-public-last-rating` (per-application classification data). Deliberately excluded pending a privacy call; see research §1.2.
- Street-level catchment geometry. Ruled out on measured grounds (research §5); the catchment stays a text list.
- Backfilling OpenSpec specs. The project is moving off OpenSpec, so the response-shape contract lives in phase 1.3's acceptance criteria and its tests instead of in a spec delta.

## Phase 1.1 — Persist source contact metadata

**Plan**: [institution-contact-fields-contract](../plans/archive/2026-09-14-institution-contact-fields-contract/PLAN.md) · status: done

**Linear**: none

**Goal**: The backend accepts and stores phone, e-mail, director and website on institutions, tolerating snapshots that omit them.

### What to build

- Extend `src/yasli/snapshot_contract/models.py` `Institution` with optional `phone`, `email`, `director`, `website` (all `str | None = None`, same non-empty-or-null validator style as `address`). Optional-with-default is what makes the old snapshot still valid.
- Add the matching nullable columns to `src/yasli/models/institution.py` plus an Alembic migration under `migrations/`.
- Map the new fields in `src/yasli/ingest/pipeline.py` where `address` is already mapped.
- Update the snapshot-contract fixtures/tests under `tests/` so both a snapshot with the fields and one without pass.

### Acceptance criteria

- [x] Ingesting the **current** production snapshot (no new fields) succeeds unchanged and leaves the new columns NULL
- [x] Ingesting a snapshot that carries all four fields stores them verbatim
- [x] An empty-string value is rejected or normalised to NULL, never stored as `""`
- [x] `GET /api/institutions` and `GET /api/institutions/:id` responses are byte-identical to before — no field leaks out yet
- [x] `just be-test` and `just be-lint` pass

### Validation

Run `just be-migrate` then `just be-ingest` against the real R2 snapshot and show the ingest summary plus a `SELECT count(*) FROM institutions WHERE phone IS NOT NULL` (expected: 0, because the scraper doesn't emit them yet). Then ingest a hand-edited local snapshot with the fields present and show the same count non-zero.

---

## Phase 1.2 — Institution locations reference dataset

**Plan**: [institution-locations-dataset](../plans/institution-locations-dataset/PLAN.md) · status: planned

**Linear**: none

**Goal**: Coordinates for all 77 institutions and the 12 addressed branch buildings load into the database from a committed file. Rows that pass strict automatic checks are accepted; only the rest are reviewed by a person, in a local map review tool.

### What to build

- A committed reference file in the backend repo (one row per building: `kind`, `external_id`, `role` = `main` | `branch`, `label` for branches, `address`, `lat`, `lon`, `precision`, `source`, `verification` = `auto` | `human`, `verified_at`).
- A committed Varna municipality boundary polygon (OSM), used as a hard reject.
- A seed script that gathers candidates (OSM POI title match, rank-30 geocode) and **auto-accepts** a row only if: the POI title match is unique; the POI is inside the municipality polygon; its settlement agrees with the address (village vs. city); and it is within 150 m of any rank-30 geocode. Everything else — geocoder-only hits, disagreements, blanks, all branches — is flagged for review with its reasons. Geocoder output is never auto-accepted: all 3 measured wrong pins were geocoder hits (research §3.2). The polygon catches 2 of them; Константиново is inside the municipality, so the settlement rule catches the third.
- **A local review tool**: a stdlib server plus a single HTML page with a Leaflet map. It shows a worklist of flagged rows with plain-language reasons, candidate pins, the municipality outline and the source address. Keyboard actions: accept a candidate, click or drag to place a pin, mark no pin, undo. Each decision is saved straight to the CSV through the parser, and the review can be resumed.
- A review pass over the flagged rows only (~25–35 expected, ~20–40 minutes), plus a spot-check of 5 auto-accepted rows.
- A `institution_locations` table plus a loader module with its own CLI, modelled on `src/yasli/ingest/grao_loader.py` — TRUNCATE + bulk INSERT, idempotent, same observable state on re-run.
- A `justfile` recipe to run the loader, and a note in the backend docs on the manual refresh cadence (mirroring the ГРАО quarterly-refresh convention).
- Join key is `(kind, external_id)`, never the DB serial id — the serial is not stable across a re-ingest.

### Acceptance criteria

- [ ] All 77 institutions have a `main` row; every coordinate is inside the Varna municipality polygon and is either auto-accepted by the rules above or resolved by a person in the review tool
- [ ] The 3 measured geocoder failures (research §3.2) are not shipped as pins
- [ ] `main` rows nobody could pin carry no coordinate and are listed by name in the loader summary (target: 0) — a blank, never a guess
- [ ] The 12 branch buildings that have an address have a `branch` row; the 3 name-only branches ("Жирафче", "Другарче", "Бисерче") are present with a label and a NULL coordinate, not silently dropped
- [ ] Every row records `precision`, `source` and `verification`, so a later pass can tell an auto-accepted pin from a human-reviewed one
- [ ] The review tool shows flagged rows on a map with their reasons, and a decision made in it lands in the committed CSV and passes the parser
- [ ] Running the loader twice leaves the table in the same state
- [ ] The loader fails loudly on a row whose `(kind, external_id)` has no matching institution
- [ ] `just be-test` and `just be-lint` pass

### Validation

Run the loader against a fresh database and show the row counts by `role`, `precision` and `verification`; a screenshot of the review tool with the worklist empty; plus a spot check of five known institutions against their source `ADDRESS`. Include the ДГ№13 "Мир" case (1 main + 4 branches) as evidence branches load.

---

## Phase 1.3 — Expose the enriched institution profile

**Plan**: [institution-profile-endpoint](../plans/institution-profile-endpoint/PLAN.md) · status: planned

**Linear**: none

**Goal**: The institution detail endpoint returns address, contacts, district, coordinates and branches, and is addressable by (kind, external_id).

### What to build

- Extend the `GET /api/institutions/{institution_id}` response with `address`, `phone`, `email`, `director`, `website`, `district_code`, `location` (lat/lon/precision or null) and `branches` (label, address, location or null).
- Add `GET /api/institutions/by-source/{kind}/{external_id}` returning the same payload, so the frontend can address a page by a stable key instead of a DB serial. 404 semantics match the existing detail route.
- Add `location` to the list endpoint only if frontend epic 01 needs it for the browse view; otherwise leave the list response alone.
- Update the tests that assert the response contains **exactly** a fixed set of keys — they will fail by design, and updating them is where the new contract gets pinned down.
- Keep the existing ETag/cache-header behaviour and the deterministic coverage ordering intact.

### Acceptance criteria

- [ ] The detail response carries every new field, with `null` (not omitted) where data is absent
- [ ] `GET /api/institutions/by-source/kindergarten/46` returns ДГ№13 "Мир" with its 4 branches
- [ ] An unknown `(kind, external_id)` returns 404 with the same error body shape as the id route; an invalid `kind` returns 422
- [ ] Coverage grouping and ordering are unchanged, and the ETag still changes only when the payload does
- [ ] `search_norm` and junction-table columns still never appear in a response
- [ ] `just be-test` and `just be-lint` pass

### Validation

`curl` both routes for one kindergarten with branches, one nursery (district-routed, empty coverage) and one preschool, and show the payloads. Regenerate the frontend's `src/lib/api/types.ts` via `just fe-api-types` against the local backend to prove the OpenAPI schema is consumable — frontend epic 01 depends on it.

---

<!-- PHASES -->

## Epic-level acceptance criteria

- [ ] Every phase merged and its acceptance criteria met
- [ ] A single API call returns everything a detail page needs for any of the 77 institutions
- [ ] The coordinate dataset is reproducible: the seeding script and review tool are committed, and the auto-accept rules and review step are documented
- [ ] Status row in [EPICS.md](./EPICS.md) updated to `Done`
