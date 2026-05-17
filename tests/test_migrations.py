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
from sqlalchemy.exc import IntegrityError

from yasli.geo.settlements import VARNA_SETTLEMENTS

REPO_ROOT = Path(__file__).resolve().parents[1]

EXPECTED_SETTLEMENT_ROWS = {
    settlement.code: (settlement.name, settlement.locality_type)
    for settlement in VARNA_SETTLEMENTS
}


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
    assert _current_revision(eng) == "0007"
    tables = _table_names(eng)
    assert {
        "institutions",
        "streets",
        "addresses",
        "address_institutions",
        "grao_addresses",
        "settlements",
    }.issubset(tables)
    assert "address_entries" not in tables
    # The addresses.district_code column is present at head.
    addr_columns = {c["name"] for c in inspect(eng).get_columns("addresses")}
    assert "district_code" in addr_columns
    assert "settlement_code" in addr_columns
    # The institutions.district_code column (from 0004) is also present.
    inst_columns = {c["name"] for c in inspect(eng).get_columns("institutions")}
    assert "district_code" in inst_columns
    with eng.connect() as conn:
        settlement_count = conn.execute(
            text("SELECT count(*) FROM settlements")
        ).scalar_one()
    assert settlement_count == 6
    eng.dispose()

    down = _alembic(["downgrade", "-1"], url)
    assert down.returncode == 0, down.stderr
    eng = _engine(url)
    assert _current_revision(eng) == "0006"
    tables = _table_names(eng)
    # 0006 shape: settlement_code remains on addresses, and only the
    # settlements table from revision 0007 is removed.
    assert {
        "institutions",
        "streets",
        "addresses",
        "address_institutions",
        "grao_addresses",
    }.issubset(tables)
    assert "settlements" not in tables
    addr_columns = {c["name"] for c in inspect(eng).get_columns("addresses")}
    assert "district_code" in addr_columns
    assert "settlement_code" in addr_columns
    inst_columns = {c["name"] for c in inspect(eng).get_columns("institutions")}
    assert "district_code" in inst_columns  # survives the downgrade
    eng.dispose()

    up2 = _alembic(["upgrade", "head"], url)
    assert up2.returncode == 0, up2.stderr
    eng = _engine(url)
    assert _current_revision(eng) == "0007"
    tables = _table_names(eng)
    assert {
        "institutions",
        "streets",
        "addresses",
        "address_institutions",
        "grao_addresses",
        "settlements",
    }.issubset(tables)
    addr_columns = {c["name"] for c in inspect(eng).get_columns("addresses")}
    assert "district_code" in addr_columns
    assert "settlement_code" in addr_columns
    with eng.connect() as conn:
        final_rows = conn.execute(
            text("SELECT code, name, locality_type FROM settlements ORDER BY code")
        ).all()
    assert {
        row.code: (row.name, row.locality_type) for row in final_rows
    } == EXPECTED_SETTLEMENT_ROWS
    eng.dispose()


def test_settlements_table_columns_constraints_and_defaults(fresh_db: str) -> None:
    url = fresh_db
    up = _alembic(["upgrade", "head"], url)
    assert up.returncode == 0, up.stderr

    eng = _engine(url)
    try:
        insp = inspect(eng)
        assert "settlements" in insp.get_table_names()

        columns = {c["name"]: c for c in insp.get_columns("settlements")}
        assert set(columns) == {
            "code",
            "name",
            "locality_type",
            "municipality_code",
            "municipality_name",
            "source",
        }
        assert columns["code"]["nullable"] is False
        assert columns["name"]["nullable"] is False
        assert columns["locality_type"]["nullable"] is False
        assert columns["municipality_code"]["nullable"] is False
        assert columns["municipality_name"]["nullable"] is False
        assert columns["source"]["nullable"] is False
        assert columns["code"]["type"].length == 5
        assert columns["name"]["type"].length == 64
        assert columns["locality_type"]["type"].length == 16
        assert columns["municipality_code"]["type"].length == 2
        assert columns["municipality_name"]["type"].length == 64
        assert columns["source"]["type"].length == 32

        pk = insp.get_pk_constraint("settlements")
        assert pk["constrained_columns"] == ["code"]
        assert pk["name"] == "settlements_pkey"
        check_names = {c["name"] for c in insp.get_check_constraints("settlements")}
        assert "ck_settlements_locality_type" in check_names

        with eng.begin() as conn, pytest.raises(IntegrityError):
            conn.execute(
                text(
                    "INSERT INTO settlements (code, name, locality_type) "
                    "VALUES ('10135', 'DUP', 'city')"
                )
            )

        with eng.begin() as conn, pytest.raises(IntegrityError):
            conn.execute(
                text(
                    "INSERT INTO settlements (code, name, locality_type) "
                    "VALUES ('99990', 'BAD', 'town')"
                )
            )

        with eng.begin() as conn:
            row = conn.execute(
                text(
                    "INSERT INTO settlements (code, name, locality_type) "
                    "VALUES ('99999', 'TEST', 'city') "
                    "RETURNING municipality_code, municipality_name, source"
                )
            ).one()
        assert tuple(row) == ("06", "ВАРНА", "grao_kads")
    finally:
        eng.dispose()


