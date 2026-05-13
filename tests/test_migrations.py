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
    assert _current_revision(eng) == "0004"
    tables = _table_names(eng)
    assert {
        "institutions",
        "streets",
        "addresses",
        "address_institutions",
    }.issubset(tables)
    assert "address_entries" not in tables
    eng.dispose()

    down = _alembic(["downgrade", "-1"], url)
    assert down.returncode == 0, down.stderr
    eng = _engine(url)
    assert _current_revision(eng) == "0003"
    tables = _table_names(eng)
    # 0003 shape: address-centric tables remain, institution metadata gone.
    assert {
        "institutions",
        "streets",
        "addresses",
        "address_institutions",
    }.issubset(tables)
    assert "address_entries" not in tables
    columns = {c["name"] for c in inspect(eng).get_columns("institutions")}
    assert {"address", "district_code", "has_infant_group"}.isdisjoint(columns)
    eng.dispose()

    up2 = _alembic(["upgrade", "head"], url)
    assert up2.returncode == 0, up2.stderr
    eng = _engine(url)
    assert _current_revision(eng) == "0004"
    tables = _table_names(eng)
    assert {
        "institutions",
        "streets",
        "addresses",
        "address_institutions",
    }.issubset(tables)
    assert "address_entries" not in tables
    eng.dispose()


def test_institutions_metadata_columns_and_constraint(fresh_db: str) -> None:
    url = fresh_db
    up = _alembic(["upgrade", "head"], url)
    assert up.returncode == 0, up.stderr

    eng = _engine(url)
    with eng.connect() as conn:
        cols = conn.execute(
            text(
                "SELECT column_name, is_nullable, column_default "
                "FROM information_schema.columns "
                "WHERE table_name = 'institutions'"
            )
        ).all()
        constraints = conn.execute(
            text(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid = 'institutions'::regclass"
            )
        ).all()
    eng.dispose()

    by_name = {row[0]: row for row in cols}
    assert by_name["address"][1] == "YES"
    assert by_name["district_code"][1] == "YES"
    assert by_name["has_infant_group"][1] == "NO"
    assert by_name["has_infant_group"][2] == "false"
    constraint_names = {c[0] for c in constraints}
    assert "ck_institutions_district_code" in constraint_names


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


def test_addresses_columns_and_natural_unique(fresh_db: str) -> None:
    url = fresh_db
    up = _alembic(["upgrade", "head"], url)
    assert up.returncode == 0, up.stderr

    eng = _engine(url)
    with eng.connect() as conn:
        cols = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'addresses'"
            )
        ).all()
        constraints = conn.execute(
            text(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid = 'addresses'::regclass"
            )
        ).all()
    eng.dispose()
    columns = {row[0] for row in cols}
    assert {"id", "street_id", "number_int", "number_suffix", "entrance"} <= columns
    constraint_names = {c[0] for c in constraints}
    assert "uq_addresses_natural" in constraint_names


def test_address_institutions_lookup_index_present(fresh_db: str) -> None:
    """Index on `(address_id)` for the s08 match endpoint's join."""
    url = fresh_db
    up = _alembic(["upgrade", "head"], url)
    assert up.returncode == 0, up.stderr

    eng = _engine(url)
    with eng.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE tablename = 'address_institutions' "
                "  AND indexname = 'ix_address_institutions_address_id'"
            )
        ).all()
    eng.dispose()
    assert len(rows) == 1
    indexdef = rows[0][0].lower()
    assert "address_id" in indexdef
