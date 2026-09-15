# Plan: Institution locations reference dataset

Status: in-progress
Branch: feature/yas-7-institution-locations-dataset
Risk: large
Epic: 01 — Institution data foundation ([epic](../../epics/01-institution-data-foundation.md))
Phase: 1.2 — Institution locations reference dataset
Linear: YAS-7
Created: 2026-08-17
Revised: 2026-09-14 — replaced "hand-verify all 77" with tiered auto-accept + a review tool

## Goal

Coordinates for all 77 institutions and the 12 addressed branch buildings load
into the database from a committed CSV file. Rows that pass strict automatic
checks are accepted without a human; the rest are resolved by a person in a
local review page. The loader is idempotent and fails loudly on data it cannot
attribute.

## Scope

- `institution_locations` table + Alembic `0010`.
- A committed CSV at `data/institution_locations.csv`, one row per building:
  `kind, external_id, role, label, address, lat, lon, precision, source,
  verification, verified_at`.
- A committed Varna municipality boundary at `data/varna_municipality.geojson`,
  used by the parser as a hard reject.
- A committed provenance file `data/institution_locations.provenance.json`:
  one entry per `auto` row recording the OSM identity and the four rule
  outcomes, written by the seed script and cross-checked by the parser.
- A parser/validator module with a symmetric CSV writer, and an idempotent
  TRUNCATE + bulk-INSERT loader with its own CLI, modelled on
  `ingest/grao_loader.py`.
- A committed one-off seeding script that gathers candidates (OSM POI title
  match, rank-30 geocode), applies the **auto-accept rules**, and flags the
  rest for review, plus the branch inventory from `/lv/api/free-places`.
- **A local review tool** — a stdlib HTTP server plus a single HTML page with a
  map — for resolving flagged rows one at a time, writing decisions straight
  back to the CSV through the parser.
- A review pass over the **flagged** rows only (~25–35 expected), not all 92.
- An OPERATIONS.md runbook entry for the manual refresh cadence.

## Out of Scope

- Exposing locations through the API — phase 1.3.
- Any map rendering in the product — frontend epic 01. The review tool is an internal
  dev tool, never deployed and never linked from the app.
- District polygons and the region overlay — frontend phase 1.2.
- Street-level catchment geometry. Ruled out on measured grounds
  (`INSTITUTION_DETAIL_MAP_RESEARCH.md` §5); the catchment stays a text list.
- Geocoding arbitrary user-searched addresses. Ruled out in §5.1.
- Free-places data as a runtime read — backend epic 02 (free-places API). This plan reads that endpoint
  **once**, offline, purely to seed the branch inventory.

## Research Summary

See [RESEARCH.md](./RESEARCH.md). The short version:

- **Geocoding alone cannot be trusted here.** A full Nominatim pass over the 77
  institutions returned 60 hits, only 16 at house precision, and at least 3
  confidently wrong: `бул. "Чаталджа" 111` → Игнатиево (Аксаково municipality),
  `ж.к."Владислав Варненчик" до бл.20` → Аксаково, and `кв. Виница, ул. "Лазур"
  №2` → Константиново.
- **Two of those three are caught automatically by a municipality polygon; the
  third is not.** Константиново is a village *inside* Varna municipality
  (re-checked 2026-09-14), so catching it takes a second rule: the settlement
  the pin falls in must agree with the settlement the source address names.
- OSM POI title-matching gets 53/77 at building precision. Those matches are
  the auto-accept candidates; geocoder-only hits always go to review.
- Branches are a **kindergarten-only** phenomenon: 8 kindergartens, 15 branch
  buildings. 12 have an address; 3 ("Жирафче", "Другарче", "Бисерче") are
  name-only and cannot be pinned from any source we have.
- The branch inventory's only source is `/lv/api/free-places`, an artifact of
  the classification cycle — wrong to depend on at runtime, fine to seed from
  once.

## Decisions

