# Operations runbook

Operator-facing tasks beyond the weekly Railway cron set up in
[`DEPLOYMENT.md`](DEPLOYMENT.md). One-off maintenance, reference data
refreshes, post-mortem digging.

---

## ГРАО quarterly reference-data refresh

The ГД ГРАО (Главна Дирекция ГРАО) Address Classifier is the ground truth
for the **(street, building number, entrance) → район** mapping that
powers nursery + preschool routing in `/api/match`. The file is republished
per Bulgarian election cycle (roughly yearly, with off-cycle by-elections
occasionally minting a fresh release). The first iteration of the refresh
process is manual — automating the probe is a separate change.

### When to refresh

- After every Bulgarian election cycle ends, check for a new file.
- If `addresses_district_unstamped` in the weekly ingest summary climbs
  past ~2% of in-city addresses, the local `grao_addresses` table is
  probably stale — new construction is appearing.
- If a user reports a clearly mis-routed nursery or preschool in a known
  район, suspect a районна reassignment and refresh.

### Where to get the file

ГРАО publishes the file at `https://varna.bg/upload/<numeric-id>/kads-03-06.zip`.
The numeric id rotates each election. To find the current id:

1. Open <https://varna.bg/> in a browser and find the latest elections
   landing page (usually titled "Избори …" with the cycle date).
2. The page links to a ZIP archive named `kads-03-06.zip`. Right-click,
   copy link. The URL has the form
   `varna.bg/upload/<6-digit-id>/kads-03-06.zip`.
3. Download the ZIP (~700 KB).
4. Extract — the archive contains a single plaintext file (typically
   also named `kads-03-06.txt`). The file is windows-1251 encoded with
   CRLF line terminators.

If `varna.bg` is unreachable, the same file (and the cycle archive) is
mirrored on `https://www.grao.bg/` — search the elections / addresses
section. The two sources are byte-identical per cycle.

### Loading the file into the database

Once the plaintext file is on a machine that can reach the production
Postgres (Railway's "exec into deployment" shell works; or run locally
against a tunneled `DATABASE_URL`):

```bash
# 1. Verify the file decodes correctly.
file kads-03-06.txt
iconv -f windows-1251 -t utf-8 kads-03-06.txt | head -5

# 2. Load it. TRUNCATE grao_addresses + bulk INSERT inside one transaction.
python -m yasli.ingest.grao_loader /path/to/kads-03-06.txt

# Expected output:
# grao_loader done rows=<50000-100000> streets=<3000-6000> skipped=0
```

If the loader exits non-zero with `error: file is not valid windows-1251`,
the file got mangled by Git, an editor, or `unzip` (rare). Re-extract from
the ZIP. The loader does not write anything if decoding fails.

### Propagating district reassignments

After a reload, the `grao_addresses` table is current but
`addresses.district_code` and `institutions.district_code` (for KG/PG —
nurseries are API-sourced and untouched) still reflect the previous
ГРАО snapshot. Run the **non-gated** restamp to propagate:

```bash
python -m yasli.ingest restamp-districts

# Expected output:
# restamp-districts done addresses={primary:<N>,fallback1:<n>,fallback2:<n>} \
#   addresses_district_unstamped=<n> institutions={primary:<N>,fallback:<n>} \
#   institutions_district_unstamped=<n>
```

This command operates inside a single transaction. On any failure the
DB is rolled back to the previous stamp. Nurseries' `district_code` is
never touched — the kind filter excludes them from both the
catchment-majority and address-parse paths.

### Verification after refresh

Spot-check a known address against the new district stamp:

```sql
SELECT a.id, s.raw_name, a.number_int, a.district_code
FROM addresses a JOIN streets s ON s.id = a.street_id
WHERE s.search_norm LIKE '%vapcarov%' AND a.number_int = 7;
-- Expect district_code = '02' for ул. Н.Й. Вапцаров №7 (район Приморски).
```

