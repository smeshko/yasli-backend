"""OpenAPI schema contract for /api/streets.

Locks the wire shape so the frontend's `openapi-typescript` step in s10
generates a stable type. If you intentionally change the contract, bump
the `v1-` ETag prefix in the route at the same time.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from yasli.main import app


@pytest.fixture
def openapi() -> dict:
    return TestClient(app).get("/openapi.json").json()


def test_streets_response_schema_has_exactly_five_fields(openapi: dict) -> None:
    op = openapi["paths"]["/api/streets"]["get"]
    schema_ref = op["responses"]["200"]["content"]["application/json"]["schema"]
    # FastAPI emits `{ type: array, items: { $ref: "#/components/schemas/StreetOut" } }`
    assert schema_ref["type"] == "array"
    item_ref = schema_ref["items"]["$ref"]
    name = item_ref.rsplit("/", 1)[-1]
    item_schema = openapi["components"]["schemas"][name]
    assert set(item_schema["properties"].keys()) == {
        "id",
        "city",
        "raw_name",
        "street_part",
        "type_marker",
    }


def test_streets_response_schema_excludes_search_norm(openapi: dict) -> None:
    op = openapi["paths"]["/api/streets"]["get"]
    item_ref = op["responses"]["200"]["content"]["application/json"]["schema"]["items"]["$ref"]
    name = item_ref.rsplit("/", 1)[-1]
    item_schema = openapi["components"]["schemas"][name]
    assert "search_norm" not in item_schema["properties"]


def test_streets_operation_declares_no_query_parameters(openapi: dict) -> None:
    op = openapi["paths"]["/api/streets"]["get"]
    params = op.get("parameters", [])
    query_params = [p for p in params if p.get("in") == "query"]
    assert query_params == []
