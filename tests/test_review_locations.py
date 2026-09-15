"""The local review tool: pure state transitions plus a server round-trip on
an ephemeral port against programmatic fixture candidates. No external
network — Leaflet and tiles are only loaded by a browser, never here."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from scripts import review_locations as review
from scripts.location_review import state
from yasli.ingest.institution_locations_loader import LocationRowError, parse_file

VARNA = "Варна"
TODAY = "2026-09-15"
AKSAKOVO = (43.258626, 27.817361)


def _poi(lat=43.2096, lon=27.9270, *, settlement=VARNA, inside=True, osm="way/1"):
    return {"source": "osm_poi", "lat": lat, "lon": lon, "osm": osm, "osm_name": "ДГ Мир №13",
            "amenity": "kindergarten", "title_matches": 1, "settlement": settlement,
            "in_municipality": inside}


def _geo(lat=43.2097, lon=27.9271, *, settlement=VARNA, inside=True, distance=13):
    return {"source": "nominatim", "lat": lat, "lon": lon, "place_rank": 30,
            "settlement": settlement, "in_municipality": inside, "distance_m": distance}


def _entry(kind, external_id, name, role, address, *, label="", candidates=(), flags=(),
           decision=None):
    return {
        "key": {"kind": kind, "external_id": external_id, "role": role, "label": label,
                "address": address},
        "name": name,
        "address_settlement": VARNA if address else None,
        "candidates": list(candidates),
        "flags": list(flags),
        "decision": decision or state.make_decision("pending"),
    }


def _fixture_entries() -> list[dict]:
    auto = _entry("kindergarten", "38", 'ДГ№5 "Слънчо"', "main", "ул. Х 1",
                  candidates=[_poi(43.2120, 27.9300, osm="way/5")],
                  decision=state.make_decision("auto", candidate=0, lat=43.2120, lon=27.9300,
                                               source="osm_poi", precision="building",
                                               decided_at=TODAY))
    auto["decision"]["provenance"] = state.provenance_for(auto, auto["candidates"][0])
    branches = [
        _entry("kindergarten", "46", 'ДГ№13 "Мир"', "branch", address,
               candidates=[_geo(43.2100 + i * 0.001, 27.9200)], flags=["branch"])
        for i, address in enumerate(
            ("ул. Н. Михайловски 1А", "ул. Тодор Икономов, 26", "ул. Тодор Икономов 36",
             "бул. Княз Борис I, 109")
        )
    ]
    return [
        _entry("kindergarten", "46", 'ДГ№13 "Мир"', "main", 'ул. "Никола Михайловски" №6',
               candidates=[_poi(), _geo(lat=43.2136, distance=442)],
               flags=["candidates_disagree"]),
        _entry("kindergarten", "56", 'ДГ№23 "Иглика"', "main", 'кв. Виница, ул. "Лазур" №2',
               candidates=[_geo(43.161943, 27.782844, settlement="Константиново")],
               flags=["geocoder_only", "settlement_mismatch"]),
        auto,
        *branches,
        _entry("kindergarten", "50", 'ДГ№17 "Петър Берон"', "branch", "", label="Жирафче",
               flags=["branch", "name_only_branch"]),
    ]


@pytest.fixture
def paths(tmp_path: Path) -> dict[str, Path]:
    p = {
        "candidates": tmp_path / "institution_locations.candidates.json",
        "csv": tmp_path / "institution_locations.csv",
        "provenance": tmp_path / "institution_locations.provenance.json",
    }
    state.persist(_fixture_entries(), candidates_path=p["candidates"], csv_path=p["csv"],
                  provenance_path=p["provenance"])
    return p


def _snapshot(paths: dict[str, Path]) -> dict[str, bytes]:
    return {name: path.read_bytes() for name, path in paths.items()}


# --- pure transitions ---------------------------------------------------------------------


def _main_entry():
    return _fixture_entries()[0]


def test_apply_decision_accepted_uses_the_candidate() -> None:
    entry = state.apply_decision(_main_entry(), {"status": "accepted", "candidate": 1}, today=TODAY)
    (row,), _ = state.render_csv_rows([entry])
    assert (row["source"], row["precision"], row["verification"]) == ("nominatim", "building", "human")
    assert (row["lat"], row["lon"], row["verified_at"]) == (43.2136, 27.9271, TODAY)
    assert entry["decision"]["candidate"] == 1


def test_apply_decision_pinned_defaults_to_building_and_can_be_approximate() -> None:
    pinned = state.apply_decision(_main_entry(), {"status": "pinned", "lat": 43.21, "lon": 27.92},
                                  today=TODAY)
    (row,), _ = state.render_csv_rows([pinned])
    assert (row["source"], row["precision"], row["lat"], row["lon"]) == ("manual", "building", 43.21, 27.92)
    approx = state.apply_decision(
        _main_entry(), {"status": "pinned", "lat": 43.21, "lon": 27.92, "precision": "approximate"},
        today=TODAY,
    )
    (row,), _ = state.render_csv_rows([approx])
    assert row["precision"] == "approximate"


def test_apply_decision_no_pin_and_pending() -> None:
    no_pin = state.apply_decision(_main_entry(), {"status": "no_pin"}, today=TODAY)
    (row,), _ = state.render_csv_rows([no_pin])
    assert (row["source"], row["precision"], row["lat"], row["verification"]) == ("manual", "none", None, "human")
    pending = state.apply_decision(no_pin, {"status": "pending"}, today=TODAY)
    rows, _ = state.render_csv_rows([pending])
    assert rows == []


@pytest.mark.parametrize(
    "request_body",
    [
        {"status": "maybe"},
        {"status": "accepted"},
        {"status": "accepted", "candidate": 7},
        {"status": "pinned", "lat": 43.21},
        {"status": "pinned", "lat": 43.21, "lon": 27.92, "precision": "street"},
        {"status": "auto", "candidate": 0},
    ],
    ids=["unknown", "accepted-no-candidate", "candidate-out-of-range", "pinned-half", "bad-precision",
         "auto-is-not-a-human-decision"],
)
def test_apply_decision_rejects_malformed_requests(request_body) -> None:
    with pytest.raises(ValueError):
        state.apply_decision(_main_entry(), request_body, today=TODAY)


def test_apply_decision_does_not_mutate_the_input() -> None:
    entry = _main_entry()
    before = json.dumps(entry, sort_keys=True)
    state.apply_decision(entry, {"status": "no_pin"}, today=TODAY)
    assert json.dumps(entry, sort_keys=True) == before


def test_validate_rejects_an_out_of_polygon_pin_without_writing() -> None:
    bad = state.apply_decision(_main_entry(), {"status": "pinned", "lat": AKSAKOVO[0], "lon": AKSAKOVO[1]},
                               today=TODAY)
    with pytest.raises(LocationRowError) as info:
        state.validate([bad])
    assert "municipality" in str(info.value)


def test_build_state_lists_pending_first_with_counts_and_plain_reasons() -> None:
    payload = state.build_state(_fixture_entries())
    statuses = [e["decision"]["status"] for e in payload["entries"]]
    assert statuses == ["pending"] * 7 + ["auto"]
    assert payload["counts"] == {"pending": 7, "auto": 1, "done": 0, "all": 8}
    assert payload["municipality"]["geometry"]["type"] == "Polygon"
    by_addr = {e["key"]["address"]: e for e in payload["entries"]}
    assert by_addr['кв. Виница, ул. "Лазур" №2']["reasons"] == [
        "only the geocoder found something",
        "pin is in Константиново, address says Варна",
    ]
    assert by_addr['ул. "Никола Михайловски" №6']["reasons"] == ["2 candidates 442 m apart"]
    assert by_addr[""]["reasons"] == ["branch building", "name-only branch: no address to search"]


# --- server round-trip ----------------------------------------------------------------------


@pytest.fixture
def server(paths):
    srv = review.create_server(
        candidates_path=paths["candidates"], csv_path=paths["csv"],
        provenance_path=paths["provenance"], port=0,
    )
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()


def _url(srv, path: str) -> str:
    host, port = srv.server_address[:2]
    return f"http://{host}:{port}{path}"


def _get(srv, path: str):
    with urllib.request.urlopen(_url(srv, path), timeout=10) as response:
        return response.status, response.headers.get("Content-Type", ""), response.read()


def _post(srv, path: str, body: dict):
    request = urllib.request.Request(
        _url(srv, path), data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _key(kind="kindergarten", external_id="46", role="main", label="", address='ул. "Никола Михайловски" №6'):
    return {"kind": kind, "external_id": external_id, "role": role, "label": label, "address": address}


def test_server_binds_loopback_only_and_serves_the_page(server) -> None:
    assert server.server_address[0] == "127.0.0.1"
    status, content_type, body = _get(server, "/")
    assert status == 200 and content_type.startswith("text/html")
    assert b"leaflet" in body.lower()
    assert b"nominatim" not in body.lower() and b"overpass" not in body.lower()


def test_state_endpoint_lists_pending_first_with_counts(server) -> None:
    status, _, body = _get(server, "/api/state")
    assert status == 200
    payload = json.loads(body)
    assert payload["counts"] == {"pending": 7, "auto": 1, "done": 0, "all": 8}
    assert payload["entries"][0]["decision"]["status"] == "pending"
    assert payload["entries"][-1]["decision"]["status"] == "auto"


def test_decision_lands_in_the_csv_and_passes_the_parser(server, paths) -> None:
    status, payload = _post(server, "/api/decision", {"key": _key(), "status": "accepted", "candidate": 0})
    assert status == 200, payload
    assert payload["entry"]["decision"]["status"] == "accepted"
    assert payload["counts"] == {"pending": 6, "auto": 1, "done": 1, "all": 8}
    rows = {r["address"]: r for r in parse_file(paths["csv"])}
    row = rows['ул. "Никола Михайловски" №6']
    assert (row["source"], row["verification"], str(row["lat"]), str(row["lon"])) == (
        "osm_poi", "human", "43.209600", "27.927000")


def test_pin_click_drag_and_no_pin_each_write_the_right_row(server, paths) -> None:
    _post(server, "/api/decision", {"key": _key(), "status": "pinned", "lat": 43.2101, "lon": 27.9201})
    _post(server, "/api/decision", {"key": _key(external_id="56", address='кв. Виница, ул. "Лазур" №2'),
                                    "status": "pinned", "lat": 43.2300, "lon": 27.8700,
                                    "precision": "approximate"})
    _post(server, "/api/decision", {"key": _key(external_id="50", role="branch", label="Жирафче", address=""),
                                    "status": "no_pin"})
    rows = {(r["external_id"], r["address"]): r for r in parse_file(paths["csv"])}
    pinned = rows[("46", 'ул. "Никола Михайловски" №6')]
    assert (pinned["source"], pinned["precision"], str(pinned["lat"])) == ("manual", "building", "43.210100")
    approx = rows[("56", 'кв. Виница, ул. "Лазур" №2')]
    assert (approx["source"], approx["precision"]) == ("manual", "approximate")
    no_pin = rows[("50", "")]
    assert (no_pin["source"], no_pin["precision"], no_pin["lat"], no_pin["label"]) == (
        "manual", "none", None, "Жирафче")


def test_pending_rows_are_absent_and_a_branch_decision_changes_only_that_branch(server, paths) -> None:
    before = list(parse_file(paths["csv"]))
    assert [r["role"] for r in before] == ["main"]  # only the auto row
    status, _ = _post(server, "/api/decision", {
        "key": _key(role="branch", address="ул. Тодор Икономов 36"), "status": "accepted", "candidate": 0})
    assert status == 200
    after = list(parse_file(paths["csv"]))
    assert len(after) == 2
    new = [r for r in after if r["role"] == "branch"]
    assert [r["address"] for r in new] == ["ул. Тодор Икономов 36"]


def test_out_of_polygon_pin_is_refused_with_the_parser_message_and_nothing_written(server, paths) -> None:
    before = _snapshot(paths)
    status, payload = _post(server, "/api/decision", {"key": _key(), "status": "pinned",
                                                      "lat": AKSAKOVO[0], "lon": AKSAKOVO[1]})
    assert status == 422
    assert "municipality" in payload["error"]
    assert payload["line"] is not None
    assert _snapshot(paths) == before
    _, _, body = _get(server, "/api/state")
    entry = next(e for e in json.loads(body)["entries"] if e["key"] == _key())
    assert entry["decision"]["status"] == "pending"


def test_unknown_key_and_malformed_body_are_4xx(server) -> None:
    status, payload = _post(server, "/api/decision", {"key": _key(external_id="999"), "status": "no_pin"})
    assert status == 404
    status, payload = _post(server, "/api/decision", {"key": _key(), "status": "accepted"})
    assert status == 400
    assert "candidate" in payload["error"]


def test_undo_reverts_all_three_files_to_their_original_bytes(server, paths) -> None:
    before = _snapshot(paths)
    status, _ = _post(server, "/api/decision", {"key": _key(), "status": "no_pin"})
    assert status == 200
    assert _snapshot(paths) != before
    status, payload = _post(server, "/api/undo", {})
    assert status == 200
    assert payload["entry"]["decision"]["status"] == "pending"
    assert _snapshot(paths) == before
    status, _ = _post(server, "/api/undo", {})
    assert status == 409


def test_restart_resumes_with_every_decision_intact(paths) -> None:
    first = review.create_server(candidates_path=paths["candidates"], csv_path=paths["csv"],
                                 provenance_path=paths["provenance"], port=0)
    t = threading.Thread(target=first.serve_forever, daemon=True)
    t.start()
    _post(first, "/api/decision", {"key": _key(), "status": "no_pin"})
    first.shutdown()
    first.server_close()

    second = review.create_server(candidates_path=paths["candidates"], csv_path=paths["csv"],
                                  provenance_path=paths["provenance"], port=0)
    t = threading.Thread(target=second.serve_forever, daemon=True)
    t.start()
    try:
        _, _, body = _get(second, "/api/state")
    finally:
        second.shutdown()
        second.server_close()
    entry = next(e for e in json.loads(body)["entries"] if e["key"] == _key())
    assert entry["decision"]["status"] == "no_pin"


def test_crash_between_the_candidates_write_and_the_derived_writes_is_repaired_on_restart(
    paths, server, monkeypatch
) -> None:
    from yasli.ingest import institution_locations_loader as loader

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(loader, "write_file", boom)
    csv_before = paths["csv"].read_bytes()
    status, payload = _post(server, "/api/decision", {"key": _key(), "status": "no_pin"})
    assert status == 500
    assert paths["csv"].read_bytes() == csv_before  # stale: the decision is only in the candidates file
    doc = json.loads(paths["candidates"].read_text(encoding="utf-8"))
    assert doc["source_hash"] == state.committed_hash(paths["csv"], paths["provenance"])
    assert any(e["decision"]["status"] == "no_pin" for e in doc["entries"])
    monkeypatch.undo()

    restarted = review.create_server(candidates_path=paths["candidates"], csv_path=paths["csv"],
                                     provenance_path=paths["provenance"], port=0)
    restarted.server_close()
    rows = {r["address"]: r for r in parse_file(paths["csv"])}
    assert rows['ул. "Никола Михайловски" №6']["precision"] == "none"


def _accept_the_auto_row(entries: list[dict]) -> list[dict]:
    """The decision that must delete a provenance entry: the fixture's one
    ``auto`` row confirmed by a person becomes ``osm_poi`` + ``human``."""
    entries = [dict(e) for e in entries]
    i = next(i for i, e in enumerate(entries) if e["decision"]["status"] == "auto")
    entries[i] = state.apply_decision(entries[i], {"status": "accepted", "candidate": 0},
                                      today=TODAY)
    return entries


def _tear_the_pair(paths: dict[str, Path]) -> list[dict]:
    """Simulate a crash between write_file's two renames: the candidates
    file (old hash) and the CSV carry the new decision, the provenance file
    is from the previous save."""
    from yasli.ingest.institution_locations_loader import render_csv

    entries = _accept_the_auto_row(_fixture_entries())
    rows, _provenance = state.render_csv_rows(entries)
    state.save_candidates(paths["candidates"], entries,
                          state.committed_hash(paths["csv"], paths["provenance"]))
    state._atomic_write(paths["csv"], render_csv(rows))
    with pytest.raises(LocationRowError, match="stale provenance"):
        list(parse_file(paths["csv"], provenance_path=paths["provenance"]))
    return entries


def test_crash_between_the_csv_and_provenance_renames_is_repaired_on_restart(paths) -> None:
    _tear_the_pair(paths)
    doc = json.loads(paths["candidates"].read_text(encoding="utf-8"))
    assert doc["source_hash"] != state.committed_hash(paths["csv"], paths["provenance"])

    restarted = review.create_server(candidates_path=paths["candidates"], csv_path=paths["csv"],
                                     provenance_path=paths["provenance"], port=0)
    restarted.server_close()
    rows = {(r["kind"], r["external_id"], r["role"]): r
            for r in parse_file(paths["csv"], provenance_path=paths["provenance"])}
    assert rows[("kindergarten", "38", "main")]["verification"] == "human"
    assert json.loads(paths["provenance"].read_text(encoding="utf-8")) == {}
    doc = json.loads(paths["candidates"].read_text(encoding="utf-8"))
    assert doc["source_hash"] == state.committed_hash(paths["csv"], paths["provenance"])


def test_load_committed_reports_a_torn_pair_only_when_local_state_vouches_for_it(paths) -> None:
    entries = _tear_the_pair(paths)
    doc = {"source_hash": None, "entries": entries}
    rows, provenance, hash_value, torn = state.load_committed(paths["csv"], paths["provenance"], doc)
    assert torn and rows == [] and provenance == {} and hash_value is None
    # The same torn pair with a candidates file that does not match either
    # file — or none at all — is a corrupted committed file, and propagates.
    stale = {"source_hash": None, "entries": _fixture_entries()}
    with pytest.raises(LocationRowError, match="stale provenance"):
        state.load_committed(paths["csv"], paths["provenance"], stale)
    with pytest.raises(LocationRowError, match="stale provenance"):
        state.load_committed(paths["csv"], paths["provenance"], None)


def test_a_hand_corrupted_committed_file_is_never_overwritten_by_local_state(paths) -> None:
    with paths["csv"].open("a", encoding="utf-8") as fh:
        fh.write("school,1,main,,x,43.2,27.9,building,manual,human,2026-09-15\n")
    before = _snapshot(paths)
    with pytest.raises(LocationRowError, match="kind 'school'"):
        review.create_server(candidates_path=paths["candidates"], csv_path=paths["csv"],
                             provenance_path=paths["provenance"], port=0)
    assert _snapshot(paths) == before


def test_stale_candidates_file_never_reverts_newer_committed_files(paths) -> None:
    # The committed files move ahead (a pull): the main row is now pinned.
    entries = _fixture_entries()
    entries[0] = state.apply_decision(entries[0], {"status": "pinned", "lat": 43.2101, "lon": 27.9201},
                                      today=TODAY)
    rows, provenance = state.render_csv_rows(entries)
    from yasli.ingest.institution_locations_loader import write_file
    write_file(paths["csv"], rows, provenance, provenance_path=paths["provenance"])
    committed = _snapshot({"csv": paths["csv"], "provenance": paths["provenance"]})
    # The local candidates file still says pending and carries an old hash.
    doc = json.loads(paths["candidates"].read_text(encoding="utf-8"))
    assert doc["source_hash"] != state.committed_hash(paths["csv"], paths["provenance"])

    srv = review.create_server(candidates_path=paths["candidates"], csv_path=paths["csv"],
                               provenance_path=paths["provenance"], port=0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        _, _, body = _get(srv, "/api/state")
    finally:
        srv.shutdown()
        srv.server_close()
    assert _snapshot({"csv": paths["csv"], "provenance": paths["provenance"]}) == committed
    entry = next(e for e in json.loads(body)["entries"] if e["key"] == _key())
    assert entry["decision"]["status"] == "pinned"
    assert entry["candidates"]  # kept from local state
    assert entry["flags"] == ["candidates_disagree"]


def test_missing_candidates_file_refuses_to_start_and_names_the_seed_script(tmp_path: Path) -> None:
    with pytest.raises(review.NoCandidatesFile) as info:
        review.create_server(candidates_path=tmp_path / "nope.json", csv_path=tmp_path / "x.csv",
                             provenance_path=tmp_path / "x.json", port=0)
    assert "scripts.seed_institution_locations" in str(info.value)


def test_nothing_under_src_imports_the_review_tool() -> None:
    src = Path(__file__).resolve().parents[1] / "src" / "yasli"
    assert not [p for p in src.rglob("*.py") if "review_locations" in p.read_text(encoding="utf-8")]
