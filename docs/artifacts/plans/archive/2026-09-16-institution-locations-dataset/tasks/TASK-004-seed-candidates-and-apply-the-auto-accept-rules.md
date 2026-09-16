# TASK-004: Seed candidates and apply the auto-accept rules

Depends on: TASK-002
Suggested commit: `feat(scripts): seed institution location candidates`

## Goal

A committed one-off script that gathers every coordinate candidate for every
building, auto-accepts the rows that pass the plan's four rules, and flags the
rest with plain-language reasons. Its output is the candidates file the review
tool (TASK-005) opens, plus the CSV of every decided row and the provenance
file for the `auto` ones — on a first run that is only the `auto` rows; on a
re-run it also carries every human decision kept from the previous
candidates file.

## Files

- `scripts/__init__.py` — makes `scripts/` importable as a package (tests and
  `python -m` both need it)
- `scripts/seed_institution_locations.py` — the script, run as
  `uv run python -m scripts.seed_institution_locations` from the repo root
- `scripts/location_review/__init__.py` + `scripts/location_review/state.py`
  — `render_csv_rows(entries) -> (rows, provenance)`: the decision → CSV row
  mapping (the table in TASK-005) plus the provenance entry for each `auto`
  row, created here because the seed script writes the same files the
  review tool does. TASK-005 adds `build_state` and `apply_decision` to it.
  Named `location_review`, not `review_locations`: a package with the same
  name as the sibling `review_locations.py` module would be un-importable
- `src/yasli/ingest/institution_locations_loader.py` — write the CSV through
  its `write_file` (TASK-002) so the script cannot emit a file the loader
  would reject
- `pyproject.toml` — add `pythonpath = ["."]` under `[tool.pytest.ini_options]`
  so tests can `import scripts.…`; nothing else changes (`testpaths` keeps
  `scripts/` out of collection, and CI's `ruff check .` already lints it, so
  the scripts must pass lint)
- `src/yasli/ingest/municipality.py` — the polygon check from TASK-002
- `tests/test_seed_institution_locations.py` — tests for the **pure** helpers
  only: title extraction, name matching, address normalisation, settlement
  extraction, the auto-accept decision, branch-row parsing
- `scripts/fixtures/` — captured Overpass, Nominatim and free-places responses
- `.gitignore` — add `data/institution_locations.candidates.json`

## Candidates file

`data/institution_locations.candidates.json` is the review tool's working state.
One entry per building:

```json
{
  "key": {"kind": "kindergarten", "external_id": "46", "role": "main",
          "label": "", "address": "ул. \"Никола Михайловски\" №6"},
  "name": "ДГ№13 \"Мир\"",
  "address_settlement": null,
  "candidates": [
    {"source": "osm_poi", "lat": 43.2065, "lon": 27.9142, "osm": "way/123",
     "osm_name": "Мир", "amenity": "kindergarten", "title_matches": 1,
     "settlement": "Варна", "in_municipality": true},
    {"source": "nominatim", "lat": 43.2066, "lon": 27.9140, "place_rank": 30,
     "settlement": "Варна", "in_municipality": true, "distance_m": 18}
  ],
  "flags": [],
  "decision": {"status": "auto", "candidate": 0, "decided_at": "2026-09-14"}
}
```

`key` is the table's full UNIQUE tuple — `label` alone does not identify a
branch (ДГ№13 has four label-less ones). `decision.status` ∈
`auto | pending | accepted | pinned | no_pin`. The seed script only ever
writes `auto` or `pending`; the review tool writes the rest.

The file's top level is `{"source_hash": "<sha256 over the committed CSV
and provenance bytes it was last regenerated from, or null>", "entries":
[…]}`. **Lineage rule**, shared with the review tool (TASK-005): if the
candidates file is missing (fresh checkout) or its `source_hash` differs from
the committed files (they changed underneath — a pull, a branch switch), every
decision is rebuilt from the committed files and only candidates and flags are
kept from local state; if the hash matches, the candidates file is in sync or
ahead (a crash between the writes) and its decisions stand. The committed
files are the record; the candidates file is a local cache. Rebuilding a
decision from a CSV row: `auto` → `auto` with its provenance entry; `human` +
`manual` + coordinate → `pinned`; `human` + `manual` + none → `no_pin`;
`human` + `osm_poi`/`nominatim` → `accepted` on the candidate at that
coordinate, else `pinned`.

## Amenity families

Rule 1's "right amenity family" is this table. A title match on a POI outside
the kind's family is not a match at all.

| `kind` | accepted OSM `amenity` values |
| --- | --- |
| `nursery` | `nursery`, `childcare`, `kindergarten` |
| `kindergarten` | `kindergarten`, `childcare` |
| `preschool` | `school`, `kindergarten` |

Confirm the table against the captured Overpass fixture in the RED step: if
Varna's data uses a family differently, change the table, not the rule, and
say so in the commit.

## Acceptance

- [ ] Every institution gets a `main` entry and every branch building a
      `branch` entry, even with no candidates
- [ ] A row is `auto` **only** when all four plan rules hold: unique POI title
      match within the kind's amenity family; inside the municipality polygon;
      settlement agrees with the address; within 150 m of every in-polygon
      rank-30 geocode when one exists
- [ ] Flags are per row and any flag forces `pending`; a candidate outside the
      polygon is kept in the list with `in_municipality: false` (the reviewer
      sees what the geocoder did) but flags the row `outside_municipality`,
      and rule 4 compares in-polygon candidates only
- [ ] Every `pending` row carries at least one flag from a fixed vocabulary:
      `no_candidate`, `ambiguous_title`, `geocoder_only`, `outside_municipality`,
      `settlement_mismatch`, `candidates_disagree`, `branch`, `name_only_branch`,
      `reverse_geocode_failed`, `address_changed`
- [ ] The three measured failures are flagged, not accepted: Игнатиево and
      Аксаково as `outside_municipality`, Константиново as `settlement_mismatch`
      (the address names кв. Виница, the pin is in the village Константиново)
- [ ] Rank 26–27 and 16–19 Nominatim hits are **discarded**, not kept as
      candidates — they look plausible and are tens to hundreds of metres off
- [ ] Title matching handles the quote-style variation (`"` `“` `„`) and matches
      on the quoted title, not the ДГ number
