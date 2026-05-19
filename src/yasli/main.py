"""FastAPI application entry point.

Importing this module is cheap; it does not open a DB connection. The engine
is created lazily on the first request that hits a route depending on
`get_db`.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from yasli.config import CorsSettings, Settings
from yasli.routes.addresses import router as addresses_router
from yasli.routes.health import router as health_router
from yasli.routes.institutions import router as institutions_router
from yasli.routes.match import router as match_router
from yasli.routes.streets import router as streets_router


def create_app(cors_allowed_origins: Sequence[str] | None = None) -> FastAPI:
    allowed_origins = (
        tuple(cors_allowed_origins)
        if cors_allowed_origins is not None
        else CorsSettings().allowed_origins
    )
    if Settings().environment == "production" and not allowed_origins:
        raise RuntimeError(
            "CORS_ALLOWED_ORIGINS must be set in production; "
            "refusing to start with no allowed origins"
        )
    app = FastAPI(title="yasli")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(allowed_origins),
        allow_methods=["GET"],
        allow_headers=["*"],
        expose_headers=["ETag"],
    )
    app.include_router(health_router, prefix="/api")
    app.include_router(streets_router, prefix="/api")
    app.include_router(addresses_router, prefix="/api")
    app.include_router(match_router, prefix="/api")
    app.include_router(institutions_router, prefix="/api")
    app.add_exception_handler(SQLAlchemyError, sqlalchemy_error_handler)
    return app


async def sqlalchemy_error_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    del request
    logging.exception("database error", exc_info=exc)
    return JSONResponse(
        status_code=503,
        content={"status": "degraded", "error": "database unreachable"},
    )


app = create_app()
