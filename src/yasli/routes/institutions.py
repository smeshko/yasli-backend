"""GET /institutions and /institutions/{id} institution read endpoints.

Mounted under `/api` by `yasli.main`, so the public paths are
`/api/institutions` and `/api/institutions/{institution_id}`.
Both responses are deterministic snapshot views with strong content-derived
ETags and the same cache headers used by the bulk dump endpoints.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, Path, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import case, nullslast, select
from sqlalchemy.orm import Session

from yasli.db import get_db
from yasli.models.address import Address, address_institutions
from yasli.models.institution import Institution
from yasli.models.street import Street
from yasli.models.types import Kind

router = APIRouter()

CACHE_CONTROL = "public, max-age=3600, stale-while-revalidate=86400"
VARY = "Accept-Encoding"


class InstitutionListItem(BaseModel):
    id: int
    external_id: str
    name: str
    kind: Kind
    source_url: str
    last_seen_at: datetime


class StreetSummary(BaseModel):
    id: int
    city: str
    raw_name: str
    street_part: str
    type_marker: str | None


class InstitutionAddress(BaseModel):
    id: int
    number_int: int
    number_suffix: str | None
    entrance: str | None


class CoverageGroup(BaseModel):
    street: StreetSummary
    addresses: list[InstitutionAddress]


class InstitutionDetail(BaseModel):
    id: int
    external_id: str
    name: str
    kind: Kind
    source_url: str
    last_seen_at: datetime
    coverage: list[CoverageGroup]


def _json_bytes(payload: BaseModel | list[BaseModel]) -> bytes:
    encoded = jsonable_encoder(payload)
    return json.dumps(encoded, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _etag(body: bytes) -> str:
    digest = hashlib.sha256(body).hexdigest()[:16]
    return f'"v1-{digest}"'


def _headers(etag: str) -> dict[str, str]:
    return {
        "ETag": etag,
        "Cache-Control": CACHE_CONTROL,
        "Vary": VARY,
    }


def _not_modified_response(
    if_none_match: str | None, etag: str, headers: dict[str, str]
) -> Response | None:
    if if_none_match is not None and if_none_match == etag:
        return Response(status_code=304, headers=headers)
    return None


def _json_response(body: bytes, headers: dict[str, str]) -> Response:
    return Response(
        status_code=200,
        content=body,
        media_type="application/json",
        headers=headers,
    )


def _institution_item(row: Any) -> InstitutionListItem:
    return InstitutionListItem(
        id=row.id,
        external_id=row.external_id,
        name=row.name,
        kind=row.kind,
        source_url=row.source_url,
        last_seen_at=row.last_seen_at,
    )


@router.get("/institutions", response_model=list[InstitutionListItem])
def list_institutions(
    session: Session = Depends(get_db),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
) -> Response:
    kind_order = case(
        (Institution.kind == "nursery", 0),
        (Institution.kind == "kindergarten", 1),
        (Institution.kind == "preschool", 2),
        else_=3,
    )
    stmt = (
        select(
            Institution.id,
            Institution.external_id,
            Institution.name,
            Institution.kind,
            Institution.source_url,
            Institution.last_seen_at,
        )
        .order_by(
            kind_order,
            Institution.name.asc(),
            Institution.external_id.asc(),
            Institution.id.asc(),
        )
    )
    rows = session.execute(stmt).all()
    institutions = [_institution_item(row) for row in rows]

    body = _json_bytes(institutions)
    etag = _etag(body)
    headers = _headers(etag)
    not_modified = _not_modified_response(if_none_match, etag, headers)
    if not_modified is not None:
        return not_modified
    return _json_response(body, headers)


@router.get("/institutions/{institution_id}", response_model=InstitutionDetail)
def get_institution(
    institution_id: int = Path(..., ge=1, description="institutions.id"),
    session: Session = Depends(get_db),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
) -> Response | JSONResponse:
    institution_row = session.execute(
        select(
            Institution.id,
            Institution.external_id,
            Institution.name,
            Institution.kind,
            Institution.source_url,
            Institution.last_seen_at,
        ).where(Institution.id == institution_id)
    ).first()
    if institution_row is None:
        return JSONResponse(status_code=404, content={"error": "institution_not_found"})

    coverage_rows = session.execute(
        select(
            Street.id.label("street_id"),
            Street.city,
            Street.raw_name,
            Street.street_part,
            Street.type_marker,
            Address.id.label("address_id"),
            Address.number_int,
            Address.number_suffix,
            Address.entrance,
        )
        .select_from(address_institutions)
        .join(Address, Address.id == address_institutions.c.address_id)
        .join(Street, Street.id == Address.street_id)
        .where(address_institutions.c.institution_id == institution_id)
        .order_by(
            Street.city.asc(),
            Street.raw_name.asc(),
            Street.id.asc(),
            Address.number_int.asc(),
            nullslast(Address.number_suffix.asc()),
            nullslast(Address.entrance.asc()),
            Address.id.asc(),
        )
    ).all()

    coverage: list[CoverageGroup] = []
    current_street_id: int | None = None
    current_group: CoverageGroup | None = None
    for row in coverage_rows:
        if row.street_id != current_street_id:
            current_group = CoverageGroup(
                street=StreetSummary(
                    id=row.street_id,
                    city=row.city,
                    raw_name=row.raw_name,
                    street_part=row.street_part,
                    type_marker=row.type_marker,
                ),
                addresses=[],
            )
            coverage.append(current_group)
            current_street_id = row.street_id

        assert current_group is not None
        current_group.addresses.append(
            InstitutionAddress(
                id=row.address_id,
                number_int=row.number_int,
                number_suffix=row.number_suffix,
                entrance=row.entrance,
            )
        )

    detail = InstitutionDetail(
        id=institution_row.id,
        external_id=institution_row.external_id,
        name=institution_row.name,
        kind=institution_row.kind,
        source_url=institution_row.source_url,
        last_seen_at=institution_row.last_seen_at,
        coverage=coverage,
    )
    body = _json_bytes(detail)
    etag = _etag(body)
    headers = _headers(etag)
    not_modified = _not_modified_response(if_none_match, etag, headers)
    if not_modified is not None:
        return not_modified
    return _json_response(body, headers)
