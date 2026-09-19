# TASK-001: Add address, contacts, district and the infant flag to the detail response

Depends on: None
Suggested commit: `feat(api): expose address, contacts, district and infant flag on the institution detail`

## Goal

`GET /api/institutions/{institution_id}` carries the seven scalar columns the
`institutions` table already stores — `address`, `phone`, `email`,
`director`, `website`, `district_code`, `has_infant_group` — each present as
`null` when absent, never omitted.

## Files

- `src/yasli/routes/institutions.py` — `InstitutionDetail` gains, after
  `last_seen_at` and before `coverage`, in this order: `address: str | None`,
  `phone: str | None`, `email: str | None`, `director: str | None`,
  `website: str | None`, `district_code: DistrictCode | None`,
  `has_infant_group: bool` — **all without defaults**. `get_institution`'s
  row SELECT adds the seven columns and the constructor passes them through.
  Module docstring: say the detail is the enriched profile.
- `tests/test_institutions.py` — `DETAIL_KEYS` becomes an explicit literal
  set (it is derived from `LIST_KEYS` today; the derivation stops holding
  between this task and TASK-004, so define both sets independently). New
  tests below. `_seed_institutions` already forwards arbitrary kwargs to
  `Institution(**payload)`, so fixtures set contacts directly.
- `tests/test_institutions_openapi.py` — `DETAIL_KEYS` grows the same way;
  add a required-nullable assertion.

## Acceptance

- [ ] Detail body keys are exactly the existing seven plus the seven new
      ones; list body keys are still the existing six (the list is TASK-004's)
- [ ] An institution seeded with no contacts returns `"address": null`,
      `"phone": null`, `"email": null`, `"director": null`, `"website": null`,
      `"district_code": null` and `"has_infant_group": false` — every key
      present
- [ ] Stored values come back verbatim: phone, e-mail, director, website,
      `district_code = "03"`, `has_infant_group = true`
- [ ] The detail ETag changes when a contact field changes (`UPDATE` the
      phone between two requests)
- [ ] OpenAPI: `InstitutionDetail.properties` equals the new key set; each of
      the six nullable fields appears in the schema's `required` list **and**
      its schema admits `null` (an `anyOf` containing `{"type": "null"}`);
      `district_code` resolves to the enum `{"01","02","03","04","05"}`;
      `has_infant_group` is `boolean` and required
- [ ] `search_norm`, `address_id`, `institution_id` still absent — the
      existing negative tests keep passing
- [ ] `uv run pytest tests/test_institutions.py tests/test_institutions_openapi.py -v`
      green; `just be-lint` clean

Evidence: the `pytest -v` output for both modules, plus two curls against the
local database with `just be-api` running. Resolve each id first — serials
are reassigned when the database is rebuilt, so never write one down in
advance: from `yasli/`,
`ID=$(docker compose exec -T postgres psql -U yasli -d yasli -tAc "SELECT id FROM institutions WHERE kind='nursery' AND external_id='1'")`,
then `curl -s localhost:8000/api/institutions/$ID | python3 -m json.tool`
(nursery ДЯ №1: `district_code` `"01"`, `phone` non-null, `website` null),
and the same for `kind='kindergarten' AND external_id='46'` (ДГ№13 "Мир":
`district_code` null locally, `website` null, `has_infant_group` per the
name marker).

## Steps

### RED
- [ ] Make `LIST_KEYS` and `DETAIL_KEYS` independent literals in both test
      modules and add the seven keys to `DETAIL_KEYS` — the exact-key tests
      now fail
- [ ] `test_detail_absent_fields_are_null_not_omitted` — seed an institution
      with no contacts; assert each key is present and `None`, and
      `has_infant_group is False`
- [ ] `test_detail_returns_contact_fields_verbatim` — seed all seven; assert
      equality
- [ ] `test_detail_etag_changes_when_contact_changes` — two requests around an
      `UPDATE institutions SET phone = …` through `db._SessionLocal`
- [ ] OpenAPI: `test_institutions_detail_new_fields_are_required_nullable` —
      for each nullable field, `name in schema["required"]` and the resolved
      property schema has an `anyOf` member `{"type": "null"}`;
      `district_code` enum via `_enum_values`

### GREEN
- [ ] Extend `InstitutionDetail`, the row SELECT and the constructor call

### REFACTOR
- [ ] If the row SELECT's column list is now long, pull it into a module-level
      tuple `_INSTITUTION_COLUMNS` — TASK-003's shared builder and TASK-004's
      list will want it

## Notes

Declare the new fields **without** `= None`. With a default, Pydantic drops
the field from `required`, and `openapi-typescript` then emits
`address?: string | null` — which lets the frontend treat "absent" and
`null` as different things, exactly what the epic forbids.

`has_infant_group` is NOT NULL in the database, so it is a plain `bool`.

Do not touch `InstitutionListItem` here; TASK-004 owns the list and the list
tests must stay green through TASK-001..003.
