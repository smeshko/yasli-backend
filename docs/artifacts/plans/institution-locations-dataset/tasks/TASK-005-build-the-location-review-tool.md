# TASK-005: Build the location review tool

Depends on: TASK-004
Suggested commit: `feat(scripts): add a local map review tool for institution locations`

## Goal

`uv run python -m scripts.review_locations` opens a local page where Ivo works
through the flagged rows on a map. Each row takes one or two keystrokes: accept a
candidate, drag or click to place a pin, or mark it as having no pin. Every
decision is committed to the candidates file immediately, and the CSV and
provenance file are regenerated from it through the parser.

## Files

- `scripts/review_locations.py` — stdlib `http.server` on `127.0.0.1:8765`
  (`--port`, `--candidates`, `--csv`); opens the browser on start
- `scripts/location_review/index.html` — the page: one file, inline CSS/JS,
  Leaflet 1.9.4 from cdnjs, OSM tiles
- `scripts/location_review/state.py` — created in TASK-004 with
  `render_csv_rows`; this task adds the pure functions `build_state` and
  `apply_decision`. (The package is `location_review`, not
  `review_locations`: a package sharing the sibling module's name would be
  un-importable.)
- `tests/test_review_locations.py` — the pure functions, plus a server round-trip
  on an ephemeral port using fixture candidates (no external network)

## Server API

| Method | Path | Does |
| --- | --- | --- |
| GET | `/` | serves `index.html` |
| GET | `/api/state` | entries (name, address, candidates, flags, decision), the municipality GeoJSON, and counts per status |
| POST | `/api/decision` | `{key, status, candidate?, lat?, lon?, precision?}` — `key` is the full `(kind, external_id, role, label, address)` tuple → applies it, validates the resulting rows through `render_csv_rows` + `parse_rows`, then writes the candidates file atomically (temp + rename) — the commit point within a session; see the lineage rule below — and regenerates the CSV and provenance file from it via `write_file`. Returns the updated entry and counts, or `422` with the parser's line and message, writing nothing |
| POST | `/api/undo` | reverts the last decision in this server session |

On startup the server applies the **lineage rule** (TASK-004): if the
candidates file's `source_hash` matches the committed CSV + provenance, the
candidates file is in sync or ahead (a crash between the writes) and the
server regenerates the derived files from it; if the hash differs, the
committed files changed underneath (a pull, a branch switch) and the server
rebuilds every decision from them, keeping only candidates and flags from
local state, then regenerates. With no candidates file at all it exits with a
message pointing at the seed script, which rebuilds decisions from the
committed files. A stale local file can never revert a newer committed one.

Decision → CSV row mapping:

| `status` | `source` | `precision` | `verification` | coordinate |
| --- | --- | --- | --- | --- |
| `auto` | candidate's source | `building` | `auto` | candidate's |
| `accepted` | candidate's source | `building` | `human` | candidate's |
| `pinned` | `manual` | `building`, or `approximate` when the reviewer toggles it (`A`) | `human` | placed by hand |
| `no_pin` | `manual` | `none` | `human` | empty |
| `pending` | — | — | — | **not written** — the row is absent from the CSV; the loader's missing-`main` count surfaces it (see Notes) |

## Page layout

