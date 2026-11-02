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

The 18 stale `ДГ№X "…"/ с яслена група/` nursery rows an earlier version of
this directory carried as a fixture were retired by migration `0011`
(YAS-35). They remain in git history.

## Refreshing the snapshot

`python -m yasli.seed freeze` regenerates the snapshot from R2. It is a deliberate maintainer
action, not something CI does: each refresh adds ~760 KB to git history,
and `verify` prints the snapshot's `scraped_at` and warns once it is more
than 90 days old, so staleness is visible rather than silent.

It is the one command here that needs credentials. That is the point —
the maintainer pays the credential cost once so every other developer pays
none.

```bash
# See what would change; writes nothing.
railway run --service backend-ingest -- python -m yasli.seed freeze --dry-run

# Do it. Needs the four R2_* variables.
railway run --service backend-ingest -- python -m yasli.seed freeze

# Then re-seed locally and confirm the row counts are unchanged.
just db-reset && just be-seed
```

| flag | effect |
| --- | --- |
| `--dry-run` | report what would change, write nothing |

The snapshot is gzipped with `mtime=0`, so an unchanged snapshot produces
a byte-identical file and a refresh shows no spurious diff. If the rename
fails, the command exits non-zero and the committed file is unchanged.

---

A local database seeded from these files is **not** identical to
production; `docs/OPERATIONS.md` records the differences that matter.
