"""OpenAPI schema contract for /api/institutions."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from yasli.main import app

EXPECTED_KINDS = {"nursery", "kindergarten", "preschool"}
LIST_KEYS = {"id", "external_id", "name", "kind", "source_url", "last_seen_at"}
DETAIL_KEYS = LIST_KEYS | {"coverage"}
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


def test_institutions_list_schema_has_exactly_six_fields(
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
