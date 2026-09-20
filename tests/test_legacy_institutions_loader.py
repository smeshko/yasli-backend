"""Parsing and CLI tests for the legacy-institutions fixture loader.

The loader is the only writer of the 18 `ДГ№X … / с яслена група/` rows
production has carried since before 2026-05-10 and that no current
snapshot creates. The parser rejects rather than skips, naming the row and
the field at fault; these tests pin that contract.

The upsert itself is exercised against a real Postgres in
`tests/ingest/test_legacy_institutions_load.py` — `institutions.id` is a
BigInteger serial, which SQLite cannot assign.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from yasli.ingest import legacy_institutions_loader as loader

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



# --- parsing ---------------------------------------------------------------


def test_parse_file_accepts_the_valid_shape(tmp_path: Path) -> None:
    rows = loader.parse_file(_write(tmp_path, [VALID_ROW]))
    assert len(rows) == 1
    assert rows[0]["external_id"] == "39"
    assert rows[0]["district_code"] is None
    assert rows[0]["last_seen_at"] == datetime(2026, 5, 10, 1, 2, 26, tzinfo=UTC)


def test_parse_file_rejects_a_missing_field_by_index(tmp_path: Path) -> None:
    bad = {k: v for k, v in VALID_ROW.items() if k != "district_code"}
    with pytest.raises(loader.LegacyFixtureError) as exc:
        loader.parse_file(_write(tmp_path, [VALID_ROW, bad]))
    assert "row 1" in str(exc.value)
    assert "district_code" in str(exc.value)


def test_parse_file_rejects_an_out_of_range_district_code(tmp_path: Path) -> None:
    bad = {**VALID_ROW, "district_code": "07"}
    with pytest.raises(loader.LegacyFixtureError, match="district_code"):
        loader.parse_file(_write(tmp_path, [bad]))


def test_parse_file_accepts_a_real_district_code(tmp_path: Path) -> None:
    rows = loader.parse_file(_write(tmp_path, [{**VALID_ROW, "district_code": "03"}]))
    assert rows[0]["district_code"] == "03"


def test_parse_file_rejects_an_unknown_kind(tmp_path: Path) -> None:
    bad = {**VALID_ROW, "kind": "creche"}
    with pytest.raises(loader.LegacyFixtureError, match="kind"):
        loader.parse_file(_write(tmp_path, [bad]))


def test_parse_file_rejects_an_unknown_field(tmp_path: Path) -> None:
    bad = {**VALID_ROW, "surprise": 1}
    with pytest.raises(loader.LegacyFixtureError, match="surprise"):
        loader.parse_file(_write(tmp_path, [bad]))


def test_parse_file_rejects_a_duplicate_key(tmp_path: Path) -> None:
    with pytest.raises(loader.LegacyFixtureError, match="duplicate"):
        loader.parse_file(_write(tmp_path, [VALID_ROW, dict(VALID_ROW)]))


def test_parse_file_rejects_a_non_list_document(tmp_path: Path) -> None:
    with pytest.raises(loader.LegacyFixtureError, match="list"):
        loader.parse_file(_write(tmp_path, {"rows": [VALID_ROW]}))


def test_parse_file_rejects_an_unparseable_timestamp(tmp_path: Path) -> None:
    bad = {**VALID_ROW, "last_seen_at": "the tenth of May"}
    with pytest.raises(loader.LegacyFixtureError, match="last_seen_at"):
        loader.parse_file(_write(tmp_path, [bad]))


# --- CLI -------------------------------------------------------------------


def test_cli_missing_file_exits_2(tmp_path: Path) -> None:
    assert loader.main([str(tmp_path / "nope.json")]) == 2


def test_cli_malformed_file_exits_3(tmp_path: Path) -> None:
    bad = {**VALID_ROW, "kind": "creche"}
    assert loader.main([str(_write(tmp_path, [bad]))]) == 3


def test_cli_dry_run_parses_without_a_database(tmp_path: Path) -> None:
    """--dry-run must not need a reachable Postgres."""
    assert loader.main([str(_write(tmp_path, [VALID_ROW])), "--dry-run"]) == 0
