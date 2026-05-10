"""FastAPI application entry point.

Importing this module is cheap; it does not open a DB connection. The engine
is created lazily on the first request that hits a route depending on
`get_db`.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from yasli.routes.addresses import router as addresses_router
from yasli.routes.health import router as health_router
from yasli.routes.institutions import router as institutions_router
from yasli.routes.match import router as match_router
from yasli.routes.streets import router as streets_router

app = FastAPI(title="yasli")
app.include_router(health_router, prefix="/api")
app.include_router(streets_router, prefix="/api")
app.include_router(addresses_router, prefix="/api")
app.include_router(match_router, prefix="/api")
app.include_router(institutions_router, prefix="/api")


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_error_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    del request
    logging.exception("database error", exc_info=exc)
    return JSONResponse(
        status_code=503,
        content={"status": "degraded", "error": "database unreachable"},
    )
