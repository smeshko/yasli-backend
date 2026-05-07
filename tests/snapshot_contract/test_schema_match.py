"""Drift test: the vendored `Snapshot` Pydantic models must produce a JSON
Schema byte-equivalent (after canonical JSON formatting) to the scraper's
committed `schemas/snapshot.v1.schema.json`.

The fixture in `fixtures/snapshot.v1.schema.json` is a manually synced copy
of `yasli/scraper/schemas/snapshot.v1.schema.json`. When `schema_version`
bumps, both repos update together and this fixture is replaced with the
freshly regenerated schema. If you see this test fail, that's a contract
drift signal — fix the vendored models in
`src/yasli/snapshot_contract/models.py` (or update the fixture) before
shipping.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yasli.snapshot_contract import Snapshot

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "snapshot.v1.schema.json"


def _canonical(obj: object) -> str:
    """Sort keys + compact separators so byte comparison is meaningful."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def test_vendored_models_match_canonical_scraper_schema() -> None:
    if not FIXTURE_PATH.exists():
        pytest.skip(
            f"Fixture {FIXTURE_PATH} is missing — copy "
            "yasli/scraper/schemas/snapshot.v1.schema.json into "
            "tests/snapshot_contract/fixtures/ to run this drift test."
        )

    expected = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    actual = Snapshot.model_json_schema()

    assert _canonical(actual) == _canonical(expected), (
        "Vendored snapshot_contract models drifted from the scraper's "
        "snapshot.v1.schema.json. Update src/yasli/snapshot_contract/models.py "
        "or refresh the fixture, but never both at once without bumping "
        "schema_version."
    )
