"""GET /match — institutions covering a given address.

Mounted under ``/api`` by ``yasli.main``, so the public path is ``/api/match``.

Three routing paths land in one response:

* **kindergartens** come from the ``address_institutions`` junction
  (street-level catchment), each row carrying ``match_type: "street"``.
* **nurseries** come from district routing only:
  ``institutions.district_code = (the query address's district_code)``.
  These rows carry ``match_type: "district"``.
* **preschools** are hybrid: the source publishes per-PG catchment
  streets for some institutions, so the junction is tried first. If
  the address has at least one PG junction row, those are returned
  (``match_type: "street"``) and the district fallback is skipped.
  Otherwise we fall back to district routing
  (``match_type: "district"``) — same SQL shape as nurseries.

The response shape depends on the query address:

* If the address's ``district_code`` is non-NULL → bare JSON array (the
  original v1 shape, preserved for the existing frontend caller).
* If the address's ``district_code`` is NULL **and** results are likely
  incomplete because of the missing district (nursery was requested,
  or preschool was requested but had no junction rows) → envelope
  ``{ match_type: "district_unknown", results: [...] }`` whose ``results``
  array still contains every matchable row we could find (kindergartens
  by junction, plus PG junction rows if any).
* If the address's ``district_code`` is NULL **and** every requested
  kind could be answered without district info (``kind=kindergarten``,
  or ``kind=preschool`` with PG junction rows present) → bare array.

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
    """Envelope returned when the queried address has no district stamp
    and nurseries/preschools were among the kinds the request could have
    returned. ``results`` carries kindergarten matches only.
    """

    match_type: Literal["district_unknown"] = Field(default="district_unknown")
    results: list[MatchInstitution]


# OpenAPI declares the 200 response as ``oneOf`` of the bare array and
# the envelope shape, so generated TypeScript types narrow correctly.
MatchResponse = Union[list[MatchInstitution], DistrictUnknownResponse]


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
                "a known district. Envelope `{match_type: 'district_unknown', "
                "results: [...]}` when the district is unknown and nursery/"
                "preschool matches were possible."
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
        select(Address.district_code).where(Address.id == address_id).limit(1)
    ).first()
    if address_row is None:
        return JSONResponse(
            status_code=404, content={"error": "address_not_found"}
        )

    address_district = address_row[0]
    requested = _effective_kinds(kind)

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

    # Envelope vs bare-array decision: envelope when the address has no
    # district stamp AND results were likely incomplete because of it.
    # Nursery requests always need district. Preschool requests need
    # district only when no junction rows answered the query.
    preschool_needs_district = (
        "preschool" in requested and not preschool_results
    )
    needs_envelope = address_district is None and (
        "nursery" in requested or preschool_needs_district
    )
    if needs_envelope:
        return DistrictUnknownResponse(results=results)
    return results
