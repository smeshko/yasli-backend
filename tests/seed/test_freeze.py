"""`yasli.seed.freeze` — regenerating the committed snapshot safely.

Every test writes into a tmp_path rather than `data/seed/`, so a failing
test can never leave the repository's snapshot altered. The properties
under test are the ones that cost data if they lapse: an unchanged snapshot
produces an unchanged file, a dry run writes nothing, and a failed publish
leaves the committed file as it was.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from yasli.seed import freeze
from yasli.seed.__main__ import main

SNAPSHOT_KEYS = [("nursery", "1"), ("kindergarten", "46")]


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


@pytest.fixture
def snapshot(tmp_path: Path) -> Path:
    """A committed snapshot standing in for `data/seed/snapshot.json.gz`."""
    path = tmp_path / "snapshot.json.gz"
    path.write_bytes(freeze.compress(_snapshot_payload(SNAPSHOT_KEYS)))
    return path


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


# --- publishing ------------------------------------------------------------


def test_freezing_an_unchanged_snapshot_produces_an_identical_file(
    snapshot: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = snapshot.read_bytes()
    monkeypatch.setattr(
        freeze, "fetch_snapshot", lambda client=None: _snapshot_payload(SNAPSHOT_KEYS)
    )

    report = freeze.run_freeze(snapshot_path=snapshot)

    assert report.snapshot_written is False
    assert snapshot.read_bytes() == before


def test_a_changed_snapshot_is_written(
    snapshot: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    changed = _snapshot_payload([*SNAPSHOT_KEYS, ("preschool", "7")])
    monkeypatch.setattr(freeze, "fetch_snapshot", lambda client=None: changed)

    report = freeze.run_freeze(snapshot_path=snapshot)

    assert report.snapshot_written is True
    assert gzip.decompress(snapshot.read_bytes()) == changed


def test_dry_run_writes_nothing(
    snapshot: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = snapshot.read_bytes()
    monkeypatch.setattr(
        freeze,
        "fetch_snapshot",
        lambda client=None: _snapshot_payload([*SNAPSHOT_KEYS, ("preschool", "7")]),
    )

    report = freeze.run_freeze(dry_run=True, snapshot_path=snapshot)

    assert report.dry_run
    assert report.snapshot_written  # it *would* write
    assert snapshot.read_bytes() == before


def test_a_failed_publish_leaves_the_committed_snapshot_unchanged(
    snapshot: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = snapshot.read_bytes()
    entries = set(tmp_path.iterdir())
    staging_dirs: list[Path] = []

    def _boom(src: object, dst: object) -> None:
        staging_dirs.append(Path(str(src)).parent)
        raise OSError("disk went away")

    monkeypatch.setattr(freeze.os, "replace", _boom)
    monkeypatch.setattr(
        freeze,
        "fetch_snapshot",
        lambda client=None: _snapshot_payload([*SNAPSHOT_KEYS, ("preschool", "7")]),
    )

    with pytest.raises(freeze.FreezeError, match="disk went away"):
        freeze.run_freeze(snapshot_path=snapshot)

    assert snapshot.read_bytes() == before
    assert set(tmp_path.iterdir()) == entries
    assert staging_dirs and not staging_dirs[0].exists()


def test_the_legacy_only_flag_is_rejected(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["freeze", "--legacy-only"])
    assert exc.value.code == 2
