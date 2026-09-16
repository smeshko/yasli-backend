# Research: Institution locations reference dataset

Curated findings only — no raw conversation transcripts.

## Key Files & Directories

- `src/yasli/ingest/grao_loader.py` — the model for this plan's loader:
  `parse_file` → `load(path, session)` → `main(argv)` CLI, TRUNCATE + bulk
  INSERT inside the caller's transaction, a `LoaderSummary` dataclass, and
  explicit exit codes (2 = file not found, 3 = decode failure).
- `src/yasli/models/settlement.py` + `migrations/versions/0007_settlements_reference_table.py`
  — the other reference-data precedent: a small table seeded from data embedded
  in the migration. Rejected for this plan because 89 rows are hand-edited.
- `src/yasli/models/institution.py` — `UniqueConstraint("external_id", "kind")`
  is the natural key this table joins against. `id` is a `BigInteger` serial and
  is **not** stable across a re-ingest.
- `src/yasli/geo/settlements.py` — `VARNA_SETTLEMENTS`, the six populated places
  in the municipality. Useful context for the bounds check.
- `tests/test_grao_loader.py` — the test shape to follow: pure parser tests on
  literal input, then loader tests against a SQLite in-memory session fixture
  defined in that module (`tests/conftest.py` has no shared one; the new test
  module defines its own copy).
- `src/yasli/ingest/__main__.py` — how a subcommand CLI is wired, including
  `_validate_startup_config` and the operator-readable summary line.

## Architecture Facts

- `grao_addresses` stores `number_suffix` and `entrance` as the **empty string**
  rather than NULL, so composite-key NOT NULL constraints hold without losing
  the "absent" meaning. Reuse that convention for `label` and `address` if they
  participate in a uniqueness constraint.
- The loader pattern deliberately takes a local path, not a URL — file
  acquisition is the operator's job. Here the file is committed, so the CLI
  defaults to the in-repo path and accepts an override.
- `just be-ingest` (the weekly cron) must **not** invoke this loader.
  Coordinates change roughly never; conflating them with the weekly snapshot
  would make a network failure in a reference load break the routing refresh.
- The root `justfile` is at `yasli/justfile`, outside all three git repos. No
  phase can commit a recipe. Verified 2026-08-17: `backend/`, `scraper/` and
  `frontend/` have no justfile of their own.

## Measured Source Facts (2026-08-17)

From `INSTITUTION_DETAIL_MAP_RESEARCH.md`:

**Address shapes (§3.1)** — 22/77 are block-relative (`ж.к. "Младост" до бл.127`),
5/77 contain no number at all (`с.Каменар`), and the rest mix quote styles
(`"` `“` `„`) with `№` glued to digits.

**Nominatim pass over all 77 (§3.2)**:

| Outcome | Count |
| --- | --- |
| No usable hit | 17 |
| `place_rank` 30 (building / POI) | 16 |
| `place_rank` 26–27 (street centroid) | 35 |
| `place_rank` 16–19 (suburb / village centroid) | 6 |

**At least 3 of the 60 hits are confidently wrong**:
`бул. "Чаталджа" 111` → Игнатиево (Аксаково); `кв. Виница, ул. "Лазур" №2` →
Константиново; `ж.к."Владислав Варненчик" до бл.20` → Аксаково.

**Correction (2026-09-14):** only two of these are in a different municipality.
Nominatim resolves Константиново as `Константиново, Варна` and Игнатиево as
`Игнатиево, Аксаково, Варна`, so Константиново is a village **inside** Varna
municipality. A municipality polygon catches Игнатиево and Аксаково. Catching
Константиново takes a settlement check: the address names кв. Виница, which is in
the city, and the pin is in a village. Candidate boundary: OSM relation 1404291
(Nominatim `state_district`, bbox 43.10–43.31 N, 27.74–28.06 E), still to be
confirmed as `admin_level=6` in TASK-002.

