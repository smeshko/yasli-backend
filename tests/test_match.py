"""/api/match: address lookup, kind filtering, ordering, validation, and DB
error -> 503.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, insert
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import StaticPool

from yasli import db
from yasli.main import app
from yasli.models import Address, Base, Institution, Street, address_institutions
from yasli.routes import match as match_module


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


def _seed_fixture(_client: TestClient) -> None:
    assert db._SessionLocal is not None
    now = datetime(2026, 5, 10, tzinfo=UTC)
    with db._SessionLocal() as session:
        session.add(
            Street(
                id=1,
                city="ГР.ВАРНА",
                raw_name="ул. Test",
                street_part="Test",
                type_marker="ул.",
                search_norm="test",
            )
        )
        session.add_all(
            [
                Address(id=1, street_id=1, number_int=1),
                Address(id=2, street_id=1, number_int=2),
                Address(id=3, street_id=1, number_int=3),
            ]
        )
        session.add_all(
            [
                Institution(
                    id=1,
                    external_id="N1",
                    name="Nursery B",
                    kind="nursery",
                    source_url="https://example.test/n1",
                    last_seen_at=now,
                ),
                Institution(
                    id=2,
                    external_id="K1",
                    name="Kindergarten B",
                    kind="kindergarten",
                    source_url="https://example.test/k1",
                    last_seen_at=now,
                ),
                Institution(
                    id=3,
                    external_id="P1",
                    name="Preschool B",
                    kind="preschool",
                    source_url="https://example.test/p1",
                    last_seen_at=now,
                ),
            ]
        )
        session.execute(
            insert(address_institutions),
            [
                {"address_id": 1, "institution_id": 1},
                {"address_id": 1, "institution_id": 2},
                {"address_id": 1, "institution_id": 3},
                {"address_id": 2, "institution_id": 2},
            ],
        )
        session.commit()


def test_returns_institutions_with_expected_shape(client: TestClient) -> None:
    _seed_fixture(client)

    resp = client.get("/api/match?address_id=1")

    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) == 3
    for item in body:
        assert set(item.keys()) == {"id", "external_id", "name", "kind", "source_url"}
    assert "cache-control" not in resp.headers
    assert "etag" not in resp.headers


def test_kind_filter_returns_only_that_kind(client: TestClient) -> None:
    _seed_fixture(client)

    resp = client.get("/api/match?address_id=1&kind=nursery")

    assert resp.status_code == 200
    body = resp.json()
    assert body
    assert {item["kind"] for item in body} == {"nursery"}


def test_no_kind_returns_all_kinds(client: TestClient) -> None:
    _seed_fixture(client)

    resp = client.get("/api/match?address_id=1")

    assert resp.status_code == 200
    assert {item["kind"] for item in resp.json()} == {
        "nursery",
        "kindergarten",
        "preschool",
    }


def test_kind_filter_empty_returns_200_empty_array(client: TestClient) -> None:
    _seed_fixture(client)

    resp = client.get("/api/match?address_id=2&kind=nursery")

    assert resp.status_code == 200
    assert resp.json() == []


def test_address_with_no_coverage_returns_200_empty(client: TestClient) -> None:
    _seed_fixture(client)

    resp = client.get("/api/match?address_id=3")

    assert resp.status_code == 200
    assert resp.json() == []


def test_unknown_address_id_returns_404(client: TestClient) -> None:
    _seed_fixture(client)

    resp = client.get("/api/match?address_id=999999")

    assert resp.status_code == 404
    assert resp.json() == {"error": "address_not_found"}


def test_missing_address_id_returns_422(client: TestClient) -> None:
    resp = client.get("/api/match")
    assert resp.status_code == 422


def test_non_integer_address_id_returns_422(client: TestClient) -> None:
    resp = client.get("/api/match?address_id=abc")
    assert resp.status_code == 422


def test_invalid_kind_returns_422(client: TestClient) -> None:
    _seed_fixture(client)

    resp = client.get("/api/match?address_id=1&kind=infant")

    assert resp.status_code == 422


def test_method_not_allowed(client: TestClient) -> None:
    resp = client.post("/api/match")
    assert resp.status_code == 405


def test_ordering_is_stable(client: TestClient) -> None:
    _seed_fixture(client)

    first = client.get("/api/match?address_id=1")
    second = client.get("/api/match?address_id=1")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.content == second.content


def test_ordering_is_kind_then_name(client: TestClient) -> None:
    _seed_fixture(client)
    assert db._SessionLocal is not None
    now = datetime(2026, 5, 10, tzinfo=UTC)
    with db._SessionLocal() as session:
        session.add_all(
            [
                Institution(
                    id=4,
                    external_id="K2",
                    name="Kindergarten Z",
                    kind="kindergarten",
                    source_url="https://example.test/k2",
                    last_seen_at=now,
                ),
                Institution(
                    id=5,
                    external_id="K3",
                    name="Kindergarten A",
                    kind="kindergarten",
                    source_url="https://example.test/k3",
                    last_seen_at=now,
                ),
            ]
        )
        session.execute(
            insert(address_institutions),
            [
                {"address_id": 1, "institution_id": 4},
                {"address_id": 1, "institution_id": 5},
            ],
        )
        session.commit()

    body = client.get("/api/match?address_id=1").json()
    keys = [(item["kind"], item["name"]) for item in body]
    assert keys == sorted(keys)


def test_database_error_returns_503(caplog: pytest.LogCaptureFixture) -> None:
    class _BrokenSession:
        def execute(self, *args, **kwargs):
            del args, kwargs
            raise OperationalError("SELECT", {}, Exception("boom"))

        def close(self) -> None:
            pass

    def _broken_get_db():
        session = _BrokenSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[match_module.get_db] = _broken_get_db
    try:
        client = TestClient(app, raise_server_exceptions=False)
        with caplog.at_level("ERROR"):
            resp = client.get("/api/match?address_id=1")
        assert resp.status_code == 503
        assert resp.json() == {"status": "degraded", "error": "database unreachable"}
        assert any("database error" in rec.message for rec in caplog.records)
    finally:
        app.dependency_overrides.pop(match_module.get_db, None)
