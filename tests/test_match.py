"""/api/match: structured address context, routing, ordering, and validation."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, insert
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import StaticPool

from yasli import db
from yasli.main import app
from yasli.models import (
    Address,
    Base,
    Institution,
    Settlement,
    Street,
    address_institutions,
)
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
    """Seed a small dataset that exercises every routing path.

    Districts: addresses 1 + 2 are in '01' (Одесос); address 3 is in '02'
    (Приморски); address 4 has both district_code and settlement_code
    NULL (truly unrecognised); address 5 is in a Varna village with
    settlement_code set but district_code NULL (the village fallback case);
    address 6 is a district-null ГР.ВАРНА row with settlement context.

    Institutions:
      N1 — nursery, district='01' (only via district routing)
      N2 — nursery, district='02'
      N3 — nursery, district=NULL  (should never match)
      K1 — kindergarten, junction to {1, 2}
      K2 — kindergarten, junction to {3}
      P1 — preschool, district='01' (district fallback in район Одесос)
      P2 — preschool, district='02'. Has a junction edge to address 1
           (source-published catchment). Exercised by the hybrid PG path:
           addr 1 returns P2 via street, suppressing the district fallback.
      P3 — preschool, district=NULL (should never match via district path)
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
                Settlement(
                    code="10135",
                    name="ГР.ВАРНА",
                    locality_type="city",
                ),
                Settlement(
                    code="35701",
                    name="С.КАМЕНАР",
                    locality_type="village",
                ),
            ]
        )
        session.add_all(
            [
                Address(
                    id=1,
                    street_id=1,
                    number_int=1,
                    district_code="01",
                    settlement_code="10135",
                ),
                Address(
                    id=2,
                    street_id=1,
                    number_int=2,
                    district_code="01",
                    settlement_code="10135",
                ),
                Address(
                    id=3,
                    street_id=1,
                    number_int=3,
                    district_code="02",
                    settlement_code="10135",
                ),
                Address(
                    id=4,
                    street_id=1,
                    number_int=4,
                    district_code=None,
                    settlement_code=None,
                ),
                Address(
                    id=5,
                    street_id=1,
                    number_int=5,
                    district_code=None,
                    settlement_code="35701",  # с. Каменар
                ),
                Address(
                    id=6,
                    street_id=1,
                    number_int=6,
                    district_code=None,
                    settlement_code="10135",
                ),
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
                    has_infant_group=True,
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
                {"address_id": 6, "institution_id": 4},
                # P2's building is at address 1 (район 01) but its
                # catchment-majority is район 02 — the new routing must
                # use institutions.district_code, not this junction edge.
                {"address_id": 1, "institution_id": 7},
            ],
        )
        session.commit()


STRUCTURED_RESULT_KEYS = {
    "id",
    "external_id",
    "name",
    "institution_kind",
    "reception_kind",
    "offering",
    "source_url",
    "match_basis",
    "has_infant_group",
}


def _result_by_external(body: dict, external_id: str) -> dict:
    return next(r for r in body["results"] if r["external_id"] == external_id)


def test_match_district_known_returns_structured_object_with_mixed_results(
    client: TestClient,
) -> None:
    _seed_fixture(client)
    resp = client.get("/api/match?address_id=1")
    assert resp.status_code == 200
    body = resp.json()

    assert set(body.keys()) == {"address", "results"}
    assert body["address"] == {
        "id": 1,
        "district_code": "01",
        "settlement": {
            "code": "10135",
            "name": "ГР.ВАРНА",
            "locality_type": "city",
        },
    }
    by_reception = {
        (r["external_id"], r["reception_kind"], r["offering"]): r
        for r in body["results"]
    }
    assert set(by_reception) == {
        ("K1", "nursery", "infant_group"),
        ("N1", "nursery", "standard"),
        ("K1", "kindergarten", "standard"),
        ("P2", "preschool", "standard"),
    }
    assert by_reception[("K1", "kindergarten", "standard")]["match_basis"] == "address"
    assert by_reception[("K1", "nursery", "infant_group")]["match_basis"] == "address"
    assert by_reception[("N1", "nursery", "standard")]["match_basis"] == "district"
    assert by_reception[("P2", "preschool", "standard")]["match_basis"] == "address"
    assert by_reception[("K1", "kindergarten", "standard")]["has_infant_group"] is True
    assert by_reception[("K1", "nursery", "infant_group")]["has_infant_group"] is True
    for item in body["results"]:
        assert set(item.keys()) == STRUCTURED_RESULT_KEYS
        assert "kind" not in item
        assert "match_type" not in item


