"""GET /streets — bulk dump of every Varna street row.

Mounted under `/api` by `yasli.main`, so the public path is `/api/streets`.
Returns a JSON array of every row in the `streets` table, ordered by
`(city, raw_name)`. Compound localities (rows whose `street_part` is the
empty string) are included alongside named streets.

The response carries a strong content-derived `ETag` (`v1-<16 hex>`) so
warm reloads can revalidate via `If-None-Match` and receive `304 Not
Modified`. `Cache-Control` permits a CDN/browser to cache the response
for up to an hour with stale-while-revalidate fallback.
"""

from __future__ import annotations

import hashlib
import json

from fastapi import APIRouter, Depends, Header, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from yasli.db import get_db
from yasli.models.street import Street

router = APIRouter()

CACHE_CONTROL = "public, max-age=3600, stale-while-revalidate=86400"
VARY = "Accept-Encoding"


class StreetOut(BaseModel):
    id: int
    city: str
    raw_name: str
    street_part: str
    type_marker: str | None


@router.get("/streets", response_model=list[StreetOut])
def list_streets(
    session: Session = Depends(get_db),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
) -> Response:
    stmt = (
        select(
            Street.id,
            Street.city,
            Street.raw_name,
            Street.street_part,
            Street.type_marker,
        )
        .order_by(Street.city, Street.raw_name)
    )
    rows = session.execute(stmt).all()
    payload = [
        {
            "id": row.id,
            "city": row.city,
            "raw_name": row.raw_name,
            "street_part": row.street_part,
            "type_marker": row.type_marker,
        }
        for row in rows
    ]

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
