"""OpenAPI schema contract for /api/institutions."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from yasli.main import app

EXPECTED_KINDS = {"nursery", "kindergarten", "preschool"}
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
# Declared independently of LIST_KEYS: the detail carries contacts the list does not.
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
EXPECTED_PRECISIONS = {"building", "approximate"}
NULLABLE_DETAIL_FIELDS = (
    "address",
    "phone",
    "email",
    "director",
    "website",
    "district_code",
)
EXPECTED_DISTRICT_CODES = {"01", "02", "03", "04", "05"}
STREET_KEYS = {"id", "city", "raw_name", "street_part", "type_marker"}
ADDRESS_KEYS = {"id", "number_int", "number_suffix", "entrance"}


@pytest.fixture
def openapi() -> dict[str, Any]:
    return TestClient(app).get("/openapi.json").json()


def _resolve_schema(openapi: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    if "$ref" not in schema:
        return schema
    name = schema["$ref"].rsplit("/", 1)[-1]
    return openapi["components"]["schemas"][name]


def _enum_values(openapi: dict[str, Any], schema: dict[str, Any]) -> set[str]:
    schema = _resolve_schema(openapi, schema)
    if "enum" in schema:
        return set(schema["enum"])
    values: set[str] = set()
    for key in ("anyOf", "oneOf", "allOf"):
        for item in schema.get(key, []):
            values.update(_enum_values(openapi, item))
    return values


def test_institutions_list_schema_has_exactly_the_expected_fields(
    openapi: dict[str, Any],
) -> None:
    op = openapi["paths"]["/api/institutions"]["get"]
    schema = op["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema["type"] == "array"
    item_schema = _resolve_schema(openapi, schema["items"])

    assert set(item_schema["properties"].keys()) == LIST_KEYS
    assert "search_norm" not in item_schema["properties"]
    assert "address_id" not in item_schema["properties"]
    assert "institution_id" not in item_schema["properties"]


def test_institutions_list_declares_no_query_or_path_parameters(
    openapi: dict[str, Any],
) -> None:
    op = openapi["paths"]["/api/institutions"]["get"]
    params = op.get("parameters", [])

    assert [p for p in params if p.get("in") == "query"] == []
    assert [p for p in params if p.get("in") == "path"] == []


def test_institutions_detail_declares_institution_id_path_param(
    openapi: dict[str, Any],
) -> None:
    op = openapi["paths"]["/api/institutions/{institution_id}"]["get"]
    params = {p["name"]: p for p in op.get("parameters", []) if p.get("in") == "path"}

    assert set(params.keys()) == {"institution_id"}
    institution_id = params["institution_id"]
    assert institution_id["required"] is True
    assert institution_id["schema"]["type"] == "integer"
    assert institution_id["schema"]["minimum"] == 1


def test_institutions_detail_schema_has_expected_top_level_fields(
    openapi: dict[str, Any],
) -> None:
    op = openapi["paths"]["/api/institutions/{institution_id}"]["get"]
    schema = op["responses"]["200"]["content"]["application/json"]["schema"]
    detail_schema = _resolve_schema(openapi, schema)

    assert set(detail_schema["properties"].keys()) == DETAIL_KEYS
    assert "search_norm" not in detail_schema["properties"]


def test_institutions_detail_nested_schemas_have_expected_fields(
    openapi: dict[str, Any],
) -> None:
    op = openapi["paths"]["/api/institutions/{institution_id}"]["get"]
    schema = op["responses"]["200"]["content"]["application/json"]["schema"]
    detail_schema = _resolve_schema(openapi, schema)
    coverage_schema = _resolve_schema(
        openapi, detail_schema["properties"]["coverage"]["items"]
    )
    street_schema = _resolve_schema(openapi, coverage_schema["properties"]["street"])
    addresses_schema = _resolve_schema(
        openapi, coverage_schema["properties"]["addresses"]["items"]
    )

    assert set(coverage_schema["properties"].keys()) == {"street", "addresses"}
    assert set(street_schema["properties"].keys()) == STREET_KEYS
    assert set(addresses_schema["properties"].keys()) == ADDRESS_KEYS
    assert "search_norm" not in street_schema["properties"]
    assert "address_id" not in addresses_schema["properties"]
    assert "institution_id" not in addresses_schema["properties"]


def _detail_schema(openapi: dict[str, Any]) -> dict[str, Any]:
    op = openapi["paths"]["/api/institutions/{institution_id}"]["get"]
    schema = op["responses"]["200"]["content"]["application/json"]["schema"]
    return _resolve_schema(openapi, schema)


def _admits_null(openapi: dict[str, Any], schema: dict[str, Any]) -> bool:
    for key in ("anyOf", "oneOf"):
        for item in schema.get(key, []):
            if item.get("type") == "null":
                return True
    return False


def test_institutions_detail_new_fields_are_required_nullable(
    openapi: dict[str, Any],
) -> None:
    detail_schema = _detail_schema(openapi)
    required = set(detail_schema["required"])

    for name in NULLABLE_DETAIL_FIELDS:
        assert name in required, name
        assert _admits_null(openapi, detail_schema["properties"][name]), name

    assert (
        _enum_values(openapi, detail_schema["properties"]["district_code"])
        == EXPECTED_DISTRICT_CODES
    )
    assert "has_infant_group" in required
    assert detail_schema["properties"]["has_infant_group"]["type"] == "boolean"


def _any_of_refs(schema: dict[str, Any]) -> set[str]:
    return {
        item["$ref"].rsplit("/", 1)[-1]
        for item in schema.get("anyOf", [])
        if "$ref" in item
    }


def test_institutions_location_and_branch_schemas(openapi: dict[str, Any]) -> None:
    detail_schema = _detail_schema(openapi)
    required = set(detail_schema["required"])
    location_schema = openapi["components"]["schemas"]["Location"]
    branch_schema = openapi["components"]["schemas"]["Branch"]

    assert set(location_schema["properties"].keys()) == LOCATION_KEYS
    assert (
        _enum_values(openapi, location_schema["properties"]["precision"])
        == EXPECTED_PRECISIONS
    )

    assert set(branch_schema["properties"].keys()) == BRANCH_KEYS
    branch_required = set(branch_schema["required"])
    for name in BRANCH_KEYS:
        assert name in branch_required, name
        assert _admits_null(openapi, branch_schema["properties"][name]), name
    assert _any_of_refs(branch_schema["properties"]["location"]) == {"Location"}

    assert "location" in required
    assert _admits_null(openapi, detail_schema["properties"]["location"])
    assert _any_of_refs(detail_schema["properties"]["location"]) == {"Location"}
    assert "branches" in required
    branches = detail_schema["properties"]["branches"]
    assert branches["type"] == "array"
    assert branches["items"]["$ref"].endswith("/Branch")


def test_institutions_schemas_hide_location_provenance(openapi: dict[str, Any]) -> None:
    for name in ("Location", "Branch", "InstitutionDetail"):
        properties = set(openapi["components"]["schemas"][name]["properties"])
        assert properties.isdisjoint(
            {"source", "verification", "verified_at", "role"}
        ), name


BY_SOURCE_PATH = "/api/institutions/by-source/{kind}/{external_id}"


def test_institutions_by_source_declares_kind_and_external_id_path_params(
    openapi: dict[str, Any],
) -> None:
    op = openapi["paths"][BY_SOURCE_PATH]["get"]
    params = {p["name"]: p for p in op.get("parameters", []) if p.get("in") == "path"}

    assert set(params.keys()) == {"kind", "external_id"}
    assert params["kind"]["required"] is True
    assert _enum_values(openapi, params["kind"]["schema"]) == EXPECTED_KINDS
    assert params["external_id"]["required"] is True
    assert params["external_id"]["schema"]["type"] == "string"
    assert "maxLength" not in params["external_id"]["schema"]

    # The id route is untouched by the extraction.
    id_op = openapi["paths"]["/api/institutions/{institution_id}"]["get"]
    id_params = {
        p["name"]: p for p in id_op.get("parameters", []) if p.get("in") == "path"
    }
    assert set(id_params.keys()) == {"institution_id"}
    assert id_params["institution_id"]["schema"]["type"] == "integer"
    assert id_params["institution_id"]["schema"]["minimum"] == 1


def test_institutions_by_source_returns_institution_detail_schema(
    openapi: dict[str, Any],
) -> None:
    by_source = openapi["paths"][BY_SOURCE_PATH]["get"]
    by_id = openapi["paths"]["/api/institutions/{institution_id}"]["get"]

    by_source_ref = by_source["responses"]["200"]["content"]["application/json"][
        "schema"
    ]["$ref"]
    by_id_ref = by_id["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ]

    assert by_source_ref == by_id_ref
    assert by_source_ref.endswith("/InstitutionDetail")


def test_institutions_list_location_reuses_location_schema(
    openapi: dict[str, Any],
) -> None:
    op = openapi["paths"]["/api/institutions"]["get"]
    schema = op["responses"]["200"]["content"]["application/json"]["schema"]
    item_schema = _resolve_schema(openapi, schema["items"])
    required = set(item_schema["required"])

    assert "location" in required
    assert _admits_null(openapi, item_schema["properties"]["location"])
    assert _any_of_refs(item_schema["properties"]["location"]) == {"Location"}
    assert "has_infant_group" in required
    assert item_schema["properties"]["has_infant_group"]["type"] == "boolean"


def test_institutions_kind_resolves_to_expected_enum_values(
    openapi: dict[str, Any],
) -> None:
    list_op = openapi["paths"]["/api/institutions"]["get"]
    list_schema = list_op["responses"]["200"]["content"]["application/json"]["schema"]
    list_item_schema = _resolve_schema(openapi, list_schema["items"])
    detail_op = openapi["paths"]["/api/institutions/{institution_id}"]["get"]
    detail_schema = _resolve_schema(
        openapi,
        detail_op["responses"]["200"]["content"]["application/json"]["schema"],
    )

    assert _enum_values(openapi, list_item_schema["properties"]["kind"]) == EXPECTED_KINDS
    assert _enum_values(openapi, detail_schema["properties"]["kind"]) == EXPECTED_KINDS
