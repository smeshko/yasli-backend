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
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from yasli.db import get_engine
from yasli.ingest import r2
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
    elapsed_ms: int = 0

    def to_log_line(self) -> str:
        """Single-line, no embedded newlines, parseable by Railway log search."""
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
    """Upsert institutions; return ``{(external_id, kind): id}`` plus counts.

    We can't use ``RETURNING`` to distinguish inserted vs updated cleanly in
    one statement (PG returns rows for both), so we do a pre-existing-id
    lookup before the upsert and compare row IDs after.
    """
    counts = TableCounts()
    if not plan.institutions:
        return {}, counts

    keys = [(row["external_id"], row["kind"]) for row in plan.institutions]
    existing: dict[InstitutionKey, Institution] = {}
    if keys:
        existing_rows = session.execute(
            select(Institution).where(
                Institution.external_id.in_({k[0] for k in keys})
            )
        ).scalars().all()
        existing = {
            (r.external_id, r.kind): r
            for r in existing_rows
            if (r.external_id, r.kind) in set(keys)
        }

    pre_existing_keys: set[InstitutionKey] = set()
    for key in keys:
        if key in existing:
            pre_existing_keys.add(key)

    stmt = pg_insert(Institution).values(plan.institutions)
    stmt = stmt.on_conflict_do_update(
        index_elements=["external_id", "kind"],
        set_={
            "name": stmt.excluded.name,
            "source_url": stmt.excluded.source_url,
            "address": stmt.excluded.address,
            "district_code": stmt.excluded.district_code,
            "has_infant_group": stmt.excluded.has_infant_group,
            "last_seen_at": stmt.excluded.last_seen_at,
        },
    ).returning(Institution.id, Institution.external_id, Institution.kind)

    id_map: dict[InstitutionKey, int] = {}
    for row in session.execute(stmt):
        key = (row.external_id, row.kind)
        id_map[key] = row.id
        if key in pre_existing_keys:
            # Was already there; row was UPDATEd. Detect "unchanged" by
            # comparing the source row to the existing one before upsert.
            new_row = next(
                r for r in plan.institutions
                if r["external_id"] == key[0] and r["kind"] == key[1]
            )
            old = existing[key]
            if (
                old.name == new_row["name"]
                and old.source_url == new_row["source_url"]
                and old.address == new_row["address"]
                and old.district_code == new_row["district_code"]
                and old.has_infant_group == new_row["has_infant_group"]
            ):
                # Only `last_seen_at` was bumped — counts as unchanged for
                # operator-readable summary purposes.
                counts.unchanged += 1
            else:
                counts.updated += 1
        else:
            counts.inserted += 1

    return id_map, counts


def _upsert_streets(
    session: Session, plan: _IngestPlan
) -> tuple[dict[str, int], TableCounts]:
    """Upsert streets; return ``{raw_name: id}`` plus counts."""
    counts = TableCounts()
    if not plan.streets:
        return {}, counts

    raw_names = [s["raw_name"] for s in plan.streets]
    existing_rows = session.execute(
        select(Street).where(Street.raw_name.in_(raw_names))
    ).scalars().all()
    existing: dict[str, Street] = {r.raw_name: r for r in existing_rows}

    stmt = pg_insert(Street).values(plan.streets)
    stmt = stmt.on_conflict_do_update(
        index_elements=["raw_name"],
        set_={"search_norm": stmt.excluded.search_norm},
    ).returning(Street.id, Street.raw_name)

    id_map: dict[str, int] = {}
    for row in session.execute(stmt):
        id_map[row.raw_name] = row.id
        if row.raw_name in existing:
            old = existing[row.raw_name]
            new_row = next(
                s for s in plan.streets if s["raw_name"] == row.raw_name
            )
            if old.search_norm == new_row["search_norm"]:
                counts.unchanged += 1
            else:
                counts.updated += 1
        else:
            counts.inserted += 1

    return id_map, counts


