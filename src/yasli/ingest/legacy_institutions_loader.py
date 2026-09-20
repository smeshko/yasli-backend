"""Legacy-institutions fixture loader.

Loads ``data/seed/legacy_institutions.json`` — the 18
``ДГ№X … / с яслена група/`` nursery rows production has carried since
before 2026-05-10 and that no current snapshot creates. Without them a
local database serves 77 institutions where production serves 95, and the
18 slugs in the frontend's ``institutions-manifest.json`` resolve to
nothing.

These rows are **not** a workaround for a data bug. They are stale entries
production has never retired; retiring them is a separate ticket. The
fixture is a faithful copy of what production holds, including what it
does *not* hold: every one of the 18 carries a NULL ``district_code`` and
a NULL address there, so it carries them here too. A value invented for
this column would make ``/api/match`` return nurseries in a район that
production does not return — the opposite of production-like. The parser
still range-checks the column, so a future refresh that does find a район
lands a checked value rather than a typo.

File format (UTF-8 JSON, a list of objects) — every field is required to
be *present*, several may be null::

    [
      {
        "kind": "nursery",
        "external_id": "39",
        "name": "ДГ№6 \\"Палечко\\"/ с яслена група/",
        "source_url": "https://dg.uslugi.io/.../39.html",
        "address": null,
        "district_code": null,
        "has_infant_group": false,
        "last_seen_at": "2026-05-10T01:02:26Z"
      }
    ]

The parser rejects rather than skips, naming the row index and the field
at fault — the file is 18 hand-reviewed rows, so every anomaly is a
mistake someone should see.

Loading (``python -m yasli.ingest.legacy_institutions_loader [path]``)
**upserts** on ``(kind, external_id)`` and touches nothing else. It
deliberately does not TRUNCATE, unlike ``grao_loader`` and
``institution_locations_loader``: this table is owned by ingest, and the
fixture only adds rows ingest no longer produces.

The hazard this shape carries is overlap, not staleness: if one of these
keys ever reappears in a snapshot, the upsert would overwrite a live row
with a months-old copy. ``tests/test_legacy_institutions_data.py`` asserts
the fixture's keys are disjoint from the committed snapshot's, and
``yasli.seed freeze`` refuses to write a pair that intersects — two
independent nets on the one outcome that costs data (DECISIONS.md D8).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from yasli.db import get_engine
from yasli.ingest.municipality import REPO_ROOT
from yasli.models import Institution
from yasli.models.types import KIND_VALUES

DEFAULT_PATH = REPO_ROOT / "data" / "seed" / "legacy_institutions.json"

# Field order is the fixture's key order; every one must be present on
# every row. Nullability is per-field, below.
FIELDS: tuple[str, ...] = (
    "kind",
    "external_id",
    "name",
    "source_url",
    "address",
    "district_code",
    "has_infant_group",
    "last_seen_at",
)

NULLABLE_FIELDS: frozenset[str] = frozenset({"address", "district_code"})

DISTRICT_CODES: frozenset[str] = frozenset({"01", "02", "03", "04", "05"})

# Mirrors the column widths on `institutions`, so a too-long value fails
# as a named fixture problem rather than a database error.
MAX_LENGTHS: dict[str, int] = {
    "external_id": 16,
    "name": 256,
    "source_url": 512,
    "address": 256,
}


class LegacyFixtureError(ValueError):
    """The fixture cannot be parsed. The message names the row and field."""


@dataclass
class LegacySummary:
    """Counts emitted by a single loader run."""

    inserted: int = 0
    updated: int = 0
    unchanged: int = 0

    @property
    def total(self) -> int:
        return self.inserted + self.updated + self.unchanged


def _fail(index: int, message: str) -> LegacyFixtureError:
    return LegacyFixtureError(f"row {index}: {message}")


def _require_str(index: int, field: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _fail(index, f"{field} must be a non-empty string, got {value!r}")
    limit = MAX_LENGTHS.get(field)
    if limit is not None and len(value) > limit:
        raise _fail(index, f"{field} is longer than {limit} characters")
    return value


def _parse_row(index: int, raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise _fail(index, f"expected an object, got {type(raw).__name__}")

    missing = [f for f in FIELDS if f not in raw]
    if missing:
        raise _fail(index, f"missing required field(s): {', '.join(missing)}")
    unknown = sorted(set(raw) - set(FIELDS))
    if unknown:
        raise _fail(index, f"unknown field(s): {', '.join(unknown)}")

    for field in FIELDS:
        if raw[field] is None and field not in NULLABLE_FIELDS:
            raise _fail(index, f"{field} must not be null")

    kind = _require_str(index, "kind", raw["kind"])
    if kind not in KIND_VALUES:
        raise _fail(
            index, f"kind must be one of {', '.join(KIND_VALUES)}, got {kind!r}"
        )

    district_code = raw["district_code"]
    if district_code is not None and district_code not in DISTRICT_CODES:
        raise _fail(
            index,
            "district_code must be null or one of "
            f"{', '.join(sorted(DISTRICT_CODES))}, got {district_code!r}",
        )

    has_infant_group = raw["has_infant_group"]
    if not isinstance(has_infant_group, bool):
        raise _fail(
            index, f"has_infant_group must be a boolean, got {has_infant_group!r}"
        )

    last_seen_raw = _require_str(index, "last_seen_at", raw["last_seen_at"])
    try:
        last_seen_at = datetime.fromisoformat(last_seen_raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _fail(
            index, f"last_seen_at is not an ISO-8601 timestamp: {last_seen_raw!r}"
        ) from exc

    address = raw["address"]
    if address is not None:
        address = _require_str(index, "address", address)

    return {
        "kind": kind,
        "external_id": _require_str(index, "external_id", raw["external_id"]),
        "name": _require_str(index, "name", raw["name"]),
        "source_url": _require_str(index, "source_url", raw["source_url"]),
        "address": address,
        "district_code": district_code,
        "has_infant_group": has_infant_group,
        "last_seen_at": last_seen_at,
    }


def parse_file(path: Path) -> list[dict[str, Any]]:
    """Parse and validate the fixture at ``path``.

    Raises :class:`LegacyFixtureError` naming the row index and the field
    at fault; nothing partial is returned.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise LegacyFixtureError(f"{path} is not valid JSON: {exc}") from exc
    except OSError as exc:
        raise LegacyFixtureError(f"cannot read {path}: {exc}") from exc

    if not isinstance(payload, list):
        raise LegacyFixtureError(
            f"{path}: expected a list of objects, got {type(payload).__name__}"
        )

    rows = [_parse_row(i, raw) for i, raw in enumerate(payload)]
    seen: set[tuple[str, str]] = set()
    for index, row in enumerate(rows):
        key = (row["kind"], row["external_id"])
        if key in seen:
            raise _fail(index, f"duplicate (kind, external_id) {key}")
        seen.add(key)
    return rows


