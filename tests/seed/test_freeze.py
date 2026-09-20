"""`yasli.seed.freeze` — regenerating the committed artifacts safely.

Every test writes into a tmp_path pair rather than `data/seed/`, so a
failing test can never leave the repository's artifacts mismatched. The
properties under test are the ones that cost data if they lapse: an
unchanged snapshot produces an unchanged file, a wrong database cannot
blank or shrink the fixture, and an overlapping pair publishes neither
file.
"""

from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from yasli.models import Base, Institution
from yasli.seed import freeze

SNAPSHOT_KEYS = [("nursery", "1"), ("kindergarten", "46")]
LEGACY_KEYS = [("nursery", "39"), ("nursery", "47")]


def _snapshot_payload(keys: list[tuple[str, str]]) -> bytes:
    return json.dumps(
        {
            "schema_version": 2,
            "city": "varna",
            "scraped_at": "2026-09-19T07:01:51Z",
            "institutions": [
                {
                    "kind": kind,
                    "external_id": external_id,
                    "name": f"{kind} {external_id}",
                    "source_url": f"https://example.invalid/{external_id}",
                }
                for kind, external_id in keys
            ],
        }
    ).encode("utf-8")


def _legacy_rows(keys: list[tuple[str, str]]) -> list[dict[str, Any]]:
    return [
        {
            "kind": kind,
            "external_id": external_id,
            "name": f'ДГ№{external_id} "…"/ с яслена група/',
            "source_url": f"https://dg.uslugi.io/{external_id}.html",
            "address": None,
            "district_code": None,
            "has_infant_group": False,
            "last_seen_at": "2026-05-10T01:02:26Z",
        }
        for kind, external_id in keys
    ]


@pytest.fixture
def artifacts(tmp_path: Path) -> tuple[Path, Path]:
    """A committed pair standing in for `data/seed/`."""
    snapshot = tmp_path / "snapshot.json.gz"
    legacy = tmp_path / "legacy_institutions.json"
    snapshot.write_bytes(freeze.compress(_snapshot_payload(SNAPSHOT_KEYS)))
    legacy.write_bytes(freeze.render_legacy(_legacy_rows(LEGACY_KEYS)))
    return snapshot, legacy


@pytest.fixture
def db() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def _populate(session: Session, keys: list[tuple[str, str]]) -> None:
    for index, (kind, external_id) in enumerate(keys, start=1):
        session.add(
            Institution(
                id=index,
                external_id=external_id,
                name=f'ДГ№{external_id} "…"/ с яслена група/',
                kind=kind,
                source_url=f"https://dg.uslugi.io/{external_id}.html",
                district_code=None,
                has_infant_group=False,
                last_seen_at=datetime(2026, 5, 10, 1, 2, 26, tzinfo=UTC),
            )
        )
    session.flush()



# --- determinism -----------------------------------------------------------


def test_compress_is_deterministic() -> None:
    payload = _snapshot_payload(SNAPSHOT_KEYS)
    assert freeze.compress(payload) == freeze.compress(payload)


def test_compress_embeds_no_mtime() -> None:
    """Byte 4..8 of a gzip header is the mtime; it must be zero."""
    blob = freeze.compress(b"{}")
    assert blob[4:8] == b"\x00\x00\x00\x00"


def test_compress_round_trips() -> None:
    payload = _snapshot_payload(SNAPSHOT_KEYS)
    assert gzip.decompress(freeze.compress(payload)) == payload


# --- the legacy derivation -------------------------------------------------


def test_derive_returns_rows_absent_from_the_snapshot(db: Session) -> None:
    _populate(db, SNAPSHOT_KEYS + LEGACY_KEYS)
    derived = freeze.derive_legacy_rows(db, _snapshot_payload(SNAPSHOT_KEYS))
    assert [(r["kind"], r["external_id"]) for r in derived] == LEGACY_KEYS


def test_derive_keeps_a_null_district_code(db: Session) -> None:
    """Production holds none for these rows; the fixture copies that."""
    _populate(db, LEGACY_KEYS)
    derived = freeze.derive_legacy_rows(db, _snapshot_payload(SNAPSHOT_KEYS))
    assert {r["district_code"] for r in derived} == {None}


