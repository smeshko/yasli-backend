"""Pytest fixtures for ingest integration tests.

The fixtures here power session-scoped tests that need a real Postgres
(testcontainers) plus a moto-mocked S3 client standing in for R2. If
either Docker or testcontainers is unavailable, the relevant tests skip
loudly — they do not silently pass.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from yasli import db as db_module

REPO_ROOT = Path(__file__).resolve().parents[2]


def _docker_available() -> bool:
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            check=False,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    """Spin up a Postgres testcontainer and migrate it to head; yield the URL."""
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        pytest.skip(
            "testcontainers[postgres] not installed — run "
            "`pip install testcontainers[postgres]` to enable ingest "
            "integration tests."
        )

    if not _docker_available():
        pytest.skip(
            "Docker not available — integration tests need a running Docker "
            "daemon to spawn a Postgres container."
        )

    container = PostgresContainer("postgres:16")
    container.start()
    try:
        url = container.get_connection_url()
        # testcontainers returns `postgresql+psycopg2://...`; rewrite to the
        # `postgresql+psycopg://` form that this project uses.
        url = url.replace("postgresql+psycopg2://", "postgresql+psycopg://")
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)

        env = os.environ.copy()
        env["DATABASE_URL"] = url
        env["PYTHONPATH"] = str(REPO_ROOT / "src") + os.pathsep + env.get(
            "PYTHONPATH", ""
        )
        proc = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, (
            f"alembic upgrade head failed: {proc.stderr}"
        )

        yield url
    finally:
        container.stop()


@pytest.fixture
def engine(postgres_url: str) -> Iterator[Engine]:
    """A SQLAlchemy engine wired into yasli.db for the duration of the test."""
    eng = create_engine(postgres_url, future=True)
    db_module.set_engine(eng)
    try:
        yield eng
    finally:
        eng.dispose()
        db_module._engine = None  # type: ignore[attr-defined]
        db_module._SessionLocal = None  # type: ignore[attr-defined]


@pytest.fixture(autouse=True)
def _truncate_tables(engine: Engine) -> Iterator[None]:
    """Wipe data between tests so per-test fixtures don't bleed."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE TABLE address_institutions, addresses, streets, institutions "
                "RESTART IDENTITY CASCADE"
            )
        )
    yield


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with Session(engine) as s:
        yield s