- **Tiered verification instead of checking every row by hand.** A row is
  auto-accepted only when *all* of these hold:
  1. it is a **unique** OSM POI title match within the kind's amenity family
     (the `kind → amenity` table in TASK-004);
  2. the POI is inside the Varna municipality polygon;
  3. the POI's settlement (reverse-geocoded) agrees with the source address —
     a named village (`с.Каменар`) must match; an address naming no village must
     resolve to the city of Varna;
  4. if a rank-30 Nominatim hit also exists, the two are ≤150 m apart.
  Everything else — geocoder-only hits, ambiguous titles, disagreements, no
  candidate, all branch rows — is flagged for the review tool with its reasons.
  Flags are per row and any flag forces review. A candidate outside the
  polygon stays in the row's candidate list so the reviewer can see what the
  geocoder did, but it can never be accepted, and rule 4 compares in-polygon
  candidates only.
  **Why:** the measured failure is confidently wrong pins, and the 3 measured
  wrong results were all geocoder hits that rules 2–4 reject. Checking 53 unambiguous
  POI matches by hand buys very little.
- **`verification` column (`auto` | `human`)** records how each row was
  decided, separately from `source` (where the coordinate came from). A POI pin
  a person confirmed is `osm_poi` + `human`; a pin a person placed is
  `manual` + `human`. `auto` is only ever `source=osm_poi`, `role=main`,
  `precision=building` — the parser and a CHECK constraint enforce that. The
  four rules themselves cannot be re-run by the parser (they need the
  network), so every `auto` row carries a committed **provenance entry** —
  OSM id and amenity, the title-match count, the polygon result, the
  reverse-geocoded settlement next to the address's, the rank-30 distance —
  and the parser rejects an `auto` row without a matching, all-pass entry. A
  forged `auto` row therefore fails to parse, and a reported bad pin can be
  audited from the repo alone. The entries are self-attested; see Risks.
- **The municipality polygon replaces the bbox as the parser's hard reject.**
  The bbox admitted Аксаково; the polygon does not. The polygon is committed
  data (OSM relation, simplified), so parsing stays network-free.
- **Unresolved rows ship without a pin, not with a guess.** A `main` row nobody
  could pin carries `precision=none`. The loader reports those rows by name, and
  frontend epic 01 renders the page without a map. Target is zero, but a blank never
  blocks the phase.
- **The review tool is a local server, not a static page.** It reads the
  candidates, writes the CSV directly through the loader's `write_file`, and
  shows parser errors inline. No download-then-copy step, and the tool can never save a
  file the loader would reject. Stdlib `http.server` only — no new dependency.
- **Review state lives in the candidates file** (`data/institution_locations.candidates.json`,
  gitignored). It holds every candidate, the flag reasons and each row's
  decision. Within a session it is the commit point: every save writes it
  atomically (temp + rename), then regenerates the CSV and the provenance
  file from it. Across sessions the **committed CSV and provenance file are
  the record**: the candidates file stores the hash of the files it last
  regenerated, and on startup or a seed re-run a matching hash means it is
  in sync or ahead (a crash between the writes) and regenerates; a mismatch,
  or no candidates file at all (a fresh checkout), rebuilds every decision
  from the committed files and keeps only candidates and flags from local
  state. A stale local file can never revert a newer committed one, a fresh
  checkout loses nothing, closing the tab loses nothing, and re-running the
  seed script keeps human decisions.
- **Only decided rows are written to the CSV** — `auto`, `accepted`, `pinned`
  and `no_pin`. A `pending` row is simply absent, and the loader's
  missing-`main` count is what surfaces it. `human` therefore always means a
  person decided; a pending row is never disguised as a `no_pin`. The seed
  script and the review tool write the file through the same renderer, so a
  seed re-run never drops a human decision.
- **CSV, not JSON or a Python module**, for the committed artifact: it is
  reviewed in a PR diff. Written and read with stdlib `csv`, `QUOTE_MINIMAL`.