Query normalisation matters more than the geocoder: leaving `ул.`/`бул.` in the
query returns **zero** results for every address; stripping it resolves cleanly.

**OSM POI matching (§3.3)** — Overpass over bbox `43.13,27.78,43.30,27.99` with
`amenity ∈ {kindergarten, childcare, nursery, school}` returns 158 objects, 137
named. Matching by the **quoted title** (`ДГ№4 "Теменужка"` → OSM `Теменужка`)
gives **53/77** at building precision. Matching by number gives only 7/53 —
OSM names kindergartens by title, not number.

Union of rank-30 geocodes and POI matches ≈ **57/77 automatic, 20 manual**. The
plan now auto-accepts only POI matches that pass the polygon, settlement and
agreement rules. Geocoder-only hits always go to review, so expect ~45–53 `auto`
and ~25–35 flagged rows, including all 15 branches.

**Branch inventory (§1.3)** — 15 rows across 8 kindergartens, from
`POST /lv/api/free-places {"reception":"garden"}` (70 data rows total, 15
containing "филиал"). `infant` returns 0 филиали, `pg` returns 0, `jasla`
returns `SPR_SWOBODNI_MESTA: null`. So this is an 8-kindergarten problem, not a
system-wide one.

| Parent | Branch label | Address |
| --- | --- | --- |
| ДГ№1 "Светулка" | — | ул. "Жолио Кюри" №51, вх.Г, ет.1, ап.3 |
| ДГ№2 "Щастливо детство" | — | ул. "Батак" №6 |
| ДГ№2 "Щастливо детство" | — | ул. "Батак" №8 |
| ДГ№5 "Слънчо" | — | ул. "Патриарх Евтимий" №52 |
| ДГ№5 "Слънчо" | — | ул. "Яне Сандански" №1 |
| ДГ№12 "Ян Бибиян" | — | "Добруджа" №1 |
| ДГ№13 "Мир" | — | ул. Н. Михайловски 1А |
| ДГ№13 "Мир" | — | ул. Тодор Икономов 26 |
| ДГ№13 "Мир" | — | ул. Тодор Икономов 36 |
| ДГ№13 "Мир" | — | бул. Княз Борис I, 109 |
| ДГ№17 "Петър Берон" | "Жирафче" | **none** |
| ДГ№17 "Петър Берон" | „Другарче“ | **none** |
| ДГ№18 "Чайка" | "Бисерче" | **none** |
| ДГ№39 "Приказка" | — | ж.к. Владислав Варненчик II м.р., бл.209 |
| ДГ№39 "Приказка" | — | ж.к. Владислав Варненчик II м.р., бл.210 |

The trap in ДГ№13's case: its own address is ул. Никола Михайловски **№6** and
one branch is ул. Н. Михайловски **1А** — same street, different building. A
single pin is not wrong, just incomplete.

The row text is free-form and inconsistent (`филиал` / `Филиал`, `- ` vs ` на `
vs ` в `, quotes glued to names) — parsing it is a real normalisation job.

## Constraints

- **Geocoder output is never accepted without review.** All three measured wrong
  pins came from Nominatim. OSM POI title matches may be auto-accepted, but
  only when they are unique, inside the municipality polygon, in the settlement
  the address names, and agree with any rank-30 geocode. Everything else goes to
  the review tool.
- Nominatim usage policy: ~1 req/s, a real `User-Agent`, no bulk geocoding.
- Public Overpass (`overpass-api.de`) returns 504 on the street query; the
  `amenity` query works. Use `overpass.kumi.systems` as a mirror when needed.
- `verified_at` is the date a row was decided: the seed run for
  `verification=auto`, the review for `verification=human`.
- The seed script must never run in CI or in tests — it makes live network
  calls to three third-party services.

## Useful Commands