def test_has_infant_group_flag_surfaces_for_kindergartens(client: TestClient) -> None:
    _seed_fixture(client)
    body = client.get("/api/match?address_id=1").json()
    assert _result_by_external(body, "K1")["has_infant_group"] is True
    assert _result_by_external(body, "N1")["has_infant_group"] is False
    assert _result_by_external(body, "P2")["has_infant_group"] is False


def test_preschool_match_basis_is_district_when_falling_back(
    client: TestClient,
) -> None:
    """addr 2 has no PG junction edges, so the district fallback kicks in
    and returns район-01 PGs with match_basis='district'.
    """
    _seed_fixture(client)
    body = client.get("/api/match?address_id=2&kind=preschool").json()
    p1 = _result_by_external(body, "P1")
    assert p1["match_basis"] == "district"


def test_kindergarten_filter_only_returns_junction_matches(
    client: TestClient,
) -> None:
    _seed_fixture(client)
    body = client.get("/api/match?address_id=1&kind=kindergarten").json()
    assert {r["external_id"] for r in body["results"]} == {"K1"}
    assert all(r["institution_kind"] == "kindergarten" for r in body["results"])
    assert all(r["match_basis"] == "address" for r in body["results"])


def test_nursery_filter_routes_by_district(client: TestClient) -> None:
    _seed_fixture(client)
    body = client.get("/api/match?address_id=1&kind=nursery").json()
    assert {r["external_id"] for r in body["results"]} == {"N1"}
    assert all(r["institution_kind"] == "nursery" for r in body["results"])
    assert all(r["match_basis"] == "district" for r in body["results"])


def test_preschool_street_match_suppresses_district_fallback(
    client: TestClient,
) -> None:
    """addr 1 has a PG junction edge to P2 — junction wins, P1 (the
    район-01 district fallback) is NOT included.
    """
    _seed_fixture(client)
    body = client.get("/api/match?address_id=1&kind=preschool").json()
    assert {r["external_id"] for r in body["results"]} == {"P2"}
    assert all(r["match_basis"] == "address" for r in body["results"])


def test_preschool_district_fallback_when_no_junction(
    client: TestClient,
) -> None:
    """addr 2 has no PG junction — fall back to район-01 PGs."""
    _seed_fixture(client)
    body = client.get("/api/match?address_id=2&kind=preschool").json()
    assert {r["external_id"] for r in body["results"]} == {"P1"}
    assert all(r["match_basis"] == "district" for r in body["results"])


def test_nursery_with_null_district_never_returned(client: TestClient) -> None:
    _seed_fixture(client)
    # N3 has district_code IS NULL — never matches any district query.
    for addr in (1, 2, 3):
        body = client.get(f"/api/match?address_id={addr}&kind=nursery").json()
        assert "N3" not in {r["external_id"] for r in body["results"]}


def test_preschool_with_null_district_never_returned(client: TestClient) -> None:
    """P3 has no junction edges and no district stamp — never matches.
    addr 1 returns a street match (P2); addr 2/3 use district fallback.
    None of them should surface P3.
    """
    _seed_fixture(client)
    for addr in (1, 2, 3):
        body = client.get(f"/api/match?address_id={addr}&kind=preschool").json()
        assert "P3" not in {r["external_id"] for r in body["results"]}


def test_unknown_district_no_filter_returns_structured_context(
    client: TestClient,
) -> None:
    _seed_fixture(client)
    resp = client.get("/api/match?address_id=4")
    assert resp.status_code == 200
    body = resp.json()
    assert body["address"] == {
        "id": 4,
        "district_code": None,
        "settlement": None,
    }
    assert body["results"] == []


def test_unknown_district_kind_nursery_returns_empty_results(
    client: TestClient,
) -> None:
    _seed_fixture(client)
    body = client.get("/api/match?address_id=4&kind=nursery").json()
    assert body["address"]["district_code"] is None
    assert body["results"] == []


def test_unknown_district_kind_preschool_returns_empty_results(
    client: TestClient,
) -> None:
    """addr 4 has no district stamp AND no PG junction edges — both
    routing paths are unavailable, so structured results are empty.
    """
    _seed_fixture(client)
    body = client.get("/api/match?address_id=4&kind=preschool").json()
    assert body["address"]["district_code"] is None
    assert body["results"] == []


def test_unknown_district_preschool_junction_match_returns_structured_result(
    client: TestClient,
) -> None:
    """Hybrid PG: when district is unknown but a PG junction edge exists,
    the structured response still carries the address-level match.
    """
    assert db._SessionLocal is not None
    _seed_fixture(client)
    # Add a junction edge between addr 4 (district NULL) and P2.
    with db._SessionLocal() as session:
        session.execute(
            insert(address_institutions),
            [{"address_id": 4, "institution_id": 7}],
        )
        session.commit()
    body = client.get("/api/match?address_id=4&kind=preschool").json()
    assert body["address"]["district_code"] is None
    assert {r["external_id"] for r in body["results"]} == {"P2"}
    assert body["results"][0]["match_basis"] == "address"


