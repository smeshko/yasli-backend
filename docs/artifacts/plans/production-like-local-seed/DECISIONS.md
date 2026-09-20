# Decisions: Production-like local seed

Date: 2026-09-19

---

## D1 — Where the snapshot data comes from

### Options Considered

1. Commit a gzipped snapshot to the repo and teach ingest to read a local file.
2. Publish the snapshot at an unauthenticated HTTPS URL and download it.
3. Keep R2 as the only source and document `railway run` so secrets are injected
   rather than copied around.
4. Commit per-table gzipped CSV dumps and bulk-`COPY` them, bypassing ingest.

### Dependencies

A snapshot is 24 MB raw but 760 KB gzipped. Per-table CSV dumps of the same data
total ~768 KB — no smaller. `pipeline.run()` reads R2 in exactly one place,
`_fetch_snapshot_bytes()`.

### Selected Option

Option 1 — commit `data/seed/snapshot.json.gz`.

### Rationale

It is the only option that needs no credential, no network and no hosting, and it
keeps the seed running the real ingest pipeline rather than a parallel loading
path that could drift from it. 760 KB is in the same range as the reference data
the repo already commits. The change to ingest is one branch in one function.

### Rejected Options

- **Option 2** — adds a network dependency and a piece of hosting to maintain, and
  a public bucket is a deployment decision this ticket should not be making.
- **Option 3** — the smallest change, but it does not solve the stated problem:
  anyone without Railway access still cannot seed. The ticket's wording is
  explicit that credentials should not be needed.
- **Option 4** — no smaller, and it means the seed never exercises ingest, so an
  ingest bug would be invisible locally. That is the opposite of "production-like".

---

## D2 — How the ГРАО KADS file is shipped

### Options Considered

1. Commit `kads-03-06.zip` (92 KB) and teach `grao_loader` to read a `.zip`.
2. Commit the extracted `kads-03-06.txt` (688 KB), no loader change.
3. Have the seed download it from `varna.bg/upload/<id>/kads-03-06.zip`.

### Dependencies

The archive is 92 KB, the extracted text 688 KB. `docs/OPERATIONS.md` already
documents downloading the **zip** and warns that the extracted text gets mangled
by Git, editors and `unzip`. The `varna.bg` numeric path rotates per election cycle.

### Selected Option

Option 1 — commit the zip, teach the loader to open it.

### Rationale

It commits the artifact ГРАО actually publishes, at a seventh of the bytes, in the
form least likely to be corrupted in transit. The loader change is a single branch
in `parse_file` that reads the archive's one member and hands the same bytes to the
same windows-1251 decode, so every existing parse test still applies.

### Rejected Options

- **Option 2** — 7× the bytes of a file the runbook already warns is fragile in Git.
- **Option 3** — the rotating numeric id means the seed breaks silently on a dead
  URL every election cycle, which is the failure mode the ticket is complaining about.

---

## D3 — What the one command is

### Options Considered

1. A new `python -m yasli.seed` module in the backend, plus a `just be-seed` alias.
2. A `just` recipe alone, chaining the existing commands.
3. A `seed` subcommand on the existing `python -m yasli.ingest`.

### Dependencies

The `yasli` root directory is **not** a git repository — the `justfile` lives there
and is untracked. Only `backend/`, `scraper/` and `frontend/` are repos.

### Selected Option

Option 1 — a module, with the recipe as a convenience alias.

### Rationale

A recipe in an untracked file cannot be the documented entrypoint: a fresh clone of
this repo would not have it. A module ships with the code, can be tested, and can
own the step-by-step summary and the verification pass that the ticket asks for.
The alias still gets added because it is how the rest of the workflow is driven.

### Rejected Options

- **Option 2** — does not survive a clone; also has nowhere to put the verify logic.
- **Option 3** — `yasli.ingest` means "pull the weekly snapshot into Postgres". A
  subcommand that also loads ГРАО, legacy institutions and locations muddies that,
  and the cron that invokes the bare `python -m yasli.ingest` is a reason to keep
  that module's remit narrow.

---

## D4 — How local reaches 95 institutions

### Options Considered

1. Commit `data/seed/legacy_institutions.json` — the 18 rows as explicit data —
   and load them after ingest.
2. Freeze a second, pre-2026-05-10 timestamped snapshot from R2 and have the seed
   ingest old-then-new, reproducing how production actually reached 95.
3. Leave local at 77 and document which 18 slugs do not resolve.

### Dependencies

All 18 missing rows are `kind=nursery`. `yasli.services.matching` routes nurseries
solely on `Institution.district_code`, never through `address_institutions`, so
those rows need no catchment edges — only a `district_code`. Round-1 validation
corrected how that value arrives: `restamp-districts` excludes nurseries, so the
fixture must carry it. See D7. Ingest is upsert-based and deletes nothing, so
old-then-new ingest would genuinely reproduce production.

### Selected Option

Option 1 — the explicit fixture.

### Rationale

