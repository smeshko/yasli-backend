# `varna_municipality.geojson`

The administrative boundary of Varna municipality (община Варна), used by
`yasli.ingest.municipality.in_varna_municipality` as the parser's hard
reject for `data/institution_locations.csv`: a coordinate outside this
polygon never reaches the database.

| | |
| --- | --- |
| Source | OpenStreetMap relation [1404291](https://www.openstreetmap.org/relation/1404291), © OpenStreetMap contributors, ODbL 1.0 |
| Tags at fetch | `boundary=administrative`, `admin_level=5`, `border_type=municipality`, `name=Варна`, `wikidata=Q748965` |
| Fetched | 2026-09-15, assembled polygon via Nominatim `lookup?osm_ids=R1404291&polygon_geojson=1` |
| Simplification | Douglas–Peucker, 100 m tolerance in a local equirectangular projection; 2131 → 167 vertices, coordinates rounded to 6 decimals |
| Bounding box | 43.1002–43.3102 N, 27.7365–28.0562 E |

## Why relation 1404291

The plan expected the municipality to be tagged `admin_level=6`; in OSM's
Bulgarian scheme relation 1404291 is `admin_level=5` with an explicit
`border_type=municipality`. What matters is the shape, which was checked
against the place nodes of every settlement the polygon has to separate
(`tests/test_municipality.py` pins the same points):

- inside: Варна, and the five villages in `yasli.geo.settlements` —
  Каменар, Тополи, Звездица, Константиново, Казашко
- outside: Игнатиево and Аксаково (община Аксаково), the two measured
  geocoder failures a bounding box could not separate from the villages

Both the raw and the simplified polygon classify all eight points the same
way. The polygon is only one guard: Константиново is *inside* the
municipality, so a pin in the wrong village is caught by the seed script's
settlement-agreement rule and by the review, not here.

## Refreshing

Municipal boundaries change roughly never. If it has to be redone: fetch the
relation through the Nominatim lookup above, simplify at 100 m, and re-run
`tests/test_municipality.py`. Simplifying at 100 m can misclassify a point
within ~100 m of the border; no institution is that close to it, and if one
ever is, the parser rejects it and a person looks, which is the safe
direction.
