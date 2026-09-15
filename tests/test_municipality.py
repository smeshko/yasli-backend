"""The committed Varna municipality polygon and the pure-Python containment
check the locations parser uses as its hard reject.

The eight reference points are OSM ``place`` nodes (fetched 2026-09-15):
the city, the five villages in ``yasli.geo.settlements`` — which must be
inside — and the two towns in община Аксаково that the research measured
as confidently wrong geocoder hits — which must be outside.
"""

from __future__ import annotations

import os

import pytest

from yasli.geo.settlements import VARNA_SETTLEMENTS
from yasli.ingest.municipality import (
    MUNICIPALITY_GEOJSON,
    in_varna_municipality,
    municipality_geojson,
)

INSIDE = {
    "Варна": (43.207387, 27.916665),
    "Каменар": (43.248526, 27.908515),
    "Тополи": (43.216413, 27.821202),
    "Звездица": (43.155090, 27.836370),
    "Константиново": (43.161943, 27.782844),
    "Казашко": (43.197852, 27.821862),
}

OUTSIDE = {
    "Игнатиево": (43.249555, 27.774731),
    "Аксаково": (43.258626, 27.817361),
    "София": (42.697708, 23.321868),
}


def test_reference_points_cover_every_settlement_in_geo_settlements() -> None:
    names = {s.name.split(".", 1)[1].casefold() for s in VARNA_SETTLEMENTS}
    assert names == {name.casefold() for name in INSIDE}


@pytest.mark.parametrize("name", sorted(INSIDE))
def test_inside(name: str) -> None:
    assert in_varna_municipality(*INSIDE[name]), name


@pytest.mark.parametrize("name", sorted(OUTSIDE))
def test_outside(name: str) -> None:
    assert not in_varna_municipality(*OUTSIDE[name]), name


def test_polygon_is_committed_and_anchored_to_the_package(tmp_path, monkeypatch) -> None:
    assert MUNICIPALITY_GEOJSON.exists()
    assert MUNICIPALITY_GEOJSON.name == "varna_municipality.geojson"
    assert MUNICIPALITY_GEOJSON.parent.name == "data"
    monkeypatch.chdir(tmp_path)
    assert os.getcwd() == str(tmp_path)
    assert in_varna_municipality(*INSIDE["Варна"])
    assert not in_varna_municipality(*OUTSIDE["Аксаково"])


def test_geojson_shape() -> None:
    feature = municipality_geojson()
    assert feature["type"] == "Feature"
    assert feature["geometry"]["type"] == "Polygon"
    assert feature["properties"]["osm"] == "relation/1404291"
    ring = feature["geometry"]["coordinates"][0]
    assert ring[0] == ring[-1]
    assert 100 <= len(ring) <= 400


def test_bounding_box_matches_the_research() -> None:
    ring = municipality_geojson()["geometry"]["coordinates"][0]
    lons = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    assert 43.09 < min(lats) < 43.11
    assert 43.30 < max(lats) < 43.32
    assert 27.73 < min(lons) < 27.75
    assert 28.05 < max(lons) < 28.07
