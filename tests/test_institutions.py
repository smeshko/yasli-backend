"""/api/institutions: list/detail shape, ordering, ETag/cache, 404/405,
validation, and DB error -> 503.
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
from yasli.routes import institutions as institutions_module

CACHE_CONTROL = "public, max-age=3600, stale-while-revalidate=86400"
LIST_KEYS = {"id", "external_id", "name", "kind", "source_url", "last_seen_at"}
DETAIL_KEYS = LIST_KEYS | {"coverage"}
STREET_KEYS = {"id", "city", "raw_name", "street_part", "type_marker"}
ADDRESS_KEYS = {"id", "number_int", "number_suffix", "entrance"}
NOW = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)


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


def _seed_institutions(
    _client: TestClient, rows: list[dict[str, object]]
) -> list[int]:
    assert db._SessionLocal is not None
    inserted: list[int] = []
    with db._SessionLocal() as session:
        for row in rows:
            payload = dict(row)
            institution_id = int(payload["id"])
            payload.setdefault("external_id", f"I{institution_id}")
            payload.setdefault("name", f"Institution {institution_id}")
            payload.setdefault("kind", "kindergarten")
            payload.setdefault("source_url", f"https://example.test/{institution_id}")
            payload.setdefault("last_seen_at", NOW)
            session.add(Institution(**payload))
            inserted.append(institution_id)
        session.commit()
    return inserted


def _seed_streets(_client: TestClient, rows: list[dict[str, object]]) -> list[int]:
    assert db._SessionLocal is not None
    inserted: list[int] = []
    with db._SessionLocal() as session:
        for row in rows:
            payload = dict(row)
            street_id = int(payload["id"])
            payload.setdefault("city", f"City {street_id}")
            payload.setdefault("raw_name", f"Street {street_id}")
            payload.setdefault("street_part", f"Street {street_id}")
            payload.setdefault("type_marker", "ул.")
            payload.setdefault("search_norm", f"street {street_id}")
            session.add(Street(**payload))
            inserted.append(street_id)
        session.commit()
    return inserted


def _seed_addresses(_client: TestClient, rows: list[dict[str, object]]) -> list[int]:
    assert db._SessionLocal is not None
    inserted: list[int] = []
    with db._SessionLocal() as session:
        for row in rows:
            payload = dict(row)
            address_id = int(payload["id"])
            payload.setdefault("number_suffix", None)
            payload.setdefault("entrance", None)
            session.add(Address(**payload))
            inserted.append(address_id)
        session.commit()
    return inserted


def _link_addresses(_client: TestClient, institution_id: int, address_ids: list[int]) -> None:
    assert db._SessionLocal is not None
    with db._SessionLocal() as session:
        session.execute(
            insert(address_institutions),
            [
                {"address_id": address_id, "institution_id": institution_id}
                for address_id in address_ids
            ],
        )
        session.commit()


def _seed_detail_fixture(client: TestClient) -> None:
    _seed_institutions(
        client,
        [
            {"id": 1, "external_id": "I1", "name": "Institution One"},
            {"id": 2, "external_id": "I2", "name": "Institution Two"},
        ],
    )
    _seed_streets(
        client,
        [
            {
                "id": 1,
                "city": "B City",
                "raw_name": "Street C",
                "street_part": "C",
                "type_marker": "ул.",
                "search_norm": "c",
            },
            {
                "id": 2,
                "city": "A City",
                "raw_name": "Street B",
                "street_part": "B",
                "type_marker": "бул.",
                "search_norm": "b",
            },
            {
                "id": 3,
                "city": "A City",
                "raw_name": "Street A",
                "street_part": "A",
                "type_marker": None,
                "search_norm": "a",
            },
        ],
    )
    _seed_addresses(
        client,
        [
            {"id": 11, "street_id": 3, "number_int": 19, "number_suffix": "A"},
            {"id": 12, "street_id": 3, "number_int": 1},
            {"id": 13, "street_id": 3, "number_int": 41, "entrance": "A"},
            {"id": 14, "street_id": 3, "number_int": 41},
            {"id": 15, "street_id": 3, "number_int": 19},
            {"id": 21, "street_id": 2, "number_int": 7},
            {"id": 31, "street_id": 1, "number_int": 3},
        ],
    )
    _link_addresses(client, 1, [11, 12, 13, 14, 15, 21, 31])


def test_returns_institutions_with_expected_shape(client: TestClient) -> None:
    _seed_institutions(
        client,
        [
            {"id": 1, "external_id": "N1", "name": "Nursery", "kind": "nursery"},
            {"id": 2, "external_id": "K1", "name": "Kindergarten"},
            {"id": 3, "external_id": "P1", "name": "Preschool", "kind": "preschool"},
        ],
    )

    resp = client.get("/api/institutions")

    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) == 3
    for item in body:
        assert set(item.keys()) == LIST_KEYS


def test_list_does_not_include_coverage_or_server_only_fields(client: TestClient) -> None:
    _seed_institutions(client, [{"id": 1}])

    body = client.get("/api/institutions").json()

    assert body
    assert all("coverage" not in item for item in body)
    assert all("search_norm" not in item for item in body)
    assert all("address_id" not in item for item in body)
    assert all("institution_id" not in item for item in body)


def test_empty_database_returns_200_empty_array_with_etag(client: TestClient) -> None:
    resp = client.get("/api/institutions")

    assert resp.status_code == 200
    assert resp.json() == []
    assert resp.headers["etag"].startswith('"v1-')


def test_list_ordering_is_kind_display_order_then_name(client: TestClient) -> None:
    _seed_institutions(
        client,
        [
            {"id": 1, "external_id": "P1", "name": "Alpha", "kind": "preschool"},
            {"id": 2, "external_id": "K9", "name": "Beta", "kind": "kindergarten"},
            {"id": 3, "external_id": "N1", "name": "Zulu", "kind": "nursery"},
            {"id": 4, "external_id": "K2", "name": "Alpha", "kind": "kindergarten"},
            {"id": 5, "external_id": "K1", "name": "Alpha", "kind": "kindergarten"},
        ],
    )

    body = client.get("/api/institutions").json()

    assert [item["id"] for item in body] == [3, 5, 4, 2, 1]


def test_list_ordering_is_stable(client: TestClient) -> None:
    _seed_institutions(client, [{"id": 2}, {"id": 1, "kind": "nursery"}])

    first = client.get("/api/institutions")
    second = client.get("/api/institutions")

    assert first.content == second.content


def test_list_etag_stable_across_requests(client: TestClient) -> None:
    _seed_institutions(client, [{"id": 1}])

    first = client.get("/api/institutions")
    second = client.get("/api/institutions")

    assert first.headers["etag"] == second.headers["etag"]


def test_list_etag_changes_when_data_changes(client: TestClient) -> None:
    _seed_institutions(client, [{"id": 1}])
    first = client.get("/api/institutions").headers["etag"]

    _seed_institutions(client, [{"id": 2}])
    second = client.get("/api/institutions").headers["etag"]

    assert first != second


def test_list_if_none_match_returns_304(client: TestClient) -> None:
    _seed_institutions(client, [{"id": 1}])
    etag = client.get("/api/institutions").headers["etag"]

    resp = client.get("/api/institutions", headers={"If-None-Match": etag})

    assert resp.status_code == 304
    assert resp.content == b""
    assert resp.headers["etag"] == etag
    assert resp.headers["cache-control"] == CACHE_CONTROL
    assert resp.headers["vary"] == "Accept-Encoding"


def test_list_if_none_match_miss_returns_full_body(client: TestClient) -> None:
    _seed_institutions(client, [{"id": 1}])

    resp = client.get(
        "/api/institutions", headers={"If-None-Match": '"v1-deadbeefdeadbeef"'}
    )

    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_list_cache_control_header_present(client: TestClient) -> None:
    resp = client.get("/api/institutions")

    assert resp.headers["cache-control"] == CACHE_CONTROL
    assert resp.headers["vary"] == "Accept-Encoding"


def test_list_method_not_allowed(client: TestClient) -> None:
    resp = client.post("/api/institutions")

    assert resp.status_code == 405


def test_list_database_error_returns_503(caplog: pytest.LogCaptureFixture) -> None:
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

    app.dependency_overrides[institutions_module.get_db] = _broken_get_db
    try:
        client = TestClient(app, raise_server_exceptions=False)
        with caplog.at_level("ERROR"):
            resp = client.get("/api/institutions")
        assert resp.status_code == 503
        assert resp.json() == {"status": "degraded", "error": "database unreachable"}
        assert any("database error" in rec.message for rec in caplog.records)
    finally:
        app.dependency_overrides.pop(institutions_module.get_db, None)


def test_detail_returns_expected_shape(client: TestClient) -> None:
    _seed_detail_fixture(client)

    resp = client.get("/api/institutions/1")

    assert resp.status_code == 200
    assert set(resp.json().keys()) == DETAIL_KEYS


def test_detail_coverage_shape(client: TestClient) -> None:
    _seed_detail_fixture(client)

    body = client.get("/api/institutions/1").json()

    assert body["coverage"]
    for group in body["coverage"]:
        assert set(group.keys()) == {"street", "addresses"}
        assert set(group["street"].keys()) == STREET_KEYS
        for address in group["addresses"]:
            assert set(address.keys()) == ADDRESS_KEYS


def test_detail_does_not_include_server_only_fields(client: TestClient) -> None:
    _seed_detail_fixture(client)

    body = client.get("/api/institutions/1").json()

    assert "search_norm" not in body
    assert "address_id" not in body
    assert "institution_id" not in body
    for group in body["coverage"]:
        assert "search_norm" not in group["street"]
        assert "address_id" not in group
        assert "institution_id" not in group
        for address in group["addresses"]:
            assert "street_id" not in address


def test_detail_institution_with_no_coverage_returns_empty_array(
    client: TestClient,
) -> None:
    _seed_detail_fixture(client)

    resp = client.get("/api/institutions/2")

    assert resp.status_code == 200
    assert resp.json()["coverage"] == []


def test_detail_preserves_nullable_address_parts(client: TestClient) -> None:
    _seed_detail_fixture(client)

    body = client.get("/api/institutions/1").json()
    addresses = {
        address["id"]: address
        for group in body["coverage"]
        for address in group["addresses"]
    }

    assert addresses[11]["number_suffix"] == "A"
    assert addresses[11]["entrance"] is None
    assert addresses[13]["number_suffix"] is None
    assert addresses[13]["entrance"] == "A"


def test_detail_groups_by_street_once(client: TestClient) -> None:
    _seed_detail_fixture(client)

    body = client.get("/api/institutions/1").json()
    street_ids = [group["street"]["id"] for group in body["coverage"]]

    assert len(street_ids) == len(set(street_ids))
    assert street_ids.count(3) == 1
    street_3 = next(group for group in body["coverage"] if group["street"]["id"] == 3)
    assert len(street_3["addresses"]) == 5


def test_detail_orders_coverage_by_street(client: TestClient) -> None:
    _seed_detail_fixture(client)

    body = client.get("/api/institutions/1").json()
    keys = [
        (group["street"]["city"], group["street"]["raw_name"], group["street"]["id"])
        for group in body["coverage"]
    ]

    assert keys == sorted(keys)
    assert [group["street"]["id"] for group in body["coverage"]] == [3, 2, 1]


def test_detail_orders_addresses_naturally_with_nulls_last(
    client: TestClient,
) -> None:
    _seed_detail_fixture(client)

    body = client.get("/api/institutions/1").json()
    street_3 = next(group for group in body["coverage"] if group["street"]["id"] == 3)

    assert [address["id"] for address in street_3["addresses"]] == [12, 11, 15, 13, 14]


def test_detail_ordering_is_stable(client: TestClient) -> None:
    _seed_detail_fixture(client)

    first = client.get("/api/institutions/1")
    second = client.get("/api/institutions/1")

    assert first.content == second.content


def test_unknown_institution_id_returns_404(client: TestClient) -> None:
    resp = client.get("/api/institutions/999999")

    assert resp.status_code == 404
    assert resp.json() == {"error": "institution_not_found"}


def test_invalid_institution_id_returns_422(client: TestClient) -> None:
    assert client.get("/api/institutions/not-an-int").status_code == 422
    assert client.get("/api/institutions/0").status_code == 422


def test_detail_method_not_allowed(client: TestClient) -> None:
    resp = client.post("/api/institutions/1")

    assert resp.status_code == 405


def test_detail_etag_stable_across_requests(client: TestClient) -> None:
    _seed_detail_fixture(client)

    first = client.get("/api/institutions/1")
    second = client.get("/api/institutions/1")

    assert first.headers["etag"] == second.headers["etag"]


def test_detail_if_none_match_returns_304(client: TestClient) -> None:
    _seed_detail_fixture(client)
    etag = client.get("/api/institutions/1").headers["etag"]

    resp = client.get("/api/institutions/1", headers={"If-None-Match": etag})

    assert resp.status_code == 304
    assert resp.content == b""
    assert resp.headers["etag"] == etag
    assert resp.headers["cache-control"] == CACHE_CONTROL
    assert resp.headers["vary"] == "Accept-Encoding"


def test_detail_if_none_match_miss_returns_full_body(client: TestClient) -> None:
    _seed_detail_fixture(client)

    resp = client.get(
        "/api/institutions/1", headers={"If-None-Match": '"v1-deadbeefdeadbeef"'}
    )

    assert resp.status_code == 200
    assert set(resp.json().keys()) == DETAIL_KEYS


def test_detail_database_error_returns_503(caplog: pytest.LogCaptureFixture) -> None:
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

    app.dependency_overrides[institutions_module.get_db] = _broken_get_db
    try:
        client = TestClient(app, raise_server_exceptions=False)
        with caplog.at_level("ERROR"):
            resp = client.get("/api/institutions/1")
        assert resp.status_code == 503
        assert resp.json() == {"status": "degraded", "error": "database unreachable"}
        assert any("database error" in rec.message for rec in caplog.records)
    finally:
        app.dependency_overrides.pop(institutions_module.get_db, None)
