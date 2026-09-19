"""/api/institutions: list/detail shape, ordering, ETag/cache, 404/405,
validation, and DB error -> 503.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, insert, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import StaticPool

from yasli import db
from yasli.main import app
from yasli.models import (
    Address,
    Base,
    Institution,
    InstitutionLocation,
    Street,
    address_institutions,
)
from yasli.routes import institutions as institutions_module

CACHE_CONTROL = "public, max-age=3600, stale-while-revalidate=86400"
LIST_KEYS = {
    "id",
    "external_id",
    "name",
    "kind",
    "source_url",
    "last_seen_at",
    "has_infant_group",
    "location",
}
# Declared independently of LIST_KEYS: the two payloads stop being a subset of
# one another once the detail carries contacts the list does not.
DETAIL_KEYS = {
    "id",
    "external_id",
    "name",
    "kind",
    "source_url",
    "last_seen_at",
    "address",
    "phone",
    "email",
    "director",
    "website",
    "district_code",
    "has_infant_group",
    "location",
    "branches",
    "coverage",
}
BRANCH_KEYS = {"label", "address", "location"}
LOCATION_KEYS = {"lat", "lon", "precision"}
CONTACT_FIELDS = ("address", "phone", "email", "director", "website", "district_code")
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


def _seed_locations(_client: TestClient, rows: list[dict[str, object]]) -> None:
    """Insert `institution_locations` rows, defaulting the provenance columns.

    `label`/`address` default to the stored empty-string sentinel and
    `precision` follows the CHECK constraint: `none` exactly when there is no
    coordinate.
    """
    assert db._SessionLocal is not None
    with db._SessionLocal() as session:
        for row in rows:
            payload = dict(row)
            payload.setdefault("role", "main")
            payload.setdefault("label", "")
            payload.setdefault("address", "")
            payload.setdefault("lat", None)
            payload.setdefault("lon", None)
            payload.setdefault(
                "precision", "none" if payload["lat"] is None else "building"
            )
            payload.setdefault("source", "manual")
            payload.setdefault("verification", "human")
            payload.setdefault("verified_at", date(2026, 9, 15))
            session.add(InstitutionLocation(**payload))
        session.commit()


# ДГ№13 "Мир" as the committed reference file has it: a pinned main building
# and four pinned branches, one of them on the main building's street.
DG13_MAIN = (43.209589, 27.926883)
DG13_BRANCHES = (
    ("бул. Княз Борис I, 109", 43.209885, 27.928446),
    ("ул. Н. Михайловски 1А", 43.209341, 27.926574),
    ("ул. Тодор Икономов 36", 43.210211, 27.928085),
    ("ул. Тодор Икономов, 26", 43.209883, 27.927021),
)


def _seed_dg13(client: TestClient) -> None:
    _seed_institutions(
        client,
        [{"id": 13, "kind": "kindergarten", "external_id": "46", "name": "ДГ№13"}],
    )
    _seed_locations(
        client,
        [
            {
                "kind": "kindergarten",
                "external_id": "46",
                "role": "main",
                "address": 'гр. Варна, ул."Никола Михайловски" №6',
                "lat": DG13_MAIN[0],
                "lon": DG13_MAIN[1],
            },
            *[
                {
                    "kind": "kindergarten",
                    "external_id": "46",
                    "role": "branch",
                    "address": address,
                    "lat": lat,
                    "lon": lon,
                }
                for address, lat, lon in DG13_BRANCHES
            ],
        ],
    )


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
    for name in (
        "coverage",
        "branches",
        "search_norm",
        "address_id",
        "institution_id",
        "source",
        "verification",
        "verified_at",
        "role",
    ):
        assert all(name not in item for item in body), name


def test_list_location_from_main_row_or_null(client: TestClient) -> None:
    _seed_institutions(
        client,
        [
            {"id": 1, "kind": "nursery", "external_id": "pinned", "name": "Alpha"},
            {"id": 2, "kind": "nursery", "external_id": "unpinned", "name": "Beta"},
            {"id": 3, "kind": "nursery", "external_id": "no-row", "name": "Gamma"},
        ],
    )
    _seed_locations(
        client,
        [
            {
                "kind": "nursery",
                "external_id": "pinned",
                "lat": 43.209589,
                "lon": 27.926883,
            },
            {"kind": "nursery", "external_id": "unpinned"},
        ],
    )

    body = client.get("/api/institutions").json()

    assert [item["id"] for item in body] == [1, 2, 3]
    assert body[0]["location"] == {
        "lat": 43.209589,
        "lon": 27.926883,
        "precision": "building",
    }
    assert body[1]["location"] is None
    assert body[2]["location"] is None


def test_list_does_not_duplicate_institutions_with_branches(client: TestClient) -> None:
    _seed_dg13(client)

    body = client.get("/api/institutions").json()

    assert [item["id"] for item in body] == [13]
    assert body[0]["location"]["precision"] == "building"


def test_list_has_infant_group_reflects_column(client: TestClient) -> None:
    _seed_institutions(
        client,
        [
            {"id": 1, "name": "Alpha", "has_infant_group": True},
            {"id": 2, "name": "Beta"},
        ],
    )

    body = client.get("/api/institutions").json()

    assert [item["has_infant_group"] for item in body] == [True, False]


def test_list_etag_changes_when_location_changes(client: TestClient) -> None:
    _seed_dg13(client)
    first = client.get("/api/institutions").headers["etag"]

    assert db._SessionLocal is not None
    with db._SessionLocal() as session:
        session.execute(
            update(InstitutionLocation)
            .where(
                InstitutionLocation.kind == "kindergarten",
                InstitutionLocation.external_id == "46",
                InstitutionLocation.role == "main",
            )
            .values(lat=43.200000)
        )
        session.commit()

    assert client.get("/api/institutions").headers["etag"] != first


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


def test_detail_absent_fields_are_null_not_omitted(client: TestClient) -> None:
    _seed_institutions(client, [{"id": 1}])

    body = client.get("/api/institutions/1").json()

    for field in CONTACT_FIELDS:
        assert field in body, field
        assert body[field] is None, field
    assert body["has_infant_group"] is False


def test_detail_returns_contact_fields_verbatim(client: TestClient) -> None:
    _seed_institutions(
        client,
        [
            {
                "id": 1,
                "address": "ул. Тест 1",
                "phone": "052/123-456",
                "email": "dg@example.bg",
                "director": "Иван Иванов",
                "website": "https://dg.example.bg",
                "district_code": "03",
                "has_infant_group": True,
            }
        ],
    )

    body = client.get("/api/institutions/1").json()

    assert body["address"] == "ул. Тест 1"
    assert body["phone"] == "052/123-456"
    assert body["email"] == "dg@example.bg"
    assert body["director"] == "Иван Иванов"
    assert body["website"] == "https://dg.example.bg"
    assert body["district_code"] == "03"
    assert body["has_infant_group"] is True


def test_detail_etag_changes_when_contact_changes(client: TestClient) -> None:
    _seed_institutions(client, [{"id": 1, "phone": "052/000-000"}])
    first = client.get("/api/institutions/1").headers["etag"]

    assert db._SessionLocal is not None
    with db._SessionLocal() as session:
        session.execute(
            update(Institution).where(Institution.id == 1).values(phone="052/999-999")
        )
        session.commit()

    second = client.get("/api/institutions/1")

    assert second.json()["phone"] == "052/999-999"
    assert second.headers["etag"] != first


def test_detail_location_is_main_pin_as_floats(client: TestClient) -> None:
    _seed_dg13(client)

    body = client.get("/api/institutions/13").json()

    assert set(body["location"].keys()) == LOCATION_KEYS
    assert body["location"] == {
        "lat": 43.209589,
        "lon": 27.926883,
        "precision": "building",
    }
    assert isinstance(body["location"]["lat"], float)
    assert isinstance(body["location"]["lon"], float)


def test_detail_location_null_without_pin(client: TestClient) -> None:
    _seed_institutions(
        client,
        [
            {"id": 1, "kind": "kindergarten", "external_id": "unpinned"},
            {"id": 2, "kind": "kindergarten", "external_id": "no-row"},
        ],
    )
    _seed_locations(
        client,
        [{"kind": "kindergarten", "external_id": "unpinned", "role": "main"}],
    )

    unpinned = client.get("/api/institutions/1").json()
    missing = client.get("/api/institutions/2").json()

    assert unpinned["location"] is None
    assert unpinned["branches"] == []
    assert missing["location"] is None
    assert missing["branches"] == []


def test_detail_branches_shape_and_blank_to_null(client: TestClient) -> None:
    _seed_dg13(client)
    _seed_locations(
        client,
        [
            {
                "kind": "kindergarten",
                "external_id": "46",
                "role": "branch",
                "label": "Annex",
            }
        ],
    )

    branches = client.get("/api/institutions/13").json()["branches"]

    for branch in branches:
        assert set(branch.keys()) == BRANCH_KEYS
    addressed = {branch["address"]: branch for branch in branches if branch["address"]}
    assert set(addressed) == {address for address, _, _ in DG13_BRANCHES}
    for branch in addressed.values():
        assert branch["label"] is None
        assert branch["location"]["precision"] == "building"
    name_only = next(branch for branch in branches if branch["label"] == "Annex")
    assert name_only["address"] is None
    assert name_only["location"] is None


def test_detail_branches_ordered_by_label_then_address(client: TestClient) -> None:
    _seed_institutions(client, [{"id": 1, "kind": "kindergarten", "external_id": "ord"}])
    _seed_locations(
        client,
        [
            {"kind": "kindergarten", "external_id": "ord", "role": "branch", **row}
            for row in (
                {"label": "Zeta"},
                {"label": "Annex", "address": "Gamma 3"},
                {"address": "Beta 2"},
                {"label": "Annex"},
                {"address": "Alpha 1"},
            )
        ],
    )

    first = client.get("/api/institutions/1")
    second = client.get("/api/institutions/1")
    branches = first.json()["branches"]

    assert [(b["label"], b["address"]) for b in branches] == [
        (None, "Alpha 1"),
        (None, "Beta 2"),
        ("Annex", None),
        ("Annex", "Gamma 3"),
        ("Zeta", None),
    ]
    assert first.content == second.content


def test_detail_branches_exclude_main(client: TestClient) -> None:
    _seed_dg13(client)

    body = client.get("/api/institutions/13").json()

    assert len(body["branches"]) == len(DG13_BRANCHES)
    main_address = 'гр. Варна, ул."Никола Михайловски" №6'
    assert all(branch["address"] != main_address for branch in body["branches"])


def test_detail_etag_changes_when_location_changes(client: TestClient) -> None:
    _seed_dg13(client)
    first = client.get("/api/institutions/13").headers["etag"]

    assert db._SessionLocal is not None
    with db._SessionLocal() as session:
        session.execute(
            update(InstitutionLocation)
            .where(
                InstitutionLocation.kind == "kindergarten",
                InstitutionLocation.external_id == "46",
                InstitutionLocation.role == "main",
            )
            .values(lat=43.200000)
        )
        session.commit()
    moved = client.get("/api/institutions/13").headers["etag"]

    _seed_locations(
        client,
        [
            {
                "kind": "kindergarten",
                "external_id": "46",
                "role": "branch",
                "label": "New annex",
            }
        ],
    )
    added = client.get("/api/institutions/13").headers["etag"]

    assert moved != first
    assert added != moved


def test_detail_does_not_leak_location_provenance(client: TestClient) -> None:
    _seed_dg13(client)

    raw = client.get("/api/institutions/13").text

    for name in ("source", "verification", "verified_at", "role"):
        assert f'"{name}"' not in raw


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


BY_SOURCE = "/api/institutions/by-source"


def test_by_source_matches_id_route_bytes_and_etag(client: TestClient) -> None:
    _seed_dg13(client)

    by_source = client.get(f"{BY_SOURCE}/kindergarten/46")
    by_id = client.get("/api/institutions/13")

    assert by_source.status_code == 200
    assert by_source.content == by_id.content
    assert by_source.headers["etag"] == by_id.headers["etag"]
    assert by_source.headers["cache-control"] == CACHE_CONTROL
    assert by_source.headers["vary"] == "Accept-Encoding"
    assert set(by_source.json().keys()) == DETAIL_KEYS


def test_by_source_unknown_pair_returns_404(client: TestClient) -> None:
    _seed_dg13(client)

    resp = client.get(f"{BY_SOURCE}/kindergarten/999")

    assert resp.status_code == 404
    assert resp.json() == {"error": "institution_not_found"}


def test_by_source_invalid_kind_returns_422(client: TestClient) -> None:
    _seed_dg13(client)

    assert client.get(f"{BY_SOURCE}/school/46").status_code == 422


def test_by_source_distinguishes_kind_and_exact_external_id(client: TestClient) -> None:
    _seed_institutions(
        client,
        [
            {"id": 1, "kind": "nursery", "external_id": "46", "name": "Nursery 46"},
            {
                "id": 2,
                "kind": "kindergarten",
                "external_id": "46",
                "name": "Kindergarten 46",
            },
        ],
    )

    assert client.get(f"{BY_SOURCE}/nursery/46").json()["id"] == 1
    assert client.get(f"{BY_SOURCE}/kindergarten/46").json()["id"] == 2
    assert client.get(f"{BY_SOURCE}/kindergarten/460").status_code == 404


def test_by_source_method_not_allowed(client: TestClient) -> None:
    assert client.post(f"{BY_SOURCE}/kindergarten/46").status_code == 405


def test_by_source_if_none_match_returns_304(client: TestClient) -> None:
    _seed_dg13(client)
    etag = client.get(f"{BY_SOURCE}/kindergarten/46").headers["etag"]

    resp = client.get(
        f"{BY_SOURCE}/kindergarten/46", headers={"If-None-Match": etag}
    )

    assert resp.status_code == 304
    assert resp.content == b""
    assert resp.headers["etag"] == etag
    assert resp.headers["cache-control"] == CACHE_CONTROL
    assert resp.headers["vary"] == "Accept-Encoding"


def test_by_source_if_none_match_miss_returns_full_body(client: TestClient) -> None:
    _seed_dg13(client)

    resp = client.get(
        f"{BY_SOURCE}/kindergarten/46",
        headers={"If-None-Match": '"v1-deadbeefdeadbeef"'},
    )

    assert resp.status_code == 200
    assert set(resp.json().keys()) == DETAIL_KEYS


def test_by_source_database_error_returns_503(caplog: pytest.LogCaptureFixture) -> None:
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
            resp = client.get(f"{BY_SOURCE}/kindergarten/46")
        assert resp.status_code == 503
        assert resp.json() == {"status": "degraded", "error": "database unreachable"}
        assert any("database error" in rec.message for rec in caplog.records)
    finally:
        app.dependency_overrides.pop(institutions_module.get_db, None)


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