~4 KB against ~760 KB, and it depends on nothing: not on R2 retention keeping a
five-month-old object, not on that object still validating as schema v2. It is also
more honest about what these rows *are* — stale entries production has never
retired — rather than smuggling them in as a second ingest whose provenance a
reader has to reconstruct.

### Rejected Options

- **Option 2** — more faithful in principle, but buys that fidelity with two
  external unknowns and 190× the bytes, for rows that carry no catchment anyway.
- **Option 3** — the ticket names the 77-vs-95 gap as a defect of the local
  environment, and the user put closing it in scope.

### Consequence

The fixture is the sole source of these rows' `district_code` (D7), which makes it
a slightly richer artifact than "the 18 rows" implies — and makes `freeze`'s
derivation responsible for reproducing that column faithfully.

---

## D5 — Whether the seed runs migrations

### Options Considered

1. The seed runs `alembic upgrade head` as step 0.
2. The seed reads `alembic_version`, and refuses with "run `just be-migrate`".
3. The seed assumes a migrated database and lets SQLAlchemy errors surface.

### Selected Option

Option 1.

### Rationale

"One command" is the entire point of the ticket, and from a bare database options 2
and 3 make it two. `alembic upgrade head` is idempotent, so it costs nothing on an
already-migrated database, and `alembic.command.upgrade` is a supported API — no
subprocess needed.

### Rejected Options

- **Option 2** — defensible, but it trades the ticket's headline requirement for a
  purity the developer does not benefit from.
- **Option 3** — produces the worst possible error message for the most likely
  first-run mistake.

---

## D6 — What the seed does against a non-empty database

### Options Considered

1. Run anyway: ingest upserts, the ГРАО/locations loaders TRUNCATE and reload as
   they already do.
2. Detect existing rows and refuse, telling the developer to `just db-reset`.
3. Reset the database itself before loading.

### Selected Option

Option 1.

### Rationale

It is the behaviour the three underlying commands already have, so the seed adds no
new semantics to reason about, and `just db-reset` is right there for a clean start.
Explicitly chosen by the user over the alternatives.

### Rejected Options

- **Option 2** — an extra gate in front of a command whose whole purpose is to be
  runnable without thinking.
- **Option 3** — a command that silently drops a developer's local database is a
  worse failure than a stale row.

### Consequence

Institutions removed from the snapshot since the last seed survive as stale rows,
exactly as they do in production. `verify` reports the institution count, so the
drift is visible rather than silent, and `just db-reset && just be-seed` is the
documented way to get a clean one. This is recorded in the README's
local-vs-production notes (TASK-007).

Round-1 validation drew out the corollary for `verify`: because this decision
permits rows beyond the committed artifacts, `verify` must not assert a hard
institution count. It derives the expected set from the union of the snapshot's and
the fixture's `(kind, external_id)` keys rather than from a literal 95.

Round 2 then corrected how *extras* are handled. The original reading — stale rows
are visible drift, not a defect — does not survive the routing code:
`_district_rows_for_kind` (`matching.py:222-249`) selects every institution of the
queried kind carrying the queried `district_code`, with no scoping to the committed
artifacts. A stale nursery surviving a dirty re-run therefore *appears in
`/api/match` results*, and a seed that exits 0 over it has reported success on a
database that answers the headline query differently from production.

The resolution keeps this decision and tightens the next one: the **seed** still
runs against a non-empty database — no new gate in front of the command, which is
what Option 2 above was rejected for — but **`verify` fails** on any institution
outside the artifact union, naming it. "The seed runs" and "this database is
production-like" are different claims, and verification is where the second one is
made. Reversing this decision outright was proposed in both validation rounds and
declined both times.

Round 3 found the same hole one level deeper and it is worth stating plainly,
because it is the recurring cost of this decision: catchment **edges** drift too.
`_insert_address_institutions` (`pipeline.py:564-630`) inserts with
`on_conflict_do_nothing` and never deletes, and `_address_rows`
(`matching.py:189-218`) joins the junction without scoping, so an edge from a
previous snapshot keeps adding a kindergarten to `/api/match` even when the
institution set is exactly right. `verify` therefore reconciles the edge set
against the snapshot as well.

**The general shape to carry into implementation:** every table a dirty re-run can
leave stale is a table `verify` must reconcile against the committed artifacts.
Institutions and `address_institutions` are the two that affect routing today. If a
third appears, it belongs in `verify` too — or this decision should be revisited in
favour of a seed that reconciles rather than accumulates.

---

## D7 — Where the legacy nurseries' `district_code` comes from

Raised by round-1 validation: D4 assumed `restamp-districts` would stamp the 18
fixture rows. It cannot.

### Options Considered

1. Carry `district_code` in `data/seed/legacy_institutions.json`, written by the
   legacy loader like any other column.
2. Add nursery support to `district_stamp` — drop the `kind <> 'nursery'` filter, or
   add a nursery-only pass that parses `institutions.address` against `grao_addresses`.
3. Leave the rows unstamped and accept that they do not route.

### Dependencies

