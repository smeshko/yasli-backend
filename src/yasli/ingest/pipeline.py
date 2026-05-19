"""Ingest orchestrator: fetch → validate → parse → upsert → log.

`run()` is the entrypoint that the CLI calls. It returns an
``IngestSummary`` so tests can assert on the counts and elapsed time
without scraping log lines.

Design notes (see ``s06-backend-ingest/design.md`` and
``address-centric-schema/design.md``):

- One transaction wraps the entire upsert phase. Rollback on any failure.
- ``INSERT … ON CONFLICT DO UPDATE`` for institutions, streets, and
  addresses; ``ON CONFLICT DO NOTHING`` for the address-institution
  composite PK — gives us idempotency without a read pass.
- Address upsert and junction insert are chunked at 5,000 rows so every
  statement stays under Postgres' 65,535 bound-parameter wire limit.
- Disappearance is computed AFTER commit by counting institutions whose
  ``last_seen_at`` is strictly older than the snapshot's ``scraped_at``.
- Skipped rows (unparseable number, unknown locality, smallint overflow)
  are logged out-of-band and counted in ``skipped_rows``; they don't
  abort the run.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from yasli.db import get_engine
from yasli.ingest import r2
from yasli.ingest.district_stamp import (
    AddressesStampSummary,
    InstitutionsStampSummary,
    stamp_addresses_unmatched,
    stamp_institutions_unmatched,
)
from yasli.ingest.normalise import (
    UnknownLocality,
    parse_street,
)
from yasli.ingest.parser import (
    NumberOutOfRange,
    UnparseableNumber,
    parse_number,
)
from yasli.models import Address, Institution, Street, address_institutions
from yasli.snapshot_contract import Snapshot

LATEST_KEY = "snapshots/varna/latest.json"

# Postgres' wire protocol caps bound parameters at 65,535 per statement.
# 5,000 rows × at most 4 params/row keeps every statement under 25,000
# params with comfortable headroom.
_CHUNK_SIZE = 5000

log = logging.getLogger("yasli.ingest")

AddressKey = tuple[str, int, str | None, str | None]
InstitutionKey = tuple[str, str]


@dataclass
class TableCounts:
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0


@dataclass
class IngestSummary:
    scraped_at: datetime
    institutions: TableCounts = field(default_factory=TableCounts)
    streets: TableCounts = field(default_factory=TableCounts)
    addresses: TableCounts = field(default_factory=TableCounts)
    address_institutions: TableCounts = field(default_factory=TableCounts)
    institutions_disappeared: int = 0
    skipped_rows: int = 0
    address_null: int = 0
    addresses_district_stamp: AddressesStampSummary = field(
        default_factory=AddressesStampSummary
    )
    institutions_district_stamp: InstitutionsStampSummary = field(
        default_factory=InstitutionsStampSummary
    )
    elapsed_ms: int = 0

    @property
    def addresses_district_unstamped(self) -> int:
        return self.addresses_district_stamp.remaining_null

    @property
    def institutions_district_unstamped(self) -> int:
        return self.institutions_district_stamp.remaining_null

    def to_log_line(self) -> str:
        """Single-line, no embedded newlines, parseable by Railway log search."""
        addr_stamp = self.addresses_district_stamp
        inst_stamp = self.institutions_district_stamp
        return (
            "ingest done "
            f"snapshot={self.scraped_at.isoformat().replace('+00:00', 'Z')} "
            f"institutions={{inserted:{self.institutions.inserted},"
            f"updated:{self.institutions.updated},"
            f"unchanged:{self.institutions.unchanged},"
            f"disappeared:{self.institutions_disappeared}}} "
            f"streets={{inserted:{self.streets.inserted},"
            f"updated:{self.streets.updated},"
            f"unchanged:{self.streets.unchanged}}} "
            f"addresses={{inserted:{self.addresses.inserted},"
            f"updated:{self.addresses.updated},"
            f"unchanged:{self.addresses.unchanged}}} "
            f"address_institutions={{inserted:{self.address_institutions.inserted},"
            f"unchanged:{self.address_institutions.unchanged}}} "
            f"address_null={self.address_null} "
            f"skipped_rows={self.skipped_rows} "
            f"addresses_district_stamp={{primary:{addr_stamp.primary_stamped},"
            f"fallback1:{addr_stamp.fallback1_stamped},"
            f"fallback2:{addr_stamp.fallback2_stamped}}} "
            f"addresses_district_unstamped={self.addresses_district_unstamped} "
            f"institutions_district_stamp={{primary:{inst_stamp.primary_stamped},"
            f"fallback:{inst_stamp.fallback_stamped}}} "
            f"institutions_district_unstamped={self.institutions_district_unstamped} "
            f"elapsed_ms={self.elapsed_ms}"
        )


@dataclass
class _IngestPlan:
    """In-memory representation of a snapshot ready for the upsert phase."""

    snapshot: Snapshot
    institutions: list[dict[str, Any]]
    streets: list[dict[str, Any]]
    addresses: list[dict[str, Any]]
    coverage_edges: list[tuple[AddressKey, InstitutionKey]]
    skipped_rows: int
    address_null: int


class UnsupportedSnapshotVersion(ValueError):
    """Raised when R2 contains a snapshot version this ingest cannot read."""


def _chunked(rows: list[dict[str, Any]], size: int = _CHUNK_SIZE) -> Iterator[list[dict[str, Any]]]:
    """Yield successive ``size``-row slices of ``rows``.

    Postgres caps bound parameters at 65,535 per statement; chunking keeps
    every multi-row INSERT well under that limit.
    """
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


def _pg_upsert(
    session: Session,
    *,
    table: Any,
    rows: list[dict[str, Any]],
    natural_key: tuple[str, ...],
    on_conflict_set: Callable[[Any], dict[str, Any]],
    value_columns_for_unchanged: tuple[str, ...],
    returning_columns: tuple[str, ...],
    preserve_old_on_null_columns: tuple[str, ...] = (),
    null_distinct_keys: tuple[str, ...] = (),
    chunk_size: int | None = None,
) -> tuple[list[dict[str, Any]], TableCounts]:
    """Generic ``INSERT … ON CONFLICT DO UPDATE`` with classify-and-count.

    Pre-fetches existing rows by the first column of ``natural_key`` (then
    filters in Python for exact natural-key matches), runs the upsert with
    ``returning_columns``, and tags each result row as
    inserted / updated / unchanged.

    ``on_conflict_set`` is a callable rather than a static dict because
    SET clauses typically reference ``stmt.excluded.col`` — that handle
    only exists after the ``pg_insert(...)`` call.

    ``preserve_old_on_null_columns`` covers the
    ``COALESCE(excluded.col, table.col)`` quirk: the SET clause is the
    caller's responsibility, but the unchanged-check needs to know that a
    NULL in the new row means "keep the old value" so it doesn't count
    as a real change.

    ``null_distinct_keys`` triggers a Python pre-filter for rows whose
    natural key already exists. Postgres' default "NULL ≠ NULL" rule on
    UNIQUE constraints means ``ON CONFLICT`` won't catch duplicates that
    differ only in a NULL column; the pre-filter prevents that.

    Returns the row dicts (one per ``returning_columns`` projection) for
    both newly upserted AND pre-existing unchanged rows, so callers can
    build their id maps from a single list.
    """
    counts = TableCounts()
    if not rows:
        return [], counts

    assert set(natural_key).issubset(returning_columns), (
        f"natural_key {natural_key!r} must be a subset of "
        f"returning_columns {returning_columns!r}"
    )

    first_col_name = natural_key[0]
    first_col_attr = getattr(table, first_col_name)
    first_col_values = {row[first_col_name] for row in rows}

    fetch_col_names = tuple(
        dict.fromkeys((*natural_key, *value_columns_for_unchanged, *returning_columns))
    )
    fetch_attrs = [getattr(table, name) for name in fetch_col_names]

    requested_keys = {tuple(row[c] for c in natural_key) for row in rows}
    existing_by_key: dict[tuple[Any, ...], dict[str, Any]] = {}
    for r in session.execute(
        select(*fetch_attrs).where(first_col_attr.in_(first_col_values))
    ).all():
        key = tuple(getattr(r, name) for name in natural_key)
        if key not in requested_keys:
            continue
        existing_by_key[key] = {name: getattr(r, name) for name in fetch_col_names}

    rows_by_key = {tuple(row[c] for c in natural_key): row for row in rows}

    result_rows: list[dict[str, Any]] = []

    if null_distinct_keys:
        fresh_rows: list[dict[str, Any]] = []
        for key, row in rows_by_key.items():
            existing = existing_by_key.get(key)
            if existing is None:
                fresh_rows.append(row)
            else:
                counts.unchanged += 1
                result_rows.append({name: existing[name] for name in returning_columns})
        rows_to_upsert = fresh_rows
    else:
        rows_to_upsert = rows

    if not rows_to_upsert:
        return result_rows, counts

    returning_attrs = [getattr(table, name) for name in returning_columns]
    chunks: Iterator[list[dict[str, Any]]] | list[list[dict[str, Any]]] = (
        _chunked(rows_to_upsert, chunk_size) if chunk_size else [rows_to_upsert]
    )

    for chunk in chunks:
        stmt = pg_insert(table).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=list(natural_key),
            set_=on_conflict_set(stmt),
        ).returning(*returning_attrs)

        for r in session.execute(stmt):
            row_dict = {name: getattr(r, name) for name in returning_columns}
            result_rows.append(row_dict)

            key = tuple(row_dict[c] for c in natural_key)
            existing = existing_by_key.get(key)
            if existing is None:
                counts.inserted += 1
                continue

            new_row = rows_by_key[key]
            if _row_is_unchanged(
                existing,
                new_row,
                value_columns_for_unchanged,
                preserve_old_on_null_columns,
            ):
                counts.unchanged += 1
            else:
                counts.updated += 1

    return result_rows, counts


def _row_is_unchanged(
    existing: dict[str, Any],
    new_row: dict[str, Any],
    value_columns: tuple[str, ...],
    preserve_on_null: tuple[str, ...],
) -> bool:
    for col in value_columns:
        new_val = new_row[col]
        if col in preserve_on_null and new_val is None:
            # COALESCE(NULL, old) → old; effectively no change.
            continue
        if new_val != existing[col]:
            return False
    return True


def _fetch_snapshot_bytes(client: Any | None) -> bytes:
    """Phase 1: fetch the snapshot bytes from R2."""
    return r2.get_object(LATEST_KEY, client=client)


def _validate_snapshot(body: bytes) -> Snapshot:
    """Phase 2: parse JSON and construct the Snapshot model.

    `json.JSONDecodeError` and `pydantic.ValidationError` propagate to the
    caller; the CLI catches them and prints to stderr.
    """
    payload = json.loads(body)
    if isinstance(payload, dict) and "schema_version" in payload and payload["schema_version"] != 2:
        raise UnsupportedSnapshotVersion(
            f"unsupported snapshot schema_version {payload['schema_version']!r}; expected 2"
        )
    return Snapshot.model_validate(payload)


def _build_plan(snapshot: Snapshot) -> _IngestPlan:
    """Phase 3: turn the validated snapshot into row-shaped dicts.

    Streets and institutions are de-duplicated by their natural keys
    (`raw_name` and `(external_id, kind)` respectively). Addresses are
    de-duplicated by `(street_raw_name, number_int, number_suffix,
    entrance)`; coverage edges by `(address_key, institution_key)`. FK
    resolution happens at upsert time.
    """
    inst_rows: dict[InstitutionKey, dict[str, Any]] = {}
    street_rows: dict[str, dict[str, Any]] = {}
    address_rows: dict[AddressKey, dict[str, Any]] = {}
    edge_set: set[tuple[AddressKey, InstitutionKey]] = set()
    edges: list[tuple[AddressKey, InstitutionKey]] = []
    skipped = 0
    address_null = 0

    for inst in snapshot.institutions:
        if inst.address is None:
            address_null += 1
        inst_key: InstitutionKey = (inst.external_id, inst.kind)
        inst_rows[inst_key] = {
            "external_id": inst.external_id,
            "name": inst.name,
            "kind": inst.kind,
            "source_url": str(inst.source_url),
            "address": inst.address,
            "district_code": inst.district_code,
            "has_infant_group": inst.has_infant_group,
            "last_seen_at": snapshot.scraped_at,
        }

        for entry in inst.address_entries:
            try:
                parsed_street = parse_street(entry.street)
            except UnknownLocality as exc:
                log.warning(
                    "skipping address: unknown locality: %s (institution %s/%s)",
                    exc.raw,
                    inst.external_id,
                    inst.kind,
                )
                skipped += 1
                continue

            try:
                number_int, suffix, entrance = parse_number(entry.number)
            except (UnparseableNumber, NumberOutOfRange) as exc:
                log.warning(
                    "skipping address: %s (institution %s/%s)",
                    exc,
                    inst.external_id,
                    inst.kind,
                )
                skipped += 1
                continue

            if parsed_street.raw_name not in street_rows:
                street_rows[parsed_street.raw_name] = {
                    "city": parsed_street.city,
                    "raw_name": parsed_street.raw_name,
                    "street_part": parsed_street.street_part,
                    "type_marker": parsed_street.type_marker,
                    "search_norm": parsed_street.search_norm,
                }

            address_key: AddressKey = (
                parsed_street.raw_name,
                number_int,
                suffix,
                entrance,
            )
            if address_key not in address_rows:
                address_rows[address_key] = {
                    "street_raw_name": parsed_street.raw_name,
                    "number_int": number_int,
                    "number_suffix": suffix,
                    "entrance": entrance,
                }

            edge = (address_key, inst_key)
            if edge not in edge_set:
                edge_set.add(edge)
                edges.append(edge)

    return _IngestPlan(
        snapshot=snapshot,
        institutions=list(inst_rows.values()),
        streets=list(street_rows.values()),
        addresses=list(address_rows.values()),
        coverage_edges=edges,
        skipped_rows=skipped,
        address_null=address_null,
    )


def _upsert_institutions(
    session: Session, plan: _IngestPlan
) -> tuple[dict[InstitutionKey, int], TableCounts]:
    """Upsert institutions; return ``{(external_id, kind): id}`` plus counts."""

    def on_conflict_set(stmt: Any) -> dict[str, Any]:
        return {
            "name": stmt.excluded.name,
            "source_url": stmt.excluded.source_url,
            "address": stmt.excluded.address,
            # Snapshot NULL means "backend-derived" for KG/PG. Preserve an
            # existing district stamp so weekly ingest stays idempotent;
            # the quarterly restamp command intentionally changes derived
            # values. Nursery snapshots carry non-NULL API district codes
            # so those still update normally.
            "district_code": func.coalesce(
                stmt.excluded.district_code, Institution.district_code
            ),
            "has_infant_group": stmt.excluded.has_infant_group,
            "last_seen_at": stmt.excluded.last_seen_at,
        }

    result_rows, counts = _pg_upsert(
        session,
        table=Institution,
        rows=plan.institutions,
        natural_key=("external_id", "kind"),
        on_conflict_set=on_conflict_set,
        # `last_seen_at` is intentionally excluded — a snapshot-time bump
        # alone counts as unchanged for the operator-readable summary.
        value_columns_for_unchanged=(
            "name", "source_url", "address", "district_code", "has_infant_group",
        ),
        preserve_old_on_null_columns=("district_code",),
        returning_columns=("id", "external_id", "kind"),
    )

    id_map: dict[InstitutionKey, int] = {
        (r["external_id"], r["kind"]): r["id"] for r in result_rows
    }
    return id_map, counts


def _upsert_streets(
    session: Session, plan: _IngestPlan
) -> tuple[dict[str, int], TableCounts]:
    """Upsert streets; return ``{raw_name: id}`` plus counts."""

    def on_conflict_set(stmt: Any) -> dict[str, Any]:
        return {"search_norm": stmt.excluded.search_norm}

    result_rows, counts = _pg_upsert(
        session,
        table=Street,
        rows=plan.streets,
        natural_key=("raw_name",),
        on_conflict_set=on_conflict_set,
        value_columns_for_unchanged=("search_norm",),
        returning_columns=("id", "raw_name"),
    )

    id_map: dict[str, int] = {r["raw_name"]: r["id"] for r in result_rows}
    return id_map, counts


def _upsert_addresses(
    session: Session,
    plan: _IngestPlan,
    street_ids: dict[str, int],
) -> tuple[dict[AddressKey, int], TableCounts]:
    """Upsert addresses; return ``{address_key: id}`` plus counts.

    The natural-key UNIQUE does NOT use ``NULLS NOT DISTINCT``, so
    Postgres' default "NULL ≠ NULL" would let ``(street_id, 85, NULL,
    NULL)`` duplicate on every re-ingest. ``_pg_upsert`` handles that
    via the ``null_distinct_keys`` pre-filter; ``ON CONFLICT`` then
    covers the all-non-NULL case for free.
    """
    if not plan.addresses:
        return {}, TableCounts()

    rows: list[dict[str, Any]] = []
    for addr in plan.addresses:
        street_id = street_ids.get(addr["street_raw_name"])
        if street_id is None:
            # Defensive — both maps are built from the same plan.
            continue
        rows.append(
            {
                "street_id": street_id,
                "number_int": addr["number_int"],
                "number_suffix": addr["number_suffix"],
                "entrance": addr["entrance"],
            }
        )

    if not rows:
        return {}, TableCounts()

    def on_conflict_set(stmt: Any) -> dict[str, Any]:
        # No-op SET so RETURNING fires on conflict too. The natural key
        # is the only identity; there are no value columns to merge.
        return {"street_id": stmt.excluded.street_id}

    result_rows, counts = _pg_upsert(
        session,
        table=Address,
        rows=rows,
        natural_key=("street_id", "number_int", "number_suffix", "entrance"),
        on_conflict_set=on_conflict_set,
        value_columns_for_unchanged=(),
        returning_columns=("id", "street_id", "number_int", "number_suffix", "entrance"),
        null_distinct_keys=("number_suffix", "entrance"),
        chunk_size=_CHUNK_SIZE,
    )

    street_id_to_raw = {v: k for k, v in street_ids.items()}
    address_id_map: dict[AddressKey, int] = {}
    for r in result_rows:
        raw_name = street_id_to_raw.get(r["street_id"])
        if raw_name is None:
            continue
        address_id_map[
            (raw_name, r["number_int"], r["number_suffix"], r["entrance"])
        ] = r["id"]

    return address_id_map, counts


def _insert_address_institutions(
    session: Session,
    plan: _IngestPlan,
    inst_ids: dict[InstitutionKey, int],
    address_ids: dict[AddressKey, int],
) -> TableCounts:
    """Insert junction rows; conflict on the composite PK → do nothing.

    Pre-loads the existing pairs once so the inserted/unchanged split is
    accurate. Edges whose either side did not resolve are skipped
    defensively (should never happen — the maps are built from the same
    plan).
    """
    counts = TableCounts()
    if not plan.coverage_edges:
        return counts

    rows: list[dict[str, Any]] = []
    pair_keys: list[tuple[int, int]] = []
    for address_key, inst_key in plan.coverage_edges:
        address_id = address_ids.get(address_key)
        institution_id = inst_ids.get(inst_key)
        if address_id is None or institution_id is None:
            continue
        rows.append(
            {"address_id": address_id, "institution_id": institution_id}
        )
        pair_keys.append((address_id, institution_id))

    if not rows:
        return counts

    address_id_set = {p[0] for p in pair_keys}
    institution_id_set = {p[1] for p in pair_keys}
    existing_rows = session.execute(
        select(
            address_institutions.c.address_id,
            address_institutions.c.institution_id,
        ).where(
            address_institutions.c.address_id.in_(address_id_set),
            address_institutions.c.institution_id.in_(institution_id_set),
        )
    ).all()
    existing_pairs: set[tuple[int, int]] = {
        (r.address_id, r.institution_id) for r in existing_rows
    }

    fresh_rows = [
        row for row, key in zip(rows, pair_keys, strict=True)
        if key not in existing_pairs
    ]

    for key in pair_keys:
        if key in existing_pairs:
            counts.unchanged += 1
        else:
            counts.inserted += 1

    if not fresh_rows:
        return counts

    for chunk in _chunked(fresh_rows):
        stmt = pg_insert(address_institutions).values(chunk)
        stmt = stmt.on_conflict_do_nothing(constraint="address_institutions_pkey")
        session.execute(stmt)

    return counts


def _count_disappeared(session: Session, scraped_at: datetime) -> int:
    """Phase 5: count institutions whose last_seen_at predates this snapshot."""
    result = session.execute(
        select(func.count())
        .select_from(Institution)
        .where(Institution.last_seen_at < scraped_at)
    ).scalar_one()
    return int(result)


def run(*, r2_client: Any | None = None) -> IngestSummary:
    """Execute the full ingest pipeline and return the summary."""
    started = time.monotonic()

    body = _fetch_snapshot_bytes(r2_client)
    snapshot = _validate_snapshot(body)
    plan = _build_plan(snapshot)

    summary = IngestSummary(
        scraped_at=snapshot.scraped_at,
        skipped_rows=plan.skipped_rows,
        address_null=plan.address_null,
    )

    engine = get_engine()
    with Session(engine) as session:
        with session.begin():
            inst_ids, summary.institutions = _upsert_institutions(session, plan)
            street_ids, summary.streets = _upsert_streets(session, plan)
            address_ids, summary.addresses = _upsert_addresses(
                session, plan, street_ids
            )
            summary.address_institutions = _insert_address_institutions(
                session, plan, inst_ids, address_ids
            )
            # District-stamping passes run in the same transaction so a
            # snapshot ingest is atomic with respect to the stamping it
            # implies. Order matters: addresses first (the institutions
            # pass consults addresses.district_code via the catchment
            # junction).
            summary.addresses_district_stamp = stamp_addresses_unmatched(session)
            summary.institutions_district_stamp = stamp_institutions_unmatched(
                session
            )
        # After commit, count disappeared institutions.
        summary.institutions_disappeared = _count_disappeared(
            session, snapshot.scraped_at
        )

    summary.elapsed_ms = int((time.monotonic() - started) * 1000)
    return summary


def emit_summary(summary: IngestSummary) -> None:
    """Print the summary as a single line on stdout."""
    print(summary.to_log_line(), file=sys.stdout, flush=True)
