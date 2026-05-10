"""GET /match — institutions covering a given address.

Mounted under `/api` by `yasli.main`, so the public path is `/api/match`.
Takes a stable `address_id` (resolved by the frontend from the bulk
`/api/addresses` payload) plus an optional `kind` filter, and returns
the institutions that serve that address.

A bare list is returned (no envelope) — the frontend already has the
address row from `/api/addresses` and does not need it echoed back.
Unknown `address_id` returns `404 {"error": "address_not_found"}` so the
frontend can distinguish a stale local cache from a kind-filtered empty
result. No cache headers; each response is parameterised by user input.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import literal, select
from sqlalchemy.orm import Session

from yasli.db import get_db
from yasli.models.address import Address, address_institutions
from yasli.models.institution import Institution
from yasli.models.types import Kind

router = APIRouter()


class MatchInstitution(BaseModel):
    id: int
    external_id: str
    name: str
    kind: Kind
    source_url: str


@router.get("/match", response_model=list[MatchInstitution])
def match(
    address_id: int = Query(..., ge=1, description="addresses.id"),
    kind: Kind | None = Query(None, description="Filter by institution kind"),
    session: Session = Depends(get_db),
) -> list[MatchInstitution] | JSONResponse:
    exists = session.execute(
        select(literal(1)).where(Address.id == address_id).limit(1)
    ).first()
    if exists is None:
        return JSONResponse(status_code=404, content={"error": "address_not_found"})

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
        .order_by(Institution.kind.asc(), Institution.name.asc())
    )
    if kind is not None:
        stmt = stmt.where(Institution.kind == kind)

    rows = session.execute(stmt).all()
    return [
        MatchInstitution(
            id=row.id,
            external_id=row.external_id,
            name=row.name,
            kind=row.kind,
            source_url=row.source_url,
        )
        for row in rows
    ]