def test_derive_aborts_on_an_out_of_range_district_code() -> None:
    """Defence in depth: `ck_institutions_district_code` should make this
    unreachable through a real database, so the guard is driven directly.
    Without it, a schema change could quietly emit a fixture the loader
    then refuses to parse."""

    class _Row:
        kind, external_id = "nursery", "39"
        name = "ДГ№6"
        source_url = "https://dg.uslugi.io/39.html"
        address = None
        district_code = "09"
        has_infant_group = False
        last_seen_at = datetime(2026, 5, 10, tzinfo=UTC)

    class _Session:
        def execute(self, *args: object, **kwargs: object) -> Any:
            class _Result:
                def all(self) -> list[Any]:
                    return [_Row()]

            return _Result()

    with pytest.raises(freeze.FreezeError, match="outside 01-05"):
        freeze.derive_legacy_rows(_Session(), _snapshot_payload(SNAPSHOT_KEYS))  # type: ignore[arg-type]


def test_derive_accepts_a_real_district_code(db: Session) -> None:
    _populate(db, LEGACY_KEYS)
    db.execute(
        Institution.__table__.update().values(district_code="03")  # type: ignore[attr-defined]
    )
    db.flush()
    derived = freeze.derive_legacy_rows(db, _snapshot_payload(SNAPSHOT_KEYS))
    assert {r["district_code"] for r in derived} == {"03"}


# --- the safety rules ------------------------------------------------------


def test_an_empty_diff_leaves_the_fixture_untouched(
    artifacts: tuple[Path, Path], db: Session
) -> None:
    """A maintainer pointed at their own local DB cannot blank the fixture."""
    snapshot, legacy = artifacts
    before = legacy.read_bytes()
    _populate(db, SNAPSHOT_KEYS)  # nothing beyond the snapshot

    report = freeze.run_freeze(
        legacy_only=True,
        snapshot_path=snapshot,
        legacy_path=legacy,
        session_factory=lambda: db,
    )

    assert legacy.read_bytes() == before
    assert not report.legacy_written
    assert any("left untouched" in note for note in report.notes)


def test_a_shrinking_fixture_is_refused(
    artifacts: tuple[Path, Path], db: Session
) -> None:
    snapshot, legacy = artifacts
    before = legacy.read_bytes()
    _populate(db, SNAPSHOT_KEYS + LEGACY_KEYS[:1])  # one row fewer

    with pytest.raises(freeze.FreezeError, match="nursery/47"):
        freeze.run_freeze(
            legacy_only=True,
            snapshot_path=snapshot,
            legacy_path=legacy,
            session_factory=lambda: db,
        )
    assert legacy.read_bytes() == before


def test_a_shrinking_fixture_is_permitted_with_allow_shrink(
    artifacts: tuple[Path, Path], db: Session
) -> None:
    snapshot, legacy = artifacts
    _populate(db, SNAPSHOT_KEYS + LEGACY_KEYS[:1])

    report = freeze.run_freeze(
        legacy_only=True,
        allow_shrink=True,
        snapshot_path=snapshot,
        legacy_path=legacy,
        session_factory=lambda: db,
    )
    assert report.legacy_written
    assert report.legacy_rows == 1


