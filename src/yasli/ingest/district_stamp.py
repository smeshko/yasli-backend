"""District-stamping passes for the post-ingest phase.

Two passes, each with a gated (NULL-only) and a non-gated (restamp-all)
variant:

1. **Addresses**: join ``addresses → streets → grao_addresses`` and stamp
   ``addresses.district_code`` from the ГРАО ground truth. Primary join is
   ``(search_norm, number_int, number_suffix, entrance)``. Two fallback
   tiers handle entrance-less and street-majority cases.

2. **Institutions** (kindergartens + preschools only — nurseries are
   API-sourced): stamp ``institutions.district_code`` via catchment
   majority across the ``address_institutions`` junction, falling back to
   parsing ``institutions.address`` and looking it up in ``grao_addresses``.

The gated variants are invoked by the weekly DG ingest after the upsert
phase; the non-gated variants are invoked manually by the operator
following a quarterly ГРАО reload to propagate reassignments.

All UPDATE statements use COALESCE-on-the-join-side so addresses with
``NULL`` ``number_suffix``/``entrance`` join against the empty-string
canonical form ГРАО stores.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from yasli.ingest.normalise import UnknownLocality, parse_street
from yasli.ingest.parser import (
    NumberOutOfRange,
    UnparseableNumber,
    parse_number,
)
from yasli.geo.settlements import VARNA_SETTLEMENTS

log = logging.getLogger("yasli.ingest.district_stamp")

# Sample size cap for the human-readable run summary.
_SAMPLE_CAP = 5


@dataclass
class AddressesStampSummary:
    primary_stamped: int = 0
    fallback1_stamped: int = 0
    fallback2_stamped: int = 0
    remaining_null: int = 0
    null_sample: list[str] = field(default_factory=list)
    settlement_stamped: int = 0


@dataclass
class _UnstampedInstReason:
    reason: str
    external_id: str
    name: str
    address: str | None
    catchment_rows: int


@dataclass
class InstitutionsStampSummary:
    primary_stamped: int = 0
    fallback_stamped: int = 0
    remaining_null: int = 0
    null_sample: list[_UnstampedInstReason] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Addresses pass
# ---------------------------------------------------------------------------

_PRIMARY_UPDATE_SQL = """
UPDATE addresses
SET district_code = (
    SELECT MIN(ga.district_code)
    FROM grao_addresses ga
    JOIN streets s ON s.search_norm = ga.search_norm
    WHERE s.id = addresses.street_id
      AND ga.number_int = addresses.number_int
      AND ga.number_suffix = COALESCE(addresses.number_suffix, '')
      AND ga.entrance = COALESCE(addresses.entrance, '')
    LIMIT 1
)
WHERE {gate}
  AND (
      SELECT COUNT(DISTINCT ga.district_code)
      FROM grao_addresses ga
      JOIN streets s ON s.search_norm = ga.search_norm
      WHERE s.id = addresses.street_id
        AND ga.number_int = addresses.number_int
        AND ga.number_suffix = COALESCE(addresses.number_suffix, '')
        AND ga.entrance = COALESCE(addresses.entrance, '')
  ) = 1
"""

# Fallback 1: ignore entrance. Accept only if every match agrees on
# district_code (counted via COUNT(DISTINCT)).
_FALLBACK1_UPDATE_SQL = """
UPDATE addresses
SET district_code = (
    SELECT MIN(ga.district_code)
    FROM grao_addresses ga
    JOIN streets s ON s.search_norm = ga.search_norm
    WHERE s.id = addresses.street_id
      AND ga.number_int = addresses.number_int
      AND ga.number_suffix = COALESCE(addresses.number_suffix, '')
)
WHERE {gate}
  AND (
      SELECT COUNT(DISTINCT ga.district_code)
      FROM grao_addresses ga
      JOIN streets s ON s.search_norm = ga.search_norm
      WHERE s.id = addresses.street_id
        AND ga.number_int = addresses.number_int
        AND ga.number_suffix = COALESCE(addresses.number_suffix, '')
  ) = 1
