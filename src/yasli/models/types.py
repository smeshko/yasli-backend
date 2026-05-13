"""Shared type aliases for ORM models.

`Kind` mirrors the closed value set of the `institutions.kind` column —
`nursery | kindergarten | preschool` — as locked by the s02 snapshot
contract. `DistrictCode` mirrors the closed value set of Varna's 5
administrative районs, used by both `institutions.district_code` (added by
revision `0004`) and `addresses.district_code` (added by revision `0005`).

Keeping these here (rather than next to the ORM classes) lets ingest and
the read endpoints import the aliases without pulling in the ORM classes.
"""

from __future__ import annotations

from typing import Literal

Kind = Literal["nursery", "kindergarten", "preschool"]

KIND_VALUES: tuple[str, ...] = ("nursery", "kindergarten", "preschool")

DistrictCode = Literal["01", "02", "03", "04", "05"]

DISTRICT_CODE_VALUES: tuple[str, ...] = ("01", "02", "03", "04", "05")

__all__ = [
    "Kind",
    "KIND_VALUES",
    "DistrictCode",
    "DISTRICT_CODE_VALUES",
]
