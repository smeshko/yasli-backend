# Plan: Production-like local seed

Status: in-progress
Branch: feature/yas-21-seed-production-like-local-database
Risk: medium
Epic: none
Phase: none
Linear: YAS-21 (https://linear.app/ivo-tsonev/issue/YAS-21)
Created: 2026-09-19

## Goal

A developer with a clone of this repo and an empty Postgres runs one command —
`uv run python -m yasli.seed` — and ends up with a database that answers the same
questions production answers, without holding a single R2 credential, and is told
loudly and by name if any part of the seed did not land.

## Scope

- Commit the ГРАО KADS archive (`data/grao/kads-03-06.zip`, 92 KB) and teach
  `yasli.ingest.grao_loader` to read a `.zip` as well as a `.txt`.
- Commit a frozen snapshot (`data/seed/snapshot.json.gz`, ~760 KB) and teach
  `yasli.ingest.pipeline` / `python -m yasli.ingest` to read the snapshot from a
  local file instead of R2.
- Commit `data/seed/legacy_institutions.json` — the 18 `kind=nursery` rows
  production still carries from before 2026-05-10 — plus a loader for them.
- Add `python -m yasli.seed`: `alembic upgrade head` → ГРАО → ingest from the
  frozen snapshot → legacy institutions → institution locations →
  `restamp-districts`, with a per-step summary line. **ГРАО precedes ingest** and
  the order is load-bearing — ingest ends with the gated district-stamping passes,
  which can only stamp what `grao_addresses` already holds. TASK-004 is the
  canonical statement of this order.
- Add `python -m yasli.seed verify`: re-check the seeded database and exit
  non-zero naming what is missing, also run automatically at the end of a seed.
- Add `python -m yasli.seed freeze`: the maintainer-only command that regenerates
  the two committed seed artifacts from R2 and from a configured database.
- Add a `be-seed` recipe to the root `justfile`, rewrite the README quickstart,
  and document the refresh cadence plus the local-vs-production differences in
  `docs/OPERATIONS.md`.

## Out of Scope

- **Retiring the 18 disappeared institutions in production.** YAS-21 calls this
  "a separate question, worth its own ticket"; this plan brings local *up* to 95,
  it does not bring production *down* to 77.
- **Regenerating the frontend's `src/data/institutions-manifest.json`.** It is a
  different repository and it already lists all 95; nothing here changes it.
- **CI-refreshed fixtures.** Refreshing the frozen snapshot stays a deliberate
  maintainer action, like the ГРАО and institution-locations datasets already are.
- **Automating the ГРАО download.** The numeric `varna.bg/upload/<id>/` path
  rotates per election cycle; `docs/OPERATIONS.md` already documents finding it by
  hand and this plan does not change that.
- **Any city but Varna.** The frozen snapshot is `snapshots/varna/latest.json`.
- **Making the seed safe to re-run over a dirty database.** It runs anyway; see
  the Decisions section.
- **Changing the schema.** No new tables, no migration.

## Research Summary

See [RESEARCH.md](./RESEARCH.md). The three findings that shaped the plan:

- `grao_addresses` is empty on a local database (0 rows against production's
  ~47.6k), which is exactly why nurseries and preschools return nothing locally.
  The KADS archive that fixes it is 92 KB zipped — small enough to commit.
- A full snapshot is 24 MB of JSON but 760 KB gzipped, so the R2 dependency can be
  removed by committing one file rather than by hosting or tunnelling anything.
- All 18 institutions local is missing are `kind=nursery`, and
  `yasli.services.matching` routes nurseries purely on
  `Institution.district_code` — no `address_institutions` edges. So the 77-vs-95
  gap closes with a ~4 KB fixture. The fixture must carry `district_code` itself:
  both `district_stamp` passes exclude `kind='nursery'` on purpose
  (`district_stamp.py:270,291`) because nursery districts are API-sourced, so
  `restamp-districts` will never supply it.

## Decisions

See [DECISIONS.md](./DECISIONS.md).

## Risks

- **Each snapshot refresh adds ~760 KB to git history.** Mitigation: one artifact
  rather than per-table dumps, and refresh stays a deliberate, documented
  maintainer action rather than something CI does weekly.
- **The frozen snapshot goes stale silently, and local quietly drifts from
  production.** Mitigation: the seed and `verify` both print the snapshot's
  `scraped_at`, and `verify` emits a warning (not a failure) once it is older than
  90 days.
- **`freeze` needs production access to derive the legacy rows.** Mitigation: it
  rewrites `snapshot.json.gz` from R2 always, but rewrites
  `legacy_institutions.json` only when the configured database actually contains
  institutions absent from the snapshot; otherwise it leaves the file untouched and
  says so, so a maintainer pointed at their own local DB cannot blank it.
- **A future snapshot could stop being schema v2**, breaking the frozen-file path
  the same way it would break R2 ingest. Mitigation: none needed — the existing
  `UnsupportedSnapshotVersion` guard already fires, and the seed surfaces it.
- **The committed snapshot carries institution contact data** (phone, e-mail,
  director, website). These are published by the source portal for public
  institutions, so there is no personal-data concern, but the plan records it
  rather than leaving it implicit.
- **`data/seed/` and `data/grao/` are binary-ish blobs Git cannot delta.** Accepted:
  ~850 KB total, and the repo already commits `data/institution_locations.csv`
  and `data/varna_municipality.geojson` on the same reasoning.
- **The legacy fixture's `district_code` values have no automated source of truth.**
  Nursery districts are API-sourced and no stamping pass touches nurseries, so the
  18 values are copied from production and will silently go stale if a район is ever
  reassigned. Mitigation: `freeze` re-derives them from production on every refresh,
  and `validate-match-data`'s `nursery_without_district` counter catches a missing
  one — though not a wrong one. Accepted: these are rows production has already
  stopped updating.
- **`freeze` writes the snapshot and the legacy fixture in separate steps**, so a
  failure between them — or a deliberate `--snapshot-only` — can commit a mismatched
  pair. The damaging case is not staleness but overwrite: the legacy loader upserts
  on `(kind, external_id)`, so a fixture row that has since become a live snapshot
  row would replace current data with a months-old copy. Mitigation: `freeze`
  refuses to write either file when the two key sets intersect, and refuses a
  shrinking fixture without `--allow-shrink`; TASK-003's committed-data test fails
  `just be-test` as the second net. A full stage-and-swap was considered and
  rejected — see DECISIONS.md D8. The temp-directory publish narrows but does not
  close the window: two `os.replace` calls are not atomic, so an interruption
  between them still leaves a mismatched pair. Accepted because `data/seed/` is a
  git working tree (`git checkout --` is a full rollback) and the command reports
  the ambiguity instead of claiming success.
- **Ingest never deletes, so a dirty local database accumulates routing state.**
  Stale institutions *and* stale `address_institutions` edges both survive a
  re-seed (`pipeline.py:564-630` inserts with `on_conflict_do_nothing`), and both
  are read by `/api/match` without any scoping to the committed artifacts.
  Mitigation: `verify` reconciles both sets against the artifacts and fails on
  anything extra, so a drifted database cannot pass as production-like. This is the
  standing cost of D6 — any future table with the same property needs the same
  treatment.

## Acceptance Criteria

- [ ] On a freshly reset database, `uv run python -m yasli.seed` completes with
      exit 0 and no R2 environment variable set
- [ ] After it, `grao_addresses` holds ~47,579 rows across districts 01–05, and
      `addresses.district_code` is non-null for the overwhelming majority of rows
- [ ] `GET /api/match` for the `addresses.id` that `ул. Н.Й.Вапцаров 007 вх.Г`
      resolves to — the endpoint takes `address_id`, not an address string — returns
      district `02` with nurseries, kindergartens **and** preschools: the three-kind
      parity the ticket names, where local previously returned `null / 0 / 4 / 0`.
      Parity with production is judged on a normalised projection (district plus the
      sorted `(institution_kind, external_id, reception_kind)` set), since surrogate
      ids do not correspond across databases
- [ ] `GET /api/institutions/by-source/kindergarten/46` returns ДГ№13 "Мир" with its
      4 branches, each carrying coordinates
- [ ] `SELECT count(*) FROM institutions` is 95 — 77 from the snapshot plus the
      fixture's 18, derived from the committed artifacts rather than asserted as a
      constant — and every `(kind, external_id)` in the frontend's
      `institutions-manifest.json` resolves
- [ ] All 18 legacy nurseries carry a non-null `district_code`, and
      `python -m yasli.ingest validate-match-data` reports
      `nursery_without_district:0`
- [ ] With any **independently required** seed step sabotaged — migration, ГРАО,
      snapshot ingest, legacy institutions, or locations — the seed exits non-zero
      and names the step and the failed check. (`restamp-districts` is deliberately
      excluded: on a clean seed ingest's gated passes have already stamped
      everything, so skipping it is unobservable. Its value is on a *dirty*
      database, and TASK-008 proves it there instead.)
- [ ] It never reports success over a database that is wrong in either direction:
      half-seeded, or carrying state the committed artifacts do not account for.
      `verify` fails on institutions outside the snapshot∪fixture union *and* on
      `address_institutions` edges the snapshot does not describe, naming them —
      an extra nursery in a район and an extra catchment edge each change what
      `/api/match` returns
- [ ] `python -m yasli.seed verify` is runnable on its own and exits non-zero on a
      database that has never been seeded
- [ ] `python -m yasli.seed freeze` regenerates both committed artifacts, and
      re-running the seed from the regenerated files reproduces the same row counts
- [ ] README quickstart and `docs/OPERATIONS.md` describe the command, the refresh
      cadence, and what a local database does and does not contain versus production
- [ ] `just be-test` and `just be-lint` pass

## Tasks

Task state lives here. Tasks are appended by `scripts/add_task.py` and
`scripts/add_final_task.py`. Update the checkboxes as work progresses.

- [x] TASK-001: Load the ГРАО KADS file from a committed zip
- [ ] TASK-002: Ingest a snapshot from a committed local file
- [ ] TASK-003: Seed the 18 legacy nursery institutions
- [ ] TASK-004: Add the yasli.seed orchestrator (depends on TASK-001,TASK-002,TASK-003)
- [ ] TASK-005: Verify the seeded database and refuse half-done (depends on TASK-004)
- [ ] TASK-006: Add the freeze maintainer command (depends on TASK-002,TASK-003,TASK-004)
- [ ] TASK-007: Document the seed command and the local-vs-production gap (depends on TASK-004,TASK-005,TASK-006)
- [ ] TASK-008: Final Validation
