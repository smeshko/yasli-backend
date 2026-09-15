"""Shared state helpers for the institution locations seed script and the
review tool: the candidates file, the decision → CSV row mapping, and the
lineage rule between local working state and the committed files.

The **candidates file** (``data/institution_locations.candidates.json``,
gitignored) holds one entry per building::

    {"source_hash": "<sha256 of the committed CSV + provenance it was last
                     regenerated from, or null>",
     "entries": [{"key": {kind, external_id, role, label, address},
                  "name": "...", "address_settlement": "Варна",
                  "candidates": [...], "flags": [...],
                  "decision": {"status": ..., "candidate": i|null, "lat", "lon",
                               "source", "precision", "decided_at",
                               "provenance": {...}|null}}]}

A decision is self-contained (it carries its own coordinate, source and
precision) so a CSV row can always be re-rendered from it, and so a decision
rebuilt from the committed CSV needs no candidate list. ``candidate`` is the
index of the candidate it was taken from, when one is present locally.

**Lineage rule.** Within a session the candidates file is the commit point:
every save writes it atomically, then regenerates the CSV and the provenance
file from it, then rewrites its ``source_hash``. Across sessions the
committed CSV + provenance are the record: on startup or a seed re-run, a
matching hash means the candidates file is in sync or ahead (a crash between
the writes) and its decisions stand; a mismatch, or no candidates file at
all, rebuilds every decision from the committed files and keeps only
candidates and flags from local state. A stale local file can never revert a
newer committed one.

Only decided entries — ``auto``, ``accepted``, ``pinned``, ``no_pin`` — are
written to the CSV. A ``pending`` row is simply absent, and the loader's
missing-``main`` guard is what surfaces it.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from collections.abc import Iterable, Mapping
from datetime import date
from pathlib import Path
from typing import Any

#: The fixed flag vocabulary. Any flag forces ``pending``.
FLAGS: tuple[str, ...] = (
    "no_candidate",
    "ambiguous_title",
    "geocoder_only",
    "outside_municipality",
    "settlement_mismatch",
    "candidates_disagree",
    "branch",
    "name_only_branch",
    "reverse_geocode_failed",
    "address_changed",
)

DECIDED: tuple[str, ...] = ("auto", "accepted", "pinned", "no_pin")
STATUSES: tuple[str, ...] = DECIDED + ("pending",)
KEY_FIELDS: tuple[str, ...] = ("kind", "external_id", "role", "label", "address")

Key = tuple[str, str, str, str, str]

_EARTH_RADIUS_M = 6_371_000.0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(a))


def _coord(value: Any) -> float | None:
    return None if value is None else round(float(value), 6)


def entry_key(entry: Mapping[str, Any]) -> Key:
    key = entry["key"]
    return tuple(str(key[field]) for field in KEY_FIELDS)  # type: ignore[return-value]


def key_dict(key: Key) -> dict[str, str]:
    return dict(zip(KEY_FIELDS, key, strict=True))


def provenance_key(key: Key | Mapping[str, Any]) -> str:
    if isinstance(key, Mapping):
        return f"{key['kind']}/{key['external_id']}"
    return f"{key[0]}/{key[1]}"


def make_decision(
    status: str,
    *,
    candidate: int | None = None,
    lat: float | None = None,
    lon: float | None = None,
    source: str | None = None,
    precision: str | None = None,
    decided_at: str | None = None,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if status not in STATUSES:
        raise ValueError(f"unknown decision status {status!r}")
    return {
        "status": status,
        "candidate": candidate,
        "lat": _coord(lat),
        "lon": _coord(lon),
        "source": source,
        "precision": precision,
        "decided_at": decided_at,
        "provenance": provenance,
    }


def resolve_candidate_index(
    decision: Mapping[str, Any], candidates: list[dict[str, Any]]
) -> int | None:
    """The index of the candidate at the decision's coordinate and source."""
    if decision.get("lat") is None or decision.get("source") in (None, "manual"):
        return None
    for i, candidate in enumerate(candidates):
        if (
            candidate.get("source") == decision["source"]
            and _coord(candidate["lat"]) == _coord(decision["lat"])
            and _coord(candidate["lon"]) == _coord(decision["lon"])
        ):
            return i
    return None


