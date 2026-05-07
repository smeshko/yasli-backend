"""Street normaliser: standard streets, every village, compound localities,
unknown bases, and determinism / round-trip tests for `to_search_norm`."""

from __future__ import annotations

import pytest

from yasli.ingest.normalise import (
    BASE_LOCALITIES,
    UnknownLocality,
    parse_street,
    to_search_norm,
)


def test_standard_varna_street() -> None:
    parsed = parse_street("ГР.ВАРНА БУЛ.ВЛАДИСЛАВ ВАРНЕНЧИК")
    assert parsed.city == "ГР.ВАРНА"
    assert parsed.type_marker == "БУЛ."
    assert parsed.street_part == "ВЛАДИСЛАВ ВАРНЕНЧИК"
    assert parsed.raw_name == "ГР.ВАРНА БУЛ.ВЛАДИСЛАВ ВАРНЕНЧИК"


@pytest.mark.parametrize(
    "village",
    [
        "С. ТОПОЛИ",
        "С. ЗВЕЗДИЦА",
        "С. КАМЕНАР",
        "С. КОНСТАНТИНОВО",
        "С. КАЗАШКО",
    ],
)
def test_each_village_locality(village: str) -> None:
    raw = f"{village} УЛ.ХАН АСПАРУХ"
    parsed = parse_street(raw)
    assert parsed.city == village
    assert parsed.type_marker == "УЛ."
    assert parsed.street_part == "ХАН АСПАРУХ"


def test_compound_locality_vilna_zona() -> None:
    raw = "ГР.ВАРНА ВИЛНА ЗОНА АЛЕН МАК-2"
    parsed = parse_street(raw)
    assert parsed.city == raw
    assert parsed.type_marker is None
    assert parsed.street_part == ""


def test_compound_locality_kad_plan() -> None:
    raw = "ГР.ВАРНА КАД.ПЛАН ТРАКАТА"
    parsed = parse_street(raw)
    assert parsed.city == raw
    assert parsed.type_marker is None
    assert parsed.street_part == ""


def test_compound_locality_blok() -> None:
    raw = "ГР.ВАРНА БЛОК ТЕЦ-Я.КОСТОВ"
    parsed = parse_street(raw)
    assert parsed.city == raw
    assert parsed.type_marker is None
    assert parsed.street_part == ""


def test_unknown_locality_raises() -> None:
    with pytest.raises(UnknownLocality):
        parse_street("ГР.СОФИЯ УЛ.ВИТОША")


def test_search_norm_lowercases_and_transliterates() -> None:
    assert to_search_norm("ГР.ВАРНА БУЛ.ГЕНЕРАЛ КОЛЕВ") == "gr.varna bul.general kolev"


def test_search_norm_handles_digraphs() -> None:
    assert to_search_norm("ЦЪР") == "tsar"
    assert to_search_norm("ЖЪЛТ") == "zhalt"


def test_search_norm_is_deterministic() -> None:
    raw = "ГР.ВАРНА УЛ.ОРБИТА"
    assert to_search_norm(raw) == to_search_norm(raw)


def test_every_cyrillic_letter_in_table_maps_to_latin() -> None:
    # Round-trip every key in the ICAO table — the output must be ASCII
    # and lowercase. (Catches accidental wide-character entries.)
    cyrillic_alphabet = "абвгдежзийклмнопрстуфхцчшщъьюя"
    for ch in cyrillic_alphabet:
        latin = to_search_norm(ch)
        assert latin.isascii(), f"{ch!r} → {latin!r} is not ASCII"
        assert latin == latin.lower(), f"{ch!r} → {latin!r} not lowercase"
        assert latin != ch, f"{ch!r} did not transliterate"


def test_base_localities_constant_is_six_elements() -> None:
    assert len(BASE_LOCALITIES) == 6
    assert "ГР.ВАРНА" in BASE_LOCALITIES


def test_bare_base_locality_is_compound() -> None:
    parsed = parse_street("ГР.ВАРНА")
    assert parsed.city == "ГР.ВАРНА"
    assert parsed.type_marker is None
    assert parsed.street_part == ""