- **Join key is `(kind, external_id)`, never the DB serial `id`.**
- **Exactly one `main` row per institution.** A partial unique index over
  `(kind, external_id)` where `role = 'main'` enforces it in the database, and
  the parser rejects a second `main` with a line number, so a duplicate never
  reaches the loader. Branch rows stay many-per-institution.
- **The loader fails loudly, before TRUNCATE, on an unmatched
  `(kind, external_id)`, on any institution without a `main` row, and on a
  `main` row whose address no longer matches the institution's.** The weekly
  ingest overwrites `institutions.address`, so a moved institution with its
  old pin is exactly the wrong pin that looks right; addresses are compared
  through one normaliser (quote styles, `№` spacing, case, whitespace). A
  partial or lagging file — a half-finished review, a CSV predating a newly
  ingested institution or an address change — never replaces a complete
  table. `--allow-incomplete` ("the CSV lags the institutions table") opts out
  of the second and third guard for local loads only, never the first;
  `--dry-run` runs all three guards and prints the summary without touching
  the table. Deliberate blanks are still explicit `no_pin` rows
  (`precision=none`), which count as present.
- **Name-only branches are stored with a label and NULL coordinates**, not
  dropped.
- **`precision` and `source` are per-row and mandatory.** `precision` ∈
  `building | approximate | none`; `source` ∈ `osm_poi | nominatim | manual`.
  `street` was dropped: rank 26–27 geocodes are discarded, so nothing can
  produce it. `approximate` is chosen by the reviewer for a hand-placed pin
  that marks a block rather than a building.
- **TRUNCATE + bulk INSERT inside one transaction**, mirroring `grao_loader`.
- **Committed data is resolved relative to the package, never the CWD.** The
  CSV and polygon defaults are anchored to the repo root via `Path(__file__)`,
  and the Dockerfile copies `data/` into the image, so the loader runs either
  from a Railway exec shell (as the ГРАО runbook does) or from a checkout
  against a tunnelled `DATABASE_URL`. Today the image copies only `src/` and
  `migrations/`.
- **Script layout.** `scripts/seed_institution_locations.py` and
  `scripts/review_locations.py` are entry points run as
  `python -m scripts.<name>` from the repo root; shared pure helpers live in
  the `scripts/location_review/` package (not `review_locations/`, which
  would collide with the module of the same name). `scripts/__init__.py` plus
  pytest `pythonpath = ["."]` let tests import them; CI's `ruff check .`
  already lints `scripts/`.
- **The seeding script and review tool are committed but are not a maintained
  pipeline.** The committed CSV is the artifact of record.
- **The `just` recipe is a local convenience, not part of the PR.** The root
  `justfile` lives in the `yasli/` parent, outside all three git repos.
  TASK-007 still adds a `be-load-locations` recipe there, because the epic
  asks for one, and the runbook names it.

## Risks

- **An auto-accepted pin can still be wrong.** For example, an OSM POI tagged at
  the wrong building, or a title shared by an institution outside our list that
  happens to be unique in the bbox. Mitigations: the uniqueness and settlement
  rules; the review tool's "auto-accepted" filter for a spot-check of ~5 rows in
  TASK-006; and `verification=auto` staying visible so a reported bad pin can be
  traced to the rule that let it through.
- **Provenance is self-attested.** The provenance file is written by the same
  seed script as the CSV, so the parser's cross-check proves consistency and
  gives auditability, not that OSM was right: a forged *pair* (CSV row plus a
  matching all-pass entry) would parse. Mitigations: the CHECK and parser
  rule that `auto` is always `osm_poi` + `main` + `building` (which rules out
  every measured failure mode, all geocoder hits); the seed script and review
  tool are the only writers; both files are reviewed in the PR diff;
  `verified_at` dates each row; the TASK-006 spot-check.
- **Settlement agreement depends on reverse geocoding**, which adds ~1 req/s of
  Nominatim calls for ~53 POIs (~1 min). If reverse geocoding fails for a row,
  that row is flagged, never auto-accepted.
