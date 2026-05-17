"""Settlement reference data for Varna municipality."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Settlement:
    code: str
    name: str
    locality_type: Literal["city", "village"]
    raw_name_patterns: tuple[str, ...]


# These are official GRAO/KADS settlement identifiers for the six populated
# places in Varna municipality. `grao_loader.py` parses settlement codes into
# `grao_addresses` for район-bearing KADS rows, but village header rows do not
# carry address-level район data usable by the district join. Settlement
# stamping therefore remains a separate pass over `streets.raw_name`, and
# `settlement_code` identifies a known settlement, not only a village.
VARNA_SETTLEMENTS: tuple[Settlement, ...] = (
    Settlement(
        code="10135",
        name="ГР.ВАРНА",
        locality_type="city",
        raw_name_patterns=("ГР.ВАРНА%", "ГР. ВАРНА%"),
    ),
    Settlement(
        code="35701",
        name="С.КАМЕНАР",
        locality_type="village",
        raw_name_patterns=("С.КАМЕНАР%", "С. КАМЕНАР%"),
    ),
    Settlement(
        code="72709",
        name="С.ТОПОЛИ",
        locality_type="village",
        raw_name_patterns=("С.ТОПОЛИ%", "С. ТОПОЛИ%"),
    ),
    Settlement(
        code="30497",
        name="С.ЗВЕЗДИЦА",
        locality_type="village",
        raw_name_patterns=("С.ЗВЕЗДИЦА%", "С. ЗВЕЗДИЦА%"),
    ),
    Settlement(
        code="38354",
        name="С.КОНСТАНТИНОВО",
        locality_type="village",
        raw_name_patterns=("С.КОНСТАНТИНОВО%", "С. КОНСТАНТИНОВО%"),
    ),
    Settlement(
        code="35211",
        name="С.КАЗАШКО",
        locality_type="village",
        raw_name_patterns=("С.КАЗАШКО%", "С. КАЗАШКО%"),
    ),
)
