"""A bare, **unmigrated** Postgres for the seed integration test.

`tests/ingest/conftest.py` migrates its container up front, which is the
wrong starting point here: step 1 of the seed is `alembic upgrade head`,
and a seed that only works on an already-migrated database is not the one
command YAS-21 asked for.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine

from yasli import db as db_module


def _docker_available() -> bool:
    try:
        result = subprocess.run(
            ["docker", "info"], capture_output=True, check=False, timeout=5
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


@pytest.fixture(scope="session")
def bare_postgres_url() -> Iterator[str]:
    """A running Postgres with no schema at all; yields its URL."""
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        pytest.skip("testcontainers[postgres] not installed")

    if not _docker_available():
        pytest.skip("Docker not available")

    container = PostgresContainer("postgres:16")
    container.start()
    try:
        url = container.get_connection_url()
        url = url.replace("postgresql+psycopg2://", "postgresql+psycopg://")
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        yield url
    finally:
        container.stop()


@pytest.fixture
def bare_engine(bare_postgres_url: str) -> Iterator[Engine]:
    """An engine wired into `yasli.db` so the seed's own steps find it."""
    engine = create_engine(bare_postgres_url, future=True)
    db_module.set_engine(engine)
    try:
        yield engine
    finally:
        engine.dispose()
        db_module._engine = None  # type: ignore[attr-defined]
        db_module._SessionLocal = None  # type: ignore[attr-defined]


@pytest.fixture(scope="session")
def seeded(bare_postgres_url: str) -> Iterator[tuple[object, Engine]]:
    """Run the full seed once per session; yields (summary, engine).

    ``DATABASE_URL`` is set rather than an engine injected, because that is
    the real path: `migrations/env.py` resolves the URL through
    `Settings()` on purpose, so Alembic and the backend share one env-var
    contract.
    """
    from yasli.seed import runner

    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = bare_postgres_url
    db_module._engine = None  # type: ignore[attr-defined]
    db_module._SessionLocal = None  # type: ignore[attr-defined]
    engine = create_engine(bare_postgres_url, future=True)
    try:
        yield runner.run_seed(), engine
    finally:
        engine.dispose()
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        db_module._engine = None  # type: ignore[attr-defined]
        db_module._SessionLocal = None  # type: ignore[attr-defined]
