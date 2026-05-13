"""/api/match: street vs district routing, district-unknown envelope,
existing-field regression, and validation.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, insert
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import StaticPool

from yasli import db
from yasli.main import app
from yasli.models import Address, Base, Institution, Street, address_institutions
from yasli.routes import match as match_module


UTC = timezone.utc


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
    """Seed a small dataset that exercises both routing paths.

    Districts: addresses 1 + 2 are in '01' (Одесос); address 3 is in '02'
    (Приморски); address 4 has district_code IS NULL.

    Institutions:
      N1 — nursery, district='01' (only via district routing)
      N2 — nursery, district='02'
      N3 — nursery, district=NULL  (should never match)
      K1 — kindergarten, junction to {1, 2}
      K2 — kindergarten, junction to {3}
      P1 — preschool, district='01' (catchment-majority Одесос)
      P2 — preschool, district='02' (catchment-majority Приморски).
           Has a junction edge to address 1 (its building sits there) —
           used by the "junction is ignored for preschools" assertion.
      P3 — preschool, district=NULL (should never match)
    """
    assert db._SessionLocal is not None
    now = datetime(2026, 5, 13, tzinfo=UTC)
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
                Address(id=1, street_id=1, number_int=1, district_code="01"),
                Address(id=2, street_id=1, number_int=2, district_code="01"),
                Address(id=3, street_id=1, number_int=3, district_code="02"),
                Address(id=4, street_id=1, number_int=4, district_code=None),
            ]
        )
        session.add_all(
            [
                Institution(
                    id=1,
                    external_id="N1",
                    name="Nursery Odessa",
                    kind="nursery",
                    source_url="https://example.test/n1",
                    district_code="01",
                    last_seen_at=now,
                ),
                Institution(
                    id=2,
                    external_id="N2",
                    name="Nursery Primorski",
                    kind="nursery",
                    source_url="https://example.test/n2",
                    district_code="02",
                    last_seen_at=now,
                ),
                Institution(
                    id=3,
                    external_id="N3",
                    name="Nursery Unstamped",
                    kind="nursery",
                    source_url="https://example.test/n3",
                    district_code=None,
                    last_seen_at=now,
                ),
                Institution(
                    id=4,
                    external_id="K1",
                    name="Kindergarten Odessa",
                    kind="kindergarten",
                    source_url="https://example.test/k1",
                    district_code="01",
                    last_seen_at=now,
                ),
                Institution(
                    id=5,
                    external_id="K2",
                    name="Kindergarten Primorski",
                    kind="kindergarten",
                    source_url="https://example.test/k2",
                    district_code="02",
                    last_seen_at=now,
                ),
                Institution(
                    id=6,
                    external_id="P1",
                    name="Preschool Odessa",
                    kind="preschool",
                    source_url="https://example.test/p1",
                    district_code="01",
                    last_seen_at=now,
                ),
                Institution(
                    id=7,
                    external_id="P2",
                    name="Preschool Primorski",
                    kind="preschool",
                    source_url="https://example.test/p2",
                    district_code="02",
                    last_seen_at=now,
                ),
                Institution(
                    id=8,
                    external_id="P3",
                    name="Preschool Unstamped",
                    kind="preschool",
                    source_url="https://example.test/p3",
                    district_code=None,
                    last_seen_at=now,
                ),
            ]
        )
        session.execute(
            insert(address_institutions),
            [
                # K1 covers addr 1, 2; K2 covers addr 3.
                {"address_id": 1, "institution_id": 4},
                {"address_id": 2, "institution_id": 4},
                {"address_id": 3, "institution_id": 5},
                # P2's building is at address 1 (район 01) but its
                # catchment-majority is район 02 — the new routing must
                # use institutions.district_code, not this junction edge.
                {"address_id": 1, "institution_id": 7},
            ],
        )
        session.commit()


def test_district_known_returns_bare_array(client: TestClient) -> None:
    _seed_fixture(client)
    resp = client.get("/api/match?address_id=1")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    # Expect N1 (district='01'), K1 (junction), P1 (district='01').
    by_external = {r["external_id"]: r for r in body}
    assert set(by_external) == {"N1", "K1", "P1"}


def test_kindergarten_match_type_is_street(client: TestClient) -> None:
    _seed_fixture(client)
    body = client.get("/api/match?address_id=1").json()
    k1 = next(r for r in body if r["external_id"] == "K1")
    assert k1["match_type"] == "street"


def test_nursery_match_type_is_district(client: TestClient) -> None:
    _seed_fixture(client)
    body = client.get("/api/match?address_id=1").json()
    n1 = next(r for r in body if r["external_id"] == "N1")
    assert n1["match_type"] == "district"


def test_preschool_match_type_is_district(client: TestClient) -> None:
    _seed_fixture(client)
    body = client.get("/api/match?address_id=1").json()
    p1 = next(r for r in body if r["external_id"] == "P1")
    assert p1["match_type"] == "district"


def test_kindergarten_filter_only_returns_junction_matches(
    client: TestClient,
) -> None:
    _seed_fixture(client)
    body = client.get("/api/match?address_id=1&kind=kindergarten").json()
    assert {r["external_id"] for r in body} == {"K1"}


def test_nursery_filter_routes_by_district(client: TestClient) -> None:
    _seed_fixture(client)
    body = client.get("/api/match?address_id=1&kind=nursery").json()
    assert {r["external_id"] for r in body} == {"N1"}
    assert all(r["match_type"] == "district" for r in body)


def test_preschool_filter_routes_by_district(client: TestClient) -> None:
    _seed_fixture(client)
    body = client.get("/api/match?address_id=1&kind=preschool").json()
    assert {r["external_id"] for r in body} == {"P1"}
    assert all(r["match_type"] == "district" for r in body)


def test_preschool_catchment_majority_overrides_building_junction(
    client: TestClient,
) -> None:
    """Task 6.11: P2's building is in район 01 (junction edge to addr 1)
    but its catchment-majority is район 02. A query for addr 3 (район 02)
    returns P2; a query for addr 1 (район 01) does NOT return P2.
    """
    _seed_fixture(client)
    body_district_02 = client.get("/api/match?address_id=3&kind=preschool").json()
    body_district_01 = client.get("/api/match?address_id=1&kind=preschool").json()
    assert "P2" in {r["external_id"] for r in body_district_02}
    assert "P2" not in {r["external_id"] for r in body_district_01}


def test_nursery_with_null_district_never_returned(client: TestClient) -> None:
    _seed_fixture(client)
    # N3 has district_code IS NULL — never matches any district query.
    for addr in (1, 2, 3):
        body = client.get(f"/api/match?address_id={addr}&kind=nursery").json()
        assert "N3" not in {r["external_id"] for r in body}


def test_preschool_with_null_district_never_returned(client: TestClient) -> None:
    _seed_fixture(client)
    for addr in (1, 2, 3):
        body = client.get(f"/api/match?address_id={addr}&kind=preschool").json()
        assert "P3" not in {r["external_id"] for r in body}


def test_unknown_district_no_filter_returns_envelope(client: TestClient) -> None:
    _seed_fixture(client)
    resp = client.get("/api/match?address_id=4")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, dict)
    assert body["match_type"] == "district_unknown"
    # Address 4 has no junction edges → no kindergartens either.
    assert body["results"] == []


def test_unknown_district_kind_nursery_returns_empty_envelope(
    client: TestClient,
) -> None:
    _seed_fixture(client)
    body = client.get("/api/match?address_id=4&kind=nursery").json()
    assert body == {"match_type": "district_unknown", "results": []}


def test_unknown_district_kind_preschool_returns_empty_envelope(
    client: TestClient,
) -> None:
    _seed_fixture(client)
    body = client.get("/api/match?address_id=4&kind=preschool").json()
    assert body == {"match_type": "district_unknown", "results": []}


def test_unknown_district_kind_kindergarten_returns_bare_array(
    client: TestClient,
) -> None:
    """The envelope only fires when nurseries/preschools could have
    appeared. With kind=kindergarten explicit, the original bare-array
    shape is preserved (district stamp is moot for KG routing).
    """
    _seed_fixture(client)
    resp = client.get("/api/match?address_id=4&kind=kindergarten")
    body = resp.json()
    assert isinstance(body, list)  # bare array, NOT envelope


def test_existing_five_fields_present_byte_identical(client: TestClient) -> None:
    """Task 6.10: regression — every row still carries the original five
    fields with their existing types (additive change for match_type).
    """
    _seed_fixture(client)
    body = client.get("/api/match?address_id=1").json()
    assert isinstance(body, list)
    assert body  # non-empty
    expected_keys = {"id", "external_id", "name", "kind", "source_url", "match_type"}
    for item in body:
        assert set(item.keys()) == expected_keys
        assert isinstance(item["id"], int)
        assert isinstance(item["external_id"], str)
        assert isinstance(item["name"], str)
        assert item["kind"] in {"nursery", "kindergarten", "preschool"}
        assert isinstance(item["source_url"], str)


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


def test_ordering_is_stable_for_district_known(client: TestClient) -> None:
    _seed_fixture(client)
    first = client.get("/api/match?address_id=1")
    second = client.get("/api/match?address_id=1")
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.content == second.content


def test_ordering_is_kind_then_name(client: TestClient) -> None:
    _seed_fixture(client)
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
