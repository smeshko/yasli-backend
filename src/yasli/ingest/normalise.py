"""Street string parsing + normalisation.

Two responsibilities:

1. ``parse_street(raw)`` decomposes the verbatim source string into the
   four columns the s05 schema declares for ``streets``: ``city``,
   ``type_marker``, ``street_part``, plus ``search_norm`` (the lossy
   lowercase Latin form used by the trigram index at query time).
2. ``to_search_norm(raw)`` is the same lossy normaliser exposed
   independently so the pipeline can re-apply it on conflict (the
   s06 design has streets' ``search_norm`` updated on every ingest).

The ICAO Cyrillic→Latin table is hardcoded here (rather than via
``unidecode``) because Bulgarian Cyrillic has a few characters where ICAO
and `unidecode` disagree (`ъ` is the canonical example), and we want a
deterministic, documented mapping.
"""

from __future__ import annotations

from dataclasses import dataclass

from yasli.geo.settlements import parser_base_localities

BASE_LOCALITIES: tuple[str, ...] = parser_base_localities()

TYPE_MARKERS: tuple[str, ...] = (
    "УЛ.",
    "БУЛ.",
    "ПЛ.",
    "Ж.К.",
    "КВ.",
)


# ICAO Bulgarian Cyrillic → Latin (lowercase) mapping. Single-character
# entries dominate; the digraphs (`ж` → `zh`, `ц` → `ts`, `ч` → `ch`,
# `ш` → `sh`, `щ` → `sht`, `ю` → `yu`, `я` → `ya`) are listed explicitly.
# `ъ` maps to `a` per the ICAO standard.
_CYRILLIC_TO_LATIN: dict[str, str] = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "h",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "sht",
    "ъ": "a",
    "ь": "y",
    "ю": "yu",
    "я": "ya",
}


class UnknownLocality(ValueError):
    """Raised when a raw street string doesn't start with one of the six
    base localities."""

    def __init__(self, raw: str) -> None:
        super().__init__(
            f"unknown base locality in street string: {raw!r}"
        )
        self.raw = raw


@dataclass(frozen=True)
class ParsedStreet:
    """Outcome of parsing one verbatim street string."""

    city: str
    type_marker: str | None
    street_part: str
    search_norm: str
    raw_name: str


def to_search_norm(raw_name: str) -> str:
    """Lowercase + ICAO Cyrillic→Latin transliteration. Pure function."""
    lowered = raw_name.lower()
    out: list[str] = []
    for ch in lowered:
        out.append(_CYRILLIC_TO_LATIN.get(ch, ch))
    return "".join(out)


def _strip_base_locality(raw: str) -> tuple[str, str]:
    """Return ``(base, remainder)`` or raise ``UnknownLocality``.

    ``remainder`` has its leading whitespace stripped; an exact match (no
    further content after the base) yields ``remainder == ""``.
    """
    for base in BASE_LOCALITIES:
        if raw == base:
            return base, ""
        if raw.startswith(base + " "):
            return base, raw[len(base) + 1 :].lstrip()
    raise UnknownLocality(raw)


def _match_type_marker(remainder: str) -> str | None:
    """Return the longest matching type marker at the start of ``remainder``,
    or ``None`` if none match.

    Order matters because ``БУЛ.`` and ``Ж.К.`` and ``КВ.`` are mutually
    exclusive prefixes, but we sort by length descending defensively.
    """
    for marker in sorted(TYPE_MARKERS, key=len, reverse=True):
        if remainder.startswith(marker):
            return marker
    return None


def parse_street(raw: str) -> ParsedStreet:
    """Decompose a raw street string per the s06 design.

    Standard street → ``(city=base, type_marker=marker,
    street_part=post-marker remainder)``.
    Compound locality (no recognised type marker after the base) →
    ``(city=raw, type_marker=None, street_part="")``.
    Unknown base → ``UnknownLocality``.
    """
    base, remainder = _strip_base_locality(raw)

    if remainder == "":
        # The raw string is the bare base locality. Treat as a compound
        # locality: city = raw, no street name within.
        return ParsedStreet(
            city=raw,
            type_marker=None,
            street_part="",
            search_norm=to_search_norm(raw),
            raw_name=raw,
        )

    marker = _match_type_marker(remainder)
    if marker is not None:
        street_part = remainder[len(marker) :].lstrip()
        return ParsedStreet(
            city=base,
            type_marker=marker,
            street_part=street_part,
            search_norm=to_search_norm(raw),
            raw_name=raw,
        )

    # Compound locality / special zone — the entire raw string is the
    # locality identity. street_part is empty (NOT the suffix).
    return ParsedStreet(
        city=raw,
        type_marker=None,
        street_part="",
        search_norm=to_search_norm(raw),
        raw_name=raw,
    )