def test_overlapping_keys_publish_neither_file(
    artifacts: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """--snapshot-only is where this check does its real work."""
    snapshot, legacy = artifacts
    snapshot_before = snapshot.read_bytes()
    legacy_before = legacy.read_bytes()

    # A newly fetched snapshot that has promoted one of the fixture's rows.
    promoted = _snapshot_payload(SNAPSHOT_KEYS + LEGACY_KEYS[:1])
    monkeypatch.setattr(freeze, "fetch_snapshot", lambda client=None: promoted)

    with pytest.raises(freeze.FreezeOverlapError, match="nursery/39"):
        freeze.run_freeze(
            snapshot_only=True,
            snapshot_path=snapshot,
            legacy_path=legacy,
        )
    assert snapshot.read_bytes() == snapshot_before
    assert legacy.read_bytes() == legacy_before


def test_the_overlap_message_names_both_ways_out(
    artifacts: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot, legacy = artifacts
    monkeypatch.setattr(
        freeze,
        "fetch_snapshot",
        lambda client=None: _snapshot_payload(SNAPSHOT_KEYS + LEGACY_KEYS[:1]),
    )
    with pytest.raises(freeze.FreezeOverlapError) as exc:
        freeze.run_freeze(
            snapshot_only=True, snapshot_path=snapshot, legacy_path=legacy
        )
    message = str(exc.value)
    assert "full freeze" in message
    assert "drop those keys" in message


def test_a_failure_before_publish_leaves_both_files_unchanged(
    artifacts: tuple[Path, Path], db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot, legacy = artifacts
    snapshot_before = snapshot.read_bytes()
    legacy_before = legacy.read_bytes()

    def _boom(*args: object, **kwargs: object) -> list[dict[str, Any]]:
        raise freeze.FreezeError("derivation blew up")

    monkeypatch.setattr(freeze, "derive_legacy_rows", _boom)
    with pytest.raises(freeze.FreezeError, match="blew up"):
        freeze.run_freeze(
            legacy_only=True,
            snapshot_path=snapshot,
            legacy_path=legacy,
            session_factory=lambda: db,
        )

    assert snapshot.read_bytes() == snapshot_before
    assert legacy.read_bytes() == legacy_before


def test_a_failure_between_the_two_renames_is_reported_honestly(
    artifacts: tuple[Path, Path], db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The residual window D8 accepts: say so, never claim success."""
    snapshot, legacy = artifacts
    _populate(db, SNAPSHOT_KEYS + LEGACY_KEYS + [("nursery", "52")])

    calls: list[int] = []
    real_replace = freeze.os.replace

    def _flaky(src: object, dst: object) -> None:
        calls.append(1)
        if len(calls) == 1:
            real_replace(src, dst)  # type: ignore[arg-type]
            return
        raise OSError("disk went away")

    monkeypatch.setattr(freeze.os, "replace", _flaky)
    # Both files must change, or there is no second rename to interrupt:
    # a snapshot with an extra institution, and a fixture with an extra row.
    monkeypatch.setattr(
        freeze,
        "fetch_snapshot",
        lambda client=None: _snapshot_payload([*SNAPSHOT_KEYS, ("preschool", "7")]),
    )

    with pytest.raises(freeze.FreezePublishError) as exc:
        freeze.run_freeze(
            snapshot_path=snapshot,
            legacy_path=legacy,
            session_factory=lambda: db,
        )
    message = str(exc.value)
    assert "may now disagree" in message
    assert "git checkout -- data/seed/" in message


def test_no_temp_files_are_left_behind_on_failure(
    artifacts: tuple[Path, Path], db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot, legacy = artifacts
    before = set(snapshot.parent.iterdir())

    monkeypatch.setattr(
        freeze,
        "derive_legacy_rows",
        lambda *a, **k: (_ for _ in ()).throw(freeze.FreezeError("nope")),
    )
    with pytest.raises(freeze.FreezeError):
        freeze.run_freeze(
            legacy_only=True,
            snapshot_path=snapshot,
            legacy_path=legacy,
            session_factory=lambda: db,
        )
    assert set(snapshot.parent.iterdir()) == before


# --- dry run ---------------------------------------------------------------


def test_dry_run_writes_nothing(
    artifacts: tuple[Path, Path], db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot, legacy = artifacts
    snapshot_before = snapshot.read_bytes()
    legacy_before = legacy.read_bytes()
    _populate(db, SNAPSHOT_KEYS + LEGACY_KEYS + [("nursery", "52")])
    monkeypatch.setattr(
        freeze, "fetch_snapshot", lambda client=None: _snapshot_payload(SNAPSHOT_KEYS)
    )

    report = freeze.run_freeze(
        dry_run=True,
        snapshot_path=snapshot,
        legacy_path=legacy,
        session_factory=lambda: db,
    )

    assert report.dry_run
    assert report.legacy_written  # it *would* write
    assert snapshot.read_bytes() == snapshot_before
    assert legacy.read_bytes() == legacy_before


def test_dry_run_reports_no_drift_when_current(
    artifacts: tuple[Path, Path], db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot, legacy = artifacts
    _populate(db, SNAPSHOT_KEYS + LEGACY_KEYS)
    monkeypatch.setattr(
        freeze, "fetch_snapshot", lambda client=None: _snapshot_payload(SNAPSHOT_KEYS)
    )

    report = freeze.run_freeze(
        dry_run=True,
        snapshot_path=snapshot,
        legacy_path=legacy,
        session_factory=lambda: db,
    )
    assert not report.snapshot_written
    assert not report.legacy_written
    assert any("no drift" in note for note in report.notes)


# --- a full round trip -----------------------------------------------------


def test_freezing_an_unchanged_snapshot_produces_an_identical_file(
    artifacts: tuple[Path, Path], db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot, legacy = artifacts
    before = snapshot.read_bytes()
    _populate(db, SNAPSHOT_KEYS + LEGACY_KEYS)
    monkeypatch.setattr(
        freeze, "fetch_snapshot", lambda client=None: _snapshot_payload(SNAPSHOT_KEYS)
    )

    report = freeze.run_freeze(
        snapshot_path=snapshot,
        legacy_path=legacy,
        session_factory=lambda: db,
    )
    assert not report.snapshot_written
    assert snapshot.read_bytes() == before
