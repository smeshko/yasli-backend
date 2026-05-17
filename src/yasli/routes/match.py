"""GET /match — institutions covering a given address.

Mounted under ``/api`` by ``yasli.main``, so the public path is ``/api/match``.

Three routing paths land in one response:

* **kindergartens** come from the ``address_institutions`` junction
  (street-level catchment), each row carrying ``match_type: "street"``.
* **nurseries** come from district routing only:
  ``institutions.district_code = (the query address's district_code)``.
  Village addresses (no район) get an empty nursery list — there are
  no standalone nurseries outside ГР.ВАРНА. These rows carry
  ``match_type: "district"``.
* **preschools** are hybrid: the source publishes per-PG catchment
  streets for some institutions, so the junction is tried first. If
  the address has at least one PG junction row, those are returned
  (``match_type: "street"``) and the district fallback is skipped.
  Otherwise we fall back to district routing
  (``match_type: "district"``) — same SQL shape as nurseries.

The response shape depends on the query address:

* If the address's ``district_code`` is non-NULL → bare JSON array (the
  original v1 shape, preserved for callers that don't care about
  village-vs-city context).
* If ``district_code`` is NULL but ``settlement_code`` is set (so the
  address is in a village in община Варна) → envelope
  ``{ match_type: "settlement_only", results: [...] }``. The frontend
  uses this signal to render village-specific empty-state copy
  (e.g. "this village has no nursery").
* If both ``district_code`` and ``settlement_code`` are NULL **and**
  results are likely incomplete (nursery requested, or PG requested
  without junction hits) → envelope
  ``{ match_type: "district_unknown", results: [...] }``. The
  ``results`` array still contains every matchable row we could find
  (kindergartens by junction, plus PG junction rows if any).

Unknown ``address_id`` returns ``404 {"error": "address_not_found"}`` so
the frontend can distinguish a stale local cache from a kind-filtered
empty result. No cache headers; each response is parameterised by user
input.
"""

from __future__ import annotations

from typing import Literal, Union

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from yasli.db import get_db
from yasli.models.address import Address, address_institutions
from yasli.models.institution import Institution
from yasli.models.types import Kind

router = APIRouter()


class MatchInstitution(BaseModel):
    """One institution covering the queried address.

    ``match_type`` is ``"street"`` for junction-based matches
    (kindergartens always; preschools when the source publishes a
    catchment that includes the address) and ``"district"`` for
    district-routed matches (nurseries always; preschools when no
    junction row was found).
    """

    id: int
    external_id: str
    name: str
    kind: Kind
    source_url: str
    match_type: Literal["street", "district"]
    has_infant_group: bool


class DistrictUnknownResponse(BaseModel):
    """Envelope returned when the queried address has neither a район
    nor a settlement stamp, so we cannot route district-based kinds at
    all. ``results`` carries whatever junction matches we could find
    (kindergartens and PGs by street).
    """

    match_type: Literal["district_unknown"] = Field(default="district_unknown")
    results: list[MatchInstitution]


class SettlementOnlyResponse(BaseModel):
    """Envelope returned when the queried address has a ``settlement_code``
    but no ``district_code`` — i.e. it sits in a village in община Варна
    (Каменар, Тополи, Звездица, Константиново, Казашко). ``results``
    carries the village's junction matches; the frontend uses this
    envelope as the signal to render village-specific copy (e.g. an
    explicit "no nursery in this village" empty state).
    """

    match_type: Literal["settlement_only"] = Field(default="settlement_only")
    results: list[MatchInstitution]


# OpenAPI declares the 200 response as ``oneOf`` of the bare array and
# the envelope shapes, so generated TypeScript types narrow correctly.
MatchResponse = Union[
    list[MatchInstitution], DistrictUnknownResponse, SettlementOnlyResponse
]


def _effective_kinds(kind: Kind | None) -> tuple[Kind, ...]:
    if kind is None:
        return ("nursery", "kindergarten", "preschool")
    return (kind,)


def _street_rows(
    session: Session, address_id: int, kind: Kind
) -> list[MatchInstitution]:
    """Junction-based rows for ``address_id`` filtered to one ``kind``."""
    stmt = (
        select(
            Institution.id,
            Institution.external_id,
            Institution.name,
            Institution.kind,
            Institution.source_url,
            Institution.has_infant_group,
        )
        .join(
            address_institutions,
            Institution.id == address_institutions.c.institution_id,
        )
        .where(address_institutions.c.address_id == address_id)
        .where(Institution.kind == kind)
    )
    return [
        MatchInstitution(
            id=row.id,
            external_id=row.external_id,
            name=row.name,
            kind=row.kind,
            source_url=row.source_url,
            match_type="street",
            has_infant_group=row.has_infant_group,
        )
        for row in session.execute(stmt).all()
    ]


