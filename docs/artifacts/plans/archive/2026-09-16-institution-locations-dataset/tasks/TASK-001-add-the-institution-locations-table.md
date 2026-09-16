# TASK-001: Add the institution_locations table

Depends on: None
Suggested commit: `feat(db): add institution_locations reference table`

## Goal

A table that can hold one row per building — main or branch — keyed to an
institution by its natural key, with mandatory provenance columns.

## Files

- `src/yasli/models/institution_location.py` — the ORM model
- `src/yasli/models/__init__.py` — export it alongside the existing models
- `migrations/versions/0010_institution_locations.py` — `down_revision = "0009"`
- `tests/test_models.py` — construction and constraint coverage
- `tests/test_constraints.py` — the CHECK constraints
- `tests/test_migrations.py` — the up/down cycle, **and** the hard-coded
  revision chain in `test_round_trip_upgrade_downgrade_upgrade`: head is
  asserted as `"0009"` twice, `downgrade -1` as `"0008"` with the contact
  columns gone, `downgrade -2` as `"0006"` with no `settlements` table. With
  `0010` those become `0010` / `0009` (contact columns present,
  `institution_locations` gone) / `0008` (settlements present) — the same
  shift the 0009 plan made

## Schema

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `id` | `BigInteger().with_variant(Integer, "sqlite")` PK | no | surrogate; the loader truncates, so this is not a join key. The variant is what lets the SQLite loader tests insert rows without an `id` — a bare `BigInteger` PK is `BIGINT`, which SQLite does not autoincrement (`NOT NULL constraint failed`, verified 2026-09-15). The migration still creates `BIGINT` on Postgres |
| `kind` | String(16) | no | CHECK against `KIND_VALUES`, as on `institutions` |
| `external_id` | String(16) | no | with `kind`, the join key into `institutions` |
| `role` | String(8) | no | CHECK `IN ('main','branch')` |
| `label` | String(128) | no | `''` when absent — the `grao_addresses` convention |
| `address` | String(256) | no | `''` when absent (the 3 name-only branches) |
| `lat` | Numeric(9,6) | yes | NULL only when `precision = 'none'` |
| `lon` | Numeric(9,6) | yes | same |
| `precision` | String(16) | no | CHECK `IN ('building','approximate','none')` — `street` dropped, nothing can produce it |
| `source` | String(16) | no | CHECK `IN ('osm_poi','nominatim','manual')` |
| `verification` | String(8) | no | CHECK `IN ('auto','human')` — how the row was decided |
| `verified_at` | Date | no | the date the row was decided: the seed run for `auto`, the review for `human` |

Constraints beyond the CHECKs above:

- `UniqueConstraint("kind", "external_id", "role", "label", "address")`
- CHECK: `(lat IS NULL) = (lon IS NULL)` — a half-coordinate is always a bug
- CHECK: `precision = 'none'` iff `lat IS NULL` — provenance and data agree
- CHECK: `NOT (source = 'manual' AND verification = 'auto')`
- CHECK: `verification <> 'auto' OR (source = 'osm_poi' AND role = 'main' AND precision = 'building')`
  — an auto-accepted row can only be a unique POI match on a main building;
  this is the part of the auto-accept rules the database *can* enforce
- `ForeignKeyConstraint(["external_id", "kind"], ["institutions.external_id",
  "institutions.kind"], ondelete="RESTRICT", onupdate="CASCADE",
  name="fk_institution_locations_institution")` — targets the natural key
  `uq_institutions_external_id_kind`, which *is* stable across a re-ingest.
  Ingest upserts institutions by that key and never deletes them
  (`pipeline.py` only counts disappeared rows), so the FK cannot block
  `just be-ingest`. Postgres enforces it (`tests/test_constraints.py`); the
  SQLite loader tests do not enforce FKs without `PRAGMA foreign_keys=ON`,
  which is one reason the loader keeps its own pre-TRUNCATE check for a
  friendlier error