- [ ] The branch parser extracts the 15 branch rows from the free-places table,
      normalising the free-form `филиал` / `Филиал` / `- ` / ` на ` / ` в ` forms;
      the 3 name-only branches get a label and no address
- [ ] Nominatim requests (search and reverse) are spaced ≥1.1 s, strip
      `ул.`/`бул.` from the query, and send a real `User-Agent`
- [ ] The script is resumable: re-running keeps every entry whose decision is
      `accepted`, `pinned` or `no_pin`, and refreshes candidates only for
      `auto` and `pending` ones — except that an entry whose institution
      address (via the loader's `normalise_address`) differs from the address
      the decision was made against is reset to `pending` with flag
      `address_changed`, whatever its previous decision
- [ ] The lineage rule holds: with no candidates file, or one whose
      `source_hash` differs from the committed files, decisions are rebuilt
      from the committed CSV + provenance and the resulting files are
      byte-identical to what was committed; with a matching hash the local
      decisions stand; `source_hash` is rewritten after every write
- [ ] The script also writes `data/institution_locations.csv` and
      `data/institution_locations.provenance.json` through `render_csv_rows`
      + `write_file`: every **decided** entry — `auto`, `accepted`, `pinned`,
      `no_pin` — and no `pending` one, so a re-run never drops a human
      decision, plus one all-pass provenance entry per `auto` row;
      `parse_file` accepts the pair
- [ ] Pure-helper tests pass with **no network access**, including a table test
      of the auto-accept decision covering each rule failing on its own, the
      amenity-family table, `render_csv_rows` omitting `pending` entries
      and emitting a provenance entry for every `auto` one, and
      `decisions_from_files(rows, provenance)` rebuilding each decision kind

Evidence: `uv run pytest tests/test_seed_institution_locations.py -v`, plus the
script's run log: per-flag counts, the number `auto` vs `pending`, and the three
measured failures shown with their flags. Expect roughly 45–53 `auto` and
25–35 `pending` rows, all 15 branches included.

## Steps

### RED
- [ ] Capture live Overpass, Nominatim (search + reverse) and free-places
      responses into `scripts/fixtures/`, including the three failure addresses
- [ ] Write tests for title extraction, POI matching, address normalisation,
      settlement extraction from the source address and from reverse-geocode
      `address` parts, and the auto-accept decision

### GREEN
- [ ] Implement: read institutions from the database → load the candidates
      file and apply the lineage rule against the committed files → Overpass
      POI fetch →
      title match → Nominatim search for every row → reverse-geocode each POI
      candidate → polygon + settlement + distance checks → decide → free-places
      fetch → branch parse → write the candidates JSON and, via
      `render_csv_rows` + `write_file`, the CSV of decided rows and the
      provenance file
- [ ] Log a per-flag summary that reads as a worklist for TASK-006

### REFACTOR
- [ ] Keep every network call behind a thin function so the decision logic is
      a pure function of the gathered candidates

## Notes

**Settlement extraction is the rule that catches what the polygon cannot.**
From the source address, recognise `с.`/`с `/`село` + name (a village) and
`кв.`/`ж.к.` + name (a city neighbourhood, so the settlement is Варна). From
Nominatim reverse, use `address.village`, then `address.town`, then
`address.city`. An address naming no settlement means Варна. If either side
cannot be determined, flag it; don't guess.

Query Overpass over the **municipality** bbox (43.10–43.31 N, 27.74–28.06 E),
not the narrower research bbox, which can clip village POIs. The polygon
filters afterwards.

Nominatim search runs for **every** row, not only POI misses: rule 4 needs the
second opinion. That is ~77 search + ~53 reverse requests at 1.1 s, about 2.5
minutes.

Branches are always flagged `branch`, even with a clean POI match. OSM usually
tags the main building, and a unique title match on a branch address is the
research §1.3 near-miss (ДГ№13 №6 vs 1А) waiting to happen.

The free-places endpoint is seasonal: `KLAS_DATE = 23-06-2026`, `IS_FINAL = 1`,
70 data rows on 2026-08-17. If the live fetch returns fewer than 15 branch rows,
fall back to the verbatim table in `RESEARCH.md` and say so in the run log.

Number-matching is the wrong key for kindergartens: OSM names them by title,
and matching by ДГ number gets only 7/53. Don't copy `NURSERY_RESEARCH.md` §2.2.

The script lives in `scripts/`, is never imported by `src/yasli/`, and must not
be reachable from CI or the network-free test path. Run it as
`python -m scripts.seed_institution_locations` from the repo root so
`scripts.location_review` resolves; running it as a file path would put
`scripts/` itself on `sys.path` and break the import.