def test_settlement_seed_rows_match_reference_data(fresh_db: str) -> None:
    url = fresh_db
    up = _alembic(["upgrade", "head"], url)
    assert up.returncode == 0, up.stderr

    eng = _engine(url)
    try:
        with eng.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT code, name, locality_type, municipality_code, "
                    "municipality_name, source FROM settlements ORDER BY code"
                )
            ).all()
    finally:
        eng.dispose()

    assert len(rows) == 6
    assert {
        row.code: (row.name, row.locality_type) for row in rows
    } == EXPECTED_SETTLEMENT_ROWS
    assert sum(1 for row in rows if row.locality_type == "city") == 1
    assert sum(1 for row in rows if row.locality_type == "village") == 5
    assert {row.municipality_code for row in rows} == {"06"}
    assert {row.municipality_name for row in rows} == {"ВАРНА"}
    assert {row.source for row in rows} == {"grao_kads"}


def test_address_settlement_code_joins_to_settlements(fresh_db: str) -> None:
    url = fresh_db
    up = _alembic(["upgrade", "head"], url)
    assert up.returncode == 0, up.stderr

    eng = _engine(url)
    try:
        with eng.begin() as conn:
            street_id = conn.execute(
                text(
                    "INSERT INTO streets (city, raw_name, street_part, "
                    "type_marker, search_norm) "
                    "VALUES ('С.КАМЕНАР', 'С.КАМЕНАР УЛ. ТЕСТ', "
                    "'ТЕСТ', 'УЛ.', 's.kamenar test') RETURNING id"
                )
            ).scalar_one()
            address_id = conn.execute(
                text(
                    "INSERT INTO addresses "
                    "(street_id, number_int, settlement_code) "
                    "VALUES (:street_id, 1, '35701') RETURNING id"
                ),
                {"street_id": street_id},
            ).scalar_one()

        with eng.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT s.code, s.name, s.locality_type "
                    "FROM addresses a "
                    "JOIN settlements s ON s.code = a.settlement_code "
                    "WHERE a.id = :address_id"
                ),
                {"address_id": address_id},
            ).one()
        assert tuple(row) == ("35701", "С.КАМЕНАР", "village")
    finally:
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


def test_grao_addresses_columns_and_constraints(fresh_db: str) -> None:
    """grao_addresses (revision 0005): columns, PK, CHECK, and helper index."""
    url = fresh_db
    up = _alembic(["upgrade", "head"], url)
    assert up.returncode == 0, up.stderr

    eng = _engine(url)
    with eng.connect() as conn:
        cols = conn.execute(
            text(
                "SELECT column_name, is_nullable FROM information_schema.columns "
                "WHERE table_name = 'grao_addresses'"
            )
        ).all()
        constraints = conn.execute(
            text(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid = 'grao_addresses'::regclass"
            )
        ).all()
        indexes = conn.execute(
            text(
                "SELECT indexname FROM pg_indexes WHERE tablename = 'grao_addresses'"
            )
        ).all()
    eng.dispose()

    by_name = {row[0]: row for row in cols}
    expected = {
        "id",
        "street_code",
        "street_raw",
        "search_norm",
        "number_int",
        "number_suffix",
        "entrance",
        "district_code",
        "district_name",
        "settlement_code",
        "section_no",
    }
    assert expected.issubset(by_name.keys())
    for col in expected:
        assert by_name[col][1] == "NO", f"{col} should be NOT NULL"

    constraint_names = {c[0] for c in constraints}
    assert "grao_addresses_pkey" in constraint_names
    assert "ck_grao_addresses_district_code" in constraint_names

    index_names = {r[0] for r in indexes}
    assert "ix_grao_addresses_search_norm_number_int" in index_names


