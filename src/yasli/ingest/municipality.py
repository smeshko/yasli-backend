"""Varna municipality boundary — the hard reject for institution coordinates.

``in_varna_municipality(lat, lon)`` is a pure-Python point-in-polygon test
(ray casting) over the committed ``data/varna_municipality.geojson``: OSM
relation 1404291, simplified to ~100 m. See ``data/varna_municipality.README.md``
for provenance and how the eight reference settlements were checked.

The polygon is only one of the guards. It catches a pin in another
municipality — Игнатиево and Аксаково, two of the three measured geocoder
failures — but it cannot catch a pin in the **wrong village inside** the
municipality. Константиново is exactly that case: it belongs to Varna
municipality, so a pin there for a кв. Виница address passes this check. The
seed script's settlement-agreement rule and the human review cover that
class; do not treat "inside the polygon" as proof the pin is right.

The boundary path is anchored to the package with ``Path(__file__)``, never
the working directory: the loader CLI runs from a Railway exec shell whose
``WORKDIR`` is ``/app`` and from checkouts, and the CLI tests run from a temp
cwd. The file is loaded lazily on the first call, so importing this module
never touches the disk.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
MUNICIPALITY_GEOJSON = REPO_ROOT / "data" / "varna_municipality.geojson"

Ring = list[tuple[float, float]]


@lru_cache(maxsize=1)
def municipality_geojson() -> dict[str, Any]:
    """The committed boundary as a GeoJSON ``Feature`` (a plain dict)."""
    with MUNICIPALITY_GEOJSON.open(encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache(maxsize=1)
def _rings() -> list[Ring]:
    geometry = municipality_geojson()["geometry"]
    if geometry["type"] != "Polygon":
        raise ValueError(f"expected a Polygon, got {geometry['type']}")
    return [[(float(x), float(y)) for x, y in ring] for ring in geometry["coordinates"]]


def _point_in_ring(ring: Ring, lat: float, lon: float) -> bool:
    """Even–odd ray casting; GeoJSON rings are ``[lon, lat]`` pairs."""
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > lat) != (yj > lat):
            x_at_lat = (xj - xi) * (lat - yi) / (yj - yi) + xi
            if lon < x_at_lat:
                inside = not inside
        j = i
    return inside


def in_varna_municipality(lat: float, lon: float) -> bool:
    """True when ``(lat, lon)`` falls inside the municipality polygon.

    The first ring is the outer boundary; any further rings are holes.
    """
    outer, *holes = _rings()
    if not _point_in_ring(outer, lat, lon):
        return False
    return not any(_point_in_ring(hole, lat, lon) for hole in holes)
