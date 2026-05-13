"""Vendored copy of the v2 snapshot contract.

The canonical contract lives in `yasli/scraper` under the `snapshot-format`
capability (see `yasli_scraper.models`). The backend re-vendors the same
Pydantic models here so ingest can validate snapshots pulled from R2 without
introducing a cross-repo build dependency.

When `schema_version` bumps:

1. Update `yasli/scraper/src/yasli_scraper/models.py` and regenerate
   `yasli/scraper/schemas/snapshot.v2.schema.json`.
2. Mirror the model changes in `yasli/backend/src/yasli/snapshot_contract/models.py`.
3. Replace `yasli/backend/tests/snapshot_contract/fixtures/snapshot.v2.schema.json`
   with the freshly regenerated scraper schema. The drift test in
   `tests/snapshot_contract/test_schema_match.py` will fail until both sides
   agree byte-for-byte after canonical formatting.
"""

from __future__ import annotations

from yasli.snapshot_contract.models import AddressEntry, Institution, Snapshot

__all__ = ["AddressEntry", "Institution", "Snapshot"]
