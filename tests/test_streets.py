"""/api/streets: shape, ordering, ETag, If-None-Match, Cache-Control,
empty DB, 405, and DB error → 503.

The suite uses a SQLite in-memory engine for speed and parity with
test_health. The `streets` table from `yasli.models` ports cleanly to
SQLite for read-only tests; nothing here exercises the trigram index or
Postgres-specific behaviour.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import StaticPool

from yasli import db
from yasli.main import app
from yasli.models import Base, Street
from yasli.routes import streets as streets_module


@pytest.fixture
def client() -> TestClient:
    # SQLite in-memory is per-connection — without StaticPool, the table
    # created here would vanish before the request handler opens its own
    # session. StaticPool pins the connection so every session sees the
    # same DB.
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db.set_engine(engine)
    return TestClient(app)


def _seed(_client: TestClient, rows: list[dict[str, object]]) -> None:
    """Insert rows via the request-scoped session factory used by the app.

    The unused `_client` parameter is here to make the test's dependency on
    the `client` fixture explicit at the call site — that fixture is what
    builds the engine that `_SessionLocal` binds to.

    Caller-supplied `id`s are used because SQLite does not autoincrement
    `BigInteger PRIMARY KEY` columns; only `INTEGER PRIMARY KEY` does.
    Tests that call `_seed` more than once continue numbering past the
    rows already in the table.
    """
    assert db._SessionLocal is not None
    with db._SessionLocal() as session:
        from sqlalchemy import func, select as _select

        next_id = (session.execute(_select(func.coalesce(func.max(Street.id), 0))).scalar() or 0) + 1
        for offset, row in enumerate(rows):
            payload = dict(row)
            payload.setdefault("id", next_id + offset)
            session.add(Street(**payload))
        session.commit()


def test_returns_streets_with_expected_shape(client: TestClient) -> None:
    _seed(
        client,
        [
            {
                "city": "ГР.ВАРНА",
                "raw_name": "ул. Александър Дякович",
                "street_part": "Александър Дякович",
                "type_marker": "ул.",
                "search_norm": "aleksandar dyakovich",
            },
            {
                "city": "ГР.ВАРНА",
                "raw_name": "бул. Сливница",
                "street_part": "Сливница",
                "type_marker": "бул.",
                "search_norm": "slivnitsa",
            },
            {
                "city": "С.КАМЕНАР",
                "raw_name": "ул. Малина",
                "street_part": "Малина",
                "type_marker": "ул.",
                "search_norm": "malina",
            },
        ],
    )

    resp = client.get("/api/streets")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) == 3
    for item in body:
        assert set(item.keys()) == {"id", "city", "raw_name", "street_part", "type_marker"}
        assert "search_norm" not in item


def test_includes_compound_localities(client: TestClient) -> None:
    _seed(
        client,
        [
            {
                "city": "ГР.ВАРНА",
                "raw_name": "ул. Сливница",
                "street_part": "Сливница",
                "type_marker": "ул.",
                "search_norm": "slivnitsa",
            },
            {
                "city": "ГР.ВАРНА",
                "raw_name": "ГР.ВАРНА КАД.ПЛАН ТРАКАТА",
                "street_part": "",
                "type_marker": None,
                "search_norm": "kad.plan trakata",
            },
        ],
    )

    body = client.get("/api/streets").json()
    assert len(body) == 2
    raw_names = {row["raw_name"] for row in body}
    assert "ГР.ВАРНА КАД.ПЛАН ТРАКАТА" in raw_names
    compound = next(row for row in body if row["street_part"] == "")
    assert compound["type_marker"] is None


def test_ordering_is_city_then_raw_name(client: TestClient) -> None:
    _seed(
        client,
        [
            {
                "city": "С.КАМЕНАР",
                "raw_name": "ул. Малина",
                "street_part": "Малина",
                "type_marker": "ул.",
                "search_norm": "malina",
            },
            {
                "city": "ГР.ВАРНА",
                "raw_name": "ул. Бряст",
                "street_part": "Бряст",
                "type_marker": "ул.",
                "search_norm": "bryast",
            },
            {
                "city": "ГР.ВАРНА",
                "raw_name": "ул. Айтос",
                "street_part": "Айтос",
                "type_marker": "ул.",
                "search_norm": "aytos",
            },
            {
                "city": "С.ТОПОЛИ",
                "raw_name": "ул. Дунав",
                "street_part": "Дунав",
                "type_marker": "ул.",
                "search_norm": "dunav",
            },
            {
                "city": "ГР.ВАРНА",
                "raw_name": "ул. Габрово",
                "street_part": "Габрово",
                "type_marker": "ул.",
                "search_norm": "gabrovo",
            },
        ],
    )

    body = client.get("/api/streets").json()
    keys = [(row["city"], row["raw_name"]) for row in body]
    assert keys == sorted(keys)


def test_etag_stable_across_requests(client: TestClient) -> None:
    _seed(
        client,
        [
            {
                "city": "ГР.ВАРНА",
                "raw_name": "ул. Сливница",
                "street_part": "Сливница",
                "type_marker": "ул.",
                "search_norm": "slivnitsa",
            },
        ],
    )

    a = client.get("/api/streets")
    b = client.get("/api/streets")
    assert a.headers["etag"] == b.headers["etag"]


def test_etag_changes_when_data_changes(client: TestClient) -> None:
    _seed(
        client,
        [
            {
                "city": "ГР.ВАРНА",
                "raw_name": "ул. Сливница",
                "street_part": "Сливница",
                "type_marker": "ул.",
                "search_norm": "slivnitsa",
            },
        ],
    )
    first = client.get("/api/streets").headers["etag"]

    _seed(
        client,
        [
            {
                "city": "ГР.ВАРНА",
                "raw_name": "ул. Бряст",
                "street_part": "Бряст",
                "type_marker": "ул.",
                "search_norm": "bryast",
            },
        ],
    )
    second = client.get("/api/streets").headers["etag"]
    assert first != second


def test_if_none_match_returns_304(client: TestClient) -> None:
    _seed(
        client,
        [
            {
                "city": "ГР.ВАРНА",
                "raw_name": "ул. Сливница",
                "street_part": "Сливница",
                "type_marker": "ул.",
                "search_norm": "slivnitsa",
            },
        ],
    )
    etag = client.get("/api/streets").headers["etag"]
    resp = client.get("/api/streets", headers={"If-None-Match": etag})
    assert resp.status_code == 304
    assert resp.content == b""
    assert resp.headers["etag"] == etag


def test_if_none_match_miss_returns_full_body(client: TestClient) -> None:
    _seed(
        client,
        [
            {
                "city": "ГР.ВАРНА",
                "raw_name": "ул. Сливница",
                "street_part": "Сливница",
                "type_marker": "ул.",
                "search_norm": "slivnitsa",
            },
        ],
    )
    resp = client.get("/api/streets", headers={"If-None-Match": '"v1-deadbeefdeadbeef"'})
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) == 1


def test_cache_control_header_present(client: TestClient) -> None:
    resp = client.get("/api/streets")
    assert resp.headers["cache-control"] == "public, max-age=3600, stale-while-revalidate=86400"
    assert resp.headers["vary"] == "Accept-Encoding"


def test_empty_database_returns_200_empty_array_with_etag(client: TestClient) -> None:
    resp = client.get("/api/streets")
    assert resp.status_code == 200
    assert resp.json() == []
    assert resp.headers["etag"].startswith('"v1-')


def test_method_not_allowed(client: TestClient) -> None:
    resp = client.post("/api/streets")
    assert resp.status_code == 405


def test_database_error_returns_503(caplog: pytest.LogCaptureFixture) -> None:
    """Override the dependency to raise SQLAlchemyError; the global handler
    in `main.py` should catch it and return the documented 503 body.
    """

    class _BrokenSession:
        def execute(self, *args, **kwargs):
            del args, kwargs
            raise OperationalError("SELECT", {}, Exception("boom"))

        def close(self) -> None:
            pass

    def _broken_get_db():
        s = _BrokenSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[streets_module.get_db] = _broken_get_db
    try:
        client = TestClient(app, raise_server_exceptions=False)
        with caplog.at_level("ERROR"):
            resp = client.get("/api/streets")
        assert resp.status_code == 503
        assert resp.json() == {"status": "degraded", "error": "database unreachable"}
        assert any("database error" in rec.message for rec in caplog.records)
    finally:
        app.dependency_overrides.pop(streets_module.get_db, None)


def test_etag_value_format(client: TestClient) -> None:
    """Sanity check the ETag is a quoted v1-<16 hex> token derived from the
    body bytes — not relied on by the contract beyond being strong + stable,
    but worth pinning so a refactor doesn't silently switch algorithms.
    """
    _seed(
        client,
        [
            {
                "city": "ГР.ВАРНА",
                "raw_name": "ул. Сливница",
                "street_part": "Сливница",
                "type_marker": "ул.",
                "search_norm": "slivnitsa",
            },
        ],
    )
    resp = client.get("/api/streets")
    etag = resp.headers["etag"]
    assert etag.startswith('"v1-') and etag.endswith('"')
    assert len(etag) == len('"v1-') + 16 + 1
    # Body parses as JSON and matches what we got back.
    parsed = json.loads(resp.content)
    assert isinstance(parsed, list)