"""

# Fallback 2: street-majority. Match on search_norm alone, accept only when
# the entire street is in one район.
_FALLBACK2_UPDATE_SQL = """
UPDATE addresses
SET district_code = (
    SELECT MIN(ga.district_code)
    FROM grao_addresses ga
    JOIN streets s ON s.search_norm = ga.search_norm
    WHERE s.id = addresses.street_id
)
WHERE {gate}
  AND (
      SELECT COUNT(DISTINCT ga.district_code)
      FROM grao_addresses ga
      JOIN streets s ON s.search_norm = ga.search_norm
      WHERE s.id = addresses.street_id
  ) = 1
"""

_COUNT_NULL_SQL = "SELECT COUNT(*) FROM addresses WHERE district_code IS NULL"

_NULL_SAMPLE_SQL = """
SELECT s.raw_name, a.number_int, a.number_suffix, a.entrance
FROM addresses a
JOIN streets s ON s.id = a.street_id
WHERE a.district_code IS NULL
LIMIT :cap
"""


def _row_count(result: Any) -> int:
    return int(result.rowcount) if result.rowcount is not None else 0


def _single_district(rows: list[Any]) -> str | None:
    return str(rows[0][0]) if len(rows) == 1 else None


def _settlement_case_sql() -> str:
    """Build the ``CASE WHEN`` body used by the settlement stamping pass.

    Returns SQL fragments wired into a correlated subquery, so the same
    text works on Postgres and SQLite (no UPDATE … FROM portability
    issues). Patterns cover the two punctuation styles ГРАО / the
    scraper emit (``С.КАМЕНАР`` and ``С. КАМЕНАР``).
    """
    branches = []
    for settlement in VARNA_SETTLEMENTS:
        conditions = " OR ".join(
            f"s.raw_name LIKE '{pattern}'"
            for pattern in settlement.raw_name_patterns
        )
        branches.append(
            f"WHEN {conditions} THEN '{settlement.code}'"
        )
    return "CASE " + " ".join(branches) + " ELSE NULL END"


def _stamp_addresses(
    session: Session, *, gated: bool
) -> AddressesStampSummary:
    """Run the three district tiers + settlement pass; return counts."""
    null_clause = "addresses.district_code IS NULL" if gated else "1=1"

    summary = AddressesStampSummary()

    result = session.execute(text(_PRIMARY_UPDATE_SQL.format(gate=null_clause)))
    summary.primary_stamped = _row_count(result)

    # Fallback tiers are always gated on NULL — they only fill in still-NULL
    # rows. When the caller asks for a non-gated restamp, the primary tier
    # has already replaced exact-match rows; the fallbacks remain NULL-
    # gated so previously-stamped rows that no longer exact-match are not
    # overwritten by a fallback guess.
    result = session.execute(
        text(_FALLBACK1_UPDATE_SQL.format(gate="addresses.district_code IS NULL"))
    )
    summary.fallback1_stamped = _row_count(result)

    result = session.execute(
        text(_FALLBACK2_UPDATE_SQL.format(gate="addresses.district_code IS NULL"))
    )
    summary.fallback2_stamped = _row_count(result)

    # Settlement pass: covers ГР.ВАРНА (also stamps the district-stamped
    # city addresses for completeness) and the five villages, which
    # never get a district stamp because villages have no район.
    settlement_gate = "settlement_code IS NULL" if gated else "1=1"
    settlement_sql = (
        f"UPDATE addresses SET settlement_code = ("
        f"  SELECT {_settlement_case_sql()} FROM streets s "
        f"  WHERE s.id = addresses.street_id"
        f") WHERE {settlement_gate}"
    )
    result = session.execute(text(settlement_sql))
    summary.settlement_stamped = _row_count(result)

    summary.remaining_null = int(
        session.execute(text(_COUNT_NULL_SQL)).scalar_one()
    )
    sample_rows = session.execute(
        text(_NULL_SAMPLE_SQL), {"cap": _SAMPLE_CAP}
    ).all()
    summary.null_sample = [
        f"{row[0]} {row[1]}{row[2] or ''}{(' вх.' + row[3]) if row[3] else ''}"
        for row in sample_rows
    ]
    return summary


def stamp_addresses_unmatched(session: Session) -> AddressesStampSummary:
    """Gated pass — touches only rows where ``district_code IS NULL``."""
    return _stamp_addresses(session, gated=True)


def restamp_addresses_all(session: Session) -> AddressesStampSummary:
    """Non-gated pass — invoked manually after a quarterly ГРАО reload."""
    return _stamp_addresses(session, gated=False)


# ---------------------------------------------------------------------------
# Institutions pass — catchment-majority primary, address-parse fallback
# ---------------------------------------------------------------------------

# Candidate list: KG/PG with NULL district_code (gated) or all KG/PG
# (non-gated). Nurseries are explicitly excluded.
_CANDIDATES_SQL = """
SELECT id, external_id, name, address
FROM institutions
WHERE kind <> 'nursery'
  AND ({null_clause})
