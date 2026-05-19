"""GET /match institution coverage endpoint.

Mounted under ``/api`` by ``yasli.main``, so the public paths are
``/api/match``.

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
    build_offerings,
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


@router.get("/match", response_model=StructuredMatchResponse)
def match(
    address_id: int = Query(..., ge=1, description="addresses.id"),
    kind: Kind | None = Query(None, description="Filter by institution kind"),
    session: Session = Depends(get_db),
) -> StructuredMatchResponse | JSONResponse:
    match_set = find_matches(session, address_id, kind)
    if match_set is None:
        return _not_found()
    offerings = build_offerings(match_set)
    return StructuredMatchResponse(
        address=_address_response(match_set.address),
        results=[
            MatchResult(
                id=o.id,
                external_id=o.external_id,
                name=o.name,
                institution_kind=o.institution_kind,
                reception_kind=o.reception_kind,
                offering=o.offering,
                source_url=o.source_url,
                match_basis=o.match_basis,
                has_infant_group=o.has_infant_group,
            )
            for o in offerings
        ],
    )
