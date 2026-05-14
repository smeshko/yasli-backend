"""OpenAPI schema contract for /api/match."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from yasli.main import app

EXPECTED_KINDS = {"nursery", "kindergarten", "preschool"}


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


def test_match_operation_declares_address_id_and_kind_parameters(openapi: dict[str, Any]) -> None:
    op = openapi["paths"]["/api/match"]["get"]
    params = {p["name"]: p for p in op.get("parameters", []) if p.get("in") == "query"}

    assert set(params.keys()) == {"address_id", "kind"}
    address_id = params["address_id"]
    assert address_id["required"] is True
    assert address_id["schema"]["type"] == "integer"
    assert address_id["schema"]["minimum"] == 1

    kind = params["kind"]
    assert kind["required"] is False
    assert _enum_values(openapi, kind["schema"]) == EXPECTED_KINDS


def _find_item_schema(openapi: dict[str, Any], shape_schema: dict[str, Any]) -> dict[str, Any]:
    """Walk the response schema to locate the array-of-items shape.

    The 200 response is now ``oneOf`` of a bare array and an envelope
    object whose ``results`` is an array — both arrays carry the same
    item shape. Either alternative is acceptable to extract from.
    """
    schema = _resolve_schema(openapi, shape_schema)
    if schema.get("type") == "array":
        return _resolve_schema(openapi, schema["items"])
    if schema.get("type") == "object" and "results" in schema.get("properties", {}):
        results = _resolve_schema(openapi, schema["properties"]["results"])
        return _resolve_schema(openapi, results["items"])
    for key in ("anyOf", "oneOf", "allOf"):
        for alt in schema.get(key, []):
            try:
                return _find_item_schema(openapi, alt)
            except AssertionError:
                continue
    raise AssertionError(f"could not find item schema in: {schema}")


def test_match_response_is_oneof_array_or_envelope(openapi: dict[str, Any]) -> None:
    op = openapi["paths"]["/api/match"]["get"]
    schema = op["responses"]["200"]["content"]["application/json"]["schema"]
    # Either the schema itself uses oneOf/anyOf, or it's already
    # the array alternative — the resolver tolerates both.
    found_array = False
    found_envelope = False

    def walk(node: dict[str, Any]) -> None:
        nonlocal found_array, found_envelope
        resolved = _resolve_schema(openapi, node)
        if resolved.get("type") == "array":
            found_array = True
        if (
            resolved.get("type") == "object"
            and "results" in resolved.get("properties", {})
            and "match_type" in resolved.get("properties", {})
        ):
            found_envelope = True
        for key in ("anyOf", "oneOf", "allOf"):
            for alt in resolved.get(key, []):
                walk(alt)

    walk(schema)
    assert found_array, "missing array alternative in /api/match 200 schema"
    assert found_envelope, "missing district_unknown envelope alternative"


def test_match_item_schema_carries_six_fields_including_match_type(
    openapi: dict[str, Any],
) -> None:
    op = openapi["paths"]["/api/match"]["get"]
    schema = op["responses"]["200"]["content"]["application/json"]["schema"]
    item_schema = _find_item_schema(openapi, schema)
    assert set(item_schema["properties"].keys()) == {
        "id",
        "external_id",
        "name",
        "kind",
        "source_url",
        "match_type",
        "has_infant_group",
    }
    assert "search_norm" not in item_schema["properties"]
    assert _enum_values(openapi, item_schema["properties"]["kind"]) == EXPECTED_KINDS
    assert _enum_values(openapi, item_schema["properties"]["match_type"]) == {
        "street",
        "district",
    }
    assert item_schema["properties"]["has_infant_group"]["type"] == "boolean"
