# TASK-002: Parse and validate the locations reference file

Depends on: TASK-001
Suggested commit: `feat(ingest): parse the institution locations reference file`

## Goal

A pure, network-free parser that turns the committed CSV into validated row
dicts, rejecting malformed and implausible rows with a message that identifies
the offending line — plus the symmetric writer every other writer of this file
(the seed script, the review tool) goes through.

## Files

- `src/yasli/ingest/institution_locations_loader.py` — the parsing half:
  `parse_file(path, provenance_path=None)` (defaults to the sibling
  `institution_locations.provenance.json`), `parse_rows(reader, provenance)`,
  `load_provenance(path)`, a `LocationRowError` exception, and
  `write_file(path, rows, provenance)` — validates the rows and provenance
  through the same checks as `parse_rows`, then writes the CSV with stdlib
  `csv`, `QUOTE_MINIMAL`, in a stable order (`kind, external_id, role, label,
  address`) and the provenance file sorted by key, each via temp + rename;
  plus `normalise_address(text) -> str` — casefold, collapse whitespace,
  map every quote character (`"` `“` `”` `„` `«` `»`) to `"`, drop spaces
  around `№`, `.` and `,` — the one comparison the loader's drift guard
  (TASK-003) and the seed script (TASK-004) both use
- `data/institution_locations.provenance.json` — one entry per `auto` row,
  keyed `"<kind>/<external_id>"`: `{"lat", "lon", "osm": "way/123",
  "amenity", "title_matches", "in_municipality", "settlement",
  "address_settlement", "geocode_distance_m", "seeded_at"}`. Written by
  the seed script and the review tool (TASK-004, TASK-005), never by hand
- `src/yasli/ingest/municipality.py` — exposes `in_varna_municipality(lat, lon)`;
  pure-Python ray casting over the (multi)polygon, no `shapely` dependency.
  The boundary path is `MUNICIPALITY_GEOJSON = REPO_ROOT / "data" /
  "varna_municipality.geojson"` with `REPO_ROOT = Path(__file__).resolve().parents[3]`
  (never CWD-relative — the CLI tests run from a temp cwd and the image's
  WORKDIR is `/app`), loaded lazily on the first call so importing the module
  never touches the disk
- `data/varna_municipality.geojson` — the committed boundary: OSM relation
  1404291 (to be confirmed, see Steps), simplified to ~100 m tolerance
- `tests/test_institution_locations_loader.py` — parser tests on literal CSV
  text, no database
- `tests/test_municipality.py` — inside/outside cases on the committed polygon

## File format

```csv
kind,external_id,role,label,address,lat,lon,precision,source,verification,verified_at
kindergarten,46,main,,"ул. ""Никола Михайловски"" №6",43.206500,27.914200,building,osm_poi,auto,2026-09-14
kindergarten,46,branch,,"ул. Н. Михайловски 1А",43.207100,27.913800,building,manual,human,2026-09-14
kindergarten,17,branch,Жирафче,,,,none,manual,human,2026-09-14
```

Read with the stdlib `csv` module, UTF-8, `QUOTE_MINIMAL`. Empty `label` and
`address` cells become `''`; empty `lat`/`lon` become `None`.

## Acceptance

- [ ] A well-formed file parses to row dicts matching the ORM column names
- [ ] An address containing a comma and doubled quotes round-trips verbatim
- [ ] A row with `lat` but no `lon` is rejected, naming the line number
- [ ] A row with `precision='none'` **and** a coordinate is rejected; so is
      `precision='building'` with no coordinate; `precision='street'` is
      rejected as an unknown value
- [ ] A coordinate outside the Varna municipality polygon is rejected, naming
      the line and the offending value — the Игнатиево and Аксаково cases from
      research §3.2
- [ ] The polygon admits the municipality's villages: points in Каменар,
      Константиново, Тополи, Казашко and Звездица (all five villages in
      `geo/settlements.py`) are inside; Игнатиево and Аксаково are outside
- [ ] `MUNICIPALITY_GEOJSON.exists()` holds and `in_varna_municipality` works
      after `os.chdir` to a temp dir — the path is anchored to the package,
      not the CWD
