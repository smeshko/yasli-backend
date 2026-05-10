"""OpenAPI schema contract for /api/addresses."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from yasli.main import app


@pytest.fixture
def openapi() -> dict:
    return TestClient(app).get("/openapi.json").json()


def test_addresses_response_schema_has_exactly_five_fields(openapi: dict) -> None:
    op = openapi["paths"]["/api/addresses"]["get"]
    schema_ref = op["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema_ref["type"] == "array"
    item_ref = schema_ref["items"]["$ref"]
    name = item_ref.rsplit("/", 1)[-1]
    item_schema = openapi["components"]["schemas"][name]
    assert set(item_schema["properties"].keys()) == {
        "id",
        "street_id",
        "number_int",
        "number_suffix",
        "entrance",
    }


def test_addresses_operation_declares_no_query_parameters(openapi: dict) -> None:
    op = openapi["paths"]["/api/addresses"]["get"]
    params = op.get("parameters", [])
    query_params = [p for p in params if p.get("in") == "query"]
    assert query_params == []