- **Left: worklist.** Filter tabs `To review (n)` · `Auto-accepted (n)` ·
  `Done (n)` · `All`. Each item shows the institution name, a role badge
  (`main` or the branch label), and flag chips in plain words ("no match
  found", "pin is in Константиново, address says кв. Виница", "2 candidates
  180 m apart"). A progress bar shows reviewed out of flagged.
- **Right: map.** The Varna municipality outline stays visible. When a row is
  selected, the map fits all its candidates: POI candidate in blue, geocoder
  candidate in orange, both numbered, and the current decision as a green
  draggable pin. Clicking the map places the green pin there.
- **Detail panel** (above the map): the source `ADDRESS` in large type, the
  kind and external id, each candidate's name and distance from the others,
  links that open the pin in OSM and Google Maps, and a "search this address
  in Google Maps" link for block-relative addresses.
- **Actions**, with keys: `1`/`2` accept candidate, click or drag to place a
  pin, `A` toggle the placed pin between `building` (default) and
  `approximate` (for a pin on the block, not the building), `N` no pin, `U`
  undo, `J`/`K` next/previous, `Enter` accept the pin and go to the next row.
  After each decision the next pending row opens on its own.
- **Save status**: "Saved" or the parser's error inline, next to the actions.
  An error keeps the row pending and never looks like it saved.
- Works at laptop width. Mobile layout is not required, since this is a dev tool.

## Acceptance

- [ ] Starting the server with fixture candidates opens a page that lists the
      pending rows first, with correct counts per tab
- [ ] Selecting a row shows the municipality outline, every candidate marker,
      the source address and the flag reasons in plain words
- [ ] Accepting a candidate, placing a pin by click or drag, and marking no pin
      each write the right CSV row per the mapping table, verified by reading
      the CSV back; a pin toggled with `A` lands as `precision=approximate`
- [ ] A `pending` row is absent from the CSV, `parse_file` still accepts the
      file, and a decision on one of ДГ№13's four label-less branches changes
      only that branch's row
- [ ] A pin placed outside the municipality is refused with the parser's
      message, and the row stays pending
- [ ] Undo reverts the last decision in both the candidates file and the CSV
- [ ] Killing the server mid-review and restarting it resumes with every earlier
      decision intact
- [ ] A failure injected between the candidates write and the derived writes
      (a stubbed `write_file` that raises) leaves the CSV stale, and the next
      start — hash still matching — regenerates it to match the candidates file
- [ ] A candidates file whose `source_hash` differs from the committed files
      (a newer CSV pulled over older local state) does **not** revert them:
      startup rebuilds decisions from the committed files and the CSV is
      byte-identical afterwards; with no candidates file the server refuses to
      start and names the seed script
- [ ] The whole flow works from the keyboard alone
- [ ] The server binds to `127.0.0.1` only, and nothing under `src/yasli/`
      imports it
- [ ] `uv run pytest tests/test_review_locations.py -v` passes with no network

Evidence: test output, plus two screenshots (the worklist with a flagged row
selected; the same row after a hand-placed pin showing "Saved"), plus the
`git diff data/institution_locations.csv` that decision produced.

## Steps

### RED
- [ ] Tests for `apply_decision`: each status gives the right CSV row, a
      `pending` row gives none; a polygon rejection gives a 422 and leaves
      both files untouched
- [ ] Server round-trip test: GET state → POST decision → candidates file, CSV
      and provenance file on disk changed → POST undo → all three back to the
      original bytes; plus the crash-between-writes case above

### GREEN
- [ ] `state.py` pure functions, then the `http.server` handler around them
- [ ] `index.html`: worklist, map, detail panel, key bindings, save status

### REFACTOR
- [ ] Confirm the decision → row mapping exists once, in `render_csv_rows`
      (TASK-004), that the server and the seed script both call it, and that
      both write through the loader's `write_file`

## Notes

`pending` rows are **not** written. A half-finished review still produces a
valid file that parses — it just has fewer `main` rows, and the loader
refuses it before TRUNCATE unless `--allow-incomplete` is passed, so it can
never replace the complete table by accident. Writing a pending row as if it were a
`no_pin` would make an undecided row indistinguishable from a deliberate
decision, and would give it a `verified_at` nobody set. Only an explicit
`no_pin` ships as `precision=none`, per the plan decision.

Why a local server instead of a static HTML file: a static page would need a
file picker to load and a download to save, and the downloaded file would have
to be copied into `data/` by hand. The server removes both steps, and it validates
through the same `parse_rows` the loader uses. It is ~150 lines of stdlib code.

Leaflet and OSM tiles load from the network, which is fine for a local dev tool.
Nothing in the page may call Nominatim or Overpass. Candidates come only from
the seed run, so the review works offline apart from map tiles.

Show the auto-accepted rows on the map too, in the `Auto-accepted` tab, so a
spot-check is a click away. Don't mix them into `To review`.
