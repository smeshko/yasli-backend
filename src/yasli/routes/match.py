"""GET /match — institutions covering a given address.

Mounted under ``/api`` by ``yasli.main``, so the public path is ``/api/match``.

Two routing paths land in one response:

* **kindergartens** come from the existing ``address_institutions`` junction
  (street-level catchment), each row carrying ``match_type: "street"``.
* **nurseries** and **preschools** come from the district-routing path:
  ``institutions.district_code = (the query address's district_code)`` with
  the requested kind filter applied. These rows carry
  ``match_type: "district"``.

The response shape depends on the query address:

* If the address's ``district_code`` is non-NULL → bare JSON array (the
  original v1 shape, preserved for the existing frontend caller).
* If the address's ``district_code`` is NULL **and** the request could
  have returned nurseries or preschools (i.e. ``kind`` is unset OR
  explicitly ``nursery``/``preschool``) → envelope
  ``{ match_type: "district_unknown", results: [...] }`` whose ``results``
  array contains kindergarten matches only (nurseries and preschools are
  omitted since their routing is by district).
* If the address's ``district_code`` is NULL **and** ``kind=kindergarten``
  was explicit → bare array of kindergartens (the envelope only fires
  when nursery/preschool results were expected).

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
from sqlalchemy import literal, select
from sqlalchemy.orm import Session

from yasli.db import get_db
from yasli.models.address import Address, address_institutions
from yasli.models.institution import Institution
from yasli.models.types import Kind

router = APIRouter()


class MatchInstitution(BaseModel):
    """One institution covering the queried address.

    ``match_type`` is ``"street"`` for kindergartens (junction match) and
    ``"district"`` for nurseries and preschools (district routing).
    """

    id: int
    external_id: str
    name: str
    kind: Kind
    source_url: str
    match_type: Literal["street", "district"]


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


def _kindergarten_rows(
    session: Session, address_id: int
) -> list[MatchInstitution]:
    """Street-routing path: junction-based kindergartens."""
    stmt = (
        select(
            Institution.id,
            Institution.external_id,
            Institution.name,
            Institution.kind,
            Institution.source_url,
        )
        .join(
            address_institutions,
            Institution.id == address_institutions.c.institution_id,
        )
        .where(address_institutions.c.address_id == address_id)
        .where(Institution.kind == "kindergarten")
    )
    return [
        MatchInstitution(
            id=row.id,
            external_id=row.external_id,
            name=row.name,
            kind=row.kind,
            source_url=row.source_url,
            match_type="street",
        )
        for row in session.execute(stmt).all()
    ]


def _district_rows(
    session: Session,
    district_code: str,
    requested_kinds: tuple[Kind, ...],
) -> list[MatchInstitution]:
    """District-routing path: filter by ``institutions.district_code``.

    Used for nurseries and preschools. Kindergartens are never routed via
    this path even when the kind filter is absent; the caller filters
    them out of ``requested_kinds`` before calling.
    """
    district_kinds = tuple(k for k in requested_kinds if k != "kindergarten")
    if not district_kinds:
        return []
    stmt = (
        select(
            Institution.id,
            Institution.external_id,
            Institution.name,
            Institution.kind,
            Institution.source_url,
        )
        .where(Institution.kind.in_(district_kinds))
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
        )
        for row in session.execute(stmt).all()
    ]


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
        results.extend(_kindergarten_rows(session, address_id))
    if address_district is not None:
        results.extend(_district_rows(session, address_district, requested))

    # Existing ordering: kind ASC, name ASC.
    results.sort(key=lambda r: (r.kind, r.name))

    # Envelope vs bare-array decision: envelope only when the request
    # could have returned nurseries or preschools AND the address has no
    # district stamp.
    needs_envelope = address_district is None and (
        "nursery" in requested or "preschool" in requested
    )
    if needs_envelope:
        return DistrictUnknownResponse(results=results)
    return results
