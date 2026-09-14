# Plan: Persist source contact metadata

Status: done
Branch: feature/institution-contact-fields-contract
Risk: medium
Epic: 01 — Institution data foundation ([epic](../../../epics/01-institution-data-foundation.md))
Phase: 1.1 — Persist source contact metadata
Linear: YAS-6
Created: 2026-08-17

## Goal

The backend accepts and stores `phone`, `email`, `director` and `website` on
institutions, tolerating snapshots that omit them — so the scraper can start
emitting them in phase 1.2 without ingest rejecting the snapshot.

## Scope

- Add four optional fields to the vendored snapshot contract
  (`src/yasli/snapshot_contract/models.py`), rejecting empty strings the same
  way `address` already does.
- Hand-sync `tests/snapshot_contract/fixtures/snapshot.v2.schema.json` so the
  drift test still passes while the scraper repo is one phase behind.
- Add four nullable columns to `institutions` (ORM model + Alembic `0009`).
- Map the fields in `ingest/pipeline.py` — `_build_plan`, the upsert's
  `on_conflict_set`, and `value_columns_for_unchanged`.
- Extend the ingest and contract tests so both a snapshot carrying the fields
  and one omitting them pass.

## Out of Scope

- Exposing any of the new fields through the API — that is phase 1.4. The
  existing "exactly these keys" assertions in `tests/test_institutions.py` must
  keep passing untouched, which is this plan's proof that nothing leaked.
- Emitting the fields from the scraper — phase 1.2.
- Coordinates and branches — phase 1.3.
- Bumping `schema_version`. The fields are additive and optional; the contract
  stays at v2.

## Research Summary

See [RESEARCH.md](./RESEARCH.md). The short version:

- `dg.uslugi.io/lv/api/childhood` returns `TEL`, `EMAIL` and `NAME_D` for all 95
  source rows with zero missing, and `WEBSITE` for the 12 `pg` rows only. The
  scraper already fetches all of it and keeps only `ADDRESS`
  (`INSTITUTION_DETAIL_MAP_RESEARCH.md` §1).
- Both the scraper and the backend validate the snapshot with `extra="forbid"`,
  so the backend has to accept the fields **before** the scraper emits them.
  That ordering is the whole reason this phase exists separately.
- The drift test (`tests/snapshot_contract/test_schema_match.py`) compares the
  vendored models against a **hand-synced copy** of the scraper's committed
  schema. It is already deliberately divergent: the fixture omits the
  `"minItems": 1` the scraper's schema carries on `institutions`.

## Decisions

- **Reject empty strings rather than coercing them to NULL** — mirrors the
  existing `_address_non_empty` validator, so the contract has one rule for
  "absent" instead of two. The scraper normalises blanks to `None` before
  serialising (phase 1.2), so a rejection here means a real contract violation,
  not a routine empty cell.
- **Extend the existing `address` validator to cover all five fields** rather
  than adding four near-identical validators — one `@field_validator` with
  multiple field names, same error message shape.
- **Hand-edit the drift fixture in this phase, keeping the `minItems`
  divergence.** The fixture is documented as a manual sync point, and during a
  two-repo additive change the leading repo necessarily moves first. Phase 1.2
  regenerates the scraper schema and re-converges the two; its final validation
  diffs them and asserts `minItems` is the only remaining difference.
- **No `schema_version` bump.** Optional-with-default fields keep every existing
  snapshot valid, which is exactly the property the acceptance criteria test.
- **Preserve-on-NULL is *not* applied to the contact fields.** `district_code`
  uses `func.coalesce(excluded, existing)` because a NULL there means
  "backend-derived, don't clobber". A NULL contact field means the source
  genuinely has no value, so a plain overwrite is correct — otherwise a phone
  number removed at the source would stick forever.

## Risks

- **The drift test hides a real desync.** Hand-editing the fixture means a typo
  in the fixture and the same typo in the model cancel out. Mitigation:
  TASK-001 generates the fixture from the model and then *only* re-removes the
  `minItems` key, and phase 1.2 diffs against the independently regenerated
  scraper schema.
- **Migration `0009` runs against production data.** Four `ADD COLUMN ... NULL`
  statements with no default and no backfill — cheap and non-locking on modern
  Postgres, but `tests/test_migrations.py` must still exercise up and down.
- **Silent field leak into the API.** The routes select explicit columns, so a
  new ORM attribute cannot leak on its own; the existing `LIST_KEYS`/`DETAIL_KEYS`
  assertions catch it if someone widens the `select()`. Final validation compares
  real response bodies rather than trusting the key-set test alone.

## Acceptance Criteria

- [x] Ingesting the **current** production snapshot (no new fields) succeeds
      unchanged and leaves all four new columns NULL
- [x] Ingesting a snapshot that carries all four fields stores them verbatim
- [x] An empty-string value is rejected by the contract, never stored as `""`
- [x] Re-ingesting the same snapshot twice reports the institution rows as
      `unchanged` — the new fields participate in the change comparison
- [x] `GET /api/institutions` and `GET /api/institutions/:id` response bodies are
      byte-identical to before the change
- [x] `just be-test` and `just be-lint` pass

## Tasks

Task state lives here. Tasks are appended by `scripts/add_task.py` and
`scripts/add_final_task.py`. Update the checkboxes as work progresses.

- [x] TASK-001: Accept contact fields in the vendored snapshot contract
- [x] TASK-002: Add nullable contact columns to institutions (depends on TASK-001)
- [x] TASK-003: Map contact fields through ingest (depends on TASK-002)
- [x] TASK-004: Final Validation
