"""Database constraint tests against a real Postgres at head.

Verifies that the schema enforces what the spec promises: the `kind` CHECK,
the `(external_id, kind)` UNIQUE, and the cascading deletes from
streets/institutions through addresses/address_institutions. Skips when no
Postgres is reachable.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

REPO_ROOT = Path(__file__).resolve().parents[1]


def _candidate_url() -> str | None:
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
        "Postgres URL to run constraint tests."
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
def head_db() -> str:
    assert _url is not None
    down = _alembic(["downgrade", "base"], _url)
    assert down.returncode == 0, down.stderr
    up = _alembic(["upgrade", "head"], _url)
    assert up.returncode == 0, up.stderr
    return _url


def _insert_institution(
    conn,
    *,
    external_id: str,
    kind: str,
    name: str = "X",
    address: str | None = None,
    district_code: str | None = None,
) -> int:
    row = conn.execute(
        text(
            "INSERT INTO institutions "
            "(external_id, name, kind, source_url, address, district_code, last_seen_at) "
            "VALUES (:external_id, :name, :kind, :source_url, :address, :district_code, :last_seen_at) "
            "RETURNING id"
        ),
        {
            "external_id": external_id,
            "name": name,
            "kind": kind,
            "source_url": "https://example.test/x",
            "address": address,
            "district_code": district_code,
            "last_seen_at": datetime.now(tz=timezone.utc),
        },
    ).scalar_one()
    return int(row)


def _insert_street(conn, *, raw_name: str) -> int:
    row = conn.execute(
        text(
            "INSERT INTO streets (city, raw_name, street_part, type_marker, search_norm) "
            "VALUES (:city, :raw_name, :street_part, :type_marker, :search_norm) "
            "RETURNING id"
        ),
        {
            "city": "ГР.ВАРНА",
            "raw_name": raw_name,
            "street_part": raw_name,
            "type_marker": None,
            "search_norm": raw_name.lower(),
        },
    ).scalar_one()
    return int(row)


def _insert_address(
    conn,
    *,
    street_id: int,
    number_int: int,
    number_suffix: str | None = None,
    entrance: str | None = None,
) -> int:
    row = conn.execute(
        text(
            "INSERT INTO addresses (street_id, number_int, number_suffix, entrance) "
            "VALUES (:s, :n, :sfx, :ent) RETURNING id"
        ),
        {"s": street_id, "n": number_int, "sfx": number_suffix, "ent": entrance},
    ).scalar_one()
    return int(row)


def _insert_edge(conn, *, address_id: int, institution_id: int) -> None:
    conn.execute(
        text(
            "INSERT INTO address_institutions (address_id, institution_id) "
            "VALUES (:a, :i)"
        ),
        {"a": address_id, "i": institution_id},
    )


def test_kind_check_rejects_old_source_value(head_db: str) -> None:
    engine = create_engine(head_db, future=True)
    try:
        with engine.begin() as conn, pytest.raises(IntegrityError):
            _insert_institution(conn, external_id="100", kind="infant")
    finally:
        engine.dispose()


def test_kind_check_accepts_contract_values(head_db: str) -> None:
    engine = create_engine(head_db, future=True)
    try:
        with engine.begin() as conn:
            for k in ("nursery", "kindergarten", "preschool"):
                _insert_institution(conn, external_id=f"v-{k}", kind=k)
    finally:
        engine.dispose()


def test_district_code_check_rejects_invalid_value(head_db: str) -> None:
    engine = create_engine(head_db, future=True)
    try:
        with engine.begin() as conn, pytest.raises(IntegrityError):
            _insert_institution(
                conn,
                external_id="bad-district",
                kind="nursery",
                district_code="06",
            )
    finally:
        engine.dispose()


def test_district_code_check_accepts_valid_and_null_values(head_db: str) -> None:
    engine = create_engine(head_db, future=True)
    try:
        with engine.begin() as conn:
            _insert_institution(
                conn,
                external_id="valid-district",
                kind="nursery",
                district_code="01",
            )
            _insert_institution(
                conn,
                external_id="null-district",
                kind="kindergarten",
                district_code=None,
            )
    finally:
        engine.dispose()


def test_has_infant_group_defaults_false(head_db: str) -> None:
    engine = create_engine(head_db, future=True)
    try:
        with engine.begin() as conn:
            inst_id = _insert_institution(
                conn,
                external_id="infant-default",
                kind="kindergarten",
            )
            value = conn.execute(
                text("SELECT has_infant_group FROM institutions WHERE id = :id"),
                {"id": inst_id},
            ).scalar_one()
            assert value is False
    finally:
        engine.dispose()


def test_external_id_kind_unique(head_db: str) -> None:
    engine = create_engine(head_db, future=True)
    try:
        with engine.begin() as conn:
            _insert_institution(conn, external_id="42", kind="nursery")

        with engine.begin() as conn, pytest.raises(IntegrityError):
            _insert_institution(conn, external_id="42", kind="nursery")
    finally:
        engine.dispose()


def test_same_external_id_different_kind_allowed(head_db: str) -> None:
    engine = create_engine(head_db, future=True)
    try:
        with engine.begin() as conn:
            a = _insert_institution(conn, external_id="77", kind="nursery")
            b = _insert_institution(conn, external_id="77", kind="kindergarten")
        assert a != b
    finally:
        engine.dispose()


def test_addresses_natural_unique_rejects_duplicate(head_db: str) -> None:
    engine = create_engine(head_db, future=True)
    try:
        with engine.begin() as conn:
            street_id = _insert_street(conn, raw_name="ГР.ВАРНА УЛ. ГЕНЕРАЛ КОЛЕВ")
            _insert_address(
                conn,
                street_id=street_id,
                number_int=5,
                number_suffix="А",
                entrance="01",
            )

        with engine.begin() as conn, pytest.raises(IntegrityError):
            _insert_address(
                conn,
                street_id=street_id,
                number_int=5,
                number_suffix="А",
                entrance="01",
            )
    finally:
        engine.dispose()


def test_addresses_cascade_on_street_delete(head_db: str) -> None:
    engine = create_engine(head_db, future=True)
    try:
        with engine.begin() as conn:
            street_id = _insert_street(conn, raw_name="ГР.ВАРНА УЛ. КАСКАД")
            _insert_address(conn, street_id=street_id, number_int=1)
            _insert_address(conn, street_id=street_id, number_int=2)

        with engine.begin() as conn:
            count_before = conn.execute(
                text("SELECT count(*) FROM addresses WHERE street_id = :s"),
                {"s": street_id},
            ).scalar_one()
            assert count_before == 2

            conn.execute(text("DELETE FROM streets WHERE id = :s"), {"s": street_id})

            count_after = conn.execute(
                text("SELECT count(*) FROM addresses WHERE street_id = :s"),
                {"s": street_id},
            ).scalar_one()
            assert count_after == 0
    finally:
        engine.dispose()


def test_address_institutions_cascade_on_address_delete(head_db: str) -> None:
    engine = create_engine(head_db, future=True)
    try:
        with engine.begin() as conn:
            inst_id = _insert_institution(conn, external_id="900", kind="nursery")
            street_id = _insert_street(conn, raw_name="ГР.ВАРНА УЛ. ГЕНЕРАЛ КОЛЕВ")
            address_id = _insert_address(
                conn, street_id=street_id, number_int=5
            )
            _insert_edge(conn, address_id=address_id, institution_id=inst_id)

        with engine.begin() as conn:
            count_before = conn.execute(
                text(
                    "SELECT count(*) FROM address_institutions "
                    "WHERE address_id = :a"
                ),
                {"a": address_id},
            ).scalar_one()
            assert count_before == 1

            conn.execute(text("DELETE FROM addresses WHERE id = :a"), {"a": address_id})

            count_after = conn.execute(
                text(
                    "SELECT count(*) FROM address_institutions "
                    "WHERE address_id = :a"
                ),
                {"a": address_id},
            ).scalar_one()
            assert count_after == 0
    finally:
        engine.dispose()


def test_address_institutions_cascade_on_institution_delete(head_db: str) -> None:
    engine = create_engine(head_db, future=True)
    try:
        with engine.begin() as conn:
            inst_id = _insert_institution(conn, external_id="901", kind="nursery")
            street_id = _insert_street(conn, raw_name="ГР.ВАРНА УЛ. ИНСТ-ДЕЛ")
            address_id = _insert_address(conn, street_id=street_id, number_int=7)
            _insert_edge(conn, address_id=address_id, institution_id=inst_id)

        with engine.begin() as conn:
            count_before = conn.execute(
                text(
                    "SELECT count(*) FROM address_institutions "
                    "WHERE institution_id = :i"
                ),
                {"i": inst_id},
            ).scalar_one()
            assert count_before == 1

            conn.execute(
                text("DELETE FROM institutions WHERE id = :i"), {"i": inst_id}
            )

            count_after = conn.execute(
                text(
                    "SELECT count(*) FROM address_institutions "
                    "WHERE institution_id = :i"
                ),
                {"i": inst_id},
            ).scalar_one()
            assert count_after == 0
            # The Address row itself is NOT cascaded — only the junction.
            still_there = conn.execute(
                text("SELECT count(*) FROM addresses WHERE id = :a"),
                {"a": address_id},
            ).scalar_one()
            assert still_there == 1
    finally:
        engine.dispose()


def test_address_institutions_pkey_rejects_duplicate(head_db: str) -> None:
    engine = create_engine(head_db, future=True)
    try:
        with engine.begin() as conn:
            inst_id = _insert_institution(conn, external_id="902", kind="nursery")
            street_id = _insert_street(conn, raw_name="ГР.ВАРНА УЛ. ДУПЛ")
            address_id = _insert_address(conn, street_id=street_id, number_int=1)
            _insert_edge(conn, address_id=address_id, institution_id=inst_id)

        with engine.begin() as conn, pytest.raises(IntegrityError):
            _insert_edge(conn, address_id=address_id, institution_id=inst_id)
    finally:
        engine.dispose()
