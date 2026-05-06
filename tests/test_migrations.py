"""Migration round-trip and structural tests against a real Postgres.

These tests require a reachable Postgres. They opt in via the
`YASLI_TEST_DATABASE_URL` env var (or fall back to `DATABASE_URL` if it
points at a real Postgres). When neither is available, the whole module
SKIPs with an explicit message — the tests do not silently pass.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

REPO_ROOT = Path(__file__).resolve().parents[1]


def _candidate_url() -> str | None:
    """Pick the Postgres URL used for migration tests.

    Prefer `YASLI_TEST_DATABASE_URL` (a dedicated, throwaway DB). Fall back
    to `DATABASE_URL` only if it looks like Postgres — the conftest sets a
    placeholder Postgres URL that points at a local server which may or may
    not exist. The reachability check below decides.
    """
    explicit = os.environ.get("YASLI_TEST_DATABASE_URL")
    if explicit:
        return explicit
    fallback = os.environ.get("DATABASE_URL")
    if fallback and ("postgres" in fallback):
        return fallback
    return None


def _is_reachable(url: str) -> bool:
    try:
        engine = create_engine(url, future=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


_url = _candidate_url()
pytestmark = pytest.mark.skipif(
    _url is None or not _is_reachable(_url),
    reason=(
        "Postgres unavailable — set YASLI_TEST_DATABASE_URL to a reachable "
        "Postgres URL (e.g. postgresql+psycopg://user:pw@localhost:5432/yasli_test) "
        "to run migration tests."
    ),
)


def _alembic(args: list[str], url: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["DATABASE_URL"] = url
    src = str(REPO_ROOT / "src")
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def db_url() -> str:
    assert _url is not None
    return _url


@pytest.fixture
def fresh_db(db_url: str) -> str:
    """Reset the target DB to revision base before each test."""
    result = _alembic(["downgrade", "base"], db_url)
    assert result.returncode == 0, result.stderr
    return db_url


def _engine(url: str) -> Engine:
    return create_engine(url, future=True)


def _current_revision(engine: Engine) -> str | None:
    insp = inspect(engine)
    if "alembic_version" not in insp.get_table_names():
        return None
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT version_num FROM alembic_version")).all()
    return rows[0][0] if rows else None


def _table_names(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names())


def test_round_trip_upgrade_downgrade_upgrade(fresh_db: str) -> None:
    url = fresh_db

    up1 = _alembic(["upgrade", "head"], url)
    assert up1.returncode == 0, up1.stderr
    eng = _engine(url)
    assert _current_revision(eng) == "0002"
    tables = _table_names(eng)
    assert {"institutions", "streets", "address_entries"}.issubset(tables)
    eng.dispose()

    down = _alembic(["downgrade", "-1"], url)
    assert down.returncode == 0, down.stderr
    eng = _engine(url)
    assert _current_revision(eng) == "0001"
    tables = _table_names(eng)
    assert "institutions" not in tables
    assert "streets" not in tables
    assert "address_entries" not in tables
    eng.dispose()

    up2 = _alembic(["upgrade", "head"], url)
    assert up2.returncode == 0, up2.stderr
    eng = _engine(url)
    assert _current_revision(eng) == "0002"
    tables = _table_names(eng)
    assert {"institutions", "streets", "address_entries"}.issubset(tables)
    eng.dispose()


def test_trigram_index_on_streets_search_norm(fresh_db: str) -> None:
    url = fresh_db
    up = _alembic(["upgrade", "head"], url)
    assert up.returncode == 0, up.stderr

    eng = _engine(url)
    with eng.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE tablename = 'streets' "
                "  AND indexname = 'streets_search_norm_trgm'"
            )
        ).all()
    eng.dispose()

    assert len(rows) == 1, "expected a single streets_search_norm_trgm index"
    indexdef = rows[0][0].lower()
    assert "gin" in indexdef
    assert "gin_trgm_ops" in indexdef
    assert "search_norm" in indexdef


def test_pg_trgm_extension_present(fresh_db: str) -> None:
    url = fresh_db
    up = _alembic(["upgrade", "head"], url)
    assert up.returncode == 0, up.stderr

    eng = _engine(url)
    with eng.connect() as conn:
        rows = conn.execute(
            text("SELECT extname FROM pg_extension WHERE extname = 'pg_trgm'")
        ).all()
    eng.dispose()
    assert rows == [("pg_trgm",)]


def test_address_entries_has_no_priority_class_column(fresh_db: str) -> None:
    url = fresh_db
    up = _alembic(["upgrade", "head"], url)
    assert up.returncode == 0, up.stderr

    eng = _engine(url)
    with eng.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'address_entries'"
            )
        ).all()
    eng.dispose()
    columns = {row[0] for row in rows}
    assert "priority_class" not in columns, (
        "priority_class is dropped per s02 Decision 8 — do not reintroduce it "
        "without a snapshot.v2 contract bump"
    )
    assert {"institution_id", "street_id", "number_int", "number_suffix", "entrance"} <= columns


def test_address_entries_lookup_index_present(fresh_db: str) -> None:
    """Index on (street_id, number_int) for the s08 match endpoint."""
    url = fresh_db
    up = _alembic(["upgrade", "head"], url)
    assert up.returncode == 0, up.stderr

    eng = _engine(url)
    with eng.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE tablename = 'address_entries' "
                "  AND indexname = 'address_entries_lookup'"
            )
        ).all()
    eng.dispose()
    assert len(rows) == 1
    indexdef = rows[0][0].lower()
    assert "street_id" in indexdef
    assert "number_int" in indexdef
