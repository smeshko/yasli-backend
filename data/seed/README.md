# `data/seed/`

The committed artifacts `python -m yasli.seed` loads instead of reaching
for R2, so a developer with a clone of this repo and an empty Postgres can
bring a local database to a production-like state without holding a single
credential.

## `snapshot.json.gz`

A frozen copy of `snapshots/varna/latest.json` — the same object the weekly
ingest pulls from R2 — gzipped at level 9.

| | |
| --- | --- |
| Source | R2 key `snapshots/varna/latest.json`, written by `yasli_scraper` |
| `scraped_at` | 2026-09-19T07:01:51Z |
| `schema_version` | 2 |
| Contents | 77 institutions — 53 kindergartens, 12 preschools, 12 nurseries — with their streets, addresses and catchment |
| Size | 24,087,331 bytes raw, 758,904 gzipped (~32×) |

`yasli.ingest.pipeline.DEFAULT_SNAPSHOT` points here, and
`python -m yasli.ingest --snapshot <path>` is the flag that reads it. The
file branch only produces bytes: validation, planning, the upserts and the
gated district-stamping are the same code an R2 ingest runs, so a local
seed exercises the real pipeline rather than a parallel loading path that
could drift from it.

### What it contains

Only what the source portal already publishes about public institutions —
names, addresses, contact details (phone, e-mail, director, website) and
catchment. There is no personal data in it beyond the publicly listed
director of each institution.

## `legacy_institutions.json`

The 18 `ДГ№X "…"/ с яслена група/` nursery rows (external ids 39–83) that
production has carried since before 2026-05-10 and that no current
snapshot creates. Without them a local database serves 77 institutions
where production serves 95, and 18 slugs in the frontend's
`institutions-manifest.json` resolve to nothing.

These are **not** a workaround for a data bug. They are stale entries
production has never retired; retiring them is a separate ticket, named as
out of scope by YAS-21.

`yasli.ingest.legacy_institutions_loader` upserts them on
`(kind, external_id)` and touches no other institution.

### It is a faithful copy, including what production lacks

Every one of the 18 carries `district_code: null` and `address: null`,
because that is what production holds — measured directly, 2026-09-20.
The earlier plan assumed production had an API-sourced район for these
rows; it does not, and no stamping pass supplies one (both
`district_stamp` passes exclude `kind='nursery'` on purpose, since nursery
districts are API-sourced).

The consequence is deliberate: these 18 route nowhere in `/api/match`,
exactly as they route nowhere in production. Production's four nurseries
for a район-02 address come entirely from the 12 *live* nurseries the
snapshot carries. Inventing a район here would make local return
nurseries production does not — the opposite of production-like. The
parser still range-checks the column against `01`–`05`, so a future
refresh that does find a район lands a checked value rather than a typo.

It follows that `python -m yasli.ingest validate-match-data` reports
`nursery_without_district:18` on a seeded local database. Production
reports the same 18 (and, unlike local, a non-zero `nursery_coverage_edges`
— the legacy rows carry ~36k catchment edges there, which nursery routing
ignores and which this fixture does not reproduce).

### Refreshing it

`python -m yasli.seed freeze` regenerates both files — the snapshot from R2
and the fixture from a configured database. It is a deliberate
maintainer action, not something CI does — each refresh adds ~760 KB to git
history, and `verify` prints the `scraped_at` above and warns once it is
more than 90 days old, so staleness is visible rather than silent.

A local database seeded from this file is **not** identical to production;
`docs/OPERATIONS.md` records the differences that matter.