Check the overall NULL rate:

```sql
SELECT
  COUNT(*) FILTER (WHERE district_code IS NULL)   AS no_district,
  COUNT(*) FILTER (WHERE settlement_code IS NULL) AS no_settlement,
  COUNT(*)                                        AS total
FROM addresses;
-- Expect no_settlement ≈ 0 (the settlement pass covers every Varna street).
-- no_district = village addresses (Каменар/Тополи/Звездица/Константиново/Казашко)
-- plus residual ГР.ВАРНА unmatched rows; aim for the city residual under 2%.
```

Then hit `/api/match` for a couple of addresses in different районs and
confirm the expected nurseries + preschools come back. Spot-check at
least one village address — it should return structured `{address, results}`
with `address.district_code = null` and settlement context.

### Match-data validation

Run the read-only validation before and after ingest/restamp work:

```bash
python -m yasli.ingest validate-match-data

# Expected first line:
# match data validation ok
```

Hard failures exit non-zero and include a `failures={...}` line. Warnings
stay exit 0; they cover allowed but important states such as Varna-city
addresses without a district stamp.

### Rollback

If a reload produces obviously wrong stamps (e.g. mass NULLs, wrong
codes), there is no "previous ГРАО" version in the DB. Two options:

1. **Re-extract the previous cycle's ZIP** (you should keep one per
   refresh as the rollback artifact) and reload it via the loader, then
   re-run `restamp-districts`.
2. **Truncate** `grao_addresses` and reset the stamps:
   ```sql
   TRUNCATE grao_addresses;
   UPDATE addresses    SET district_code = NULL, settlement_code = NULL;
   UPDATE institutions SET district_code = NULL WHERE kind <> 'nursery';
   ```
   The next weekly ingest will leave all KG/PG `district_code` columns
   at NULL until the next loader run; `/match` will return structured
   address context with `address.district_code = null`, and district-routed
   groups will be unavailable for affected queries.

### What the weekly cron does automatically

`backend-ingest` runs both **gated** stamping passes after the snapshot
upsert phase:

1. `stamp_addresses_unmatched()` — only fills in addresses with
   `district_code IS NULL` (new construction the previous weekly run
   missed because ГРАО had nothing to join against).
2. `stamp_institutions_unmatched()` — only fills in KG/PG with
   `district_code IS NULL`. Nurseries are never touched by this pass.

The gated passes will NOT propagate ГРАО reassignments that affect
already-stamped rows. That is by design (the weekly pipeline must not
silently churn district stamps). Use `restamp-districts` for that.

---

## Institution locations refresh

`institution_locations` is what puts a pin on a parent's map: one row per
building an institution occupies — its `main` building and any `branch`
buildings — with a coordinate and how that coordinate was decided. No
source publishes coordinates, and geocoding measurably cannot be trusted
here (three of the sixty addresses Nominatim resolved in the research were
confidently wrong, one in Игнатиево, one in Аксаково, one in the village of
Константиново — see `INSTITUTION_DETAIL_MAP_RESEARCH.md` §3.2 in the
`openspec/docs` folder of the `yasli/` parent). So the table is a **curated
reference dataset**: a committed CSV, seeded by strict rules and finished
by a person, loaded by its own CLI. A stale row is a parent at the wrong
building, which is why the loader refuses to load a file it cannot fully
attribute.

The committed artifacts, both in `data/`:

- `institution_locations.csv` — the rows. Columns: `kind, external_id,
  role, label, address, lat, lon, precision, source, verification,
  verified_at`. Joins `institutions` on `(kind, external_id)`, never on the
  serial id, which a re-ingest does not preserve.
- `institution_locations.provenance.json` — one entry per
  `verification=auto` row, recording the OSM identity and the four
  auto-accept rule outcomes (title-match count, inside the municipality,
  reverse-geocoded settlement next to the address's settlement, distance to
  the rank-30 geocode). The parser rejects an `auto` row without a matching,
  all-pass entry, so an `auto` pin can be audited from the repo alone, and a
  hand-edited `auto` row fails to parse.

