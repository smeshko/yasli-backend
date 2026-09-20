"""Where ingest reads its snapshot from: R2, or a local file.

`_fetch_snapshot_bytes()` is the single place the snapshot enters the
pipeline. These tests pin both of its branches — that a path bypasses R2
entirely, that `.gz` and plain `.json` are equivalent, and that an
unusable file surfaces as a named `SnapshotFileError` rather than an
`OSError` or a `gzip` traceback.
"""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest

from yasli.ingest import pipeline

FIXTURE = Path(__file__).parent / "fixtures" / "snapshot_v2_minimal.json"


def _gzipped(tmp_path: Path, payload: bytes, name: str = "snapshot.json.gz") -> Path:
    path = tmp_path / name
    path.write_bytes(gzip.compress(payload, 9))
    return path


def test_plain_json_path_returns_file_bytes() -> None:
    assert pipeline._fetch_snapshot_bytes(None, snapshot_path=FIXTURE) == (
        FIXTURE.read_bytes()
    )


def test_gzipped_path_is_transparently_decompressed(tmp_path: Path) -> None:
    archive = _gzipped(tmp_path, FIXTURE.read_bytes())
    assert pipeline._fetch_snapshot_bytes(None, snapshot_path=archive) == (
        FIXTURE.read_bytes()
    )


def test_gz_and_plain_json_validate_to_equal_snapshots(tmp_path: Path) -> None:
    archive = _gzipped(tmp_path, FIXTURE.read_bytes())
    from_plain = pipeline._validate_snapshot(
        pipeline._fetch_snapshot_bytes(None, snapshot_path=FIXTURE)
    )
    from_gz = pipeline._validate_snapshot(
        pipeline._fetch_snapshot_bytes(None, snapshot_path=archive)
    )
    assert from_plain == from_gz


def test_path_branch_never_touches_r2(monkeypatch: pytest.MonkeyPatch) -> None:
    """A path-based run must not reach R2, even with a client in hand."""

    def _boom(*args: object, **kwargs: object) -> bytes:
        raise AssertionError("r2.get_object must not be called for a file path")

    monkeypatch.setattr(pipeline.r2, "get_object", _boom)
    assert pipeline._fetch_snapshot_bytes(None, snapshot_path=FIXTURE)


def test_missing_file_raises_snapshot_file_error(tmp_path: Path) -> None:
    missing = tmp_path / "nope.json.gz"
    with pytest.raises(pipeline.SnapshotFileError, match=str(missing)):
        pipeline._fetch_snapshot_bytes(None, snapshot_path=missing)


def test_corrupt_gzip_raises_snapshot_file_error(tmp_path: Path) -> None:
    corrupt = tmp_path / "snapshot.json.gz"
    corrupt.write_bytes(b"this is not gzip")
    with pytest.raises(pipeline.SnapshotFileError, match="not a readable gzip"):
        pipeline._fetch_snapshot_bytes(None, snapshot_path=corrupt)


def test_unreadable_file_raises_snapshot_file_error(tmp_path: Path) -> None:
    """A directory stands in for any path that exists but cannot be read."""
    with pytest.raises(pipeline.SnapshotFileError, match=str(tmp_path)):
        pipeline._fetch_snapshot_bytes(None, snapshot_path=tmp_path)


def test_no_path_still_reads_r2(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no path the R2 branch is unchanged: one get_object on LATEST_KEY."""
    calls: list[tuple[str, object]] = []

    def _fake_get_object(key: str, client: object = None) -> bytes:
        calls.append((key, client))
        return b"{}"

    monkeypatch.setattr(pipeline.r2, "get_object", _fake_get_object)
    assert pipeline._fetch_snapshot_bytes(None) == b"{}"
    assert calls == [(pipeline.LATEST_KEY, None)]
