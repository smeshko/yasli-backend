# Research: Persist source contact metadata

Curated findings only — no raw conversation transcripts.

## Key Files & Directories

- `src/yasli/snapshot_contract/models.py` — the vendored copy of the scraper's
  Pydantic contract. `Institution` is `extra="forbid"`, `frozen=True`; `address`
  is the existing precedent for an optional string with a non-empty validator
  (`_address_non_empty`, raises rather than coercing).
- `src/yasli/models/institution.py` — the ORM table. `address` is
  `String(256), nullable=True`; `district_code` is `String(2)` with a CHECK.
  Natural key is `UniqueConstraint("external_id", "kind")`.
- `src/yasli/ingest/pipeline.py` — three places touch each institution field:
  `_build_plan` (row dict, ~line 342), `_upsert_institutions.on_conflict_set`
  (~line 422), and the `value_columns_for_unchanged` tuple (~line 447) that
  drives the operator-readable inserted/updated/unchanged summary.
- `migrations/versions/0004_nursery_metadata.py` — the closest precedent
  migration: `op.add_column` per field plus a CHECK constraint, with a
  symmetrical `downgrade()`.
- `tests/snapshot_contract/test_schema_match.py` + `fixtures/snapshot.v2.schema.json`
  — the drift test and its hand-synced fixture.
- `src/yasli/routes/institutions.py` — both routes `select()` explicit columns,
  so new ORM attributes cannot leak into a response by accident.

## Architecture Facts

- The snapshot contract exists in two repos and must stay schema-equivalent.
  The backend copy is authoritative for *ingest*; the scraper copy is
  authoritative for *emission*. `extra="forbid"` on both sides makes the
  deploy order load-bearing: backend first, then scraper.
- The two committed schemas are **not** byte-identical today, by design:
  the scraper's `Snapshot.institutions` carries `Field(min_length=1)`
  (`"minItems": 1` in JSON Schema), the backend's does not, so the backend
  tolerates an empty-institutions snapshot. `diff` confirms this is the only
  difference as of 2026-08-17.
- `_pg_upsert` compares `value_columns_for_unchanged` to decide
  inserted/updated/unchanged. A field left out of that tuple is written but
  never counted, so a changed phone number would report as `unchanged`.
- `preserve_old_on_null_columns=("district_code",)` is the mechanism that stops
  a NULL snapshot value clobbering a backend-derived district stamp. It is
  opt-in per column and should **not** include the contact fields.
- `Institution.address` is `String(256)`. Contact values are short —
  `NAME_D` is a person's name, `EMAIL` a single address — except `TEL`, which
  is free-form and can carry several slash- or tab-separated numbers.

## Constraints

- No `schema_version` bump: the fields are optional with defaults, so every
  existing snapshot stays valid. Bumping would force a lockstep two-repo
  deploy for no gain.
- The API response must not change in this phase. `tests/test_institutions.py`
  asserts `set(body.keys()) == LIST_KEYS` / `DETAIL_KEYS`; those constants stay
  untouched until phase 1.4.
- The migration must be reversible — `tests/test_migrations.py` exercises the
  full up/down cycle.
- Postgres is the production dialect; the route/model tests run on in-memory
  SQLite via `Base.metadata.create_all`, so column types must work on both.

## Useful Commands

```bash
# Confirm the deliberate scraper-vs-backend schema divergence
diff ../scraper/schemas/snapshot.v2.schema.json \
     tests/snapshot_contract/fixtures/snapshot.v2.schema.json

# Regenerate the fixture from the vendored models (then re-remove "minItems")
cd backend && uv run python -c \
  'import json;from yasli.snapshot_contract import Snapshot;\
print(json.dumps(Snapshot.model_json_schema(),indent=2,sort_keys=True,ensure_ascii=False))'

# Full local loop
just db-reset && just be-ingest && just be-test && just be-lint

# Prove the new columns stay NULL under the current snapshot
just db-psql -c "SELECT count(*) FROM institutions WHERE phone IS NOT NULL"
```

## Uncertainty

- **Column width for `phone`.** The source packs multiple numbers into one
  free-form `TEL` string. Resolved: use `String(128)` for `phone` and
  `String(256)` for `website`/`email`/`director`, matching `address`'s
  generosity. If a real value overflows, ingest fails loudly on the insert
  rather than truncating — acceptable, and phase 1.2's live run will surface it
  before production ever sees it.
- **Whether to reject or coerce empty strings.** Resolved: reject, matching
  `address`. The scraper is responsible for emitting `null`, and it already
  does this for `address` via `_normalise_address`.
- **Whether the fields should be part of the `unchanged` comparison.** Resolved:
  yes. Leaving them out would make a corrected phone number invisible in the
  ingest summary, which is the operator's only signal that a refresh did
  anything.

## References

- `openspec/docs/INSTITUTION_DETAIL_MAP_RESEARCH.md` §1 (field coverage per
  reception), §8 (impact surface, including the deploy-order constraint)
- `openspec/docs/ARCHITECTURE.md` — the scraper → R2 → ingest → API pipeline
- `docs/artifacts/epics/01-institution-data-foundation.md` — phase 1.1
- `migrations/versions/0004_nursery_metadata.py` — precedent migration
