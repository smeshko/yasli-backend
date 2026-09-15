"""Shared type aliases for ORM models.

`Kind` mirrors the closed value set of the `institutions.kind` column —
`nursery | kindergarten | preschool` — as locked by the s02 snapshot
contract. `DistrictCode` mirrors the closed value set of Varna's 5
administrative районs, used by both `institutions.district_code` (added by
revision `0004`) and `addresses.district_code` (added by revision `0005`).
`LocalityType` mirrors the closed city/village set of `settlements`.
`LocationRole`, `LocationPrecision`, `LocationSource` and
`LocationVerification` mirror the closed value sets of the
`institution_locations` reference table (revision `0010`).

Keeping these here (rather than next to the ORM classes) lets ingest and
the read endpoints import the aliases without pulling in the ORM classes.
"""

from __future__ import annotations

from typing import Literal

Kind = Literal["nursery", "kindergarten", "preschool"]

KIND_VALUES: tuple[str, ...] = ("nursery", "kindergarten", "preschool")

DistrictCode = Literal["01", "02", "03", "04", "05"]

DISTRICT_CODE_VALUES: tuple[str, ...] = ("01", "02", "03", "04", "05")

LocalityType = Literal["city", "village"]

LOCALITY_TYPE_VALUES: tuple[str, ...] = ("city", "village")

LocationRole = Literal["main", "branch"]

ROLE_VALUES: tuple[str, ...] = ("main", "branch")

# ``street`` is deliberately absent: rank 26–27 geocodes are discarded by the
# seed script, so nothing can produce a street-level pin. ``approximate`` is a
# reviewer's hand-placed pin on a block rather than a building.
LocationPrecision = Literal["building", "approximate", "none"]

PRECISION_VALUES: tuple[str, ...] = ("building", "approximate", "none")

LocationSource = Literal["osm_poi", "nominatim", "manual"]

SOURCE_VALUES: tuple[str, ...] = ("osm_poi", "nominatim", "manual")

LocationVerification = Literal["auto", "human"]

VERIFICATION_VALUES: tuple[str, ...] = ("auto", "human")

__all__ = [
    "Kind",
    "KIND_VALUES",
    "DistrictCode",
    "DISTRICT_CODE_VALUES",
    "LocalityType",
    "LOCALITY_TYPE_VALUES",
    "LocationRole",
    "ROLE_VALUES",
    "LocationPrecision",
    "PRECISION_VALUES",
    "LocationSource",
    "SOURCE_VALUES",
    "LocationVerification",
    "VERIFICATION_VALUES",
]
