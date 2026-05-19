"""CORS configuration for browser clients."""

from __future__ import annotations

from pathlib import Path

import pytest
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


def test_dev_environment_allows_empty_cors_origins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subproject = tmp_path / "backend"
    subproject.mkdir()
    monkeypatch.chdir(subproject)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)

    create_app()


def test_production_environment_rejects_empty_cors_origins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subproject = tmp_path / "backend"
    subproject.mkdir()
    monkeypatch.chdir(subproject)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)

    with pytest.raises(RuntimeError) as excinfo:
        create_app(cors_allowed_origins=())

    assert "CORS_ALLOWED_ORIGINS" in str(excinfo.value)
