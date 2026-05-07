"""House-number parser: cover the four supported shapes plus rejections."""

from __future__ import annotations

import pytest

from yasli.ingest.parser import (
    NumberOutOfRange,
    UnparseableNumber,
    parse_number,
)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("085", (85, None, None)),
        ("019А", (19, "А", None)),
        ("041 вх.А", (41, None, "А")),
        ("002А вх.01", (2, "А", "01")),
        ("123", (123, None, None)),
        ("0", (0, None, None)),
        ("1 вх.1234", (1, None, "1234")),
    ],
)
def test_parse_accepts_all_four_shapes(
    raw: str, expected: tuple[int, str | None, str | None]
) -> None:
    assert parse_number(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "abc",
        "12B",
        "12 вх.",
        "  041 вх.А",
        "041вх.А",
        "041 вх.ABCDE",
    ],
)
def test_parse_rejects_unparseable(raw: str) -> None:
    with pytest.raises(UnparseableNumber):
        parse_number(raw)


def test_parse_rejects_out_of_range() -> None:
    with pytest.raises(NumberOutOfRange):
        parse_number("999999")


def test_unparseable_carries_source_in_message() -> None:
    with pytest.raises(UnparseableNumber) as excinfo:
        parse_number("nonsense")
    assert "nonsense" in str(excinfo.value)
    assert excinfo.value.source == "nonsense"