"""

# Catchment-majority: plurality district_code across the institution's
# catchment, tie-broken alphabetically by district_code ascending.
_CATCHMENT_MAJORITY_SQL = """
SELECT a.district_code, COUNT(*) AS n
FROM address_institutions ai
JOIN addresses a ON a.id = ai.address_id
WHERE ai.institution_id = :inst_id
  AND a.district_code IS NOT NULL
GROUP BY a.district_code
ORDER BY n DESC, a.district_code ASC
LIMIT 1
"""

_SET_INST_DISTRICT_SQL = """
UPDATE institutions
SET district_code = :district_code
WHERE id = :inst_id
  AND kind <> 'nursery'
"""

_CATCHMENT_COUNT_SQL = """
SELECT COUNT(*) FROM address_institutions WHERE institution_id = :inst_id
"""


def _lookup_grao_district(
    session: Session,
    search_norm: str,
    number_int: int,
    number_suffix: str | None,
    entrance: str | None,
) -> str | None:
    """Look up a (search_norm, number, suffix, entrance) tuple in
    ``grao_addresses`` using the same two-tier fallback as the addresses
    pass. Returns the district_code or None.
    """
    suffix = number_suffix or ""
    ent = entrance or ""

    rows = session.execute(
        text(
            "SELECT DISTINCT district_code FROM grao_addresses "
            "WHERE search_norm = :sn AND number_int = :n "
            "AND number_suffix = :sfx AND entrance = :ent "
        ),
        {"sn": search_norm, "n": number_int, "sfx": suffix, "ent": ent},
    ).all()
    exact = _single_district(rows)
    if exact is not None:
        return exact

    # Entrance-less retry.
    rows = session.execute(
        text(
            "SELECT DISTINCT district_code FROM grao_addresses "
            "WHERE search_norm = :sn AND number_int = :n "
            "AND number_suffix = :sfx"
        ),
        {"sn": search_norm, "n": number_int, "sfx": suffix},
    ).all()
    entrance_less = _single_district(rows)
    if entrance_less is not None:
        return entrance_less

    # Street-majority retry.
    rows = session.execute(
        text(
            "SELECT DISTINCT district_code FROM grao_addresses "
            "WHERE search_norm = :sn"
        ),
        {"sn": search_norm},
    ).all()
    street_majority = _single_district(rows)
    if street_majority is not None:
        return street_majority

    return None


def _parse_and_lookup_address(session: Session, address: str | None) -> str | None:
    """Run ``parse_street`` + ``parse_number`` over an institution's
    ``address`` and look the resulting tuple up in ``grao_addresses``.
    """
    if not address:
        return None
    # Address strings can be "ГР.ВАРНА УЛ.X 5" — the existing parser knows
    # the format and yields a ParsedStreet plus a number string. The DG
    # address strings in the institution row aren't separated like the
    # snapshot's `address_entries` (which has discrete street + number
    # fields); we rsplit on the last whitespace to peel off the number.
    if " " not in address:
        return None
    head, _, tail = address.rpartition(" ")
    try:
        parsed = parse_street(head)
    except UnknownLocality:
        return None
    try:
        number_int, suffix, entrance = parse_number(tail)
    except (UnparseableNumber, NumberOutOfRange):
        return None
    return _lookup_grao_district(
        session, parsed.search_norm, number_int, suffix, entrance
    )


def _stamp_institutions(
    session: Session, *, gated: bool
) -> InstitutionsStampSummary:
    null_clause = (
        "district_code IS NULL" if gated else "1=1"
    )
    summary = InstitutionsStampSummary()
    candidates = session.execute(
        text(_CANDIDATES_SQL.format(null_clause=null_clause))
    ).all()

    for cand in candidates:
        inst_id = cand[0]
        external_id = cand[1]
        name = cand[2]
        address = cand[3]
        catchment_count = int(
            session.execute(
                text(_CATCHMENT_COUNT_SQL), {"inst_id": inst_id}
            ).scalar_one()
        )

        # Primary: catchment-majority.
        majority = session.execute(
            text(_CATCHMENT_MAJORITY_SQL), {"inst_id": inst_id}
        ).first()
        if majority is not None:
            session.execute(
                text(_SET_INST_DISTRICT_SQL),
                {"district_code": majority[0], "inst_id": inst_id},
            )
            summary.primary_stamped += 1
            continue

        # Fallback: address-parse + grao_addresses lookup.
        parsed_dc = _parse_and_lookup_address(session, address)
        if parsed_dc is not None:
            session.execute(
                text(_SET_INST_DISTRICT_SQL),
                {"district_code": parsed_dc, "inst_id": inst_id},
            )
            summary.fallback_stamped += 1
            continue

        # Still NULL — figure out *why* for the log line.
        if catchment_count == 0:
            reason = "no_catchment" if not address else "no_catchment"
        else:
            # We had catchment rows but they all had district_code IS NULL,
            # AND the address-parse fallback didn't find anything either.
            if not address:
                reason = "all_catchment_null"
            else:
                reason = "all_catchment_null"
        if not address:
            address_for_log = None
        else:
            address_for_log = address

        # Pin a more specific reason when the address path itself failed.
        if address:
            # Re-evaluate address parsing to label the specific failure.
            try:
                if " " in address:
                    head, _, tail = address.rpartition(" ")
                    parse_street(head)
                    try:
                        parse_number(tail)
                    except (UnparseableNumber, NumberOutOfRange):
                        reason = "address_parse_failed"
                else:
                    reason = "address_parse_failed"
            except UnknownLocality:
                reason = "address_parse_failed"
            # If parsing succeeded but no grao row matched:
            if reason not in ("address_parse_failed",) and catchment_count == 0:
                reason = "grao_lookup_failed"

        summary.remaining_null += 1
        if len(summary.null_sample) < _SAMPLE_CAP:
            summary.null_sample.append(
                _UnstampedInstReason(
                    reason=reason,
                    external_id=external_id,
                    name=name,
                    address=address_for_log,
                    catchment_rows=catchment_count,
                )
            )

    return summary


def stamp_institutions_unmatched(session: Session) -> InstitutionsStampSummary:
    """Gated pass — touches only KG/PG rows where ``district_code IS NULL``."""
    return _stamp_institutions(session, gated=True)


def restamp_institutions_all(session: Session) -> InstitutionsStampSummary:
    """Non-gated pass — invoked manually after a quarterly ГРАО reload.

    Nurseries remain untouched (the ``kind <> 'nursery'`` filter is in the
    candidate query and the UPDATE statement).
    """
    return _stamp_institutions(session, gated=False)
