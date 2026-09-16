"""Shape of the committed institution locations dataset.

``data/institution_locations.csv`` and its provenance file are the artifact
of record for phase 1.2; this is the permanent guard that a hand edit or a
bad seed re-run cannot break them. The parser already enforces the per-row
rules (polygon, ``auto`` shape, provenance cross-check); this test pins the
counts and the cases the plan calls out by name.
"""

from __future__ import annotations

from collections import Counter

import pytest

from scripts.institution_locations_state import haversine_m
from yasli.ingest.institution_locations_loader import (
    DEFAULT_CSV,
    DEFAULT_PROVENANCE,
    load_provenance,
    parse_file,
)

# OSM place nodes of the three settlements the measured geocoder failures
# pointed at (research §3.2). No pin may sit in any of them.
WRONG_SETTLEMENTS = {
    "Игнатиево": (43.249555, 27.774731),
    "Аксаково": (43.258626, 27.817361),
    "Константиново": (43.161943, 27.782844),
}


@pytest.fixture(scope="module")
def rows() -> list[dict]:
    return list(parse_file(DEFAULT_CSV, provenance_path=DEFAULT_PROVENANCE))


@pytest.fixture(scope="module")
def provenance() -> dict:
    return load_provenance(DEFAULT_PROVENANCE)


def test_committed_files_exist() -> None:
    assert DEFAULT_CSV.exists()
    assert DEFAULT_PROVENANCE.exists()


def test_row_counts(rows) -> None:
    by_role = Counter(r["role"] for r in rows)
    assert by_role["main"] == 77
    # 17 branch rows: the free-places table on 2026-09-15 listed 17 филиал
    # rows across 10 kindergartens (the research measured 15 on 2026-08-17).
    assert by_role["branch"] == 17
    assert len(rows) == 94


def test_exactly_one_main_per_institution(rows) -> None:
    mains = Counter((r["kind"], r["external_id"]) for r in rows if r["role"] == "main")
    assert all(count == 1 for count in mains.values())
    assert len(mains) == 77
    assert Counter(k for k, _ in mains) == {"kindergarten": 53, "nursery": 12, "preschool": 12}


def test_every_main_row_has_a_pin(rows) -> None:
    unresolved = [r["address"] for r in rows if r["role"] == "main" and r["lat"] is None]
    assert unresolved == []


def test_every_row_records_precision_source_and_verification(rows) -> None:
    for r in rows:
        assert r["precision"] in ("building", "approximate", "none")
        assert r["source"] in ("osm_poi", "nominatim", "manual")
        assert r["verification"] in ("auto", "human")
        assert r["verified_at"] is not None


def test_auto_rows_are_unique_poi_matches_on_main_buildings(rows, provenance) -> None:
    auto = [r for r in rows if r["verification"] == "auto"]
    assert auto, "expected some auto-accepted rows"
    for r in auto:
        assert (r["source"], r["role"], r["precision"]) == ("osm_poi", "main", "building")
    assert len(provenance) == len(auto)
    assert set(provenance) == {f"{r['kind']}/{r['external_id']}" for r in auto}


def test_name_only_branches_are_present_with_their_label(rows) -> None:
    name_only = {(r["external_id"], r["label"]) for r in rows if r["role"] == "branch" and not r["address"]}
    assert name_only == {("50", "Жирафче"), ("50", "Другарче"), ("51", "Бисерче")}


def test_dg13_mir_has_one_main_and_four_branches_on_different_buildings(rows) -> None:
    mir = [r for r in rows if (r["kind"], r["external_id"]) == ("kindergarten", "46")]
    assert Counter(r["role"] for r in mir) == {"main": 1, "branch": 4}
    main = next(r for r in mir if r["role"] == "main")
    branch_1a = next(r for r in mir if "1А" in r["address"])
    assert main["lat"] is not None and branch_1a["lat"] is not None
    # Same street, different building: the research §1.3 near-miss.
    assert haversine_m(float(main["lat"]), float(main["lon"]),
                       float(branch_1a["lat"]), float(branch_1a["lon"])) > 20


@pytest.mark.parametrize(
    "address_fragment",
    ['Чаталджа" 111', 'Лазур" №2', 'Варненчик" до блок 20'],
)
def test_measured_geocoder_failures_are_pinned_in_varna(rows, address_fragment) -> None:
    row = next(r for r in rows if r["role"] == "main" and address_fragment in r["address"])
    assert row["lat"] is not None
    for name, (lat, lon) in WRONG_SETTLEMENTS.items():
        assert haversine_m(float(row["lat"]), float(row["lon"]), lat, lon) > 2000, name