def test_addresses_district_code_column_and_check(fresh_db: str) -> None:
    """addresses.district_code (revision 0005): nullable CHAR(2) with CHECK."""
    url = fresh_db
    up = _alembic(["upgrade", "head"], url)
    assert up.returncode == 0, up.stderr

    eng = _engine(url)
    with eng.connect() as conn:
        cols = conn.execute(
            text(
                "SELECT column_name, is_nullable FROM information_schema.columns "
                "WHERE table_name = 'addresses' AND column_name = 'district_code'"
            )
        ).all()
        constraints = conn.execute(
            text(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid = 'addresses'::regclass"
            )
        ).all()
    eng.dispose()

    assert len(cols) == 1
    assert cols[0][1] == "YES"  # nullable
    constraint_names = {c[0] for c in constraints}
    assert "ck_addresses_district_code" in constraint_names


def test_grao_addresses_district_code_check_rejects_invalid(fresh_db: str) -> None:
    """grao_addresses CHECK rejects district codes outside the 5-value set."""
    url = fresh_db
    up = _alembic(["upgrade", "head"], url)
    assert up.returncode == 0, up.stderr

    from sqlalchemy.exc import IntegrityError

    eng = _engine(url)
    try:
        with eng.begin() as conn, pytest.raises(IntegrityError):
            conn.execute(
                text(
                    "INSERT INTO grao_addresses "
                    "(street_code, street_raw, search_norm, number_int, number_suffix, "
                    " entrance, district_code, district_name, settlement_code, section_no) "
                    "VALUES ('00001','УЛ.X','ul.x',1,'','','99','BAD','10135',1)"
                )
            )
    finally:
        eng.dispose()


def test_grao_addresses_accepts_duplicate_source_tuples(fresh_db: str) -> None:
    """Real KADS can repeat apparent street/number tuples across districts."""
    url = fresh_db
    up = _alembic(["upgrade", "head"], url)
    assert up.returncode == 0, up.stderr

    eng = _engine(url)
    try:
        with eng.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO grao_addresses "
                    "(street_code, street_raw, search_norm, number_int, number_suffix, "
                    " entrance, district_code, district_name, settlement_code, section_no) "
                    "VALUES "
                    "('00446','УЛ.АКАЦИЯ','gr.varna ul.akatsiya',2,'','','02','ПРИМОРСКИ','10135',96),"
                    "('02751','УЛ.АКАЦИЯ','gr.varna ul.akatsiya',2,'','','05','АСПАРУХОВО','10135',400)"
                )
            )
            count = conn.execute(
                text("SELECT COUNT(*) FROM grao_addresses")
            ).scalar_one()
        assert count == 2
    finally:
        eng.dispose()


def test_addresses_district_code_check_rejects_invalid(fresh_db: str) -> None:
    """addresses.district_code CHECK rejects values outside the 5-value set."""
    url = fresh_db
    up = _alembic(["upgrade", "head"], url)
    assert up.returncode == 0, up.stderr

    from sqlalchemy.exc import IntegrityError

    eng = _engine(url)
    try:
        with eng.begin() as conn:
            street_id = conn.execute(
                text(
                    "INSERT INTO streets (city, raw_name, street_part, type_marker, "
                    "search_norm) VALUES ('ГР.ВАРНА','UNIQ-DC','x',NULL,'x') "
                    "RETURNING id"
                )
            ).scalar_one()
        with eng.begin() as conn, pytest.raises(IntegrityError):
            conn.execute(
                text(
                    "INSERT INTO addresses (street_id, number_int, district_code) "
                    "VALUES (:s, 1, '99')"
                ),
                {"s": street_id},
            )
    finally:
        eng.dispose()


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