def load(path: Path, session: Session) -> LegacySummary:
    """Upsert the fixture at ``path`` on ``(kind, external_id)``.

    Runs inside the caller's transaction; rolling back leaves the table
    untouched. Institutions not named by the fixture are never read,
    written or deleted.
    """
    rows = parse_file(path)
    return load_rows(rows, session)


def load_rows(rows: list[dict[str, Any]], session: Session) -> LegacySummary:
    """Upsert already-parsed ``rows``; see :func:`load`."""
    summary = LegacySummary()
    for row in rows:
        existing = session.scalars(
            select(Institution).where(
                Institution.kind == row["kind"],
                Institution.external_id == row["external_id"],
            )
        ).one_or_none()
        if existing is None:
            session.add(Institution(**row))
            summary.inserted += 1
            continue
        changed = False
        for column, value in row.items():
            if getattr(existing, column) != value:
                setattr(existing, column, value)
                changed = True
        if changed:
            summary.updated += 1
        else:
            summary.unchanged += 1
    session.flush()
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="yasli.ingest.legacy_institutions_loader",
        description=(
            "Upsert data/seed/legacy_institutions.json into institutions. "
            "Idempotent, and touches no institution the fixture does not name."
        ),
    )
    parser.add_argument(
        "path",
        type=Path,
        nargs="?",
        default=DEFAULT_PATH,
        help=f"Path to the fixture (default: {DEFAULT_PATH}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and report without opening a database connection.",
    )
    args = parser.parse_args(argv)
    if not args.path.exists():
        print(f"error: file not found: {args.path}", file=sys.stderr)
        return 2

    try:
        rows = parse_file(args.path)
    except LegacyFixtureError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3

    if args.dry_run:
        print(
            f"legacy_institutions dry-run rows={len(rows)} (nothing written)",
            flush=True,
        )
        return 0

    engine = get_engine()
    with Session(engine) as session, session.begin():
        summary = load_rows(rows, session)
    print(
        f"legacy_institutions done inserted={summary.inserted} "
        f"updated={summary.updated} unchanged={summary.unchanged}",
        flush=True,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - delegated to tests via main()
    raise SystemExit(main())
