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
    _assert_match_parameters(openapi, "/api/match")


def _assert_match_parameters(openapi: dict[str, Any], path: str) -> None:
    op = openapi["paths"][path]["get"]
    params = {p["name"]: p for p in op.get("parameters", []) if p.get("in") == "query"}

    assert set(params.keys()) == {"address_id", "kind"}
    address_id = params["address_id"]
    assert address_id["required"] is True
    assert address_id["schema"]["type"] == "integer"
    assert address_id["schema"]["minimum"] == 1

    kind = params["kind"]
    assert kind["required"] is False
    assert _enum_values(openapi, kind["schema"]) == EXPECTED_KINDS


def test_match_response_is_stable_object_schema(openapi: dict[str, Any]) -> None:
    _assert_structured_response_schema(openapi, "/api/match")


def _assert_structured_response_schema(openapi: dict[str, Any], path: str) -> None:
    op = openapi["paths"][path]["get"]
    schema = op["responses"]["200"]["content"]["application/json"]["schema"]
    root = _resolve_schema(openapi, schema)

    assert root["type"] == "object"
    assert set(root["properties"].keys()) == {"address", "results"}
    assert "oneOf" not in root
    assert "anyOf" not in root

    address = _resolve_schema(openapi, root["properties"]["address"])
    assert set(address["properties"].keys()) == {
        "id",
        "district_code",
        "settlement",
    }

    results = _resolve_schema(openapi, root["properties"]["results"])
    assert results["type"] == "array"
    item = _resolve_schema(openapi, results["items"])
    assert set(item["properties"].keys()) == {
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
    assert _enum_values(openapi, item["properties"]["institution_kind"]) == EXPECTED_KINDS
    assert _enum_values(openapi, item["properties"]["reception_kind"]) == EXPECTED_KINDS
    assert _enum_values(openapi, item["properties"]["offering"]) == {
        "standard",
        "infant_group",
    }
    assert _enum_values(openapi, item["properties"]["match_basis"]) == {
        "address",
        "district",
    }
    assert {
        "institution_kind",
        "reception_kind",
        "offering",
        "source_url",
        "match_basis",
        "has_infant_group",
    }.issubset(set(item["required"]))


def test_match_response_schema_has_no_alternative_success_shapes(
    openapi: dict[str, Any],
) -> None:
    op = openapi["paths"]["/api/match"]["get"]
    schema = op["responses"]["200"]["content"]["application/json"]["schema"]
    root = _resolve_schema(openapi, schema)

    assert root.get("type") != "array"
    assert "oneOf" not in root
    assert "anyOf" not in root


def test_match_v2_path_is_absent_from_openapi(openapi: dict[str, Any]) -> None:
    assert "/api/match/v2" not in openapi["paths"]