def _upsert_addresses(
    session: Session,
    plan: _IngestPlan,
    street_ids: dict[str, int],
) -> tuple[dict[AddressKey, int], TableCounts]:
    """Upsert addresses; return ``{address_key: id}`` plus counts.

    Idempotent upsert via ``INSERT … ON CONFLICT (street_id, number_int,
    number_suffix, entrance) DO UPDATE SET street_id = EXCLUDED.street_id``
    (no-op) so ``RETURNING`` emits the row id on conflict too. Pre-loads
    existing rows via the same composite identity to count
    inserted/unchanged accurately under the NULL-as-distinct semantics
    that ``ON CONFLICT`` would otherwise let through.
    """
    counts = TableCounts()
    if not plan.addresses:
        return {}, counts

    rows: list[dict[str, Any]] = []
    address_keys: list[AddressKey] = []
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
        address_keys.append(
            (
                addr["street_raw_name"],
                addr["number_int"],
                addr["number_suffix"],
                addr["entrance"],
            )
        )

    if not rows:
        return {}, counts

    # Pre-fetch existing rows by composite identity. The natural-key
    # UNIQUE does NOT use NULLS NOT DISTINCT, so Postgres' default
    # "NULL ≠ NULL" rule would otherwise let
    # `(street_id, 85, NULL, NULL)` duplicate on every re-ingest. We
    # filter matches out of the insert batch in Python; ON CONFLICT
    # handles the all-non-NULL case for free.
    street_id_set = {r["street_id"] for r in rows}
    existing_rows = session.execute(
        select(
            Address.id,
            Address.street_id,
            Address.number_int,
            Address.number_suffix,
            Address.entrance,
        ).where(Address.street_id.in_(street_id_set))
    ).all()
    street_id_to_raw = {v: k for k, v in street_ids.items()}
    existing_by_key: dict[AddressKey, int] = {}
    for r in existing_rows:
        raw_name = street_id_to_raw.get(r.street_id)
        if raw_name is None:
            continue
        existing_by_key[(raw_name, r.number_int, r.number_suffix, r.entrance)] = r.id

    fresh_rows: list[dict[str, Any]] = []
    fresh_keys: list[AddressKey] = []
    address_id_map: dict[AddressKey, int] = {}
    for row, key in zip(rows, address_keys, strict=True):
        if key in existing_by_key:
            address_id_map[key] = existing_by_key[key]
            counts.unchanged += 1
        else:
            fresh_rows.append(row)
            fresh_keys.append(key)

    if not fresh_rows:
        return address_id_map, counts

    fresh_index = 0
    for chunk in _chunked(fresh_rows):
        chunk_size = len(chunk)
        chunk_keys = fresh_keys[fresh_index : fresh_index + chunk_size]
        fresh_index += chunk_size

        stmt = pg_insert(Address).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=["street_id", "number_int", "number_suffix", "entrance"],
            set_={"street_id": stmt.excluded.street_id},
        ).returning(
            Address.id,
            Address.street_id,
            Address.number_int,
            Address.number_suffix,
            Address.entrance,
        )

        returned_by_key: dict[AddressKey, int] = {}
        for r in session.execute(stmt):
            raw_name = street_id_to_raw.get(r.street_id)
            if raw_name is None:
                continue
            returned_by_key[
                (raw_name, r.number_int, r.number_suffix, r.entrance)
            ] = r.id

        for key in chunk_keys:
            address_id = returned_by_key.get(key)
            if address_id is None:
                continue
            address_id_map[key] = address_id
            counts.inserted += 1

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
    from sqlalchemy import func

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
        # After commit, count disappeared institutions.
        summary.institutions_disappeared = _count_disappeared(
            session, snapshot.scraped_at
        )

    summary.elapsed_ms = int((time.monotonic() - started) * 1000)
    return summary


def emit_summary(summary: IngestSummary) -> None:
    """Print the summary as a single line on stdout."""
    print(summary.to_log_line(), file=sys.stdout, flush=True)
