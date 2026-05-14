"""GET /health — DB-backed liveness probe.

Mounted under `/api` by `yasli.main`, so the public path is `/api/health`.
Healthy responses are 200 with `{"status": "ok", "db": "ok"}`. Any
SQLAlchemy error returned by `SELECT 1` becomes a 503 with a generic body;
the traceback is still logged for Railway diagnostics.
"""

from __future__ import annotations

import logging

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
    except SQLAlchemyError:
        logging.exception("health check database error")
        response.status_code = 503
        return {"status": "degraded", "db": "unreachable"}
    return {"status": "ok", "db": "ok"}
