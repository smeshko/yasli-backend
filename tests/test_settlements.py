from __future__ import annotations

from collections import Counter

from yasli.geo.settlements import VARNA_SETTLEMENTS


EXPECTED_SETTLEMENTS = {
    "10135": ("ГР.ВАРНА", "city", ("ГР.ВАРНА%", "ГР. ВАРНА%")),
    "35701": ("С.КАМЕНАР", "village", ("С.КАМЕНАР%", "С. КАМЕНАР%")),
    "72709": ("С.ТОПОЛИ", "village", ("С.ТОПОЛИ%", "С. ТОПОЛИ%")),
    "30497": ("С.ЗВЕЗДИЦА", "village", ("С.ЗВЕЗДИЦА%", "С. ЗВЕЗДИЦА%")),
    "38354": (
        "С.КОНСТАНТИНОВО",
        "village",
        ("С.КОНСТАНТИНОВО%", "С. КОНСТАНТИНОВО%"),
    ),
    "35211": ("С.КАЗАШКО", "village", ("С.КАЗАШКО%", "С. КАЗАШКО%")),
}


def test_varna_settlements_are_complete_and_typed() -> None:
    assert len(VARNA_SETTLEMENTS) == 6
    assert {settlement.code for settlement in VARNA_SETTLEMENTS} == set(
        EXPECTED_SETTLEMENTS
    )
    assert all(
        settlement.code.isdigit() and len(settlement.code) == 5
        for settlement in VARNA_SETTLEMENTS
    )

    type_counts = Counter(
        settlement.locality_type for settlement in VARNA_SETTLEMENTS
    )
    assert type_counts == {"city": 1, "village": 5}


def test_varna_settlement_patterns_include_source_spacing_variants() -> None:
    settlements_by_code = {
        settlement.code: settlement for settlement in VARNA_SETTLEMENTS
    }

    for code, (name, locality_type, patterns) in EXPECTED_SETTLEMENTS.items():
        settlement = settlements_by_code[code]
        assert settlement.name == name
        assert settlement.locality_type == locality_type
        assert settlement.raw_name_patterns == patterns