def provenance_for(entry: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
    """The committed record of the four auto-accept rule outcomes for an
    ``auto`` row, so the parser can cross-check it without the network."""
    geocodes = [
        c
        for c in entry["candidates"]
        if c.get("source") == "nominatim" and c.get("in_municipality")
    ]
    distance = None
    if geocodes:
        distance = round(
            min(
                haversine_m(candidate["lat"], candidate["lon"], g["lat"], g["lon"])
                for g in geocodes
            )
        )
    return {
        "lat": _coord(candidate["lat"]),
        "lon": _coord(candidate["lon"]),
        "osm": candidate.get("osm"),
        "amenity": candidate.get("amenity"),
        "title_matches": candidate.get("title_matches"),
        "in_municipality": bool(candidate.get("in_municipality")),
        "settlement": candidate.get("settlement"),
        "address_settlement": entry.get("address_settlement"),
        "geocode_distance_m": distance,
        "seeded_at": entry["decision"].get("decided_at"),
    }


def _candidate_of(entry: Mapping[str, Any]) -> Mapping[str, Any] | None:
    index = entry["decision"].get("candidate")
    if index is None:
        return None
    try:
        return entry["candidates"][index]
    except (IndexError, TypeError):
        return None


def render_csv_rows(
    entries: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Decision → CSV row for every **decided** entry, plus one provenance
    entry per ``auto`` row. ``pending`` entries are not written.

    | status     | source      | precision                  | verification |
    | ---------- | ----------- | -------------------------- | ------------ |
    | auto       | candidate's | building                   | auto         |
    | accepted   | candidate's | building                   | human        |
    | pinned     | manual      | building or approximate    | human        |
    | no_pin     | manual      | none                       | human        |
    """
    rows: list[dict[str, Any]] = []
    provenance: dict[str, dict[str, Any]] = {}
    for entry in entries:
        decision = entry["decision"]
        status = decision["status"]
        if status not in DECIDED:
            continue
        candidate = _candidate_of(entry)
        lat, lon = decision.get("lat"), decision.get("lon")
        if lat is None and candidate is not None and status in ("auto", "accepted"):
            lat, lon = candidate["lat"], candidate["lon"]
        if status == "auto":
            source, precision, verification = "osm_poi", "building", "auto"
            record = decision.get("provenance")
            if record is None:
                if candidate is None:
                    raise ValueError(f"auto entry {entry_key(entry)} has no candidate")
                record = provenance_for(entry, candidate)
            provenance[provenance_key(entry["key"])] = record
        elif status == "accepted":
            source = decision.get("source") or (candidate or {}).get("source")
            precision, verification = "building", "human"
        elif status == "pinned":
            source, precision, verification = "manual", decision.get("precision") or "building", "human"
        else:  # no_pin
            source, precision, verification = "manual", "none", "human"
            lat = lon = None
        rows.append(
            {
                **{field: entry["key"][field] for field in KEY_FIELDS},
                "lat": _coord(lat),
                "lon": _coord(lon),
                "precision": precision,
                "source": source,
                "verification": verification,
                "verified_at": decision.get("decided_at"),
            }
        )
    return rows, provenance


def decisions_from_files(
    rows: Iterable[Mapping[str, Any]], provenance: Mapping[str, dict[str, Any]]
) -> dict[Key, dict[str, Any]]:
    """Rebuild each decision from a committed CSV row: ``auto`` → ``auto`` with
    its provenance entry; ``human`` + ``manual`` + coordinate → ``pinned``;
    ``human`` + ``manual`` + none → ``no_pin``; ``human`` + ``osm_poi`` /
    ``nominatim`` → ``accepted``."""
    decisions: dict[Key, dict[str, Any]] = {}
    for row in rows:
        key: Key = tuple(str(row[field]) for field in KEY_FIELDS)  # type: ignore[assignment]
        verified_at = row.get("verified_at")
        decided_at = verified_at.isoformat() if isinstance(verified_at, date) else verified_at
        lat, lon = _coord(row.get("lat")), _coord(row.get("lon"))
        if row["verification"] == "auto":
            decisions[key] = make_decision(
                "auto",
                lat=lat,
                lon=lon,
                source="osm_poi",
                precision="building",
                decided_at=decided_at,
                provenance=provenance.get(provenance_key(key)),
            )
        elif row["source"] == "manual":
            decisions[key] = make_decision(
                "no_pin" if lat is None else "pinned",
                lat=lat,
                lon=lon,
                source="manual",
                precision=row["precision"],
                decided_at=decided_at,
            )
        else:
            decisions[key] = make_decision(
                "accepted",
                lat=lat,
                lon=lon,
                source=row["source"],
                precision=row["precision"],
                decided_at=decided_at,
            )
    return decisions


def source_hash(csv_bytes: bytes | None, provenance_bytes: bytes | None) -> str | None:
    if csv_bytes is None:
        return None
    digest = hashlib.sha256()
    digest.update(csv_bytes)
    digest.update(b"\n--provenance--\n")
    digest.update(provenance_bytes or b"")
    return digest.hexdigest()


def committed_hash(csv_path: Path, provenance_path: Path) -> str | None:
    """The hash of the committed files as they are on disk now."""
    if not csv_path.exists():
        return None
    return source_hash(
        csv_path.read_bytes(),
        provenance_path.read_bytes() if provenance_path.exists() else None,
    )


def reconcile(
    doc: Mapping[str, Any] | None,
    committed_rows: Iterable[Mapping[str, Any]],
    committed_provenance: Mapping[str, dict[str, Any]],
    committed_hash_value: str | None,
) -> tuple[dict[Key, dict[str, Any]], bool]:
    """Apply the lineage rule. Returns ``(entries_by_key, rebuilt)``.

    With a matching hash the local decisions stand. Otherwise every decision
    is rebuilt from the committed files; local entries keep their
    candidates and flags, and a local entry with no committed row becomes
    ``pending``.
    """
    local: dict[Key, dict[str, Any]] = {
        entry_key(e): dict(e) for e in (doc or {}).get("entries", [])
    }
    if doc is not None and doc.get("source_hash") == committed_hash_value:
        return local, False

    entries: dict[Key, dict[str, Any]] = {}
    for key, decision in decisions_from_files(committed_rows, committed_provenance).items():
        base = local.get(key)
        entry = {
            "key": key_dict(key),
            "name": base.get("name", "") if base else "",
            "address_settlement": base.get("address_settlement") if base else None,
            "candidates": list(base.get("candidates", [])) if base else [],
            "flags": list(base.get("flags", [])) if base else [],
            "decision": decision,
        }
        decision["candidate"] = resolve_candidate_index(decision, entry["candidates"])
        entries[key] = entry
    for key, base in local.items():
        if key not in entries:
            entries[key] = {**base, "decision": make_decision("pending")}
    return entries, True


def load_candidates(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        os.chmod(tmp_name, 0o644)  # mkstemp creates 0600; these are committed files
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def save_candidates(
    path: Path, entries: Iterable[Mapping[str, Any]], source_hash_value: str | None
) -> None:
    ordered = sorted(entries, key=entry_key)
    doc = {"source_hash": source_hash_value, "entries": ordered}
    _atomic_write(path, json.dumps(doc, ensure_ascii=False, indent=1) + "\n")


def persist(
    entries: Iterable[Mapping[str, Any]],
    *,
    candidates_path: Path,
    csv_path: Path,
    provenance_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """The one save path for both writers: candidates file first (the commit
    point, stamped with the hash of the committed files it was derived
    from), then the CSV and provenance file through the loader's validating
    writer, then the candidates file again with the new hash.

    A crash between the first and second write leaves a matching hash, so
    the next start regenerates the derived files from the candidates file;
    a crash between the second and third leaves a mismatch, and the next
    start rebuilds from the committed files, which already carry the
    decision. Nothing is lost either way.
    """
    from yasli.ingest.institution_locations_loader import write_file  # local: keeps import light

    entries = [dict(e) for e in entries]
    rows, provenance = render_csv_rows(entries)
    save_candidates(candidates_path, entries, committed_hash(csv_path, provenance_path))
    write_file(csv_path, rows, provenance, provenance_path=provenance_path)
    save_candidates(candidates_path, entries, committed_hash(csv_path, provenance_path))
    return rows, provenance


# --- review tool: transitions, validation, page state --------------------------------


#: Plain words for each flag, for the worklist chips. Two are filled in from
#: the entry: the settlement pair and the candidate spread.
FLAG_TEXT: dict[str, str] = {
    "no_candidate": "no match found",
    "ambiguous_title": "more than one place carries this title",
    "geocoder_only": "only the geocoder found something",
    "outside_municipality": "a candidate lies outside Varna municipality",
    "settlement_mismatch": "pin is in {settlement}, address says {address_settlement}",
    "candidates_disagree": "{n} candidates {d} m apart",
    "branch": "branch building",
    "name_only_branch": "name-only branch: no address to search",
    "reverse_geocode_failed": "could not tell which settlement the pin is in",
    "address_changed": "the institution's address changed since this was decided",
}

HUMAN_STATUSES: tuple[str, ...] = ("accepted", "pinned", "no_pin", "pending")


def reasons_for(entry: Mapping[str, Any]) -> list[str]:
    reasons = []
    candidates = entry.get("candidates", [])
    for flag in entry.get("flags", []):
        text = FLAG_TEXT.get(flag, flag)
        if flag == "settlement_mismatch":
            address_settlement = entry.get("address_settlement") or "?"
            mismatch = next(
                (
                    c["settlement"]
                    for c in candidates
                    if c.get("in_municipality")
                    and c.get("settlement")
                    and c["settlement"].casefold() != str(address_settlement).casefold()
                ),
                "?",
            )
            text = text.format(settlement=mismatch, address_settlement=address_settlement)
        elif flag == "candidates_disagree":
            spread = max(
                (c.get("distance_m") or 0 for c in candidates if c.get("source") == "nominatim"),
                default=0,
            )
            text = text.format(n=len(candidates), d=spread)
        reasons.append(text)
    return reasons


def apply_decision(
    entry: Mapping[str, Any], request: Mapping[str, Any], *, today: str
) -> dict[str, Any]:
    """A person's decision on one entry — ``accepted`` (a candidate index),
    ``pinned`` (a coordinate, ``building`` or ``approximate``), ``no_pin``,
    or back to ``pending``. Returns a new entry; never mutates the input.
    Malformed requests raise ``ValueError``; ``auto`` is not a human
    decision and is refused."""
    status = request.get("status")
    if status not in HUMAN_STATUSES:
        raise ValueError(f"unknown decision status {status!r}")
    candidates = list(entry.get("candidates", []))
    if status == "accepted":
        index = request.get("candidate")
        if index is None:
            raise ValueError("accepted needs a candidate index")
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(candidates):
            raise ValueError(f"candidate index {index!r} is out of range")
        chosen = candidates[index]
        decision = make_decision(
            "accepted",
            candidate=index,
            lat=chosen["lat"],
            lon=chosen["lon"],
            source=chosen["source"],
            precision="building",
            decided_at=today,
        )
    elif status == "pinned":
        lat, lon = request.get("lat"), request.get("lon")
        if lat is None or lon is None:
            raise ValueError("pinned needs lat and lon")
        precision = request.get("precision") or "building"
        if precision not in ("building", "approximate"):
            raise ValueError(f"precision {precision!r} must be 'building' or 'approximate'")
        decision = make_decision(
            "pinned",
            lat=float(lat),
            lon=float(lon),
            source="manual",
            precision=precision,
            decided_at=today,
        )
    elif status == "no_pin":
        decision = make_decision("no_pin", source="manual", precision="none", decided_at=today)
    else:
        decision = make_decision("pending")
    new_entry = json.loads(json.dumps(entry))
    new_entry["decision"] = decision
    return new_entry


def validate(
    entries: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Render the decided entries and run them through the loader's parser —
    the same checks ``write_file`` applies, without writing."""
    import csv
    import io

    from yasli.ingest.institution_locations_loader import parse_rows, render_csv

    rows, provenance = render_csv_rows(entries)
    list(parse_rows(csv.DictReader(io.StringIO(render_csv(rows))), provenance))
    return rows, provenance


_STATUS_ORDER = {"pending": 0, "auto": 1, "accepted": 2, "pinned": 2, "no_pin": 2}


def counts_for(entries: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    counts = {"pending": 0, "auto": 0, "done": 0, "all": 0}
    for entry in entries:
        status = entry["decision"]["status"]
        counts["all"] += 1
        if status == "pending":
            counts["pending"] += 1
        elif status == "auto":
            counts["auto"] += 1
        else:
            counts["done"] += 1
    return counts


def with_reasons(entry: Mapping[str, Any]) -> dict[str, Any]:
    return {**entry, "reasons": reasons_for(entry)}


def build_state(entries: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """The ``GET /api/state`` payload: entries pending-first, counts per tab,
    and the municipality outline for the map."""
    from yasli.ingest.municipality import municipality_geojson

    ordered = sorted(
        entries, key=lambda e: (_STATUS_ORDER.get(e["decision"]["status"], 3), entry_key(e))
    )
    return {
        "entries": [with_reasons(e) for e in ordered],
        "counts": counts_for(ordered),
        "municipality": municipality_geojson(),
    }
