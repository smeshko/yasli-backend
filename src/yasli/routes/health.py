"""GET /health — DB-backed liveness probe.

Mounted under `/api` by `yasli.main`, so the public path is `/api/health`.
Healthy responses are 200 with `{"status": "ok", "db": "ok"}`. Any
SQLAlchemy error returned by `SELECT 1` becomes a 503 with the error string
in the body so Railway logs surface the underlying cause.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from yasli.db import get_db

router = APIRouter()


@router.get("/health")
def health(response: Response, session: Session = Depends(get_db)) -> dict[str, str]:
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        response.status_code = 503
        return {"status": "degraded", "db": "unreachable", "error": str(exc)}
    return {"status": "ok", "db": "ok"}
