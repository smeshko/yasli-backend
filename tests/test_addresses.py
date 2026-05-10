"""/api/addresses: shape, ordering, ETag, If-None-Match, Cache-Control,
empty DB, 405, and DB error → 503.

Mirrors test_streets.py. SQLite in-memory + StaticPool: the SELECT is
plain SQL with NULLS LAST, supported on SQLite ≥ 3.30 (universal on
modern systems).
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import StaticPool

from yasli import db
from yasli.main import app
from yasli.models import Address, Base, Street
from yasli.routes import addresses as addresses_module


@pytest.fixture
def client() -> TestClient:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db.set_engine(engine)
    return TestClient(app)


def _seed_street(_client: TestClient, **fields: object) -> int:
    """Insert one street row and return its id. SQLite doesn't autoincrement
    BigInteger PKs, so we assign explicitly."""
    assert db._SessionLocal is not None
    with db._SessionLocal() as session:
        from sqlalchemy import func, select as _select

        next_id = (session.execute(_select(func.coalesce(func.max(Street.id), 0))).scalar() or 0) + 1
        payload = {
            "id": next_id,
            "city": "ГР.ВАРНА",
            "raw_name": "ул. Test",
            "street_part": "Test",
            "type_marker": "ул.",
            "search_norm": "test",
        }
        payload.update(fields)
        session.add(Street(**payload))
        session.commit()
        return int(payload["id"])


def _seed_addresses(_client: TestClient, rows: list[dict[str, object]]) -> list[int]:
    """Insert address rows and return their ids in order."""
    assert db._SessionLocal is not None
    inserted: list[int] = []
    with db._SessionLocal() as session:
        from sqlalchemy import func, select as _select

        next_id = (session.execute(_select(func.coalesce(func.max(Address.id), 0))).scalar() or 0) + 1
        for offset, row in enumerate(rows):
            payload = dict(row)
            payload.setdefault("id", next_id + offset)
            payload.setdefault("number_suffix", None)
            payload.setdefault("entrance", None)
            session.add(Address(**payload))
            inserted.append(int(payload["id"]))
        session.commit()
    return inserted


def test_returns_addresses_with_expected_shape(client: TestClient) -> None:
    sid = _seed_street(client)
    _seed_addresses(
        client,
        [
            {"street_id": sid, "number_int": 1, "number_suffix": None, "entrance": None},
            {"street_id": sid, "number_int": 2, "number_suffix": "А", "entrance": None},
            {"street_id": sid, "number_int": 3, "number_suffix": None, "entrance": "01"},
        ],
    )

    resp = client.get("/api/addresses")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) == 3
    for item in body:
        assert set(item.keys()) == {
            "id",
            "street_id",
            "number_int",
            "number_suffix",
            "entrance",
        }


def test_includes_addresses_with_null_suffix_and_entrance(client: TestClient) -> None:
    sid = _seed_street(client)
    _seed_addresses(
        client,
        [
            {"street_id": sid, "number_int": 1, "number_suffix": "А", "entrance": "01"},
            {"street_id": sid, "number_int": 2, "number_suffix": None, "entrance": None},
        ],
    )

    body = client.get("/api/addresses").json()
    assert len(body) == 2
    by_num = {row["number_int"]: row for row in body}
    assert by_num[1]["number_suffix"] == "А"
    assert by_num[1]["entrance"] == "01"
    assert by_num[2]["number_suffix"] is None
    assert by_num[2]["entrance"] is None


def test_ordering_is_street_then_number_then_suffix_then_entrance(
    client: TestClient,
) -> None:
    s1 = _seed_street(client, raw_name="ул. A")
    s2 = _seed_street(client, raw_name="ул. B")
    _seed_addresses(
        client,
        [
            {"street_id": s2, "number_int": 1, "number_suffix": None, "entrance": None},
            {"street_id": s1, "number_int": 5, "number_suffix": None, "entrance": None},
            {"street_id": s1, "number_int": 1, "number_suffix": "Б", "entrance": None},
            {"street_id": s1, "number_int": 1, "number_suffix": "А", "entrance": "02"},
            {"street_id": s1, "number_int": 1, "number_suffix": "А", "entrance": "01"},
            {"street_id": s1, "number_int": 1, "number_suffix": None, "entrance": None},
            {"street_id": s1, "number_int": 1, "number_suffix": "А", "entrance": None},
        ],
    )

    body = client.get("/api/addresses").json()
    keys = [
        (
            row["street_id"],
            row["number_int"],
            row["number_suffix"] is None,  # NULLs last → True sorts after False
            row["number_suffix"] or "",
            row["entrance"] is None,
            row["entrance"] or "",
        )
        for row in body
    ]
    assert keys == sorted(keys)


def test_etag_stable_across_requests(client: TestClient) -> None:
    sid = _seed_street(client)
    _seed_addresses(
        client,
        [{"street_id": sid, "number_int": 1, "number_suffix": None, "entrance": None}],
    )

    a = client.get("/api/addresses")
    b = client.get("/api/addresses")
    assert a.headers["etag"] == b.headers["etag"]


def test_etag_changes_when_data_changes(client: TestClient) -> None:
    sid = _seed_street(client)
    _seed_addresses(
        client,
        [{"street_id": sid, "number_int": 1, "number_suffix": None, "entrance": None}],
    )
    first = client.get("/api/addresses").headers["etag"]

    _seed_addresses(
        client,
        [{"street_id": sid, "number_int": 2, "number_suffix": None, "entrance": None}],
    )
    second = client.get("/api/addresses").headers["etag"]
    assert first != second


def test_if_none_match_returns_304(client: TestClient) -> None:
    sid = _seed_street(client)
    _seed_addresses(
        client,
        [{"street_id": sid, "number_int": 1, "number_suffix": None, "entrance": None}],
    )
    etag = client.get("/api/addresses").headers["etag"]
    resp = client.get("/api/addresses", headers={"If-None-Match": etag})
    assert resp.status_code == 304
    assert resp.content == b""
    assert resp.headers["etag"] == etag


def test_if_none_match_miss_returns_full_body(client: TestClient) -> None:
    sid = _seed_street(client)
    _seed_addresses(
        client,
        [{"street_id": sid, "number_int": 1, "number_suffix": None, "entrance": None}],
    )
    resp = client.get(
        "/api/addresses", headers={"If-None-Match": '"v1-deadbeefdeadbeef"'}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) == 1


def test_cache_control_header_present(client: TestClient) -> None:
    resp = client.get("/api/addresses")
    assert resp.headers["cache-control"] == "public, max-age=3600, stale-while-revalidate=86400"
    assert resp.headers["vary"] == "Accept-Encoding"


def test_empty_database_returns_200_empty_array_with_etag(client: TestClient) -> None:
    resp = client.get("/api/addresses")
    assert resp.status_code == 200
    assert resp.json() == []
    assert resp.headers["etag"].startswith('"v1-')


def test_method_not_allowed(client: TestClient) -> None:
    resp = client.post("/api/addresses")
    assert resp.status_code == 405


def test_database_error_returns_503(caplog: pytest.LogCaptureFixture) -> None:
    """Override the dependency to raise SQLAlchemyError; the global handler
    in `main.py` should catch it and return the documented 503 body.
    """

    class _BrokenSession:
        def execute(self, *args, **kwargs):
            del args, kwargs
            raise OperationalError("SELECT", {}, Exception("boom"))

        def close(self) -> None:
            pass

    def _broken_get_db():
        s = _BrokenSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[addresses_module.get_db] = _broken_get_db
    try:
        client = TestClient(app, raise_server_exceptions=False)
        with caplog.at_level("ERROR"):
            resp = client.get("/api/addresses")
        assert resp.status_code == 503
        assert resp.json() == {"status": "degraded", "error": "database unreachable"}
        assert any("database error" in rec.message for rec in caplog.records)
    finally:
        app.dependency_overrides.pop(addresses_module.get_db, None)


def test_etag_value_format(client: TestClient) -> None:
    sid = _seed_street(client)
    _seed_addresses(
        client,
        [{"street_id": sid, "number_int": 1, "number_suffix": None, "entrance": None}],
    )
    resp = client.get("/api/addresses")
    etag = resp.headers["etag"]
    assert etag.startswith('"v1-') and etag.endswith('"')
    assert len(etag) == len('"v1-') + 16 + 1
    parsed = json.loads(resp.content)
    assert isinstance(parsed, list)