```bash
# Branch inventory (HTML table inside JSON)
curl -sS -X POST 'https://dg.uslugi.io/lv/api/free-places' \
  -H 'Content-Type: application/json' -d '{"reception":"garden"}'

# Education POIs in Varna
cat > q.overpass << 'EOF'
[out:json][timeout:90];
(
  node["amenity"~"^(kindergarten|childcare|nursery|school)$"](43.13,27.78,43.30,27.99);
  way["amenity"~"^(kindergarten|childcare|nursery|school)$"](43.13,27.78,43.30,27.99);
  relation["amenity"~"^(kindergarten|childcare|nursery|school)$"](43.13,27.78,43.30,27.99);
);
out tags center;
EOF
curl -sS 'https://overpass-api.de/api/interpreter' --data-urlencode "data@q.overpass" \
  -H 'User-Agent: yasli-research/1.0'

# Geocode one address — note the ул./бул. stripping
curl -sSG 'https://nominatim.openstreetmap.org/search' \
  --data-urlencode 'q=Шейново 18, Варна' --data 'format=jsonv2&limit=2' \
  -H 'User-Agent: yasli-research/1.0'

# Load and verify. `just db-psql` is interactive and takes no arguments, so
# one-shot queries go through docker compose from the yasli/ parent, where
# docker-compose.yml lives.
uv run python -m yasli.ingest.institution_locations_loader   # default: data/institution_locations.csv
(cd .. && docker compose exec -T postgres psql -U yasli -d yasli \
  -c "SELECT role, precision, count(*) FROM institution_locations GROUP BY 1,2 ORDER BY 1,2")
(cd .. && docker compose exec -T postgres psql -U yasli -d yasli \
  -c "SELECT i.kind, i.external_id, i.name FROM institutions i \
  LEFT JOIN institution_locations l ON l.kind=i.kind AND l.external_id=i.external_id AND l.role='main' \
  WHERE l.kind IS NULL")
```

## Uncertainty

- **Varna municipality bounds for the rejection check.** Revised 2026-09-14. A
  bbox loose enough for the villages also admits Аксаково, so a bbox cannot
  separate them. Resolved: a committed, simplified municipality polygon (OSM
  relation 1404291, to be confirmed) as the hard reject, plus the
  settlement-agreement rule for wrong-village pins inside the municipality
  (Константиново). Rows that fail either go to the TASK-005 review tool.
- **The Overpass bbox may clip the municipality.** The research bbox
  `43.13,27.78,43.30,27.99` is narrower than the municipality's
  (43.10–43.31 N, 27.74–28.06 E), so village POIs near the edges (for example
  Казашко to the west) could be missed. TASK-004 should query the
  municipality bbox and let the polygon filter.
- **Whether `precision` should be an enum CHECK or free text.** Resolved: CHECK
  constraint, matching `ck_institutions_district_code`. The value drives
  presentation in frontend epic 01, so an unconstrained string would leak typos into UI
  logic.
- **How to key branch rows uniquely.** Resolved: surrogate serial PK plus a
  UNIQUE over `(kind, external_id, role, label, address)` with `label` and
  `address` stored as `''` when absent — the `grao_addresses` convention. The
  loader truncates, so this is a data-quality guard rather than an upsert key.
- **Table name.** Research §3.4 proposed `institution_coordinates`; the epic
  specifies `institution_locations`. Resolved: follow the epic — the table holds
  buildings with labels and addresses, not just coordinates.

## References

- `../openspec/docs/INSTITUTION_DETAIL_MAP_RESEARCH.md` (the `yasli/` parent) §1.3 (branch inventory),
  §3 (coordinates, with the failure modes), §10 (reproducible commands)
- `../openspec/docs/NURSERY_RESEARCH.md` §2.2 — OSM nursery coordinates by number,
  and why that key does not work for kindergartens
- `docs/artifacts/epics/01-institution-data-foundation.md` — phase 1.2
- `src/yasli/ingest/grao_loader.py` — the loader precedent
- `docs/OPERATIONS.md` — the ГРАО quarterly refresh entry this plan mirrors
