"""/api/health: 200 + healthy body, 503 + error body when the DB raises."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError

from yasli import db
from yasli.main import app


@pytest.fixture
def client() -> TestClient:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    db.set_engine(engine)
    return TestClient(app)


def test_health_returns_ok_when_db_reachable(client: TestClient) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "db": "ok"}


def test_health_returns_503_when_db_unreachable() -> None:
    # Point the engine at an invalid SQLite file path the driver will reject
    # on first execute.
    engine = create_engine("sqlite+pysqlite:////nonexistent/path/db.sqlite", future=True)
    db.set_engine(engine)
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.get("/api/health")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["db"] == "unreachable"
    assert "error" in body


def test_health_returns_503_via_broken_session() -> None:
    """Use a session whose execute() raises to verify the error path
    deterministically."""

    class _BrokenSession:
        def execute(self, *args, **kwargs):
            del args, kwargs
            raise OperationalError("SELECT 1", {}, Exception("boom"))

        def close(self) -> None:
            pass

    def _broken_get_db():
        s = _BrokenSession()
        try:
            yield s
        finally:
            s.close()

    from yasli.routes import health as health_module

    app.dependency_overrides[health_module.get_db] = _broken_get_db
    try:
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/health")
        assert resp.status_code == 503
        body = resp.json()
        assert body["status"] == "degraded"
        assert body["db"] == "unreachable"
        assert "error" in body
    finally:
        app.dependency_overrides.pop(health_module.get_db, None)