- [ ] An unknown `kind`, `role`, `precision`, `source` or `verification` is
      rejected, and `source=manual` with `verification=auto` is rejected
- [ ] `verification=auto` with `source=nominatim`, with `role=branch`, or with
      `precision=approximate` is rejected, naming the line — the part of the
      auto-accept rules a network-free parser can check
- [ ] An `auto` row is rejected, naming the line, when it has no provenance
      entry, when the entry's coordinate differs from the row's, or when any
      outcome fails: `title_matches != 1`, `in_municipality` false,
      `settlement != address_settlement`, `geocode_distance_m > 150`
- [ ] A provenance entry with no `auto` row (stale provenance) is rejected;
      a file with no `auto` rows parses with an empty provenance file
- [ ] `normalise_address` treats the research §3.1 variants as equal — the
      three quote styles, `№6` vs `№ 6`, trailing whitespace, case — and
      different house numbers or streets as different
- [ ] A missing or extra header column is rejected before any row is read
- [ ] A `verified_at` that is not `YYYY-MM-DD` is rejected
- [ ] A duplicate `(kind, external_id, role, label, address)` tuple is rejected
      by the parser, not left to the database
- [ ] A second `main` row for the same `(kind, external_id)` is rejected by the
      parser, naming the line, even when its `address` differs
- [ ] `write_file` round-trips: `parse_file` over what `write_file` wrote
      yields the same rows and provenance, including the
      comma-and-doubled-quotes address, and `write_file` refuses (without
      writing either file) rows `parse_rows` would reject

Evidence: `uv run pytest tests/test_institution_locations_loader.py tests/test_municipality.py -v`,
with each rejection case asserting on the error message's line number. (The
77 `main` / 15 `branch` count over the committed file is asserted in TASK-006,
where the file first exists.)

## Steps

### Prepare the boundary
- [ ] Fetch relation 1404291 (`out geom`) and confirm its tags: `admin_level=6`,
      name Варна, a municipality, not the province. If not, find the right
      relation by `boundary=administrative` + `admin_level=6` + `name=Варна`
- [ ] Convert to GeoJSON, simplify to ~100 m, commit to `data/`, and record the
      relation id, fetch date and simplification tolerance in a sibling
      `data/varna_municipality.README.md`

### RED
- [ ] Write the parser tests first, one per rejection case, using inline CSV
      strings so the fixtures are readable in the test body

### GREEN
- [ ] Implement `parse_rows` as a generator validating each row and raising
      `LocationRowError(line_no, message)`
- [ ] Implement `parse_file` as the UTF-8 decode + `csv.DictReader` wrapper,
      mirroring `grao_loader.parse_file`'s shape
- [ ] Implement `load_provenance` and the `auto`-row cross-check inside
      `parse_rows`, then `write_file` as validate-then-write for both files,
      each via a temp file and rename so a rejected batch leaves the old
      files intact

### REFACTOR
- [ ] Extract the coordinate checks into one `_validate_coordinate` helper —
      the both-or-neither rule, the precision agreement, and the bounds check
      all operate on the same two values

## Notes

The polygon replaces the research bbox (`43.13,27.78,43.30,27.99`), which is
loose enough to admit Аксаково. It is still only one of the guards: it cannot
catch a pin in the **wrong village inside the municipality**. The Константиново
case is exactly that, since Константиново belongs to Varna municipality. The
settlement-agreement rule in TASK-004 and the review in TASK-006 cover that
class; say so in the module docstring so nobody treats the polygon as proof.

Simplifying at ~100 m can misclassify a point within ~100 m of the border.
No institution is that close to it. If one ever is, the parser rejects it and
a person looks, which is the safe direction.

Reject rather than skip, throughout. `grao_loader` silently skips unrecognised
lines because it parses a 236k-row printed report where noise is expected. This
file is 92 hand-maintained rows — every anomaly is a mistake someone should see.

The duplicate check has to happen in the parser because the loader truncates
first: with an empty table, the database's UNIQUE constraint would only fire on
the second copy within the same INSERT batch, producing an opaque error instead
of a line number.
