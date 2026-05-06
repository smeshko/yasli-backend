"""FastAPI application entry point.

Importing this module is cheap; it does not open a DB connection. The engine
is created lazily on the first request that hits a route depending on
`get_db`.
"""

from __future__ import annotations

from fastapi import FastAPI

from yasli.routes.health import router as health_router

app = FastAPI(title="yasli")
app.include_router(health_router, prefix="/api")