Both files are written only by the seed script and the review tool, never
by hand, and always together.

Each row carries three provenance columns:

| Column | Values | Meaning |
| --- | --- | --- |
| `precision` | `building`, `approximate`, `none` | how precise the pin is; `approximate` is a hand-placed pin on the block rather than the building; `none` is a deliberate blank |
| `source` | `osm_poi`, `nominatim`, `manual` | where the coordinate came from: an OSM point of interest, the geocoder, or a person's hand |
| `verification` | `auto`, `human` | how the row was decided: by the seed script's rules, or by a person in the review tool |

`auto` is only ever `osm_poi` + `main` + `building` — the database CHECK and
the parser both enforce it. A row is auto-accepted only when **all four**
rules hold: the OSM POI title match is unique (one POI carries the title,
one institution owns it) within the kind's amenity family; the POI is inside
the committed Varna municipality polygon (`data/varna_municipality.geojson`);
its reverse-geocoded settlement agrees with the settlement the address
names (a village address must match its village, a city address must
resolve to Варна); and if a rank-30 geocode exists it lies within 150 m.
Everything else — geocoder-only hits, ambiguous titles, disagreements, no
candidate, every branch — goes to a person. **Geocoder output is never
accepted without review**: all three measured wrong pins were geocoder hits.

A `verification=human` row is a person's judgement that the seed script
cannot reproduce. The script is resumable and keeps those decisions; do not
"fix" a row by editing the CSV by hand, re-run the tool instead.

### When to refresh

- **A new institution appears in the weekly ingest.** It has no `main` row,
  so the next loader run aborts until the row is reviewed. `--dry-run`
  shows it without loading.
- **An institution's address changes in the weekly ingest.** Ingest
  overwrites `institutions.address`, and a moved institution with its old
  pin is exactly the wrong pin that looks right. The loader compares every
  `main` row's address with the table's through one normaliser (quote
  styles, `№` spacing, case, whitespace) and aborts on a difference; a seed
  re-run returns the row to review flagged `address_changed`.
- **Someone reports a wrong pin.** Correct it in the review tool; the row
  becomes `human` and its provenance entry is dropped.

The loader runs **after** ingest, never with it: `just be-ingest` does not
touch this table. Coordinates change roughly never, and coupling a
reference load to the weekly cron would let a third-party outage during the
seed script's data collection break the routing refresh.

### Where to get the file

The file is in the repo. A fresh checkout is complete: the committed CSV
and provenance file are the record, and the review tool's working state
(`data/institution_locations.candidates.json`, gitignored) is a local cache
that the seed script rebuilds from the committed files whenever it is
missing or stale (it stores the hash of the files it was last regenerated
from; a mismatch means the committed files moved and they win).

To refresh the file, run the loop on a checkout with `DATABASE_URL`
pointing at a database with current institutions (a fresh `just be-ingest`
locally is enough):

```bash
# 1. Gather candidates and apply the auto-accept rules. Needs the network
#    (Overpass, Nominatim at ~1 req/s, dg.uslugi.io); ~10 minutes.
#    Keeps every accepted / pinned / no_pin decision from a previous run;
#    refreshes only auto and pending rows; re-flags moved institutions.
uv run python -m scripts.seed_institution_locations

# 2. Resolve the flagged rows on a map. Opens http://127.0.0.1:8765/.
#    1/2 accept a candidate, click or paste coordinates (P) to place a pin,
#    A marks it approximate, N no pin, U undo, Enter saves and moves on.
#    Every decision lands in the CSV at once, through the parser.
uv run python -m scripts.review_locations

# 3. Commit the two files together.
git add data/institution_locations.csv data/institution_locations.provenance.json
git commit -m "feat(data): refresh institution locations"

# 4. Load — see below.
```

