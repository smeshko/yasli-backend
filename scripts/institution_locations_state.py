"""State helpers for the institution locations seed script: the candidates
file, the decision → CSV row mapping, and the lineage rule between local
working state and the committed files.

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

**Lineage rule.** Within a run the candidates file is the commit point:
every save writes it atomically, then regenerates the CSV and the provenance
file from it, then rewrites its ``source_hash``. Across runs the
committed CSV + provenance are the record: on a seed re-run, a
matching hash means the candidates file is in sync or ahead (a crash between
the writes) and its decisions stand; a mismatch, or no candidates file at
all, rebuilds every decision from the committed files and keeps only
candidates and flags from local state. A stale local file can never revert a
newer committed one. The one pair the strict parser must not be asked to
read — a new CSV next to the previous provenance file, left by a crash
between ``write_file``'s two renames — is recognised by
:func:`load_committed` from a journal ``persist`` stamps on the candidates
file before the renames (``pending_write``: the hashes of the CSV and the
provenance file about to be written, and of the provenance file on disk at
that moment) and repaired from the candidates file. The journal is cleared
once both renames landed, so in steady state no parse failure is ever
"repaired".

Only decided entries — ``auto``, ``accepted``, ``pinned``, ``no_pin`` — are
written to the CSV. A ``pending`` row is simply absent, and the loader's
missing-``main`` guard is what surfaces it. A person resolves it by writing
the row into the CSV by hand; the next seed run rebuilds that decision from
the committed file (:func:`decisions_from_files`).
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


def load_committed(
    csv_path: Path, provenance_path: Path, doc: Mapping[str, Any] | None
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], str | None, bool]:
    """Parse the committed pair for :func:`reconcile`: ``(rows, provenance,
    hash, torn)``.

    ``torn`` is the one parse failure that is repaired rather than raised:
    a crash between ``write_file``'s two renames leaves a new CSV next to
    the previous provenance file, which the parser's provenance cross-check
    rejects. It is recognised from the journal, never guessed: the
    candidates file still carries the ``pending_write`` record ``persist``
    stamped before the renames (it is cleared once both landed), the CSV
    on disk hashes to the CSV that record said was about to be written,
    and the provenance file hashes to the one the record says was on disk
    at the time. The caller keeps the local decisions and regenerates both
    files. Every other parse failure propagates — no journal, a CSV edited
    since, a provenance file that is neither the previous nor the intended
    one — so a hand-corrupted committed file is never silently overwritten.
    """
    from yasli.ingest.institution_locations_loader import (
        LocationRowError,
        load_provenance,
        parse_file,
    )

    if not csv_path.exists():
        return [], load_provenance(provenance_path), None, False
    try:
        rows = list(parse_file(csv_path, provenance_path=provenance_path))
    except LocationRowError:
        if doc is not None and _torn_by_journal(doc.get("pending_write"), csv_path, provenance_path):
            return [], {}, None, True
        raise
    provenance = load_provenance(provenance_path)
    return rows, provenance, committed_hash(csv_path, provenance_path), False


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_sha256(path: Path) -> str:
    return _sha256(path.read_bytes() if path.exists() else b"")


def pending_write(csv_text: str, provenance_text: str, provenance_path: Path) -> dict[str, str]:
    """The journal entry ``persist`` stamps on the candidates file before
    the two renames: what the CSV and the provenance file are about to
    become, and what the provenance file is right now."""
    return {
        "csv": _sha256(csv_text.encode("utf-8")),
        "provenance": _sha256(provenance_text.encode("utf-8")),
        "previous_provenance": _file_sha256(provenance_path),
    }


def _torn_by_journal(journal: Any, csv_path: Path, provenance_path: Path) -> bool:
    """True only for the pair an interrupted ``persist`` leaves: the CSV is
    the one the journal said it was about to write, and the provenance
    file is the one that was on disk when it started."""
    if not isinstance(journal, dict):
        return False
    return (
        _file_sha256(csv_path) == journal.get("csv")
        and _file_sha256(provenance_path) == journal.get("previous_provenance")
    )


def reconcile(
    doc: Mapping[str, Any] | None,
    committed_rows: Iterable[Mapping[str, Any]],
    committed_provenance: Mapping[str, dict[str, Any]],
    committed_hash_value: str | None,
    *,
    torn: bool = False,
) -> tuple[dict[Key, dict[str, Any]], bool]:
    """Apply the lineage rule. Returns ``(entries_by_key, rebuilt)``.

    With a matching hash — or a committed pair :func:`load_committed`
    found torn — the local decisions stand. Otherwise every decision is
    rebuilt from the committed files; local entries keep their candidates
    and flags, and a local entry with no committed row becomes ``pending``.
    """
    local: dict[Key, dict[str, Any]] = {
        entry_key(e): dict(e) for e in (doc or {}).get("entries", [])
    }
    if doc is not None and (torn or doc.get("source_hash") == committed_hash_value):
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
    path: Path,
    entries: Iterable[Mapping[str, Any]],
    source_hash_value: str | None,
    pending: Mapping[str, str] | None = None,
) -> None:
    """``pending`` is the :func:`pending_write` journal, present only
    between ``persist``'s first write and its last."""
    ordered = sorted(entries, key=entry_key)
    doc = {"source_hash": source_hash_value, "pending_write": pending, "entries": ordered}
    _atomic_write(path, json.dumps(doc, ensure_ascii=False, indent=1) + "\n")


def persist(
    entries: Iterable[Mapping[str, Any]],
    *,
    candidates_path: Path,
    csv_path: Path,
    provenance_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """The one save path: candidates file first (the commit
    point, stamped with the hash of the committed files it was derived
    from), then the CSV and provenance file through the loader's validating
    writer, then the candidates file again with the new hash.

    A crash between the first and second write leaves a matching hash, so
    the next run regenerates the derived files from the candidates file;
    a crash between the second and third leaves a mismatch, and the next
    run rebuilds from the committed files, which already carry the
    decision; a crash inside the second, between the CSV rename and the
    provenance rename, leaves a torn pair that :func:`load_committed`
    recognises from the ``pending_write`` journal the first write stamped
    (cleared by the third) and the next run regenerates from the
    candidates file. Nothing is lost in any of the three.
    """
    from yasli.ingest.institution_locations_loader import (  # local: keeps import light
        render_csv,
        render_provenance,
        write_file,
    )

    entries = [dict(e) for e in entries]
    rows, provenance = render_csv_rows(entries)
    journal = pending_write(render_csv(rows), render_provenance(provenance), provenance_path)
    save_candidates(candidates_path, entries, committed_hash(csv_path, provenance_path), journal)
    write_file(csv_path, rows, provenance, provenance_path=provenance_path)
    save_candidates(candidates_path, entries, committed_hash(csv_path, provenance_path))
    return rows, provenance
