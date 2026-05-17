"""GET /match and /match/v2 institution coverage endpoints.

Mounted under ``/api`` by ``yasli.main``, so the public paths are
``/api/match`` and ``/api/match/v2``.

The legacy ``/api/match`` response is intentionally preserved for the current
frontend: it can return a bare array, a ``settlement_only`` envelope, or a
``district_unknown`` envelope. The structured ``/api/match/v2`` endpoint is
additive and always returns ``{address, results}`` for known addresses.

Unknown ``address_id`` returns ``404 {"error": "address_not_found"}`` so the
frontend can distinguish a stale local cache from a kind-filtered empty result.
No cache headers; each response is parameterised by user input.
"""

from __future__ import annotations

from typing import Literal, Union

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from yasli.db import get_db
from yasli.models.types import DistrictCode, Kind, LocalityType
from yasli.services.matching import (
    AddressContext,
    MatchedInstitution,
    MatchSet,
    find_matches,
)

router = APIRouter()


class MatchInstitution(BaseModel):
    """One legacy institution row covering the queried address.

    ``match_type`` is ``"street"`` for junction-based matches
    (kindergartens always; preschools when the source publishes a catchment
    that includes the address) and ``"district"`` for district-routed matches
    (nurseries always; preschools when no junction row was found).
    """

    id: int
    external_id: str
    name: str
    kind: Kind
    source_url: str
    match_type: Literal["street", "district"]
    has_infant_group: bool


class DistrictUnknownResponse(BaseModel):
    """Legacy envelope for addresses with neither rayon nor settlement stamp."""

    match_type: Literal["district_unknown"] = Field(default="district_unknown")
    results: list[MatchInstitution]


class SettlementOnlyResponse(BaseModel):
    """Legacy envelope for addresses with settlement stamp but no rayon."""

    match_type: Literal["settlement_only"] = Field(default="settlement_only")
    results: list[MatchInstitution]


# OpenAPI declares the legacy 200 response as ``oneOf`` of the bare array and
# the envelope shapes, so generated TypeScript types narrow correctly.
MatchResponse = Union[
    list[MatchInstitution], DistrictUnknownResponse, SettlementOnlyResponse
]


class MatchSettlementContext(BaseModel):
    code: str
    name: str
    locality_type: LocalityType


class MatchAddressContext(BaseModel):
    id: int
    district_code: DistrictCode | None
    settlement: MatchSettlementContext | None


class MatchResult(BaseModel):
    id: int
    external_id: str
    name: str
    institution_kind: Kind
    source_url: str
    match_basis: Literal["address", "district"]
    has_infant_group: bool


class StructuredMatchResponse(BaseModel):
    address: MatchAddressContext
    results: list[MatchResult]


def _not_found() -> JSONResponse:
    return JSONResponse(status_code=404, content={"error": "address_not_found"})


def _legacy_row(row: MatchedInstitution) -> MatchInstitution:
    return MatchInstitution(
        id=row.id,
        external_id=row.external_id,
        name=row.name,
        kind=row.institution_kind,
        source_url=row.source_url,
        match_type="street" if row.match_basis == "address" else "district",
        has_infant_group=row.has_infant_group,
    )


def _legacy_response(match_set: MatchSet) -> MatchResponse:
    results = [_legacy_row(row) for row in match_set.results]
    address = match_set.address
    requested = match_set.requested_kinds

    preschool_needs_district = "preschool" in requested and not any(
        row.institution_kind == "preschool" for row in match_set.results
    )
    if address.district_code is None and address.settlement_code is not None:
        return SettlementOnlyResponse(results=results)
    needs_district_unknown = (
        address.district_code is None
        and address.settlement_code is None
        and ("nursery" in requested or preschool_needs_district)
    )
    if needs_district_unknown:
        return DistrictUnknownResponse(results=results)
    return results


def _address_response(address: AddressContext) -> MatchAddressContext:
    settlement = None
    if address.settlement is not None:
        settlement = MatchSettlementContext(
            code=address.settlement.code,
            name=address.settlement.name,
            locality_type=address.settlement.locality_type,
        )
    return MatchAddressContext(
        id=address.id,
        district_code=address.district_code,
        settlement=settlement,
    )


def _structured_row(row: MatchedInstitution) -> MatchResult:
    return MatchResult(
        id=row.id,
        external_id=row.external_id,
        name=row.name,
        institution_kind=row.institution_kind,
        source_url=row.source_url,
        match_basis=row.match_basis,
        has_infant_group=row.has_infant_group,
    )


def _structured_response(match_set: MatchSet) -> StructuredMatchResponse:
    return StructuredMatchResponse(
        address=_address_response(match_set.address),
        results=[_structured_row(row) for row in match_set.results],
    )


@router.get(
    "/match",
    response_model=MatchResponse,
    responses={
        200: {
            "description": (
                "Bare array of institution rows when the queried address has "
                "a known rayon. Envelope `{match_type: 'settlement_only', "
                "results: [...]}` for settlement-stamped rows with no rayon. "
                "Envelope `{match_type: 'district_unknown', results: [...]}` "
                "when neither rayon nor settlement is stamped."
            )
        }
    },
)
def match(
    address_id: int = Query(..., ge=1, description="addresses.id"),
    kind: Kind | None = Query(None, description="Filter by institution kind"),
    session: Session = Depends(get_db),
) -> MatchResponse | JSONResponse:
    match_set = find_matches(session, address_id, kind)
    if match_set is None:
        return _not_found()
    return _legacy_response(match_set)


@router.get("/match/v2", response_model=StructuredMatchResponse)
def structured_match(
    address_id: int = Query(..., ge=1, description="addresses.id"),
    kind: Kind | None = Query(None, description="Filter by institution kind"),
    session: Session = Depends(get_db),
) -> StructuredMatchResponse | JSONResponse:
    match_set = find_matches(session, address_id, kind)
    if match_set is None:
        return _not_found()
    return _structured_response(match_set)