def _district_rows_for_kind(
    session: Session, district_code: str, kind: Kind
) -> list[MatchInstitution]:
    """District-routing rows filtered to one ``kind``."""
    stmt = (
        select(
            Institution.id,
            Institution.external_id,
            Institution.name,
            Institution.kind,
            Institution.source_url,
            Institution.has_infant_group,
        )
        .where(Institution.kind == kind)
        .where(Institution.district_code == district_code)
        .where(Institution.district_code.is_not(None))
    )
    return [
        MatchInstitution(
            id=row.id,
            external_id=row.external_id,
            name=row.name,
            kind=row.kind,
            source_url=row.source_url,
            match_type="district",
            has_infant_group=row.has_infant_group,
        )
        for row in session.execute(stmt).all()
    ]


def _preschool_rows(
    session: Session, address_id: int, address_district: str | None
) -> list[MatchInstitution]:
    """Preschools: prefer junction match; fall back to district routing.

    The source publishes per-PG catchment streets for many institutions
    in dg.uslugi.io's ``pg/region`` listings, so the junction is the
    more specific signal when present. If the address has zero PG
    junction rows we fall back to district routing (matches nursery
    behaviour). When ``address_district`` is ``None`` the fallback is
    skipped — the caller may emit the ``district_unknown`` envelope.
    """
    street_rows = _street_rows(session, address_id, "preschool")
    if street_rows:
        return street_rows
    if address_district is None:
        return []
    return _district_rows_for_kind(session, address_district, "preschool")


@router.get(
    "/match",
    response_model=MatchResponse,
    responses={
        200: {
            "description": (
                "Bare array of institution rows when the queried address has "
                "a known район. Envelope `{match_type: 'settlement_only', "
                "results: [...]}` for villages (settlement stamped, район "
                "NULL). Envelope `{match_type: 'district_unknown', results: "
                "[...]}` when neither район nor settlement is stamped."
            )
        }
    },
)
def match(
    address_id: int = Query(..., ge=1, description="addresses.id"),
    kind: Kind | None = Query(None, description="Filter by institution kind"),
    session: Session = Depends(get_db),
) -> MatchResponse | JSONResponse:
    address_row = session.execute(
        select(Address.district_code, Address.settlement_code)
        .where(Address.id == address_id)
        .limit(1)
    ).first()
    if address_row is None:
        return JSONResponse(
            status_code=404, content={"error": "address_not_found"}
        )

    address_district = address_row[0]
    address_settlement = address_row[1]
    requested = _effective_kinds(kind)

    # Nursery routing: район-filtered when the address has a district
    # stamp. Village addresses (settlement set, no район) get no
    # standalone nurseries here — there are zero standalone nurseries
    # outside ГР.ВАРНА, so the city-wide list would just be noise.
    # KGs-with-infant-group still surface in the nursery section via
    # frontend grouping on the junction match.
    results: list[MatchInstitution] = []
    if "kindergarten" in requested:
        results.extend(_street_rows(session, address_id, "kindergarten"))
    if "nursery" in requested and address_district is not None:
        results.extend(
            _district_rows_for_kind(session, address_district, "nursery")
        )
    preschool_results: list[MatchInstitution] = []
    if "preschool" in requested:
        preschool_results = _preschool_rows(
            session, address_id, address_district
        )
        results.extend(preschool_results)

    # Existing ordering: kind ASC, name ASC.
    results.sort(key=lambda r: (r.kind, r.name))

    # Response shape: bare array when район is known. SettlementOnly
    # envelope when район is unknown but settlement is set (village
    # addresses — the frontend uses this to pick village-specific copy).
    # DistrictUnknown envelope when neither stamp is set AND a kind
    # that needs them was requested.
    preschool_needs_district = (
        "preschool" in requested and not preschool_results
    )
    if address_district is None and address_settlement is not None:
        return SettlementOnlyResponse(results=results)
    needs_district_unknown = (
        address_district is None
        and address_settlement is None
        and ("nursery" in requested or preschool_needs_district)
    )
    if needs_district_unknown:
        return DistrictUnknownResponse(results=results)
    return results
