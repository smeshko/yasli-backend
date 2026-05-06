"""Shared type aliases for ORM models.

`Kind` mirrors the closed value set of the `institutions.kind` column —
`nursery | kindergarten | preschool` — as locked by the s02 snapshot
contract. Keeping it here (rather than next to `Institution`) lets ingest
and the read endpoints import the alias without pulling in the ORM class.
"""

from __future__ import annotations

from typing import Literal

Kind = Literal["nursery", "kindergarten", "preschool"]

KIND_VALUES: tuple[str, ...] = ("nursery", "kindergarten", "preschool")

__all__ = ["Kind", "KIND_VALUES"]