- Partial unique index `uq_institution_locations_main` on `(kind, external_id)`
  `WHERE role = 'main'` — exactly one `main` per institution. Declare it as
  `Index(..., unique=True, postgresql_where=text("role = 'main'"),
  sqlite_where=text("role = 'main'"))` so `create_all` on SQLite enforces it
  too, and `op.create_index(..., unique=True, postgresql_where=...)` in the
  migration. Together with the UNIQUE tuple's leading columns it also serves
  phase 1.3's `(kind, external_id)` lookup, so there is no separate plain index

## Acceptance

- [ ] `alembic upgrade head` creates the table with every constraint above
- [ ] `alembic downgrade -1` drops it cleanly and leaves `0009` intact
- [ ] Inserting a row with `lat` set and `lon` NULL is rejected
- [ ] Inserting `precision='none'` with a coordinate is rejected, and
      `precision='building'` without one is rejected
- [ ] Inserting `role='satellite'`, `source='guess'`, `precision='street'` or
      `verification='maybe'` is rejected
- [ ] Inserting `source='manual'` with `verification='auto'` is rejected — a
      hand-placed pin cannot have been auto-accepted
- [ ] Inserting `verification='auto'` with `source='nominatim'`, or with
      `role='branch'`, or with `precision='approximate'` is rejected
- [ ] Two rows differing only by `label` both insert; an exact duplicate is rejected
- [ ] A second `main` row for the same `(kind, external_id)` is rejected even
      with a different `address`; two `branch` rows for it both insert
- [ ] On Postgres, inserting a row whose `(kind, external_id)` matches no
      institution is rejected, and deleting an institution that has location
      rows is rejected (RESTRICT)
- [ ] `Base.metadata.create_all` works on SQLite so the loader tests can run
      in-memory, **and** `session.execute(insert(InstitutionLocation), rows)`
      with no `id` in the rows succeeds there — the other tables never proved
      this (`grao_addresses` has a composite natural PK)
- [ ] `uv run alembic check` reports no model/migration drift
- [ ] `tests/test_migrations.py`'s revision-chain assertions pass at `0010`:
      head `0010`; `downgrade -1` → `0009` with the contact columns present and
      no `institution_locations` table; `downgrade -2` → `0008` with
      `settlements` present

Evidence: `uv run pytest tests/test_models.py tests/test_constraints.py tests/test_migrations.py -v`,
plus `docker compose exec -T postgres psql -U yasli -d yasli -c "\d institution_locations"`
run from the `yasli/` parent (`just db-psql` is interactive and takes no arguments).

## Steps

### RED
- [ ] Add constraint tests for each rejection case above

### GREEN
- [ ] Write the model, following `institution.py`'s `__table_args__` style —
      `CheckConstraint("kind IN ('" + "','".join(KIND_VALUES) + "')", ...)`
- [ ] Write `0010_institution_locations.py` with `op.create_table`, the partial
      unique index, and a symmetrical `downgrade()`
- [ ] Shift the revision-chain assertions in `tests/test_migrations.py` to
      `0010` / `0009` / `0008` and adjust the per-step column and table
      expectations to match

### REFACTOR
- [ ] Move the `precision`, `source` and `verification` value tuples into `models/types.py`
      next to `KIND_VALUES`, so the loader and phase 1.3 import them rather than
      restating string literals

## Notes

No foreign key to `institutions.id`: the serial is not stable across a
re-ingest. The FK targets the natural key `(external_id, kind)` instead, which
is — ingest upserts on it and never deletes institutions, so `RESTRICT` can
never fire during `just be-ingest`. The loader still checks the pairs itself
before TRUNCATE (TASK-003) so a bad file fails with the pair named rather
than a constraint error, and so the SQLite tests cover it.

`Numeric(9,6)` gives ~11 cm resolution and avoids float drift in the round-trip
through CSV. Varna's coordinates are around `43.2, 27.9`, so 3 integer digits
and 6 decimals is comfortable.

The `''`-not-NULL convention for `label` and `address` exists so the UNIQUE
constraint actually constrains — in Postgres, NULLs are distinct, so a nullable
`label` would let identical rows insert repeatedly.
