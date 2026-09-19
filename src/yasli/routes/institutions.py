"""Institution read endpoints: the browse list and the detail profile.

Mounted under `/api` by `yasli.main`, so the public paths are
`/api/institutions`, `/api/institutions/{institution_id}` and
`/api/institutions/by-source/{kind}/{external_id}` — the last two return the
same payload, built by one function, addressed by the database serial and by
the stable natural key respectively.
The detail is the enriched institution profile: the snapshot columns, the
address, contact and district metadata the `institutions` table stores, and
the buildings the institution occupies, read from `institution_locations` by
the natural key `(kind, external_id)`.
Both responses are deterministic snapshot views with strong content-derived
ETags and the same cache headers used by the bulk dump endpoints.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, Path, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import and_, case, nullslast, select
from sqlalchemy.orm import Session

from yasli.db import get_db
from yasli.models.address import Address, address_institutions
from yasli.models.institution import Institution
from yasli.models.institution_location import InstitutionLocation
from yasli.models.street import Street
from yasli.models.types import DistrictCode, Kind, LocationPrecision

router = APIRouter()

CACHE_CONTROL = "public, max-age=3600, stale-while-revalidate=86400"
VARY = "Accept-Encoding"

# The detail's scalar columns, in response key order.
_INSTITUTION_COLUMNS = (
    Institution.id,
    Institution.external_id,
    Institution.name,
    Institution.kind,
    Institution.source_url,
    Institution.last_seen_at,
    Institution.address,
    Institution.phone,
    Institution.email,
    Institution.director,
    Institution.website,
    Institution.district_code,
    Institution.has_infant_group,
)


class InstitutionListItem(BaseModel):
    id: int
    external_id: str
    name: str
    kind: Kind
    source_url: str
    last_seen_at: datetime
    has_infant_group: bool
    location: Location | None


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


class Location(BaseModel):
    lat: float
    lon: float
    # `none` is deliberately absent: a row with that precision has no
    # coordinate (CHECK constraint), and an absent pin is `location: null`.
    precision: Literal["building", "approximate"]


class Branch(BaseModel):
    label: str | None
    address: str | None
    location: Location | None


class InstitutionDetail(BaseModel):
    # Field order is JSON key order: the body is serialised from this model by
    # hand, and the ETag hashes exactly those bytes.
    id: int
    external_id: str
    name: str
    kind: Kind
    source_url: str
    last_seen_at: datetime
    # Declared without defaults so they are required-and-nullable: always
    # present in the body, in OpenAPI's `required`, and `X | null` in the
    # generated TypeScript.
    address: str | None
    phone: str | None
    email: str | None
    director: str | None
    website: str | None
    district_code: DistrictCode | None
    has_infant_group: bool
    location: Location | None
    branches: list[Branch]
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


def _location(
    lat: Decimal | None, lon: Decimal | None, precision: LocationPrecision
) -> Location | None:
    """A pin, or `None` when the row carries no coordinate.

    `float()` is explicit: `jsonable_encoder` would render an integral
    `Decimal` as an int, which is not what a coordinate is.
    """
    if lat is None or lon is None:
        return None
    return Location(lat=float(lat), lon=float(lon), precision=precision)


def _blank_to_none(value: str) -> str | None:
    """`institution_locations` stores an absent label/address as `""` so the
    UNIQUE tuple constrains. That is storage, not a value."""
    return value or None


def _locations_for(
    session: Session, kind: str, external_id: str
) -> tuple[Location | None, list[Branch]]:
    rows = session.execute(
        select(
            InstitutionLocation.role,
            InstitutionLocation.label,
            InstitutionLocation.address,
            InstitutionLocation.lat,
            InstitutionLocation.lon,
            InstitutionLocation.precision,
        )
        .where(
            InstitutionLocation.kind == kind,
            InstitutionLocation.external_id == external_id,
        )
        # Never order by `id`: the loader truncates and reinserts, so it is
        # reassigned on every run. The UNIQUE tuple makes (label, address)
        # unique within one institution's branches.
        .order_by(
            case((InstitutionLocation.role == "main", 0), else_=1),
            InstitutionLocation.label.asc(),
            InstitutionLocation.address.asc(),
        )
    ).all()

    location: Location | None = None
    branches: list[Branch] = []
    for row in rows:
        if row.role == "main":
            if location is None:
                location = _location(row.lat, row.lon, row.precision)
            continue
        branches.append(
            Branch(
                label=_blank_to_none(row.label),
                address=_blank_to_none(row.address),
                location=_location(row.lat, row.lon, row.precision),
            )
        )
    return location, branches


def _institution_item(row: Any) -> InstitutionListItem:
    return InstitutionListItem(
        id=row.id,
        external_id=row.external_id,
        name=row.name,
        kind=row.kind,
        source_url=row.source_url,
        last_seen_at=row.last_seen_at,
        has_infant_group=row.has_infant_group,
        location=_location(row.lat, row.lon, row.precision),
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
            Institution.has_infant_group,
            InstitutionLocation.lat,
            InstitutionLocation.lon,
            InstitutionLocation.precision,
        )
        # `uq_institution_locations_main` is a partial unique index on
        # (kind, external_id) WHERE role = 'main', so this join matches at
        # most one row and cannot multiply list items. `role == "main"` must
        # stay in the ON clause: in a WHERE clause it would turn the outer
        # join into an inner one and drop every unlocated institution.
        .outerjoin(
            InstitutionLocation,
            and_(
                InstitutionLocation.kind == Institution.kind,
                InstitutionLocation.external_id == Institution.external_id,
                InstitutionLocation.role == "main",
            ),
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


def _institution_row(session: Session, *where: Any) -> Any:
    return session.execute(select(*_INSTITUTION_COLUMNS).where(*where)).first()


def _coverage_for(session: Session, institution_id: int) -> list[CoverageGroup]:
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
    return coverage


def _detail_response(
    session: Session, institution_row: Any, if_none_match: str | None
) -> Response:
    """The one detail payload: both handlers are a lookup plus this call."""
    location, branches = _locations_for(
        session, institution_row.kind, institution_row.external_id
    )
    detail = InstitutionDetail(
        id=institution_row.id,
        external_id=institution_row.external_id,
        name=institution_row.name,
        kind=institution_row.kind,
        source_url=institution_row.source_url,
        last_seen_at=institution_row.last_seen_at,
        address=institution_row.address,
        phone=institution_row.phone,
        email=institution_row.email,
        director=institution_row.director,
        website=institution_row.website,
        district_code=institution_row.district_code,
        has_infant_group=institution_row.has_infant_group,
        location=location,
        branches=branches,
        coverage=_coverage_for(session, institution_row.id),
    )
    body = _json_bytes(detail)
    etag = _etag(body)
    headers = _headers(etag)
    not_modified = _not_modified_response(if_none_match, etag, headers)
    if not_modified is not None:
        return not_modified
    return _json_response(body, headers)


def _not_found() -> JSONResponse:
    return JSONResponse(status_code=404, content={"error": "institution_not_found"})


@router.get("/institutions/{institution_id}", response_model=InstitutionDetail)
def get_institution(
    institution_id: int = Path(..., ge=1, description="institutions.id"),
    session: Session = Depends(get_db),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
) -> Response | JSONResponse:
    """The detail by database serial.

    `{institution_id}` matches exactly one path segment, so the three-segment
    by-source path below can never be captured here regardless of registration
    order. The reverse — `/api/institutions/by-source` with nothing after it —
    does land here and returns 422, because `"by-source"` is not an integer.
    """
    institution_row = _institution_row(session, Institution.id == institution_id)
    if institution_row is None:
        return _not_found()
    return _detail_response(session, institution_row, if_none_match)


@router.get(
    "/institutions/by-source/{kind}/{external_id}", response_model=InstitutionDetail
)
def get_institution_by_source(
    kind: Kind = Path(..., description="institutions.kind"),
    external_id: str = Path(..., description="institutions.external_id"),
    session: Session = Depends(get_db),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
) -> Response | JSONResponse:
    """The same detail by the stable natural key `(kind, external_id)`.

    `institutions.id` is a serial reassigned on every re-ingest; this pair is
    not, so the frontend addresses a page by it. `external_id` carries no
    length constraint: a value longer than the column is "no such
    institution", not a malformed request.
    """
    institution_row = _institution_row(
        session,
        Institution.kind == kind,
        Institution.external_id == external_id,
    )
    if institution_row is None:
        return _not_found()
    return _detail_response(session, institution_row, if_none_match)
