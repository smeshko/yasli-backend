"""House-number parser for snapshot `address_entries[i].number` strings.

Source data has four observed shapes (counts from CONTEXT.md):

| Format               | Count   | Example      |
| -------------------- | ------- | ------------ |
| simple_3digits       | 187,351 | 085          |
| with_letter          |  21,058 | 019А         |
| with_entrance        |  26,471 | 041 вх.А     |
| other (combos)       |   1,562 | 002А вх.01   |

A single regex with optional groups parses all four. Leading zeros are
stripped before `int()`, so `"085"` parses to `85` (the column is
`SMALLINT`, capped at `[0, 32767]`).

Skipped row policy is the pipeline's concern — this module only knows
about `UnparseableNumber` and `NumberOutOfRange`. The orchestrator
catches them, logs the offending input, and bumps `skipped_rows`.
"""

from __future__ import annotations

import re

# Single regex covering all four shapes. The four groups are:
#   1. digits  (always present)
#   2. suffix  (optional Cyrillic uppercase letter immediately after digits)
#   3. entrance prefix " вх." (presence indicator only — captured but not used)
#   4. entrance value (one Cyrillic uppercase letter or up to four digits)
_NUMBER_RE = re.compile(
    r"^(\d+)([А-Я])?(\s+вх\.([А-Я]|\d{1,4}))?$"
)

SMALLINT_MAX = 32767


class UnparseableNumber(ValueError):
    """Raised when the source string doesn't match any of the four shapes."""

    def __init__(self, source: str) -> None:
        super().__init__(f"unparseable number string: {source!r}")
        self.source = source


class NumberOutOfRange(ValueError):
    """Raised when the parsed integer overflows SMALLINT [0, 32767]."""

    def __init__(self, source: str, value: int) -> None:
        super().__init__(
            f"number {value} (from {source!r}) is outside SMALLINT range [0, {SMALLINT_MAX}]"
        )
        self.source = source
        self.value = value


def parse_number(s: str) -> tuple[int, str | None, str | None]:
    """Parse ``s`` into ``(number_int, number_suffix, entrance)``.

    ``number_suffix`` and ``entrance`` are ``None`` when absent. Leading
    zeros are stripped from the digit group before integer conversion.
    """
    match = _NUMBER_RE.match(s)
    if match is None:
        raise UnparseableNumber(s)

    digits = match.group(1)
    suffix = match.group(2)
    entrance = match.group(4)

    value = int(digits)
    if value < 0 or value > SMALLINT_MAX:
        raise NumberOutOfRange(s, value)

    return value, suffix, entrance
