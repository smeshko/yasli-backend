# Project — Institution profiles

Status: planned
Created: 2026-09-14
linear_project: c980a4e3-e9b6-4dcb-af33-53cb3c2cd705

## Goal

Give every Varna nursery, kindergarten and preschool a complete, shareable
profile: where it is, how to reach it, which buildings it occupies and what it
serves — reachable from a search result or a browsable directory. Search today answers "who is responsible for my address";
this project answers "tell me more about this institution" (PRD jobs #2 and #3).

The work spans all three repos, each of which carries its own copy of this
charter linked to the same Linear Project.

## Scope

- Backend: contact fields, curated coordinates and the enriched profile API
  (backend epic 01). The free-places live read (backend epic 02) is
  **deferred as of 2026-09-19** — the source table was measured 88 days stale
  and unchanged in a month; see that epic for the numbers.
- Scraper: carrying the source's contact metadata into the snapshot (scraper epic 01).
- Frontend: the detail page with map (frontend epic 01); the browse-all directory
  and free places on the page (frontend epic 02).

## Member epics

Epics filed under this project (managed by `create-epic --project <slug>` /
`link_epic.py`; do not hand-edit the list below):

<!-- EPICS -->
- [02 — Free-places API](../epics/02-free-places-api.md)
- [01 — Institution data foundation](../epics/01-institution-data-foundation.md)

## Out of scope

- Publishing anything derived from `/lv/api/new-public-last-rating` — a privacy decision, not a feature.
- Street-level catchment geometry, and any pin for the parent's own address — ruled out on measured grounds.
- Ingesting institutions that publish no catchment (the free-places gap) — a data-model change and its own project.
