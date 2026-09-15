"""Institution locations reference-file loader.

Parses the committed ``data/institution_locations.csv`` — one row per
building an institution occupies — into validated row dicts for
``institution_locations``, and writes the same file back through the same
checks so no other writer (the seed script, the review tool) can produce a
file this module would reject.

File format (UTF-8, stdlib ``csv``, ``QUOTE_MINIMAL``)::

    kind,external_id,role,label,address,lat,lon,precision,source,verification,verified_at
    kindergarten,46,main,,"ул. ""Никола Михайловски"" №6",43.206500,27.914200,building,osm_poi,auto,2026-09-14
    kindergarten,46,branch,,"ул. Н. Михайловски 1А",43.207100,27.913800,building,manual,human,2026-09-14
    kindergarten,17,branch,Жирафче,,,,none,manual,human,2026-09-14

Empty ``label`` and ``address`` cells become ``''`` (the ``grao_addresses``
convention, so the UNIQUE tuple constrains); empty ``lat``/``lon`` become
``None``.

The parser rejects rather than skips, throughout. ``grao_loader`` silently
skips unrecognised lines because it parses a 236k-row printed report where
noise is expected; this file is ~92 hand-maintained rows, and every anomaly
is a mistake someone should see, named by line number.

Beyond per-row shape, three cross-row rules live here because the loader
truncates before inserting — with an empty table the database's constraints
would only fire on the second copy inside the same INSERT batch, producing
an opaque error instead of a line number:

* a duplicate ``(kind, external_id, role, label, address)`` tuple;
* a second ``main`` row for the same ``(kind, external_id)``;
* every ``verification=auto`` row must have a **provenance entry** in the
  sibling ``institution_locations.provenance.json`` recording the seed
  script's four auto-accept rule outcomes, all passing, at the row's
  coordinate — and every entry must have its ``auto`` row. The rules
  themselves need the network, so the parser cross-checks the committed
  record of them instead; a forged ``auto`` row without one fails to parse.

The municipality polygon (``yasli.ingest.municipality``) is the hard
reject for every coordinate. It is one guard among several — see that
module's docstring for what it cannot catch.

Loading (``python -m yasli.ingest.institution_locations_loader [path]``)
mirrors ``grao_loader``: TRUNCATE + bulk INSERT inside one transaction, so
re-running against the same file leaves the table in the same observable
state (every column except the surrogate ``id``, which plain ``TRUNCATE``
does not reset). Three referential guards run **before** the TRUNCATE, all
resolved against ``institutions`` in one query, so a bad file fails as a
data problem with names, not as a constraint error after the table was
emptied:

1. every ``(kind, external_id)`` in the file must match an institution —
   never skippable;
2. every current institution must have a ``main`` row (an explicit
   ``no_pin`` row with ``precision=none`` counts as present) — a
   half-finished review or a CSV predating a newly ingested institution
   never replaces a complete table;
3. a ``main`` row's ``address`` must still match the institution's, through
   :func:`normalise_address` — ingest overwrites ``institutions.address``,
   so a moved institution with its old pin is exactly the wrong pin that
   looks right.

``--allow-incomplete`` ("the CSV lags the institutions table") skips guards
2 and 3 for local partial loads only, never guard 1; ``--dry-run`` runs all
three and prints the summary without touching the table.

The weekly ``python -m yasli.ingest`` must not call this: coordinates change
roughly never, and coupling a reference load to the cron would let a
third-party outage during the seed script's data collection break routing
refreshes.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
import tempfile
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import delete, insert, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from yasli.db import get_engine
from yasli.ingest.municipality import REPO_ROOT, in_varna_municipality
from yasli.models import Institution, InstitutionLocation
from yasli.models.types import (
    KIND_VALUES,
    PRECISION_VALUES,
    ROLE_VALUES,
    SOURCE_VALUES,
    VERIFICATION_VALUES,
)

DEFAULT_CSV = REPO_ROOT / "data" / "institution_locations.csv"
DEFAULT_PROVENANCE = REPO_ROOT / "data" / "institution_locations.provenance.json"

COLUMNS: tuple[str, ...] = (
    "kind",
    "external_id",
    "role",
    "label",
    "address",
    "lat",
    "lon",
    "precision",
    "source",
    "verification",
    "verified_at",
)

#: The natural key of a building row — the table's UNIQUE tuple.
KEY_COLUMNS: tuple[str, ...] = ("kind", "external_id", "role", "label", "address")

#: Rule 4 of the auto-accept rules: a rank-30 geocode, when one exists,
#: must agree with the POI within this distance.
MAX_GEOCODE_DISTANCE_M = 150

_COORD_PLACES = Decimal("0.000001")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_QUOTES_RE = re.compile("[\"“”„«»]")
_PUNCT_SPACING_RE = re.compile(r"\s*([№.,])\s*")
_WHITESPACE_RE = re.compile(r"\s+")


class LocationRowError(ValueError):
    """A row (or the file as a whole) failed validation.

    ``line_no`` is the 1-based physical line in the CSV (the header is
    line 1), or ``None`` for file-level failures such as stale provenance.
    """

    def __init__(self, line_no: int | None, message: str) -> None:
        self.line_no = line_no
        self.message = message
        prefix = f"line {line_no}: " if line_no is not None else ""
        super().__init__(prefix + message)


def normalise_address(text: str) -> str:
    """The one address comparison every consumer uses.

    Casefolds, maps every quote style (``"`` ``“`` ``”`` ``„`` ``«`` ``»``)
    to ``"``, collapses whitespace, and drops spaces around ``№``, ``.``
    and ``,`` — so the research §3.1 variants of one address compare
    equal while a different house number or street does not.
    """
    out = _QUOTES_RE.sub('"', text.casefold())
    out = _WHITESPACE_RE.sub(" ", out).strip()
    out = _PUNCT_SPACING_RE.sub(r"\1", out)
    return out


def provenance_key(kind: str, external_id: str) -> str:
    return f"{kind}/{external_id}"


def load_provenance(path: Path) -> dict[str, dict[str, Any]]:
    """Read the provenance file; a missing file is an empty mapping."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise LocationRowError(None, f"provenance file {path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or not all(isinstance(v, dict) for v in data.values()):
        raise LocationRowError(
            None, f"provenance file {path} must be an object of key -> entry objects"
        )
    return data


def _quantise(value: Any, *, line_no: int | None, field: str) -> Decimal:
    try:
        return Decimal(str(value)).quantize(_COORD_PLACES)
    except (InvalidOperation, ValueError) as exc:
        raise LocationRowError(line_no, f"{field} is not a number: {value!r}") from exc


def _validate_coordinate(
    line_no: int, lat_raw: Any, lon_raw: Any, precision: str
) -> tuple[Decimal | None, Decimal | None]:
    """The both-or-neither rule, the precision agreement, and the polygon."""
    has_lat = lat_raw is not None and str(lat_raw).strip() != ""
    has_lon = lon_raw is not None and str(lon_raw).strip() != ""
    if has_lat != has_lon:
        missing = "lon" if has_lat else "lat"
        raise LocationRowError(line_no, f"{missing} is missing while the other coordinate is set")
    if not has_lat:
        if precision != "none":
            raise LocationRowError(
                line_no, f"precision {precision!r} requires a coordinate; use 'none' for no pin"
            )
        return None, None
    if precision == "none":
        raise LocationRowError(line_no, "precision 'none' must not carry a coordinate")
    lat = _quantise(lat_raw, line_no=line_no, field="lat")
    lon = _quantise(lon_raw, line_no=line_no, field="lon")
    if not in_varna_municipality(float(lat), float(lon)):
        raise LocationRowError(
            line_no, f"coordinate {lat},{lon} is outside the Varna municipality polygon"
        )
    return lat, lon


def _require_in(line_no: int, field: str, value: str, allowed: tuple[str, ...]) -> str:
    if value not in allowed:
        raise LocationRowError(
            line_no, f"{field} {value!r} is not one of {', '.join(allowed)}"
        )
    return value


def _check_provenance_entry(
    line_no: int, key: str, entry: dict[str, Any] | None, lat: Decimal, lon: Decimal
) -> None:
    """An ``auto`` row needs an all-pass provenance entry at its coordinate."""
    if entry is None:
        raise LocationRowError(line_no, f"auto row {key} has no provenance entry")
    try:
        entry_lat = _quantise(entry["lat"], line_no=line_no, field="provenance lat")
        entry_lon = _quantise(entry["lon"], line_no=line_no, field="provenance lon")
    except KeyError as exc:
        raise LocationRowError(line_no, f"provenance entry {key} lacks {exc}") from exc
    if (entry_lat, entry_lon) != (lat, lon):
        raise LocationRowError(
            line_no,
            f"provenance entry {key} records coordinate {entry_lat},{entry_lon}, "
            f"row has {lat},{lon}",
        )
    if entry.get("title_matches") != 1:
        raise LocationRowError(
            line_no, f"auto row {key}: title_matches is {entry.get('title_matches')!r}, not 1"
        )
    if entry.get("in_municipality") is not True:
        raise LocationRowError(line_no, f"auto row {key}: in_municipality is not true")
    settlement = entry.get("settlement")
    address_settlement = entry.get("address_settlement")
    if not settlement or settlement != address_settlement:
        raise LocationRowError(
            line_no,
            f"auto row {key}: settlement {settlement!r} does not agree with "
            f"address_settlement {address_settlement!r}",
        )
    distance = entry.get("geocode_distance_m")
    if distance is not None and distance > MAX_GEOCODE_DISTANCE_M:
        raise LocationRowError(
            line_no,
            f"auto row {key}: geocode_distance_m {distance} exceeds {MAX_GEOCODE_DISTANCE_M}",
        )


def _parse_row(
    line_no: int, raw: Mapping[str, str | None], provenance: Mapping[str, dict[str, Any]]
) -> dict[str, Any]:
    cells = {c: (raw.get(c) or "").strip() for c in COLUMNS}
    kind = _require_in(line_no, "kind", cells["kind"], KIND_VALUES)
    external_id = cells["external_id"]
    if not external_id:
        raise LocationRowError(line_no, "external_id is empty")
    role = _require_in(line_no, "role", cells["role"], ROLE_VALUES)
    precision = _require_in(line_no, "precision", cells["precision"], PRECISION_VALUES)
    source = _require_in(line_no, "source", cells["source"], SOURCE_VALUES)
    verification = _require_in(
        line_no, "verification", cells["verification"], VERIFICATION_VALUES
    )
    if source == "manual" and verification == "auto":
        raise LocationRowError(line_no, "source 'manual' cannot be verification 'auto'")
    if verification == "auto" and not (
        source == "osm_poi" and role == "main" and precision == "building"
    ):
        raise LocationRowError(
            line_no,
            "verification 'auto' is only allowed for source 'osm_poi', role 'main', "
            f"precision 'building' (got {source!r}, {role!r}, {precision!r})",
        )
    if not _DATE_RE.match(cells["verified_at"]):
        raise LocationRowError(
            line_no, f"verified_at {cells['verified_at']!r} is not a YYYY-MM-DD date"
        )
    try:
        verified_at = date.fromisoformat(cells["verified_at"])
    except ValueError as exc:
        raise LocationRowError(line_no, f"verified_at {cells['verified_at']!r}: {exc}") from exc

    lat, lon = _validate_coordinate(line_no, cells["lat"], cells["lon"], precision)
    if verification == "auto":
        assert lat is not None and lon is not None  # precision 'building' guarantees it
        key = provenance_key(kind, external_id)
        _check_provenance_entry(line_no, key, provenance.get(key), lat, lon)

    return {
        "kind": kind,
        "external_id": external_id,
        "role": role,
        "label": cells["label"],
        "address": cells["address"],
        "lat": lat,
        "lon": lon,
        "precision": precision,
        "source": source,
        "verification": verification,
        "verified_at": verified_at,
    }


def parse_rows(
    reader: csv.DictReader, provenance: Mapping[str, dict[str, Any]]
) -> Iterator[dict[str, Any]]:
    """Validate the header, then yield one row dict per CSV line.

    Raises :class:`LocationRowError` naming the line on the first problem.
    The stale-provenance check runs after the last row, with ``line_no``
    ``None``.
    """
    fieldnames = reader.fieldnames
    if fieldnames is None:
        raise LocationRowError(1, "file is empty")
    if tuple(fieldnames) != COLUMNS:
        missing = [c for c in COLUMNS if c not in fieldnames]
        extra = [c for c in fieldnames if c not in COLUMNS]
        problems = []
        if missing:
            problems.append("missing " + ", ".join(missing))
        if extra:
            problems.append("unexpected " + ", ".join(extra))
        if not problems:
            problems.append("wrong column order")
        raise LocationRowError(1, "header: " + "; ".join(problems))

    seen_keys: dict[tuple[str, ...], int] = {}
    seen_main: dict[tuple[str, str], int] = {}
    auto_keys: set[str] = set()
    for raw in reader:
        line_no = reader.line_num
        if raw.get(None):
            raise LocationRowError(line_no, "row has more cells than the header")
        row = _parse_row(line_no, raw, provenance)
        key = tuple(row[c] for c in KEY_COLUMNS)
        if key in seen_keys:
            raise LocationRowError(
                line_no, f"duplicate building {key!r} already on line {seen_keys[key]}"
            )
        seen_keys[key] = line_no
        if row["role"] == "main":
            pair = (row["kind"], row["external_id"])
            if pair in seen_main:
                raise LocationRowError(
                    line_no,
                    f"second main row for {provenance_key(*pair)}; "
                    f"the first is on line {seen_main[pair]}",
                )
            seen_main[pair] = line_no
        if row["verification"] == "auto":
            auto_keys.add(provenance_key(row["kind"], row["external_id"]))
        yield row

    stale = sorted(set(provenance) - auto_keys)
    if stale:
        raise LocationRowError(
            None, "stale provenance: entries with no auto row: " + ", ".join(stale)
        )


def parse_file(path: Path, provenance_path: Path | None = None) -> Iterator[dict[str, Any]]:
    """Decode ``path`` as UTF-8 and yield validated row dicts.

    ``provenance_path`` defaults to ``institution_locations.provenance.json``
    next to the CSV; a missing provenance file is treated as empty, which
    makes every ``auto`` row fail with its line number.
    """
    if provenance_path is None:
        provenance_path = path.with_name("institution_locations.provenance.json")
    provenance = load_provenance(provenance_path)
    text = path.read_text(encoding="utf-8")
    yield from parse_rows(csv.DictReader(io.StringIO(text)), provenance)


def _format_cell(column: str, value: Any) -> str:
    if value is None:
        return ""
    if column in ("lat", "lon"):
        return f"{Decimal(str(value)).quantize(_COORD_PLACES):f}"
    if column == "verified_at" and isinstance(value, date):
        return value.isoformat()
    return str(value)


def render_csv(rows: Iterable[Mapping[str, Any]]) -> str:
    """Rows -> CSV text in the file's stable order, without validating."""
    ordered = sorted(rows, key=lambda r: tuple(str(r.get(c) or "") for c in KEY_COLUMNS))
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    writer.writerow(COLUMNS)
    for row in ordered:
        writer.writerow([_format_cell(c, row.get(c)) for c in COLUMNS])
    return buf.getvalue()


def render_provenance(provenance: Mapping[str, dict[str, Any]]) -> str:
    return json.dumps(dict(sorted(provenance.items())), ensure_ascii=False, indent=2) + "\n"


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        os.chmod(tmp_name, 0o644)  # mkstemp creates 0600; these are committed files
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def write_file(
    path: Path,
    rows: Iterable[Mapping[str, Any]],
    provenance: Mapping[str, dict[str, Any]],
    provenance_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Validate ``rows`` + ``provenance`` exactly as :func:`parse_rows`
    would, then write the CSV and the provenance file, each via a temp
    file and rename.

    A rejected batch raises :class:`LocationRowError` before either file is
    touched, so the old files stay intact. Returns the parsed rows.
    """
    if provenance_path is None:
        provenance_path = path.with_name("institution_locations.provenance.json")
    csv_text = render_csv(rows)
    parsed = list(parse_rows(csv.DictReader(io.StringIO(csv_text)), provenance))
    _atomic_write(path, csv_text)
    _atomic_write(provenance_path, render_provenance(provenance))
    return parsed


# --- loading -------------------------------------------------------------------


class UnmatchedInstitution(Exception):
    """A row's ``(kind, external_id)`` matches no institution. Never skippable."""

    def __init__(self, pairs: list[tuple[str, str]]) -> None:
        self.pairs = pairs
        names = ", ".join(provenance_key(kind, external_id) for kind, external_id in pairs)
        super().__init__(f"{len(pairs)} row(s) match no institution: {names}")


class IncompleteFile(Exception):
    """The file lags the institutions table: an institution has no ``main``
    row, or a ``main`` row's address drifted. Skippable with
    ``--allow-incomplete`` for local loads."""

    def __init__(
        self, missing_main: list[str], address_drift: list[tuple[str, str, str]]
    ) -> None:
        self.missing_main = missing_main
        self.address_drift = address_drift
        parts = []
        if missing_main:
            parts.append(
                f"{len(missing_main)} institution(s) have no main row: " + "; ".join(missing_main)
            )
        if address_drift:
            parts.append(
                f"{len(address_drift)} main row(s) no longer match the institution's address: "
                + "; ".join(
                    f"{name}: csv={csv_address!r} db={db_address!r}"
                    for name, csv_address, db_address in address_drift
                )
            )
        super().__init__(" | ".join(parts))


@dataclass
class LoaderSummary:
    """What one loader run found and did."""

    rows_loaded: int = 0
    by_role: dict[str, int] = field(default_factory=dict)
    by_verification: dict[str, int] = field(default_factory=dict)
    #: Institutions with no ``main`` row, as ``name (kind/external_id)``.
    #: Non-empty only under ``allow_incomplete``.
    missing_main: list[str] = field(default_factory=list)
    #: ``(institution, csv address, db address)`` for drifted ``main`` rows.
    #: Non-empty only under ``allow_incomplete``.
    address_drift: list[tuple[str, str, str]] = field(default_factory=list)
    #: ``main`` rows shipped without a pin (``precision=none``), by name.
    unresolved_main: list[str] = field(default_factory=list)
    dry_run: bool = False


def _label(name: str, kind: str, external_id: str) -> str:
    return f"{name} ({provenance_key(kind, external_id)})"


def load_rows(
    rows: list[dict[str, Any]],
    session: Session,
    *,
    allow_incomplete: bool = False,
    dry_run: bool = False,
) -> LoaderSummary:
    """Run the three guards, then (unless ``dry_run``) TRUNCATE + INSERT.

    The whole operation runs inside the caller's transaction; on any error,
    rolling back leaves the previous contents intact. The guards run before
    the TRUNCATE so a rejected file never empties the table even
    transiently.
    """
    institutions = {
        (kind, external_id): (name, address)
        for kind, external_id, name, address in session.execute(
            select(
                Institution.kind,
                Institution.external_id,
                Institution.name,
                Institution.address,
            )
        )
    }

    # Guard 1: locations without an institution.
    unmatched = sorted(
        {(r["kind"], r["external_id"]) for r in rows} - set(institutions)
    )
    if unmatched:
        raise UnmatchedInstitution(unmatched)

    # Guard 2: institutions without a location.
    main_rows = {(r["kind"], r["external_id"]): r for r in rows if r["role"] == "main"}
    missing_main = [
        _label(name, kind, external_id)
        for (kind, external_id), (name, _address) in sorted(institutions.items())
        if (kind, external_id) not in main_rows
    ]

    # Guard 3: a location whose institution moved.
    address_drift: list[tuple[str, str, str]] = []
    for (kind, external_id), row in sorted(main_rows.items()):
        name, db_address = institutions[(kind, external_id)]
        if db_address is None:
            continue
        if normalise_address(row["address"]) != normalise_address(db_address):
            address_drift.append((_label(name, kind, external_id), row["address"], db_address))

    if (missing_main or address_drift) and not allow_incomplete:
        raise IncompleteFile(missing_main, address_drift)

    if not dry_run:
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            session.execute(text("TRUNCATE TABLE institution_locations"))
        else:
            session.execute(delete(InstitutionLocation))
        if rows:
            session.execute(insert(InstitutionLocation), rows)

    unresolved_main = [
        _label(institutions[(kind, external_id)][0], kind, external_id)
        for (kind, external_id), row in sorted(main_rows.items())
        if row["precision"] == "none"
    ]
    return LoaderSummary(
        rows_loaded=len(rows),
        by_role=dict(Counter(r["role"] for r in rows)),
        by_verification=dict(Counter(r["verification"] for r in rows)),
        missing_main=missing_main,
        address_drift=address_drift,
        unresolved_main=unresolved_main,
        dry_run=dry_run,
    )


def load(
    path: Path,
    session: Session,
    *,
    allow_incomplete: bool = False,
    dry_run: bool = False,
    provenance_path: Path | None = None,
) -> LoaderSummary:
    """Parse ``path`` (raising :class:`LocationRowError` with its line
    number) and load it — see :func:`load_rows`."""
    rows = list(parse_file(path, provenance_path=provenance_path))
    return load_rows(rows, session, allow_incomplete=allow_incomplete, dry_run=dry_run)


def format_summary(summary: LoaderSummary) -> str:
    """The operator-readable report: one summary line, then one line per
    named item so an unresolved or missing ``main`` row is never hidden
    behind a count."""
    lines = [
        "institution_locations_loader done "
        f"rows={summary.rows_loaded} "
        f"main={summary.by_role.get('main', 0)} "
        f"branch={summary.by_role.get('branch', 0)} "
        f"auto={summary.by_verification.get('auto', 0)} "
        f"human={summary.by_verification.get('human', 0)} "
        f"missing_main={len(summary.missing_main)} "
        f"address_drift={len(summary.address_drift)} "
        f"unresolved_main={len(summary.unresolved_main)} "
        f"dry_run={int(summary.dry_run)}"
    ]
    lines.extend(f"  unresolved main (no pin): {name}" for name in summary.unresolved_main)
    lines.extend(f"  missing main: {name}" for name in summary.missing_main)
    lines.extend(
        f"  address drift: {name}: csv={csv_address!r} db={db_address!r}"
        for name, csv_address, db_address in summary.address_drift
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="yasli.ingest.institution_locations_loader",
        description=(
            "Load data/institution_locations.csv into institution_locations. "
            "Idempotent: TRUNCATE + INSERT inside one transaction, after checking "
            "every row against the institutions table."
        ),
    )
    parser.add_argument(
        "path",
        type=Path,
        nargs="?",
        default=DEFAULT_CSV,
        help=f"Path to the locations CSV (default: {DEFAULT_CSV}).",
    )
    parser.add_argument(
        "--allow-incomplete",
        action="store_true",
        help=(
            "Load even when an institution has no main row or a main row's "
            "address drifted (the CSV lags the institutions table). Local loads "
            "only; never against production."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run every check and print the summary without TRUNCATE or INSERT.",
    )
    args = parser.parse_args(argv)
    if not args.path.exists():
        print(f"error: file not found: {args.path}", file=sys.stderr)
        return 2
    try:
        rows = list(parse_file(args.path))
    except LocationRowError as exc:
        print(f"error: {args.path}: {exc}", file=sys.stderr)
        return 3
    try:
        engine = get_engine()
    except ValueError as exc:  # Settings(): DATABASE_URL missing or malformed
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        with Session(engine) as session, session.begin():
            summary = load_rows(
                rows, session, allow_incomplete=args.allow_incomplete, dry_run=args.dry_run
            )
    except UnmatchedInstitution as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 4
    except IncompleteFile as exc:
        print(
            f"error: {exc}\n"
            "The table was not touched. Refresh the file (seed script -> review tool), "
            "or pass --allow-incomplete for a local partial load.",
            file=sys.stderr,
        )
        return 4
    except SQLAlchemyError as exc:
        print(f"error: database error: {exc}", file=sys.stderr)
        return 5
    print(format_summary(summary), flush=True)
    return 0


if __name__ == "__main__":  # pragma: no cover - delegated to tests via main()
    raise SystemExit(main())
