# TASK-002: Add location and branches to the detail response

Depends on: TASK-001
Suggested commit: `feat(api): expose location and branches on the institution detail`

## Goal

The detail carries the main building's pin as `location` and every branch
building as `branches`, read from `institution_locations` by
`(kind, external_id)`, with `null` wherever no pin exists.

## Files

- `src/yasli/routes/institutions.py` — new models `Location` (`lat: float`,
  `lon: float`, `precision: Literal["building", "approximate"]`) and `Branch`
  (`label: str | None`, `address: str | None`, `location: Location | None`);
  `InstitutionDetail` gains `location: Location | None` and
  `branches: list[Branch]` after `has_infant_group`, before `coverage`.
  Helpers: `_location(lat, lon, precision) -> Location | None` (returns
  `None` when `lat is None`, else floats), `_blank_to_none(value: str) ->
  str | None`, and `_locations_for(session, kind, external_id) ->
  tuple[Location | None, list[Branch]]` — one SELECT over
  `InstitutionLocation` filtered by kind and external_id, ordered by
  `case((InstitutionLocation.role == "main", 0), else_=1)`, `label`,
  `address`; the first `main` row becomes `location`, every `branch` row a
  `Branch`.
- `tests/test_institutions.py` — `_seed_locations(client, rows)` helper with
  defaults `role="main"`, `label=""`, `address=""`, `lat/lon=None`,
  `precision="none"` when no coordinate else `"building"`, `source="manual"`,
  `verification="human"`, `verified_at=date(2026, 9, 15)`; a ДГ№13-shaped
  fixture (`{"id": 13, "kind": "kindergarten", "external_id": "46"}` with one
  pinned `main` at `43.209589, 27.926883` and four pinned `branch` rows with
  distinct addresses); an institution whose `main` is `precision="none"`; an
  institution with no location row; an institution with two name-only
  branches (`label` set, `address=""`, no coordinate).
- `tests/test_institutions_openapi.py` — `Location` and `Branch` component
  schemas.

## Acceptance

- [ ] Detail keys are TASK-001's set plus `location` and `branches`
- [ ] A pinned `main` row gives
      `{"lat": 43.209589, "lon": 27.926883, "precision": "building"}` —
      floats, six decimals intact
- [ ] `location` is `null` when the `main` row has `precision = 'none'` and
      when the institution has no location row at all; `branches` is `[]` in
      the no-row case
- [ ] Each branch is `{label, address, location}`; a stored `""` label or
      address comes out as `null`; a branch without a coordinate is present
      with `location: null`
- [ ] Branches are ordered by `label, address` and the order is identical
      across two requests; the `main` row never appears in `branches`
- [ ] The detail ETag changes when a coordinate is updated and when a branch
      row is added
- [ ] OpenAPI: `Location.properties == {lat, lon, precision}` with
      `precision` enum exactly `{building, approximate}` (no `none`);
      `Branch.properties == {label, address, location}` with `label`,
      `address`, `location` required-nullable; `InstitutionDetail.location`
      required-nullable and `branches` an array of `Branch`; no schema under
      `components` for these responses mentions `source`, `verification`,
      `verified_at` or `role`
- [ ] Existing `test_detail_ordering_is_stable` and the coverage tests are
      untouched and green

Evidence: `pytest -v` for both modules; against the local database, resolve
ДГ№13's id by natural key (TASK-001's psql query with
`kind='kindergarten' AND external_id='46'`) and
`curl -s localhost:8000/api/institutions/$ID | python3 -m json.tool` showing
the main pin plus four branches with distinct coordinates, including the
`ул. Н. Михайловски 1А` branch on the same street as the main building.

## Steps

### RED
- [ ] `_seed_locations` helper and the fixtures above
- [ ] `test_detail_location_is_main_pin_as_floats`,
      `test_detail_location_null_without_pin` (both the `none` row and the
      no-row case), `test_detail_branches_shape_and_blank_to_null`,
      `test_detail_branches_ordered_by_label_then_address`,
      `test_detail_branches_exclude_main`, `test_detail_etag_changes_when_location_changes`
- [ ] OpenAPI: `test_institutions_location_and_branch_schemas`

### GREEN
- [ ] Models, helpers, `_locations_for`, the two new constructor arguments

### REFACTOR
- [ ] Keep `_locations_for` self-contained: TASK-003's shared builder and
      TASK-004's list item both reuse `_location`

## Notes

`InstitutionLocation.lat`/`lon` are `Decimal` (`Numeric(9, 6)`); convert with
`float()` explicitly rather than trusting `jsonable_encoder`, which would turn
an integral `Decimal` into an `int`.

`precision = 'none'` rows always have NULL coordinates (CHECK constraint), so
`_location` can key on `lat is None` and the `precision` literal on the
response model can safely exclude `none`.

Order by `label, address`, never by `id`: the loader truncates and reinserts,
so `id` changes on every run. The UNIQUE tuple makes `(label, address)`
unique within one institution's branches.

Seeding `InstitutionLocation` on SQLite prints
`SAWarning: Dialect sqlite+pysqlite does *not* support Decimal objects natively`.
The loader tests already live with it; do not add a warnings filter unless it
turns into an error.