A seed re-run rewrites the CSV and the provenance file from every decided
entry, so `human` rows survive it. Nothing decided is lost by deleting the
candidates file either — the seed script rebuilds decisions from the
committed files; what would lose decisions is discarding the CSV changes
before they are committed.

The seed script and review tool are committed but are not a maintained
pipeline: the CSV is the artifact of record, and `tests/test_institution_locations_data.py`
pins its shape (77 `main` rows, one per institution; 17 `branch` rows; the
cases the plan names).

### Loading the file into the database

The loader runs wherever the ГРАО loader runs: from a Railway "exec into
deployment" shell (the image copies `data/`), or from a checkout against a
tunnelled `DATABASE_URL`. The `just be-load-locations` recipe lives in the
`yasli/` parent `justfile`, outside this repo, next to `be-ingest`.

```bash
# Check first: runs every guard and prints the summary without touching
# the table. This is the "is the CSV still current?" question.
python -m yasli.ingest.institution_locations_loader --dry-run

# Load. Default path: data/institution_locations.csv, resolved relative
# to the package, not the working directory. TRUNCATE + INSERT inside
# one transaction; running it twice leaves the same observable state.
python -m yasli.ingest.institution_locations_loader

# Expected output:
# institution_locations_loader done rows=94 main=77 branch=17 auto=37 \
#   human=57 missing_main=0 address_drift=0 unresolved_main=0 dry_run=0
# followed by one line per unresolved main row (none expected).
```

Three guards run **before** the TRUNCATE, all resolved against
`institutions` in one query, so a bad file fails as a data problem with
names and the table is never emptied even transiently:

1. **Unmatched `(kind, external_id)`** — a row whose pair matches no
   institution. Never skippable. Exit 4.
2. **Missing `main`** — a current institution with no `main` row: a
   half-finished review, or a CSV predating a newly ingested institution.
   Exit 4, naming the institutions. An explicit `no_pin` row
   (`precision=none`) counts as present.
3. **Address drift** — a `main` row whose address no longer matches the
   institution's. Exit 4, naming the institution and both addresses.

`--allow-incomplete` ("the CSV lags the institutions table") skips guards 2
and 3 for **local partial loads only** and is never used against
production; the summary then reports the missing and drifted rows by name.
Other exit codes: 2 file not found, 3 parse failure (with the line
number), 5 database error.

### Verification after refresh

```bash
# From the yasli/ parent (`just db-psql` is interactive and takes no arguments).
docker compose exec -T postgres psql -U yasli -d yasli \
  -c "SELECT role, precision, count(*) FROM institution_locations GROUP BY 1,2 ORDER BY 1,2"
# Expect main/building 77 (or a few main/approximate), branch/building 16, branch/none 1.

docker compose exec -T postgres psql -U yasli -d yasli \
  -c "SELECT i.kind, i.external_id, i.name FROM institutions i \
      LEFT JOIN institution_locations l \
        ON l.kind = i.kind AND l.external_id = i.external_id AND l.role = 'main' \
      WHERE l.kind IS NULL"
# Expect zero rows: every institution has a main row.

# Address drift is not expressible in SQL (the comparison is normalised);
# the dry run is the check:
python -m yasli.ingest.institution_locations_loader --dry-run
# Expect missing_main=0 address_drift=0.
```

Then open a kindergarten with branches in the API (phase 1.3) or the
review tool's `Auto-accepted` tab and spot-check a few pins against their
source address.

### Rollback

There is no "previous locations" version in the database, but there is in
git: check out the previous `data/institution_locations.csv` and
`data/institution_locations.provenance.json` together and run the loader
again. Never roll back one file without the other — the parser rejects a
CSV whose `auto` rows have no matching provenance entry, and a provenance
entry with no `auto` row.

If the table must be emptied, `TRUNCATE institution_locations;` is safe:
nothing else references it, the detail endpoint renders without a map, and
the next loader run fills it again.
