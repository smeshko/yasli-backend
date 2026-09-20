# Epic 02 — Free-places API

Status: deferred
Created: 2026-08-17
Deferred: 2026-09-19
Depends on: Epic 01
Project: institution-profiles
Linear: YAS-2 (https://linear.app/ivo-tsonev/issue/YAS-2)
Milestone: 56acf8f6-b6d9-4430-ae49-62e9aec24670

## Deferral (2026-09-19)

Not being built. The epic was scoped from a single measurement taken inside
the admission cycle; measured again out of season, the source carries nothing
worth serving.

Measured 2026-09-19, fetching all four receptions directly:

| Reception | Rows | Rows with any free place | Places total | `KLAS_DATE` | `IS_FINAL` |
| --- | --- | --- | --- | --- | --- |
| `garden` | 70 | 23 | 151 | 23-06-2026 | `1` |
| `infant` | 20 | 7 | 26 | 23-06-2026 | `1` |
| `pg` | 13 | 11 | 70 | 23-06-2026 | `1` |
| `jasla` | — | — | — | HTTP 403 (HTML error page, not JSON) | — |

- `KLAS_DATE` is **88 days old**, and `IS_FINAL = 1` — the round it describes
  closed in June.
- The `garden` payload fetched today is **byte-identical** (26,813 B) to the
  copy captured on 2026-08-17 in `scripts/fixtures/free_places_garden.json`.
  The table did not move in a month.

So for roughly nine months a year the endpoint would serve a frozen historical
artifact, and the epic's own mitigation for that — "the copy must lead with the
date, not the number" — is an admission that the number is usually not the
answer. Against that: a fetch/parse module for malformed free-form HTML, name
matching for 103 rows, branch attribution for 15, a cache with a stale-serve
path, and a standing liability on a third party's table shape.

Nothing depends on this epic inside the backend. The one consumer is
[frontend epic 02](../../../../frontend/docs/artifacts/epics/02-institution-directory-and-availability.md)
phase 2.2, a block on the detail page — not the page itself. That phase needs
its own decision.

**If this is revisited** — the natural moment is inside the next cycle, around
April, when the table is live and it is possible to see whether `KLAS_DATE`
moves weekly or daily and whether `IS_FINAL` flips mid-round. The groundwork
survives: the payload shape is recorded below and in research §1.1, a captured
fixture is committed, and `scripts/seed_institution_locations.py` already
parses this table's branch rows (`parse_branch_rows`, `dg_number`) and matches
them to institutions by ДГ number.

The phase below is left as written, as the specification to pick back up.

Linear has no deferred state, so YAS-2 and YAS-9 are tracked there as
`Canceled`, each carrying these measurements as a comment.

## Overview

The source portal publishes a live per-cohort availability table on an
unauthenticated endpoint that nothing in the project reads yet — the one
genuinely new answer we can give a parent beyond "who is responsible for my
address". This epic serves it from the backend; the detail-page block that shows
it is [frontend epic 02](../../../../frontend/docs/artifacts/epics/02-institution-directory-and-availability.md),
phase 2.2.

Free places refreshes independently of the weekly snapshot, so it gets its own
cache and its own visible date rather than borrowing the snapshot's freshness.

## Architecture references

- [INSTITUTION_DETAIL_MAP_RESEARCH.md](../../../../openspec/docs/INSTITUTION_DETAIL_MAP_RESEARCH.md) — the free-places payload shape and seasonality (§1.1), the branch rows inside it (§1.3), and the institutions it lists that we don't have (§1.4)
- [PRD.md](../../../../openspec/docs/PRD.md) — FR-14/FR-15 (freshness), §7.4
- [OPERATIONS.md](../../OPERATIONS.md) — where the cache/refresh behaviour of a live external read has to be documented

## Dependencies

- **Epic 01** — rows are matched to institutions and their branches, which Epic 01 phase 1.2 inventories.

## Out of scope

- Rendering free places — frontend epic 02, phase 2.2.
- Anything derived from `/lv/api/new-public-last-rating`. It is per-application data with registration numbers; republishing it in a friendlier form is a privacy decision, not a feature. Research §1.2.
- Reconciling the institutions that appear in free-places but not in the institution list (research §1.4). Closing that gap means ingesting institutions with no catchment, which is a data-model change and its own epic.
- Free places for nurseries — the source returns `null` for `jasla`.
- Any notification or watch feature on availability.

## Phase 2.1 — Free-places live read

**Plan**: _not created — epic deferred 2026-09-19, see above_

**Linear**: YAS-9 (https://linear.app/ivo-tsonev/issue/YAS-9)

**Goal**: The backend serves the source portal's free-places table as cached JSON, carrying its own date and finality flag.

### What to build

- A fetch + parse module for `POST https://dg.uslugi.io/lv/api/free-places` for receptions `garden`, `infant` and `pg`. The payload is `{KLAS_DATE, SPR_SWOBODNI_MESTA, IS_FINAL}` where the table is an HTML string — parse it into rows of institution name plus per-cohort counts, with the cohort labels taken from the table header (they are birth years for `garden`, group names for `pg`).
- Match rows to institutions by name, and keep the branch rows attributed to their parent — research §1.3 shows 15 rows are филиали. Rows that match nothing (research §1.4: 3 institutions we don't have) must be counted and logged, never silently dropped.
- A `GET /api/free-places` endpoint (or per-institution field — the plan decides) exposing counts plus `klas_date` and `is_final`. Cache with a TTL measured in hours, and serve the last good response if the source is unreachable rather than failing the detail page.
- Document the cadence and the failure behaviour in `docs/OPERATIONS.md`.
- The source is seasonal: outside the admission cycle the table can be all zeros or stale by months. The API must expose the date, never a bare number.

### Acceptance criteria

- [ ] The endpoint returns per-institution, per-cohort counts with `klas_date` and `is_final`
- [ ] Branch rows are attributed to their parent institution, and ДГ№13 "Мир"'s 5 rows are all accounted for
- [ ] Unmatched source rows are reported in the response metadata or logs with their names, not dropped
- [ ] A source outage returns the last cached payload with its original date; it never 500s the detail page
- [ ] Repeated requests inside the TTL do not hit the source portal
- [ ] Parsing is resilient to the free-form quirks in the table (inconsistent casing, embedded newlines, quotes glued to names)
- [ ] `just be-test` and `just be-lint` pass, with a recorded fixture of the live payload

### Validation

`curl` the endpoint and show the parsed output next to the raw source table for the same date. Show the cache holding on a second call, and the stale-serve path with the source blocked.

---

<!-- PHASES -->

## Epic-level acceptance criteria

- [ ] Every phase merged and its acceptance criteria met
- [ ] Availability numbers are never served without the date they were published
- [ ] Status row in [EPICS.md](./EPICS.md) updated to `Done`
