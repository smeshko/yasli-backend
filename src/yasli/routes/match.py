"""GET /match and /match/v2 institution coverage endpoints.

Mounted under ``/api`` by ``yasli.main``, so the public paths are
``/api/match`` and ``/api/match/v2``.

``/api/match`` is the canonical structured endpoint. ``/api/match/v2`` remains
as a temporary alias during the cleanup release.

Unknown ``address_id`` returns ``404 {"error": "address_not_found"}`` so the
frontend can distinguish a stale local cache from a kind-filtered empty result.
No cache headers; each response is parameterised by user input.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
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
    reception_kind: Kind
    offering: Literal["standard", "infant_group"]
    source_url: str
    match_basis: Literal["address", "district"]
    has_infant_group: bool


class StructuredMatchResponse(BaseModel):
    address: MatchAddressContext
    results: list[MatchResult]


def _not_found() -> JSONResponse:
    return JSONResponse(status_code=404, content={"error": "address_not_found"})


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


_RECEPTION_KIND_ORDER: dict[Kind, int] = {
    "nursery": 0,
    "kindergarten": 1,
    "preschool": 2,
}


def _structured_standard_row(row: MatchedInstitution) -> MatchResult:
    return MatchResult(
        id=row.id,
        external_id=row.external_id,
        name=row.name,
        institution_kind=row.institution_kind,
        reception_kind=row.institution_kind,
        offering="standard",
        source_url=row.source_url,
        match_basis=row.match_basis,
        has_infant_group=row.has_infant_group,
    )


def _structured_infant_group_row(row: MatchedInstitution) -> MatchResult:
    return MatchResult(
        id=row.id,
        external_id=row.external_id,
        name=row.name,
        institution_kind=row.institution_kind,
        reception_kind="nursery",
        offering="infant_group",
        source_url=row.source_url,
        match_basis=row.match_basis,
        has_infant_group=row.has_infant_group,
    )


def _structured_rows(row: MatchedInstitution) -> list[MatchResult]:
    results = [_structured_standard_row(row)]
    if (
        row.institution_kind == "kindergarten"
        and row.has_infant_group
        and row.match_basis == "address"
    ):
        results.append(_structured_infant_group_row(row))
    return results


def _structured_sort_key(row: MatchResult) -> tuple[int, str, Kind, str]:
    return (
        _RECEPTION_KIND_ORDER[row.reception_kind],
        row.name,
        row.institution_kind,
        row.offering,
    )


def _structured_response(match_set: MatchSet) -> StructuredMatchResponse:
    results = [
        result
        for row in match_set.results
        for result in _structured_rows(row)
    ]
    results.sort(key=_structured_sort_key)
    return StructuredMatchResponse(
        address=_address_response(match_set.address),
        results=results,
    )


def _match_response(
    session: Session,
    address_id: int,
    kind: Kind | None,
) -> StructuredMatchResponse | JSONResponse:
    match_set = find_matches(session, address_id, kind)
    if match_set is None:
        return _not_found()
    return _structured_response(match_set)


@router.get("/match", response_model=StructuredMatchResponse)
def match(
    address_id: int = Query(..., ge=1, description="addresses.id"),
    kind: Kind | None = Query(None, description="Filter by institution kind"),
    session: Session = Depends(get_db),
) -> StructuredMatchResponse | JSONResponse:
    return _match_response(session, address_id, kind)


@router.get("/match/v2", response_model=StructuredMatchResponse)
def structured_match(
    address_id: int = Query(..., ge=1, description="addresses.id"),
    kind: Kind | None = Query(None, description="Filter by institution kind"),
    session: Session = Depends(get_db),
) -> StructuredMatchResponse | JSONResponse:
    return _match_response(session, address_id, kind)
