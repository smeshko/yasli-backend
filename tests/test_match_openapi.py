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


def test_match_response_schema_has_exactly_five_fields(openapi: dict[str, Any]) -> None:
    op = openapi["paths"]["/api/match"]["get"]
    schema_ref = op["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema_ref["type"] == "array"
    item_schema = _resolve_schema(openapi, schema_ref["items"])

    assert set(item_schema["properties"].keys()) == {
        "id",
        "external_id",
        "name",
        "kind",
        "source_url",
    }
    assert "search_norm" not in item_schema["properties"]
    assert _enum_values(openapi, item_schema["properties"]["kind"]) == EXPECTED_KINDS
