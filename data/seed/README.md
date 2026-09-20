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

### Refreshing it

`python -m yasli.seed freeze` regenerates this file from R2 (and the legacy
fixture beside it from a configured database). It is a deliberate
maintainer action, not something CI does — each refresh adds ~760 KB to git
history, and `verify` prints the `scraped_at` above and warns once it is
more than 90 days old, so staleness is visible rather than silent.

A local database seeded from this file is **not** identical to production;
`docs/OPERATIONS.md` records the differences that matter.
