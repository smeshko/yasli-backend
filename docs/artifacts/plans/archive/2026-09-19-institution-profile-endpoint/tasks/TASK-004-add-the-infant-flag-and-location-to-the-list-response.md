# TASK-004: Add the infant flag and location to the list response

Depends on: TASK-002
Suggested commit: `feat(api): expose has_infant_group and location on the institution list`

## Goal

Every list item carries `has_infant_group` and the main building's
`location` (or `null`), with the list's row count, ordering and cache
behaviour unchanged.

## Files

- `src/yasli/routes/institutions.py` — `InstitutionListItem` gains
  `has_infant_group: bool` and `location: Location | None` after
  `last_seen_at`; `list_institutions` selects `Institution.has_infant_group`,
  `InstitutionLocation.lat`, `.lon`, `.precision` through
  `.outerjoin(InstitutionLocation, and_(InstitutionLocation.kind ==
  Institution.kind, InstitutionLocation.external_id ==
  Institution.external_id, InstitutionLocation.role == "main"))` with the
  `ORDER BY` untouched; `_institution_item` builds `location` with TASK-002's
  `_location`.
- `tests/test_institutions.py` — `LIST_KEYS` grows by two; new tests below;
  reuse `_seed_locations`.
- `tests/test_institutions_openapi.py` — `LIST_KEYS` grows by two; assert the
  list item's `location` references the same `Location` schema as the detail.

## Acceptance

- [ ] List item keys are exactly the existing six plus `has_infant_group` and
      `location`
- [ ] With three institutions — a pinned `main`, a `main` at
      `precision = 'none'`, and no location row — the list has exactly three
      items in the existing order, with `location` an object, `null`, `null`
- [ ] An institution with one `main` and four `branch` rows appears exactly
      once
- [ ] `has_infant_group` reflects the column for `true` and `false`
- [ ] The list ETag changes when a `main` coordinate changes;
      `test_list_ordering_is_kind_display_order_then_name`,
      `test_list_ordering_is_stable`, `test_list_etag_stable_across_requests`
      are unchanged and green
- [ ] `test_list_does_not_include_coverage_or_server_only_fields` still passes
      and additionally asserts no `branches`, `source`, `verification`,
      `verified_at` or `role` in list items
- [ ] OpenAPI: list item `properties` equals the new set; `location` is
      required-nullable and its `anyOf` references `#/components/schemas/Location`;
      the list operation still declares no query or path parameters

Evidence: `pytest -v` for both modules; against the local database,
`curl -s localhost:8000/api/institutions | python3 -c 'import json,sys; d=json.load(sys.stdin); print(len(d), sum(1 for i in d if i["location"]), sum(1 for i in d if i["has_infant_group"]))'`
printing `77`, the pinned count (expected 77 — the committed CSV has no
unpinned `main` rows) and the infant-group count.

## Steps

### RED
- [ ] Grow `LIST_KEYS` in both modules — the exact-key tests fail
- [ ] `test_list_location_from_main_row_or_null`,
      `test_list_does_not_duplicate_institutions_with_branches`,
      `test_list_has_infant_group_reflects_column`,
      `test_list_etag_changes_when_location_changes`; extend the server-only
      negative test
- [ ] OpenAPI: extend the list schema test; add
      `test_institutions_list_location_reuses_location_schema`

### GREEN
- [ ] Outer join, two new columns, two new constructor arguments

### REFACTOR
- [ ] If `_INSTITUTION_COLUMNS` exists from TASK-001, check whether the list
      can share its scalar prefix without changing the selected column order

## Notes

The outer join is safe only because `uq_institution_locations_main` guarantees
at most one `main` row per `(kind, external_id)`. Keep `role == "main"` in the
`ON` clause: in a `WHERE` clause it turns the outer join into an inner one
and silently drops every institution that has no location row.

The list does **not** gain `address` or the contacts — those stay
detail-only (user decision, 2026-09-16).
