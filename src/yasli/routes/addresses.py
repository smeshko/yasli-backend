"""GET /addresses — bulk dump of every Varna address row.

Mounted under `/api` by `yasli.main`, so the public path is `/api/addresses`.
Returns a JSON array of every row in the `addresses` table, ordered by
`(street_id, number_int, number_suffix, entrance)` with NULLs last so the
byte sequence is deterministic across Postgres and SQLite.

The response carries a strong content-derived `ETag` (`v1-<16 hex>`) so
warm reloads can revalidate via `If-None-Match` and receive `304 Not
Modified`. `Cache-Control` permits a CDN/browser to cache the response
for up to an hour with stale-while-revalidate fallback.
"""

from __future__ import annotations

import hashlib
import json

from fastapi import APIRouter, Depends, Header, Response
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel
from sqlalchemy import nullslast, select
from sqlalchemy.orm import Session

from yasli.db import get_db
from yasli.models.address import Address

router = APIRouter()

CACHE_CONTROL = "public, max-age=3600, stale-while-revalidate=86400"
VARY = "Accept-Encoding"


class AddressOut(BaseModel):
    id: int
    street_id: int
    number_int: int
    number_suffix: str | None
    entrance: str | None


@router.get("/addresses", response_model=list[AddressOut])
def list_addresses(
    session: Session = Depends(get_db),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
) -> Response:
    stmt = (
        select(
            Address.id,
            Address.street_id,
            Address.number_int,
            Address.number_suffix,
            Address.entrance,
        )
        .order_by(
            Address.street_id,
            Address.number_int,
            nullslast(Address.number_suffix.asc()),
            nullslast(Address.entrance.asc()),
        )
    )
    rows = session.execute(stmt).all()
    addresses = [
        AddressOut(
            id=row.id,
            street_id=row.street_id,
            number_int=row.number_int,
            number_suffix=row.number_suffix,
            entrance=row.entrance,
        )
        for row in rows
    ]

    payload = jsonable_encoder(addresses)
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(body).hexdigest()[:16]
    etag = f'"v1-{digest}"'

    headers = {
        "ETag": etag,
        "Cache-Control": CACHE_CONTROL,
        "Vary": VARY,
    }

    if if_none_match is not None and if_none_match == etag:
        return Response(status_code=304, headers=headers)

    return Response(
        status_code=200,
        content=body,
        media_type="application/json",
        headers=headers,
    )