- **Relation 1404291 is not yet confirmed as the municipality boundary.**
  Nominatim labels it `state_district`, but its bbox (43.10–43.31 N,
  27.74–28.06 E) is municipality-sized, not province-sized. TASK-002 confirms
  `admin_level` and that Каменар, Константиново, Тополи, Казашко and Звездица
  (the five villages in `geo/settlements.py`) fall inside while Игнатиево and
  Аксаково fall outside.
- **The seed script depends on three external services** (Overpass, Nominatim,
  `dg.uslugi.io`) with rate limits and observed 504s. Use the kumi Overpass
  mirror; ~1.1 s Nominatim spacing with a real User-Agent. Resumable, never a
  build or test dependency.
- **The branch inventory is seasonal.** If the live fetch returns fewer than
  the 15 branch rows measured on 2026-08-17, fall back to the table in research
  §1.3 and say so.
- **The loader runs after ingest, not with it.** An institution added by a future
  ingest has no location row until someone refreshes this file, and an
  institution whose address changed keeps its old pin; the next loader run
  (or `--dry-run`) aborts on the missing `main` or the address drift until
  the row is re-reviewed, and the runbook's trigger list covers both.

## Acceptance Criteria

- [ ] All 77 institutions have a `main` row, and no institution has two: a
      second `main` for the same `(kind, external_id)` is rejected by the parser
      with its line number, and by the database
- [ ] Every coordinate is inside the Varna municipality polygon, and each row is
      either `verification=auto` (with a committed provenance entry recording
      that all four rules passed) or `verification=human` (resolved in the
      review tool)
- [ ] The three measured geocoder failures do not appear as pins: Игнатиево and
      Аксаково are rejected by the polygon, Константиново by the settlement rule
- [ ] `main` rows without a coordinate are listed by name in the loader summary
      (target: 0)
- [ ] The 12 branch buildings that have an address have a `branch` row; the 3
      name-only branches are present with a label and NULL coordinates
- [ ] Every row records `precision`, `source` and `verification`
- [ ] Every `verification=auto` row is `source=osm_poi`, `role=main` and
      `precision=building`; the parser and the database reject anything else
- [ ] An `auto` row without a matching, all-pass provenance entry is rejected
      by the parser with its line number
- [ ] The review tool loads the candidates, shows flagged rows on a map with
      their reasons, and a decision made in it lands in the CSV and passes the
      parser
- [ ] Running the loader twice leaves the table in the same observable state
- [ ] The loader fails loudly on a row whose `(kind, external_id)` has no
      matching institution
- [ ] The loader aborts, before TRUNCATE and naming the institutions, when any
      institution has **no** `main` row, unless `--allow-incomplete` is passed;
      either way the summary reports the count (expected: 0)
- [ ] The loader aborts, before TRUNCATE and naming the institution, when a
      `main` row's address differs (normalised) from the institution's current
      address, unless `--allow-incomplete` is passed; a seed re-run returns
      such a row to review flagged `address_changed`
- [ ] Starting the review tool with a stale candidates file, or re-running the
      seed script on a fresh checkout, rebuilds decisions from the committed
      files and never reverts them
- [ ] A row with a coordinate outside the municipality polygon is rejected by
      the parser, with the offending row identified
- [ ] `just be-test` and `just be-lint` pass

## Tasks

Task state lives here. Update the checkboxes as work progresses.

- [x] TASK-001: Add the institution_locations table
- [x] TASK-002: Parse and validate the locations reference file (depends on TASK-001)
- [x] TASK-003: Load the reference file idempotently via a CLI (depends on TASK-002)
- [x] TASK-004: Seed candidates and apply the auto-accept rules (depends on TASK-002)
- [x] TASK-005: Build the location review tool (depends on TASK-004)
- [x] TASK-006: Review flagged rows in the review tool (depends on TASK-005)
- [ ] TASK-007: Document the manual refresh cadence (depends on TASK-006)
- [ ] TASK-008: Final Validation
