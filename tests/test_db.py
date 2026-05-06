"""`get_db` yields a session bound to the active engine and closes it."""

from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from yasli import db


def test_get_db_yields_and_closes_session(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    db.set_engine(engine)

    closed = []
    original_close = Session.close

    def _spy_close(self):
        closed.append(self)
        return original_close(self)

    monkeypatch.setattr(Session, "close", _spy_close)

    gen = db.get_db()
    session = next(gen)
    assert session.execute(text("SELECT 1")).scalar() == 1
    try:
        next(gen)
    except StopIteration:
        pass

    assert session in closed
