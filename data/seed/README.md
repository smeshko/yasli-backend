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

## Refreshing both files

`python -m yasli.seed freeze` regenerates the pair — the snapshot from R2,
the fixture from the configured database. It is a deliberate maintainer
action, not something CI does: each refresh adds ~760 KB to git history,
and `verify` prints the snapshot's `scraped_at` and warns once it is more
than 90 days old, so staleness is visible rather than silent.

It is the one command here that needs credentials. That is the point —
the maintainer pays the credential cost once so every other developer pays
none.

```bash
# See what would change; writes nothing.
railway run --service backend-ingest -- python -m yasli.seed freeze --dry-run

# Do it. Needs the four R2_* variables and read access to production.
railway run --service backend-ingest -- python -m yasli.seed freeze

# Then re-seed locally and confirm the row counts are unchanged.
just db-reset && just be-seed
```

`railway run --service backend-ingest` supplies the `R2_*` variables, but
its `DATABASE_URL` points at `postgres.railway.internal`, which does not
resolve from a laptop. Pass the Postgres service's `DATABASE_PUBLIC_URL`
instead — via a file or `railway connect`, not by pasting the URL into a
shell history.

| flag | effect |
| --- | --- |
| `--dry-run` | report what would change, write nothing |
| `--snapshot-only` | refresh the snapshot; keep and re-check the committed fixture |
| `--legacy-only` | re-derive the fixture against the committed snapshot; no R2 needed |
| `--allow-shrink` | permit a derived fixture with fewer rows than the committed one |

### The guards, and what they are for

The two files are a **pair**, because the fixture loader upserts on
`(kind, external_id)`. A fixture row whose key has since become a live
snapshot row would overwrite current data with a months-old copy — that,
not staleness, is the failure that costs data. So:

- both candidates are built in a temp directory and checked for key
  overlap **as a pair**; on overlap nothing is published, the command
  exits 3 and names the colliding keys and the two ways out;
- an **empty** derived fixture leaves the file untouched and says so, so a
  maintainer pointed at their own local database cannot blank all 18 rows
  in a way that looks like a legitimate refresh in review;
- a **shrinking** fixture is refused without `--allow-shrink`, naming the
  rows that would disappear — the empty-diff guard alone does not catch a
  partial database;
- the snapshot is gzipped with `mtime=0`, so an unchanged snapshot
  produces a byte-identical file and a refresh shows no spurious diff.

Publishing two files with two `os.replace` calls is **not** atomic. The
window is two syscalls wide, and if the second rename fails the command
says both files may now disagree and tells you to run
`git checkout -- data/seed/`, rather than reporting success. See
DECISIONS.md D8 for why a versioned-directory pointer swap was not taken.

---

A local database seeded from these files is **not** identical to
production; `docs/OPERATIONS.md` records the differences that matter.