def test_village_address_returns_settlement_context_without_envelope(
    client: TestClient,
) -> None:
    _seed_fixture(client)
    resp = client.get("/api/match?address_id=5")
    assert resp.status_code == 200
    body = resp.json()
    assert body["address"] == {
        "id": 5,
        "district_code": None,
        "settlement": {
            "code": "35701",
            "name": "С.КАМЕНАР",
            "locality_type": "village",
        },
    }
    assert {
        r["external_id"]
        for r in body["results"]
        if r["institution_kind"] == "nursery"
    } == set()


def test_village_address_kind_nursery_returns_empty_structured_results(
    client: TestClient,
) -> None:
    _seed_fixture(client)
    body = client.get("/api/match?address_id=5&kind=nursery").json()
    assert body["address"]["settlement"]["locality_type"] == "village"
    assert body["results"] == []


def test_district_null_city_returns_city_context_without_envelope(
    client: TestClient,
) -> None:
    _seed_fixture(client)
    resp = client.get("/api/match?address_id=6")
    assert resp.status_code == 200
    body = resp.json()
    assert body["address"]["district_code"] is None
    assert body["address"]["settlement"] == {
        "code": "10135",
        "name": "ГР.ВАРНА",
        "locality_type": "city",
    }


def test_unknown_district_kind_kindergarten_returns_structured_results(
    client: TestClient,
) -> None:
    _seed_fixture(client)
    resp = client.get("/api/match?address_id=4&kind=kindergarten")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"address", "results"}
    assert body["address"]["district_code"] is None
    assert body["results"] == []


def test_structured_result_fields_present(client: TestClient) -> None:
    _seed_fixture(client)
    body = client.get("/api/match?address_id=1").json()
    assert body["results"]
    for item in body["results"]:
        assert set(item.keys()) == STRUCTURED_RESULT_KEYS
        assert isinstance(item["id"], int)
        assert isinstance(item["external_id"], str)
        assert isinstance(item["name"], str)
        assert item["institution_kind"] in {"nursery", "kindergarten", "preschool"}
        assert item["reception_kind"] in {"nursery", "kindergarten", "preschool"}
        assert item["offering"] in {"standard", "infant_group"}
        assert isinstance(item["source_url"], str)
        assert item["match_basis"] in {"address", "district"}
        assert isinstance(item["has_infant_group"], bool)


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


def test_kindergarten_filter_works_without_district_context(
    client: TestClient,
) -> None:
    _seed_fixture(client)
    resp = client.get("/api/match?address_id=6&kind=kindergarten")
    assert resp.status_code == 200
    body = resp.json()

    assert {r["external_id"] for r in body["results"]} == {"K1"}
    assert all(r["institution_kind"] == "kindergarten" for r in body["results"])
    assert all(r["match_basis"] == "address" for r in body["results"])
    assert {
        (r["reception_kind"], r["offering"]) for r in body["results"]
    } == {
        ("nursery", "infant_group"),
        ("kindergarten", "standard"),
    }


def test_nursery_and_preschool_routing_semantics(
    client: TestClient,
) -> None:
    _seed_fixture(client)

    nursery = client.get("/api/match?address_id=1&kind=nursery").json()
    assert {r["external_id"] for r in nursery["results"]} == {"N1"}
    assert all(r["institution_kind"] == "nursery" for r in nursery["results"])
    assert all(r["reception_kind"] == "nursery" for r in nursery["results"])
    assert all(r["offering"] == "standard" for r in nursery["results"])
    assert all(r["match_basis"] == "district" for r in nursery["results"])

    preschool_junction = client.get(
        "/api/match?address_id=1&kind=preschool"
    ).json()
    assert {r["external_id"] for r in preschool_junction["results"]} == {"P2"}
    assert all(r["match_basis"] == "address" for r in preschool_junction["results"])

    preschool_fallback = client.get(
        "/api/match?address_id=2&kind=preschool"
    ).json()
    assert {r["external_id"] for r in preschool_fallback["results"]} == {"P1"}
    assert all(r["match_basis"] == "district" for r in preschool_fallback["results"])


def test_match_v2_route_is_removed(client: TestClient) -> None:
    _seed_fixture(client)
    resp = client.get("/api/match/v2?address_id=999999")

    assert resp.status_code == 404
    assert resp.json() == {"detail": "Not Found"}


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
