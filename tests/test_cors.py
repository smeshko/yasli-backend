"""CORS configuration for browser clients."""

from __future__ import annotations

from fastapi.testclient import TestClient

from yasli.main import create_app


def test_configured_cors_origin_is_allowed() -> None:
    client = TestClient(create_app(cors_allowed_origins=("http://localhost:4321",)))

    response = client.get("/openapi.json", headers={"Origin": "http://localhost:4321"})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:4321"
    assert response.headers["access-control-expose-headers"] == "ETag"


def test_unconfigured_cors_origin_is_not_allowed() -> None:
    client = TestClient(create_app(cors_allowed_origins=("http://localhost:4321",)))

    response = client.get("/openapi.json", headers={"Origin": "http://localhost:4322"})

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers
