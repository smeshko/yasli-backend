"""Seed coordinate candidates for every institution building and apply the
auto-accept rules.

Run from the repo root::

    uv run python -m scripts.seed_institution_locations

Reads the institutions table, gathers candidates for every ``main`` building
(OSM POI title match via Overpass, rank-30 Nominatim geocode) and every
``branch`` building (from the ``/lv/api/free-places`` table, geocode only),
then decides each row:

* **auto** only when all four rules hold — a unique OSM POI title match
  within the kind's amenity family (unique from both sides: one POI for the
  title, one institution owning it); the POI inside the Varna municipality
  polygon; the POI's reverse-geocoded settlement agreeing with the source
  address; and, if an in-polygon rank-30 geocode exists, the two within
  150 m;
* **pending**, with plain flags, otherwise — geocoder-only hits, ambiguous
  titles, disagreements, no candidate, every branch. Any flag forces
  pending. A candidate outside the polygon stays in the list so a person
  sees what the geocoder did, but can never be accepted.

Geocoder output is never accepted without review: all three measured wrong
pins (research §3.2) were Nominatim hits. Rank 26–27 (street) and 16–19
(settlement centroid) hits are discarded outright.

Output: the candidates file (the script's working state, and the worklist a
person resolves by hand: every ``pending`` entry with its flags and
candidates), plus — through the same renderer and the loader's validating
writer — the CSV of every decided row and the provenance file for the
``auto`` ones. Resumable: entries a person decided (``accepted``,
``pinned``, ``no_pin``) are kept and never re-gathered, except that a
``main`` entry whose institution address changed is reset to ``pending``
with flag ``address_changed``. The lineage rule in
``scripts.institution_locations_state`` decides whether local decisions or
the committed files win on startup, so a row written into the CSV by hand
is picked up as a decision on the next run.

Never imported by ``src/yasli`` and never run in CI or tests: it talks to
three third-party services (Overpass, Nominatim, dg.uslugi.io) with rate
limits and observed 504s. The pure helpers are tested against captured
responses in ``scripts/fixtures/``.
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from scripts import institution_locations_state as state
from scripts.institution_locations_state import haversine_m  # noqa: F401 - re-exported for callers
from yasli.db import get_engine
from yasli.ingest.institution_locations_loader import (
    DEFAULT_CSV,
    DEFAULT_PROVENANCE,
    MAX_GEOCODE_DISTANCE_M,
    normalise_address,
)
from yasli.ingest.municipality import in_varna_municipality
from yasli.models import Institution

log = logging.getLogger("scripts.seed_institution_locations")

CANDIDATES_PATH = DEFAULT_CSV.with_name("institution_locations.candidates.json")
FIXTURES = Path(__file__).resolve().parent / "fixtures"

USER_AGENT = "yasli-backend-locations/1.0 (+https://github.com/smeshko/yasli-backend)"
OVERPASS_URLS = (
    "https://lz4.overpass-api.de/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
NOMINATIM_URL = "https://nominatim.openstreetmap.org"
FREE_PLACES_URL = "https://dg.uslugi.io/lv/api/free-places"
NOMINATIM_SPACING_S = 1.1
#: The municipality bbox (south, west, north, east) — wider than the research
#: bbox so village POIs near the edge are not clipped; the polygon filters.
MUNICIPALITY_BBOX = (43.10, 27.74, 43.31, 28.06)

VARNA = "Варна"

#: Rule 1's "right amenity family": a title match on a POI outside the
#: kind's family is not a match at all. Confirmed against the captured
#: Overpass fixture: Varna's nurseries are tagged ``kindergarten`` or
#: ``childcare``, its kindergartens ``kindergarten``, its schools ``school``.
AMENITY_FAMILIES: dict[str, tuple[str, ...]] = {
    "nursery": ("nursery", "childcare", "kindergarten"),
    "kindergarten": ("kindergarten", "childcare"),
    "preschool": ("school", "kindergarten"),
}

#: The branch inventory measured on 2026-08-17 (research §1.3), used only if
#: the live free-places fetch returns fewer rows than this.
RESEARCH_BRANCH_COUNT = 15


# --- titles and POIs --------------------------------------------------------------


_QUOTED_RE = re.compile(r'(?:["“”„«»]|,,)\s*([^"“”„«»]+?)\s*["“”„«»]')
_LEADING_RE = re.compile(
    r"^(?:(?:\d+\.?|[IVX]+|№\s*\d+|ЦДГ|ОДЗ|ОДГ|ЧДГ|ДГ|ДЯ|ЧСУ|ЧОУ|СОУ|СУ|ОУ|НУ|ПГ|"
    r"Детска\s+ясла|Детска\s+градина|\(ДЯ\)|Оздравителна|Логопедична|Частна)"
    r"(?=[\s\-:.,(]|$)[\s\-:.,]*)+",
    re.IGNORECASE,
)
_TRAILING_RE = re.compile(
    r"(?:\s*(?:№\s*\d+|\(филиал\)|-\s*филиал|Филиал\s*\d*|/.*?/|с\.\s*\S.*))+$",
    re.IGNORECASE,
)


def title_of(name: str) -> str | None:
    """The quoted title of an institution or POI name, casefolded — or, for
    an unquoted OSM name, what is left after stripping type words and
    numbers (``ДГ Мир №13`` → ``мир``). ``None`` when nothing is left."""
    name = name.strip()
    if not name:
        return None
    match = _QUOTED_RE.search(name)
    if match:
        title = match.group(1)
    else:
        title = _TRAILING_RE.sub("", _LEADING_RE.sub("", name))
    title = re.sub(r"\s+", " ", title).strip(" -.,")
    return title.casefold() or None


def parse_pois(overpass_json: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Overpass ``out tags center`` elements → ``{osm, name, amenity, lat, lon}``."""
    pois = []
    for element in overpass_json.get("elements", []):
        centre = element if "lat" in element else element.get("center")
        if not centre:
            continue
        tags = element.get("tags", {})
        pois.append(
            {
                "osm": f"{element['type']}/{element['id']}",
                "name": tags.get("name", ""),
                "amenity": tags.get("amenity"),
                "lat": float(centre["lat"]),
                "lon": float(centre["lon"]),
            }
        )
    return pois


def poi_candidates(kind: str, name: str, pois: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Every POI in the kind's amenity family whose title equals the
    institution's. ``title_matches`` on each is the size of this list."""
    title = title_of(name)
    if title is None:
        return []
    family = AMENITY_FAMILIES[kind]
    matches = [p for p in pois if p["amenity"] in family and title_of(p["name"]) == title]
    return [
        {
            "source": "osm_poi",
            "lat": p["lat"],
            "lon": p["lon"],
            "osm": p["osm"],
            "osm_name": p["name"],
            "amenity": p["amenity"],
            "title_matches": len(matches),
            "settlement": None,
            "in_municipality": in_varna_municipality(p["lat"], p["lon"]),
        }
        for p in matches
    ]


def poi_candidates_for_branch(
    kind: str, parent_name: str, label: str, pois: Iterable[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """POIs that name a branch building: a title equal to the branch's own
    label (``Детска градина "Жирафче"``), or the parent's title on a POI whose
    name says филиал (``ДГ-4 "Теменужка" Филиал 1``). The parent's own
    building never qualifies. Branches are always flagged for review, so
    these are hints for one keystroke, never auto-accepted."""
    family = AMENITY_FAMILIES[kind]
    own = label.casefold().strip() or None
    parent = title_of(parent_name)
    matches = [
        p
        for p in pois
        if p["amenity"] in family
        and (
            (own is not None and title_of(p["name"]) == own)
            or (parent is not None and title_of(p["name"]) == parent and "филиал" in p["name"].casefold())
        )
    ]
    return [
        {
            "source": "osm_poi",
            "lat": p["lat"],
            "lon": p["lon"],
            "osm": p["osm"],
            "osm_name": p["name"],
            "amenity": p["amenity"],
            "title_matches": len(matches),
            "settlement": None,
            "in_municipality": in_varna_municipality(p["lat"], p["lon"]),
        }
        for p in matches
    ]


def title_owner_counts(institutions: Iterable[tuple[str, str, str]]) -> Counter[str]:
    """How many institutions share each title, across kinds — a POI whose
    title two institutions own cannot be a unique match for either."""
    counts: Counter[str] = Counter()
    for _kind, _external_id, name in institutions:
        title = title_of(name)
        if title is not None:
            counts[title] += 1
    return counts


# --- addresses ---------------------------------------------------------------------


_CITY_PREFIX_RE = re.compile(r"(?<![А-Яа-я])гр\.\s*Варна\s*,?\s*", re.IGNORECASE)
_MARKER_RE = re.compile(r"(?<![А-Яа-я])(?:ул|бул|ж\.к|кв|с)\.\s*|(?<![А-Яа-я])село\s+", re.IGNORECASE)
_VILLAGE_RE = re.compile(r"(?<![А-Яа-я])(?:с\.|село)\s*([А-Яа-я]+)")


def build_query(address: str) -> str:
    """The Nominatim query for a source address: leaving ``ул.``/``бул.`` in
    returns zero results for every address (research §3.2), so type markers,
    quotes, ``№`` and the city prefix go, and ``, Варна`` is appended."""
    query = _CITY_PREFIX_RE.sub("", address)
    query = _MARKER_RE.sub("", query)
    query = re.sub(r'["“”„«»]', "", query)
    query = re.sub(r"№\s*", "", query)
    query = re.sub(r"(?<![А-Яа-я])до\s+", "", query)
    query = re.sub(r"\s+", " ", query)
    query = re.sub(r"\s*,\s*", ", ", query).strip(" ,")
    return f"{query}, {VARNA}" if query else VARNA


def settlement_from_address(address: str) -> str:
    """The settlement a source address names: a village after ``с.``/``село``,
    otherwise the city — ``кв.``/``ж.к.`` are city neighbourhoods."""
    match = _VILLAGE_RE.search(address)
    if match:
        return match.group(1).capitalize()
    return VARNA


def settlement_from_reverse(response: Mapping[str, Any]) -> str | None:
    """``address.village``, then ``town``, then ``city`` — or ``None``."""
    address = response.get("address") or {}
    for field in ("village", "town", "city"):
        if address.get(field):
            return str(address[field])
    return None


def geocode_candidates(search_response: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Rank-30 (building / POI) hits only. Street centroids (26–27) and
    settlement centroids (16–19) look plausible and are tens to hundreds of
    metres off, so they are discarded rather than kept as candidates."""
    candidates = []
    for hit in search_response:
        if int(hit.get("place_rank", 0)) != 30:
            continue
        lat, lon = float(hit["lat"]), float(hit["lon"])
        candidates.append(
            {
                "source": "nominatim",
                "lat": lat,
                "lon": lon,
                "place_rank": 30,
                "settlement": settlement_from_reverse(hit),
                "in_municipality": in_varna_municipality(lat, lon),
            }
        )
    return candidates


# --- the decision -----------------------------------------------------------------------


def decide(
    *,
    role: str,
    address: str,
    address_settlement: str | None,
    candidates: list[dict[str, Any]],
    title_owners: int = 1,
) -> tuple[str, int | None, list[str]]:
    """Apply the four auto-accept rules. Returns ``(status, candidate_index,
    flags)``; any flag forces ``pending``."""
    flags: list[str] = []
    if role == "branch":
        flags.append("branch")
        if not address:
            flags.append("name_only_branch")
    if any(not c.get("in_municipality") for c in candidates):
        flags.append("outside_municipality")
    for c in candidates:
        if (
            c.get("in_municipality")
            and c.get("settlement")
            and (address_settlement is None or c["settlement"].casefold() != address_settlement.casefold())
        ):
            flags.append("settlement_mismatch")
            break

    poi_indexes = [i for i, c in enumerate(candidates) if c["source"] == "osm_poi"]
    geocodes_inside = [
        c for c in candidates if c["source"] == "nominatim" and c.get("in_municipality")
    ]
    chosen: int | None = None
    if not candidates:
        if "name_only_branch" not in flags:
            flags.append("no_candidate")
    elif not poi_indexes:
        flags.append("geocoder_only")
    elif (
        len(poi_indexes) > 1
        or candidates[poi_indexes[0]].get("title_matches") != 1
        or title_owners > 1
    ):
        flags.append("ambiguous_title")
    else:
        index = poi_indexes[0]
        poi = candidates[index]
        if poi.get("in_municipality"):
            if poi.get("settlement") is None:
                flags.append("reverse_geocode_failed")
            for geocode in geocodes_inside:
                if haversine_m(poi["lat"], poi["lon"], geocode["lat"], geocode["lon"]) > (
                    MAX_GEOCODE_DISTANCE_M
                ):
                    flags.append("candidates_disagree")
                    break
            chosen = index
    if flags:
        return "pending", None, flags
    return "auto", chosen, []


# --- branches ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BranchRow:
    parent_number: int
    label: str
    address: str
    raw: str


_TR_RE = re.compile(r"<tr>(.*?)</tr>", re.S)
_TD_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_DG_NUMBER_RE = re.compile(r"ДГ\s*№?\s*(\d+)")
_BRANCH_LABEL_RE = re.compile(r'филиал\s*["„“«]\s*([^"„“”»]+?)\s*["“”»]\s*ДГ', re.IGNORECASE)
_PARENT_TITLE_RE = re.compile(r'ДГ\s*№?\s*\d+\s*["„“«]?\s*[^"„“”»]*?["“”»]')
_NURSERY_NOTE_RE = re.compile(r"/\s*с(?:ъс)?\s+яслена\s+група\s*/|с\s+яслена\s+група", re.IGNORECASE)
_LEADING_TOKEN_RE = re.compile(r"^(?:[-–—\s]+|филиал\b|на\b|в\b)\s*", re.IGNORECASE)


def dg_number(name: str) -> int | None:
    """``ДГ№13 "Мир"`` → 13; nurseries and schools → ``None``."""
    match = re.match(r"\s*ДГ\s*№\s*(\d+)", name)
    return int(match.group(1)) if match else None


def _clean_branch_address(rest: str) -> str:
    rest = _NURSERY_NOTE_RE.sub(" ", rest)
    rest = re.sub(r"\s+", " ", rest).strip()
    while True:
        stripped = _LEADING_TOKEN_RE.sub("", rest)
        if stripped == rest:
            break
        rest = stripped
    return rest.rstrip(" .")


def parse_branch_rows(table_html: str) -> list[BranchRow]:
    """The ``филиал`` rows of the free-places HTML table, normalised from
    their free-form ``филиал`` / ``Филиал`` / ``- `` / `` на `` / `` в ``
    shapes into ``(parent ДГ number, label, address)``. Name-only branches
    have a label and no address."""
    rows: list[BranchRow] = []
    for tr in _TR_RE.findall(table_html):
        cells = _TD_RE.findall(tr)
        if not cells:
            continue
        text = html.unescape(_TAG_RE.sub("", cells[0])).replace("\r\n", "\n").strip()
        if "филиал" not in text.casefold():
            continue
        number = _DG_NUMBER_RE.search(text)
        if not number:
            log.warning("branch row without a ДГ number skipped: %r", text)
            continue
        label_match = _BRANCH_LABEL_RE.search(text)
        label = re.sub(r"\s+", " ", label_match.group(1)).strip() if label_match else ""
        parents = list(_PARENT_TITLE_RE.finditer(text))
        rest = text[parents[-1].end() :] if parents else ""
        rows.append(
            BranchRow(
                parent_number=int(number.group(1)),
                label=label,
                address=_clean_branch_address(rest),
                raw=text,
            )
        )
    return rows


def branch_entries(
    rows: Iterable[BranchRow], institutions: Mapping[tuple[str, str], Mapping[str, Any]]
) -> tuple[list[dict[str, Any]], list[BranchRow]]:
    """Attach each branch row to its parent kindergarten by ДГ number."""
    by_number = {
        dg_number(inst["name"]): (key, inst)
        for key, inst in institutions.items()
        if key[0] == "kindergarten" and dg_number(inst["name"]) is not None
    }
    entries: list[dict[str, Any]] = []
    orphans: list[BranchRow] = []
    for row in rows:
        parent = by_number.get(row.parent_number)
        if parent is None:
            orphans.append(row)
            continue
        (kind, external_id), inst = parent
        entries.append(
            {
                "key": {
                    "kind": kind,
                    "external_id": external_id,
                    "role": "branch",
                    "label": row.label,
                    "address": row.address,
                },
                "name": inst["name"],
                "address_settlement": settlement_from_address(row.address) if row.address else None,
                "candidates": [],
                "flags": [],
                "decision": state.make_decision("pending"),
            }
        )
    return entries, orphans


# --- resumability -------------------------------------------------------------------------


def prune_stale_branches(
    entries: Mapping[state.Key, Mapping[str, Any]], inventory: Iterable[state.Key]
) -> tuple[dict[state.Key, dict[str, Any]], list[state.Key]]:
    """Drop branch entries the current free-places inventory no longer lists —
    a branch whose address text changed at the source would otherwise linger
    next to its new key. Main entries are never touched here (they are re-keyed
    by ``plan_refresh``). Only call this with a full inventory: the endpoint is
    seasonal, and a short fetch must not retire real branches."""
    keep_keys = set(inventory)
    kept: dict[state.Key, dict[str, Any]] = {}
    dropped: list[state.Key] = []
    for key, entry in entries.items():
        if key[2] == "branch" and key not in keep_keys:
            dropped.append(key)
        else:
            kept[key] = dict(entry)
    return kept, dropped



def _with_address_changed(flags: Iterable[str]) -> list[str]:
    return ["address_changed", *(f for f in flags if f != "address_changed")]


def plan_refresh(
    existing: Mapping[state.Key, Mapping[str, Any]],
    institutions: Mapping[tuple[str, str], Mapping[str, Any]],
) -> tuple[dict[state.Key, dict[str, Any]], list[dict[str, Any]]]:
    """Split existing entries into those to re-gather and those to keep.

    Human decisions (``accepted``, ``pinned``, ``no_pin``) are kept untouched;
    ``auto`` and ``pending`` entries are refreshed. A ``main`` entry whose
    institution address no longer matches (through ``normalise_address``) is
    replaced by a pending entry under the new address, flagged
    ``address_changed``, carrying the previous key and decision — whatever
    its previous decision was.

    ``existing`` can hold both the old-address and the new-address entry of
    one institution (a rebuild from a committed file that still has the old
    row, next to a local new-address entry). The outcome must not depend on
    which is visited first: the new-address entry always carries
    ``address_changed`` while it is pending, and a person's decision on the
    new address stands alone, with the old-address entry dropped.
    """
    to_gather: dict[state.Key, dict[str, Any]] = {}
    kept: dict[state.Key, dict[str, Any]] = {}
    for key, entry in existing.items():
        kind, external_id, role, _label, address = key
        inst = institutions.get((kind, external_id))
        if inst is None:
            log.warning("dropping %s: institution no longer exists", key)
            continue
        current = (inst.get("address") or "").strip()  # the parser strips; keys must too
        if role == "main" and normalise_address(address) != normalise_address(current):
            new_key: state.Key = (kind, external_id, "main", "", current)
            if new_key in kept:
                continue  # a person already decided the new address
            already = to_gather.get(new_key, {})
            to_gather[new_key] = {
                "key": state.key_dict(new_key),
                "name": inst["name"],
                "address_settlement": settlement_from_address(current),
                "candidates": list(already.get("candidates", [])),
                "flags": _with_address_changed(already.get("flags", [])),
                "decision": state.make_decision("pending"),
                "previous": {"key": dict(entry["key"]), "decision": dict(entry["decision"])},
            }
            continue
        moved = to_gather.pop(key, None)  # the old-address entry was visited first
        if entry["decision"]["status"] in ("accepted", "pinned", "no_pin"):
            kept[key] = dict(entry)
        else:
            to_gather[key] = dict(entry)
            if moved is not None:
                to_gather[key]["flags"] = _with_address_changed(entry.get("flags", []))
                to_gather[key]["previous"] = moved["previous"]
    return to_gather, list(kept.values())


# --- network (thin, untested) ---------------------------------------------------------------


_last_nominatim_call = 0.0


def _get_json(url: str, *, data: bytes | None = None, headers: dict[str, str] | None = None) -> Any:
    request = urllib.request.Request(
        url, data=data, headers={"User-Agent": USER_AGENT, **(headers or {})}
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.load(response)


def fetch_overpass() -> dict[str, Any]:
    south, west, north, east = MUNICIPALITY_BBOX
    bbox = f"({south},{west},{north},{east})"
    amenities = '["amenity"~"^(kindergarten|childcare|nursery|school)$"]'
    query = (
        "[out:json][timeout:180];("
        f"node{amenities}{bbox};way{amenities}{bbox};relation{amenities}{bbox};"
        ");out tags center;"
    )
    last_error: Exception | None = None
    for url in OVERPASS_URLS:
        try:
            log.info("overpass: %s", url)
            return _get_json(url, data=urllib.parse.urlencode({"data": query}).encode())
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
            log.warning("overpass %s failed: %s", url, exc)
            last_error = exc
    raise RuntimeError(f"every Overpass mirror failed: {last_error}")


def _nominatim(path: str, params: dict[str, Any]) -> Any:
    global _last_nominatim_call
    wait = NOMINATIM_SPACING_S - (time.monotonic() - _last_nominatim_call)
    if wait > 0:
        time.sleep(wait)
    try:
        return _get_json(f"{NOMINATIM_URL}/{path}?{urllib.parse.urlencode(params)}")
    finally:
        _last_nominatim_call = time.monotonic()


def nominatim_search(query: str) -> list[dict[str, Any]]:
    return _nominatim("search", {"q": query, "format": "jsonv2", "limit": 3, "addressdetails": 1})


def nominatim_reverse(lat: float, lon: float) -> dict[str, Any]:
    return _nominatim(
        "reverse", {"lat": lat, "lon": lon, "format": "jsonv2", "addressdetails": 1, "zoom": 16}
    )


def fetch_free_places() -> dict[str, Any]:
    return _get_json(
        FREE_PLACES_URL,
        data=json.dumps({"reception": "garden"}).encode(),
        headers={"Content-Type": "application/json"},
    )


# --- orchestration -----------------------------------------------------------------------


def read_institutions(session: Session) -> dict[tuple[str, str], dict[str, Any]]:
    """Names and addresses, stripped: the snapshot contract does not strip,
    the loader's parser does, and a key must survive that round trip."""
    return {
        (kind, external_id): {"name": name.strip(), "address": address.strip() if address else address}
        for kind, external_id, name, address in session.execute(
            select(
                Institution.kind, Institution.external_id, Institution.name, Institution.address
            )
        )
    }


class Gatherer:
    """Network-backed candidate gathering with a reverse-geocode cache, so the
    decision logic stays a pure function of what was gathered."""

    def __init__(self, pois: list[dict[str, Any]], owners: Counter[str]) -> None:
        self.pois = pois
        self.owners = owners
        self._reverse_cache: dict[tuple[float, float], str | None] = {}

    def settlement_at(self, lat: float, lon: float) -> str | None:
        key = (round(lat, 5), round(lon, 5))
        if key not in self._reverse_cache:
            try:
                self._reverse_cache[key] = settlement_from_reverse(nominatim_reverse(lat, lon))
            except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
                log.warning("reverse geocode %s,%s failed: %s", lat, lon, exc)
                self._reverse_cache[key] = None
        return self._reverse_cache[key]

    def gather(self, entry: dict[str, Any], kind: str, today: str) -> dict[str, Any]:
        key = entry["key"]
        role, address = key["role"], key["address"]
        candidates: list[dict[str, Any]] = []
        if role == "main":
            candidates = poi_candidates(kind, entry["name"], self.pois)
        else:
            candidates = poi_candidates_for_branch(kind, entry["name"], key["label"], self.pois)
        for candidate in candidates:
            candidate["settlement"] = self.settlement_at(candidate["lat"], candidate["lon"])
        if address:
            try:
                geocodes = geocode_candidates(nominatim_search(build_query(address)))
            except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
                log.warning("geocode %r failed: %s", address, exc)
                geocodes = []
            pois = [c for c in candidates if c["source"] == "osm_poi"]
            for geocode in geocodes:
                if pois:
                    geocode["distance_m"] = round(
                        min(haversine_m(p["lat"], p["lon"], geocode["lat"], geocode["lon"]) for p in pois)
                    )
            candidates.extend(geocodes)
        flags_before = [f for f in entry.get("flags", []) if f == "address_changed"]
        status, index, flags = decide(
            role=role,
            address=address,
            address_settlement=entry.get("address_settlement"),
            candidates=candidates,
            title_owners=self.owners.get(title_of(entry["name"]) or "", 1),
        )
        flags = flags_before + [f for f in flags if f not in flags_before]
        if flags:
            status, index = "pending", None
        entry = {**entry, "candidates": candidates, "flags": flags}
        if status == "auto":
            candidate = candidates[index]  # type: ignore[index]
            entry["decision"] = state.make_decision(
                "auto",
                candidate=index,
                lat=candidate["lat"],
                lon=candidate["lon"],
                source="osm_poi",
                precision="building",
                decided_at=today,
            )
            entry["decision"]["provenance"] = state.provenance_for(entry, candidate)
        else:
            entry["decision"] = state.make_decision("pending")
        return entry


def _log_summary(entries: list[dict[str, Any]], orphans: list[BranchRow], rebuilt: bool) -> None:
    statuses = Counter(e["decision"]["status"] for e in entries)
    flags = Counter(flag for e in entries for flag in e["flags"])
    log.info("lineage: %s", "rebuilt decisions from the committed files" if rebuilt else "local decisions kept")
    log.info("entries: %d — %s", len(entries), ", ".join(f"{k}={v}" for k, v in sorted(statuses.items())))
    log.info("flags (worklist): %s", ", ".join(f"{k}={v}" for k, v in flags.most_common()) or "none")
    for orphan in orphans:
        log.warning("branch row with no parent institution: %r", orphan.raw)
    # The three measured geocoder failures (research §3.2), by address.
    for needle in ('Чаталджа" 111', 'Лазур" №2', 'Варненчик" до блок 20'):
        for entry in entries:
            if needle in entry["key"]["address"] and entry["key"]["role"] == "main":
                log.info(
                    "measured failure %r → %s %s",
                    entry["key"]["address"],
                    entry["decision"]["status"],
                    entry["flags"],
                )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="scripts.seed_institution_locations",
        description="Gather coordinate candidates and apply the auto-accept rules.",
    )
    parser.add_argument("--candidates", type=Path, default=CANDIDATES_PATH)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--provenance", type=Path, default=DEFAULT_PROVENANCE)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stderr)
    today = date.today().isoformat()

    with Session(get_engine()) as session:
        institutions = read_institutions(session)
    log.info("institutions: %d", len(institutions))

    doc = state.load_candidates(args.candidates)
    committed_rows, committed_provenance, committed_hash_value, torn = state.load_committed(
        args.csv, args.provenance, doc
    )
    if torn:
        log.warning(
            "%s and %s were torn by an interrupted save; regenerating both from %s",
            args.csv, args.provenance, args.candidates,
        )
    existing, rebuilt = state.reconcile(
        doc, committed_rows, committed_provenance, committed_hash_value, torn=torn
    )
    for entry in existing.values():  # names come from the database, not the CSV
        inst = institutions.get((entry["key"]["kind"], entry["key"]["external_id"]))
        if inst:
            entry["name"] = inst["name"]
            if entry["key"]["role"] == "main":
                entry["address_settlement"] = settlement_from_address(entry["key"]["address"])
    to_gather, kept = plan_refresh(existing, institutions)

    for (kind, external_id), inst in sorted(institutions.items()):
        address = (inst["address"] or "").strip()
        key: state.Key = (kind, external_id, "main", "", address)
        if key not in to_gather and not any(state.entry_key(e) == key for e in kept):
            to_gather[key] = {
                "key": state.key_dict(key),
                "name": inst["name"],
                "address_settlement": settlement_from_address(address),
                "candidates": [],
                "flags": [],
                "decision": state.make_decision("pending"),
            }

    free_places = fetch_free_places()
    branch_rows = parse_branch_rows(free_places["free-places"]["SPR_SWOBODNI_MESTA"])
    log.info("free-places: KLAS_DATE=%s branch rows=%d", free_places["free-places"].get("KLAS_DATE"), len(branch_rows))
    if len(branch_rows) < RESEARCH_BRANCH_COUNT:
        log.warning(
            "only %d branch rows (research measured %d on 2026-08-17): the endpoint is seasonal — "
            "check RESEARCH.md §1.3 before trusting this inventory",
            len(branch_rows),
            RESEARCH_BRANCH_COUNT,
        )
    branches, orphans = branch_entries(branch_rows, institutions)
    if len(branch_rows) >= RESEARCH_BRANCH_COUNT:
        inventory = [state.entry_key(e) for e in branches]
        to_gather, dropped = prune_stale_branches(to_gather, inventory)
        kept_by_key, dropped_kept = prune_stale_branches(
            {state.entry_key(e): e for e in kept}, inventory
        )
        kept = list(kept_by_key.values())
        for key in dropped + dropped_kept:
            log.warning("retiring branch no longer in the free-places table: %s", key)
    for entry in branches:
        key = state.entry_key(entry)
        if key not in to_gather and not any(state.entry_key(e) == key for e in kept):
            to_gather[key] = entry

    pois = parse_pois(fetch_overpass())
    log.info("overpass: %d POIs", len(pois))
    gatherer = Gatherer(pois, title_owner_counts((k, e, i["name"]) for (k, e), i in institutions.items()))
    gathered = []
    for i, (key, entry) in enumerate(sorted(to_gather.items()), start=1):
        log.info("[%d/%d] %s %s", i, len(to_gather), key[0], entry["name"] if key[2] == "main" else f"{entry['name']} branch {key[3] or key[4]}")
        gathered.append(gatherer.gather(entry, key[0], today))

    entries = kept + gathered
    rows, provenance = state.persist(
        entries,
        candidates_path=args.candidates,
        csv_path=args.csv,
        provenance_path=args.provenance,
    )
    _log_summary(entries, orphans, rebuilt)
    log.info("wrote %s (%d entries), %s (%d rows), %s (%d auto entries)",
             args.candidates, len(entries), args.csv, len(rows), args.provenance, len(provenance))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