`district_stamp` excludes nurseries in three places — the candidate query
(`district_stamp.py:270`), the UPDATE (`:291`) and the module docstring (`:11`,
"kindergartens + preschools only — nurseries are API-sourced"). `restamp_institutions_all`
repeats the guarantee in its docstring (`:477-482`). `match_data_validation` counts
`nursery_without_district` as a **hard failure** (`:119`), and `pipeline.py:442`
preserves an existing `district_code` when the incoming value is NULL
(`preserve_old_on_null_columns=("district_code",)`).

### Selected Option

Option 1 — the fixture carries `district_code`, and the loader writes it.

### Rationale

It matches where the value comes from everywhere else in the system: the DG API
supplies each nursery's район, ingest writes it, and nothing recomputes it. The 18
rows are production rows, so production already holds the correct value and
`freeze` can re-derive it. The fixture stays a faithful copy of what production has
rather than a guess reconstructed from an address string.

### Rejected Options

- **Option 2** — would undo a deliberate architectural exclusion for the benefit of
  18 stale rows, and address-parsing a nursery's district is strictly less reliable
  than the API value production already holds. It also widens the blast radius to
  the weekly ingest, which is not this plan's business.
- **Option 3** — the routing parity criterion is the ticket's headline; unrouted
  nurseries are the bug YAS-21 was filed about.

### Consequence

`district_code` becomes a required, validated field of the fixture (TASK-003), a
required output of the legacy derivation in `freeze` (TASK-006), and a checked
property in `verify` (TASK-005). Step 6 of the seed no longer has anything to do
with the legacy rows; TASK-004 records that.

---

## D8 — How far `freeze` goes to keep the two artifacts consistent

Raised by round-1 validation.

### Options Considered

1. A validation guard: refuse to write when the fixture and snapshot key sets
   intersect (re-checked under `--snapshot-only`), plus an `--allow-shrink` gate on
   a fixture that loses rows.
2. A full stage-and-swap: write both artifacts to a staging directory, validate
   both, seed and `verify` a throwaway database from the staged pair, then replace
   both files together.
3. Document the hazard as a known risk and rely on review.

### Selected Option

Option 1. Chosen by the user over the alternatives.

### Rationale

The failure that actually costs data is a fixture row overlapping a live snapshot
row, because the legacy upsert would overwrite current data with a months-old copy.
A key-set disjointness check catches exactly that, before either file is written,
and costs one query. TASK-003's committed-data test asserts the same property over
the committed artifacts, so `just be-test` fails before a mismatched pair can be
merged — two independent nets on the one outcome that matters.

### Rejected Options

- **Option 2** — strictly safer, but it makes a maintainer command depend on the
  whole seed and verify path (so TASK-006 would also depend on TASK-005), and it is
  close to being its own task. The residual risk it buys down — two artifacts from
  different epochs but with disjoint keys — is staleness, which `verify`'s
  `scraped_at` warning already surfaces.
- **Option 3** — leaves a silent data-overwrite path open in a command whose whole
  purpose is to be run rarely and trusted.

### Amendment after round 2

Round 2 pressed Option 2 again on two grounds. One landed: the guard validates
before two *separate* writes, so a crash after the snapshot is written but before
the fixture is leaves precisely the mismatched pair the guard exists to prevent.
The other — that no valid transition exists when a former legacy key reappears in
the snapshot — is overstated, but the spec did not say what the transition is.

Both are addressed without reversing the decision: `freeze` now builds both
artifacts in a temp directory, checks disjointness over that *candidate pair*, and
publishes both with `os.replace` back to back as its last act, which narrows the
mismatch window from the whole fetch-and-derive to the gap between two renames.
(It does not close it — see the round-3 correction below.) The overlap error names
the two ways forward —
run a full `freeze`, or drop the colliding keys from the fixture. On the full path
the disjointness check is trivially satisfied by construction (the fixture is
derived as production minus the snapshot); it is retained because it is the only
check doing real work on the `--snapshot-only` path.

Option 2 remains rejected. Seeding and verifying a throwaway database inside
`freeze` would make a maintainer command depend on the entire seed *and* verify
path — TASK-006 would gain a dependency on TASK-005 — to buy down a residual risk
(two artifacts from different epochs but with disjoint keys) that is staleness, not
corruption, and that `verify`'s `scraped_at` warning already surfaces.

### Correction after round 3

The amendment above overstated its own guarantee. Two sequential `os.replace` calls
are **not** an atomic pair publish: an interruption between them leaves one new file
beside one old one. The honest claim is that the temp-directory build narrows the
exposure from the whole fetch-and-derive to the gap between two renames.

That residual window is accepted rather than closed, on three grounds: it is two
syscalls wide; `data/seed/` is a git working tree, so `git checkout -- data/seed/`
is a complete rollback; and TASK-003's committed-data test fails `just be-test`
before a mismatched pair could be committed. What the command owes in exchange is
accurate reporting — a failed second rename exits non-zero and names both files as
possibly disagreeing, rather than reporting a successful freeze. A versioned
directory with a single pointer swap would make the publish genuinely atomic and
remains available if this ever proves insufficient in practice.
