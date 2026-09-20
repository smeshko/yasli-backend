"""Shape of the committed seed artifacts under ``data/seed/``.

These are the files `python -m yasli.seed` loads instead of reaching for
R2, so they are the artifact of record for what a local database contains.
A truncated download, a hand edit or a half-finished `freeze` has to fail
here rather than seed quietly.
"""

from __future__ import annotations

import gzip
import json

import pytest

from yasli.ingest.pipeline import DEFAULT_SNAPSHOT, _validate_snapshot
from yasli.snapshot_contract import Snapshot


@pytest.fixture(scope="module")
def snapshot() -> Snapshot:
    return _validate_snapshot(gzip.decompress(DEFAULT_SNAPSHOT.read_bytes()))


def test_committed_snapshot_exists_and_is_gzipped() -> None:
    assert DEFAULT_SNAPSHOT.is_file()
    assert DEFAULT_SNAPSHOT.name == "snapshot.json.gz"
    payload = json.loads(gzip.decompress(DEFAULT_SNAPSHOT.read_bytes()))
    assert isinstance(payload, dict)


def test_committed_snapshot_is_schema_v2(snapshot: Snapshot) -> None:
    """`_validate_snapshot` is the only version check; reuse it."""
    payload = json.loads(gzip.decompress(DEFAULT_SNAPSHOT.read_bytes()))
    assert payload["schema_version"] == 2
    assert snapshot.scraped_at is not None


def test_committed_snapshot_holds_the_expected_institutions(
    snapshot: Snapshot,
) -> None:
    """77 institutions — the count a real R2 ingest produces."""
    assert len(snapshot.institutions) == 77
    kinds = {inst.kind for inst in snapshot.institutions}
    assert kinds == {"kindergarten", "nursery", "preschool"}


def test_committed_snapshot_keys_are_unique(snapshot: Snapshot) -> None:
    keys = [(inst.kind, inst.external_id) for inst in snapshot.institutions]
    assert len(keys) == len(set(keys))
