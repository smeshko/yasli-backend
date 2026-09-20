"""The legacy-institutions upsert, against a real Postgres.

Lives here rather than beside the parsing tests because
``institutions.id`` is a BigInteger serial, which SQLite cannot assign —
and because the property under test is precisely that the upsert touches
nothing outside the fixture, which is only meaningful on the real schema.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from yasli.ingest import legacy_institutions_loader as loader
from yasli.models import Institution

VALID_ROW: dict[str, object] = {
    "kind": "nursery",
    "external_id": "39",
    "name": 'ДГ№6 "Палечко"/ с яслена група/',
    "source_url": "https://dg.uslugi.io/lv/documents/infant/varna/rajon/39.html",
    "address": None,
    "district_code": None,
    "has_infant_group": False,
    "last_seen_at": "2026-05-10T01:02:26Z",
}


def _write(tmp_path: Path, rows: object) -> Path:
    path = tmp_path / "legacy_institutions.json"
    path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    return path


def _add_live(session: Session, external_id: str = "1") -> Institution:
    """A row standing in for one the snapshot owns."""
    inst = Institution(
        external_id=external_id,
        name="ДЯ № 1 (live)",
        kind="nursery",
        source_url="https://example.invalid/live",
        district_code="02",
        has_infant_group=True,
        last_seen_at=datetime(2026, 9, 19, tzinfo=UTC),
    )
    session.add(inst)
    session.flush()
    return inst


def test_load_inserts_the_rows(tmp_path: Path, session: Session) -> None:
    summary = loader.load(_write(tmp_path, [VALID_ROW]), session)
    session.commit()
    assert (summary.inserted, summary.updated) == (1, 0)
    stored = session.scalars(select(Institution)).all()
    assert [i.external_id for i in stored] == ["39"]
    assert stored[0].district_code is None


def test_load_is_idempotent(tmp_path: Path, session: Session) -> None:
    path = _write(tmp_path, [VALID_ROW])
    loader.load(path, session)
    session.commit()
    second = loader.load(path, session)
    session.commit()
    assert (second.inserted, second.updated, second.unchanged) == (0, 0, 1)
    assert session.query(Institution).count() == 1  # type: ignore[attr-defined]


def test_load_leaves_other_institutions_untouched(
    tmp_path: Path, session: Session
) -> None:
    live = _add_live(session)
    session.commit()
    before = (live.name, live.district_code, live.has_infant_group)

    loader.load(_write(tmp_path, [VALID_ROW]), session)
    session.commit()

    session.refresh(live)
    assert (live.name, live.district_code, live.has_infant_group) == before
    assert session.query(Institution).count() == 2  # type: ignore[attr-defined]


def test_load_refreshes_a_changed_legacy_row(
    tmp_path: Path, session: Session
) -> None:
    loader.load(_write(tmp_path, [VALID_ROW]), session)
    session.commit()
    summary = loader.load(
        _write(tmp_path, [{**VALID_ROW, "name": "ДГ№6 (renamed)"}]), session
    )
    session.commit()
    assert summary.updated == 1
    assert session.scalars(select(Institution)).one().name == "ДГ№6 (renamed)"


def test_load_writes_nothing_when_a_row_is_malformed(
    tmp_path: Path, session: Session
) -> None:
    bad = {**VALID_ROW, "external_id": "47", "kind": "creche"}
    with pytest.raises(loader.LegacyFixtureError):
        loader.load(_write(tmp_path, [VALID_ROW, bad]), session)
    session.rollback()
    assert session.query(Institution).count() == 0  # type: ignore[attr-defined]


def test_committed_fixture_takes_the_snapshot_count_to_95(
    session: Session,
) -> None:
    """77 snapshot rows + the fixture's 18, none of them overlapping."""
    from yasli.ingest import pipeline

    pipeline.run(snapshot_path=pipeline.DEFAULT_SNAPSHOT)
    before = session.query(Institution).count()  # type: ignore[attr-defined]
    assert before == 77

    summary = loader.load(loader.DEFAULT_PATH, session)
    session.commit()
    assert summary.inserted == 18
    assert session.query(Institution).count() == 95  # type: ignore[attr-defined]
