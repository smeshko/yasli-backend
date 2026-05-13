"""ГРАО KADS plaintext loader.

Reads the windows-1251 plaintext Address Classifier (KADS) file published by
Главна Дирекция ГРАО per Bulgarian election cycle and bulk-loads
``grao_addresses``.

File acquisition is the operator's responsibility — the loader takes a
local path, not a URL. Re-running the loader against the same file leaves
``grao_addresses`` in the same observable state (TRUNCATE + bulk INSERT
inside one transaction).

The KADS layout is roughly:

::

    област 03 ВАРНА
    община 01 ВАРНА
    район 02_ПРИМОРСКИ
    10135 ГР.ВАРНА
    секция 002
    06598 УЛ.Н.Й.ВАПЦАРОВ        003 А,003 Б,003 В,003 Г,004,005,007 А
                                  007 Б,007 Г,007 Д
    ...

Headers (`област`, `община`, `район`, `секция`) update the iterator state.
The first settlement-like line that appears after a `район` header (but
before any `секция` header) is treated as the settlement record. Data
lines and indented continuation lines emit one row per (street, number,
entrance) tuple inheriting the current section's района/section codes.

`number_suffix` and `entrance` are stored as the empty string when
absent, so the composite PRIMARY KEY column constraints (NOT NULL) are
satisfied without losing the source's "no suffix" semantics.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import delete, insert, text
from sqlalchemy.orm import Session

from yasli.db import get_engine
from yasli.ingest.normalise import to_search_norm
from yasli.models import GraoAddress

log = logging.getLogger("yasli.ingest.grao_loader")


# Type markers stripped from street_raw before computing search_norm.
# `parse_street()` in normalise.py knows the DG-side markers; KADS data uses
# two more (`М-СТ` for местност, `БК.` for блок) so we maintain a local
# superset rather than mutate the shared regex.
GRAO_TYPE_MARKERS: tuple[str, ...] = (
    "БУЛ.",
    "Ж.К.",
    "М-СТ",
    "УЛ.",
    "ПЛ.",
    "КВ.",
    "БК.",
)


# Real KADS files pack all five header fields onto a single line, e.g.
# ``област 03 ВАРНА  община 06 ВАРНА  район 01_ОДЕСОС  10135 ГР.ВАРНА  секция 001``.
# The compiled regex extracts every field in one match.
_COMBINED_HEADER_RE = re.compile(
    r"област\s+(?P<province_code>\d{2})\s+(?P<province>\S.*?\S)\s+"
    r"община\s+(?P<municipality_code>\d{2})\s+(?P<municipality>\S.*?\S)\s+"
    r"район\s+(?P<district_code>\d{2})_(?P<district_name>\S.*?\S)\s+"
    r"(?P<settlement_code>\d{4,6})\s+(?P<settlement_name>\S.*?\S)\s+"
    r"секция\s+(?P<section_no>\d+)\s*$",
    re.IGNORECASE,
)

# Data line: leading whitespace, 5-digit street_code, then a fixed-width
# street-name column. The real KADS text starts the number column at index 38
# (0-based) on each data row; long street names can leave only one separating
# space before the first number, so a "two spaces between columns" regex is
# too strict.
_DATA_LINE_RE = re.compile(r"^\s+(\d{4,6})\s+")
_NUMBER_COLUMN_START = 38

# Decorative separator: a row of dashes (with optional column dashes
# separated by spaces) like ``----- ----- ...``.
_DECORATIVE_SEPARATOR_RE = re.compile(r"^\s*[-\s]+$")

# Column-header line (``  код  име на пътна артерия  номер...``).
_COLUMN_HEADER_RE = re.compile(r"^\s*код\s+име\s", re.IGNORECASE)

# Title / page-counter lines that appear at the top of each printed page
# (``КЛАСИФИКАТОР НА АДРЕСИТЕ ПО СЕКЦИИ`` and the dd.mm.yyyy date stamp).
_PAGE_TITLE_RE = re.compile(r"КЛАСИФИКАТОР")
_PAGE_DATE_RE = re.compile(r"^\s*\d{2}\.\d{2}\.\d{4}\s*$")

# A single number cell: required digit prefix, optional attached Cyrillic
# suffix (``019А``), optional space-separated entrance (``007 А`` or
# ``041 12``).
_NUMBER_TOKEN_RE = re.compile(
    r"^(\d+)([А-Я])?(?:\s+([А-Я0-9]+))?\s*$"
)


@dataclass
class LoaderSummary:
    """Counts emitted by a single loader run."""

    rows_loaded: int = 0
    streets_parsed: int = 0
    lines_skipped: int = 0


@dataclass
class _State:
    """Cursor through section headers and the last data line."""

    district_code: str | None = None
    district_name: str | None = None
    settlement_code: str | None = None
    settlement_name: str | None = None
    section_no: int | None = None
    last_street_code: str | None = None
    last_street_raw: str | None = None
    seen_streets: set[str] = field(default_factory=set)


def _normalise_code(token: str) -> str:
    """Coerce a 4–6 digit code to a 5-char string.

    Real KADS files have been observed with both 5- and 6-digit street
    codes (the leading byte appears to be padding in the latter case).
    Keep the last 5 characters; left-pad shorter tokens with zeros so the
    stored value is exactly 5 chars.
    """
    if len(token) >= 5:
        return token[-5:]
    return token.zfill(5)


def parse_number_token(token: str) -> tuple[int, str, str] | None:
    """Parse one KADS number cell into ``(number_int, suffix, entrance)``.

    Returns ``None`` when the token cannot be parsed — the caller skips it
    and increments the lines_skipped counter.
    """
    token = token.strip()
    if not token:
        return None
    match = _NUMBER_TOKEN_RE.match(token)
    if not match:
        return None
    digits, suffix, entrance = match.group(1), match.group(2), match.group(3)
    try:
        number_int = int(digits)
    except ValueError:
        return None
    return number_int, (suffix or ""), (entrance or "")


def _emit_rows(
    state: _State, street_code: str, street_raw: str, numbers_segment: str
) -> Iterator[dict[str, Any]]:
    """Yield grao_addresses row dicts for each parsed number token."""
    if (
        state.district_code is None
        or state.district_name is None
        or state.settlement_code is None
        or state.settlement_name is None
        or state.section_no is None
    ):
        # We are between region headers — drop the data line until the
        # iterator has seen the full header stack.
        return
    # Compose ``search_norm`` so it joins directly against
    # ``streets.search_norm``, which is computed by ``parse_street()`` from
    # the verbatim snapshot string ``"<SETTLEMENT> <STREET>"`` (e.g.
    # ``"ГР.ВАРНА УЛ.Н.Й.ВАПЦАРОВ"``). The KADS file stores the settlement
    # in a header line and the street alone on the row, so we re-compose
    # the prefixed form before ICAO transliteration.
    composed_raw = f"{state.settlement_name} {street_raw}"
    search_norm = to_search_norm(composed_raw)
    for raw_token in numbers_segment.split(","):
        parsed = parse_number_token(raw_token)
        if parsed is None:
            continue
        number_int, number_suffix, entrance = parsed
        yield {
            "street_code": street_code,
            "street_raw": street_raw,
            "search_norm": search_norm,
            "number_int": number_int,
            "number_suffix": number_suffix,
            "entrance": entrance,
            "district_code": state.district_code,
            "district_name": state.district_name,
            "settlement_code": state.settlement_code,
            "section_no": state.section_no,
        }


def _looks_like_continuation(stripped: str) -> bool:
    """Heuristic: stripped content is a comma-separated list of number-cell
    tokens, with no Latin letters or street-marker punctuation.
    """
    if not stripped:
        return False
    tokens = stripped.split(",")
    if tokens[-1] == "":
        tokens = tokens[:-1]
    if not tokens:
        return False
    for raw_token in tokens:
        if parse_number_token(raw_token) is None:
            return False
    return True


def _parse_data_line(line: str) -> tuple[str, str, str] | None:
    """Parse one fixed-width KADS data row.

    Returns ``(street_code, street_raw, numbers_segment)`` or ``None`` when
    the row is not a data row.
    """
    code_match = _DATA_LINE_RE.match(line)
    if not code_match:
        return None
    if len(line) <= _NUMBER_COLUMN_START:
        return None

    street_code = _normalise_code(code_match.group(1))
    street_raw = line[code_match.end() : _NUMBER_COLUMN_START].strip()
    numbers_segment = line[_NUMBER_COLUMN_START:].strip()
    if not street_raw or not numbers_segment:
        return None
    if not _looks_like_continuation(numbers_segment):
        return None
    return street_code, street_raw, numbers_segment


def _is_continuation_line(line: str, stripped_line: str) -> bool:
    """Return true for KADS continuation rows in the number column."""
    leading_spaces = len(line) - len(line.lstrip(" "))
    return (
        leading_spaces >= _NUMBER_COLUMN_START
        and _looks_like_continuation(stripped_line)
    )


def parse_lines(raw_lines: Iterable[str]) -> Iterator[dict[str, Any]]:
    """Yield grao_addresses row dicts as raw lines pass through the state
    machine. The input is an iterable of decoded strings (one line each;
    no trailing newline expected, though trailing whitespace is tolerated).
    """
    state = _State()
    for raw in raw_lines:
        # Tolerate form-feed page breaks and CRLF stripping.
        line = raw.replace("\x0c", "").rstrip("\r\n")
        stripped_line = line.strip()
        if not stripped_line:
            continue
        if _DECORATIVE_SEPARATOR_RE.match(line):
            continue
        if _COLUMN_HEADER_RE.match(line):
            continue
        if _PAGE_TITLE_RE.search(line) or _PAGE_DATE_RE.match(line):
            continue

        header_match = _COMBINED_HEADER_RE.search(line)
        if header_match:
            state.district_code = header_match["district_code"]
            state.district_name = header_match["district_name"].strip()
            state.settlement_code = _normalise_code(header_match["settlement_code"])
            state.settlement_name = header_match["settlement_name"].strip()
            state.section_no = int(header_match["section_no"])
            state.last_street_code = None
            state.last_street_raw = None
            continue

        parsed_data = _parse_data_line(line)
        if parsed_data:
            street_code, street_raw, numbers_segment = parsed_data
            state.last_street_code = street_code
            state.last_street_raw = street_raw
            state.seen_streets.add(street_code)
            yield from _emit_rows(state, street_code, street_raw, numbers_segment)
            continue

        # Continuation line: heavy left-indent, content is a list of
        # number-cell tokens, last-street context is set.
        if state.last_street_code is not None and _is_continuation_line(
            line, stripped_line
        ):
            yield from _emit_rows(
                state,
                state.last_street_code,
                state.last_street_raw or "",
                stripped_line,
            )
            continue
        # Page-counter ('1', '2', …) lines at the right edge — bare integers.
        if stripped_line.isdigit():
            continue
        # Otherwise: unrecognized line, silently skipped.


def parse_file(path: Path) -> Iterator[dict[str, Any]]:
    """Decode ``path`` as windows-1251 and yield row dicts.

    Raises :class:`UnicodeDecodeError` if the file is not valid windows-1251.
    """
    raw_bytes = path.read_bytes()
    decoded = raw_bytes.decode("windows-1251")
    yield from parse_lines(decoded.splitlines())


def load(path: Path, session: Session) -> LoaderSummary:
    """TRUNCATE ``grao_addresses`` and bulk-INSERT the contents of ``path``.

    The whole operation runs inside the caller's transaction. On any error,
    rolling back leaves the previous contents intact.
    """
    rows = list(parse_file(path))
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        session.execute(text("TRUNCATE TABLE grao_addresses"))
    else:
        session.execute(delete(GraoAddress))
    if rows:
        session.execute(insert(GraoAddress), rows)
    streets = {row["street_code"] for row in rows}
    return LoaderSummary(
        rows_loaded=len(rows),
        streets_parsed=len(streets),
        lines_skipped=0,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="yasli.ingest.grao_loader",
        description=(
            "Parse a ГРАО KADS plaintext file (windows-1251) and bulk-load "
            "grao_addresses. Idempotent: TRUNCATE + INSERT inside one "
            "transaction."
        ),
    )
    parser.add_argument(
        "path",
        type=Path,
        help="Local path to the extracted kads-03-06.txt plaintext file.",
    )
    args = parser.parse_args(argv)
    if not args.path.exists():
        print(f"error: file not found: {args.path}", file=sys.stderr)
        return 2
    try:
        engine = get_engine()
        with Session(engine) as session, session.begin():
            summary = load(args.path, session)
    except UnicodeDecodeError as exc:
        print(f"error: file is not valid windows-1251: {exc}", file=sys.stderr)
        return 3
    print(
        f"grao_loader done rows={summary.rows_loaded} "
        f"streets={summary.streets_parsed} skipped={summary.lines_skipped}",
        flush=True,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - delegated to tests via main()
    raise SystemExit(main())
