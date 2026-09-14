# TASK-001: Accept contact fields in the vendored snapshot contract

Depends on: None
Suggested commit: `feat(contract): accept phone, email, director and website`

## Goal

`Institution` in the vendored snapshot contract accepts four new optional
string fields, and the drift fixture is re-synced so the contract test passes.

## Files

- `src/yasli/snapshot_contract/models.py` — add `phone`, `email`, `director`,
  `website` as `str | None = None`; widen the existing `_address_non_empty`
  validator to cover all five nullable strings and rename it accordingly
- `tests/snapshot_contract/fixtures/snapshot.v2.schema.json` — regenerate from
  the updated models, then re-remove the `"minItems": 1` key so the deliberate
  backend-tolerates-empty divergence survives
- `tests/snapshot_contract/test_schema_match.py` — unchanged; it is the gate
- `tests/snapshot_contract/test_contract_fields.py` (new) — the contract unit
  tests below; they build payloads inline and need no database. (There is no
  snapshot factory in `tests/ingest/conftest.py` — that file only provides the
  testcontainers Postgres `engine`/`session`; ingest tests build payloads from
  `tests/ingest/fixtures/snapshot_v2_minimal.json`.)

## Acceptance

- [ ] A snapshot payload omitting all four fields validates, and the parsed
      `Institution` has `None` for each
- [ ] A snapshot payload carrying all four validates and preserves them verbatim,
      including a `phone` holding several slash-separated numbers
- [ ] `Institution(phone="")` raises `ValidationError`; same for `email`,
      `director`, `website` and the pre-existing `address`
- [ ] A payload with an unknown extra field still raises `ValidationError` —
      `extra="forbid"` is intact
- [ ] `test_vendored_models_match_canonical_scraper_schema` passes
- [ ] The regenerated fixture differs from the scraper's committed
      `schemas/snapshot.v2.schema.json` by exactly two things: the absent
      `"minItems": 1` (pre-existing) and the four new contact properties,
      present **only on the backend side** — the scraper is unchanged until
      phase 1.2. The drift test cannot prove scraper convergence (it compares
      the model to this hand-edited fixture); that independent check is phase
      1.2's final validation.

Evidence: `uv run pytest tests/snapshot_contract -v` output, plus the
`diff ../scraper/schemas/snapshot.v2.schema.json tests/snapshot_contract/fixtures/snapshot.v2.schema.json`
output showing only the `minItems` line and the four backend-only properties.

## Steps

### RED
- [ ] Before touching code, capture the API response baseline described in
      TASK-004 (base SHA, `scraped_at`, the two saved bodies) — it cannot be
      reproduced cleanly once the columns exist
- [ ] Add contract tests: contacts-absent parses to `None`; contacts-present
      round-trips verbatim; empty string raises for each of the five fields;
      extra field still forbidden
- [ ] Watch the drift test fail once the model gains fields (the fixture is
      still the old one) — that failure is the signal the fixture needs syncing

### GREEN
- [ ] Add the four fields to `Institution`, ordered after `address` so the
      generated schema stays readable
- [ ] Replace `_address_non_empty` with a single validator over
      `("address", "phone", "email", "director", "website")`
- [ ] Regenerate the fixture from `Snapshot.model_json_schema()` with
      `indent=2, sort_keys=True, ensure_ascii=False` and a trailing newline —
      the same rendering `gen_schema.py` uses — then delete the `"minItems"` line

### REFACTOR
- [ ] Update the module docstring's note about the two copies to mention that
      this repo is intentionally one phase ahead until 1.2 lands

## Notes

The validator must not reject `None` — only the empty string. `address` already
gets this right; keep the `if value == "":` comparison rather than a falsy check,
or `None` starts raising.

Do **not** add `Field(min_length=1)` to the new fields as a shortcut for the
validator: that would emit `"minLength": 1` into the schema, which the scraper's
regenerated schema in phase 1.2 would also have to carry, and it changes the
error type from a clear message to a generic constraint failure.
