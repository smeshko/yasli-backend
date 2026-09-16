"""Pure-helper tests for the institution locations seed script and the
shared state module. No network: every external response comes from
``scripts/fixtures/`` (captured 2026-09-15) or is inline.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest

from scripts import seed_institution_locations as seed
from scripts import institution_locations_state as state
from yasli.ingest.institution_locations_loader import LocationRowError, parse_file, parse_rows

FIXTURES = Path(__file__).resolve().parents[1] / "scripts" / "fixtures"
OVERPASS = json.loads((FIXTURES / "overpass_education.json").read_text(encoding="utf-8"))
NOMINATIM = json.loads((FIXTURES / "nominatim.json").read_text(encoding="utf-8"))
FREE_PLACES = json.loads((FIXTURES / "free_places_garden.json").read_text(encoding="utf-8"))

VARNA = "Варна"

# Candidate factories --------------------------------------------------------


def _poi(lat=43.2096, lon=27.9270, *, settlement=VARNA, inside=True, matches=1, osm="way/1"):
    return {
        "source": "osm_poi",
        "lat": lat,
        "lon": lon,
        "osm": osm,
        "osm_name": "ДГ Мир №13",
        "amenity": "kindergarten",
        "title_matches": matches,
        "settlement": settlement,
        "in_municipality": inside,
    }


def _geo(lat=43.2097, lon=27.9271, *, settlement=VARNA, inside=True):
    return {
        "source": "nominatim",
        "lat": lat,
        "lon": lon,
        "place_rank": 30,
        "settlement": settlement,
        "in_municipality": inside,
    }


# --- title extraction and POI matching --------------------------------------------


@pytest.mark.parametrize(
    ("name", "title"),
    [
        ('ДГ№4 "Теменужка"', "теменужка"),
        ('ДГ№20 "Бриз"/със специални групи/', "бриз"),
        ('ДЯ № 1 "ЩАСТЛИВО ДЕТСТВО"', "щастливо детство"),
        ('ОУ "Добри Войников" с. Каменар', "добри войников"),
        ('III ОУ "Ангел Кънчев"', "ангел кънчев"),
        ("ДГ 33 „Делфинче“", "делфинче"),
        ("ОДЗ ”Ран Босилек”", "ран босилек"),
        ('ОУ ,,Панайот Волов"', "панайот волов"),
        ("Детска ясла (ДЯ) №3 „Зайо Байо“", "зайо байо"),
        ("ДГ Мир №13", "мир"),
        ("13 ЦДГ Звездичка", "звездичка"),
        ("ЦДГ 8 - Христо Ботев", "христо ботев"),
        ("СОУ Неофит Бозвели", "неофит бозвели"),
        ("3 ОУ Ангел Кънчев", "ангел кънчев"),
        ("9. Детска ясла Детелина", "детелина"),
        ("Калина Малина", "калина малина"),
        ("Детска градина", None),
        ("", None),
    ],
)
def test_title_of(name: str, title: str | None) -> None:
    assert seed.title_of(name) == title


def test_parse_pois_reads_every_fixture_element_with_a_coordinate() -> None:
    pois = seed.parse_pois(OVERPASS)
    assert len(pois) == 171
    assert all({"osm", "name", "amenity", "lat", "lon"} <= set(p) for p in pois)
    assert all(43.10 <= p["lat"] <= 43.31 and 27.74 <= p["lon"] <= 28.06 for p in pois)
    assert any(p["osm"].startswith("way/") for p in pois)
    assert any(p["osm"].startswith("node/") for p in pois)


def test_amenity_families_match_the_plan_table() -> None:
    assert seed.AMENITY_FAMILIES == {
        "nursery": ("nursery", "childcare", "kindergarten"),
        "kindergarten": ("kindergarten", "childcare"),
        "preschool": ("school", "kindergarten"),
    }


@pytest.mark.parametrize(
    ("kind", "name", "expected_names"),
    [
        ("kindergarten", 'ДГ№13 "Мир"', ["ДГ Мир №13"]),
        ("kindergarten", 'ДГ№12 "Ян Бибиян"', ["3 ЦДГ Ян Бибиян", "Ян Бибиян"]),
        ("kindergarten", 'ДГ№4 "Теменужка"', ['ДГ-4 "Теменужка" Филиал 1', "Теменужка"]),
        ("nursery", 'ДЯ № 3 "ЗАЙО БАЙО"', ["Детска ясла (ДЯ) №3 „Зайо Байо“"]),
        ("nursery", 'ДЯ № 5 "ЧУДЕН СВЯТ"', ["5 ДЯ Чуден свят"]),
        ("preschool", 'СУ "Неофит Бозвели"', ["СОУ Неофит Бозвели"]),
        ("preschool", 'ОУ "Константин Арабаджиев"',
         ['ОУ "Константин Арабаджиев"', 'ОУ "Константин Арабаджиев" - филиал']),
        ("preschool", 'ОУ "Свети Иван Рилски"', []),
        # A nursery title must not match a school, and a preschool title must
        # not match a childcare POI: the family table gates the match.
        ("nursery", 'ДЯ № 9 "ДЕТЕЛИНА"', ["9. Детска ясла Детелина", 'ЦДГ "Детелина"']),
        ("preschool", 'СУ "Чуден свят"', []),
    ],
)
def test_poi_candidates_title_match_within_family(kind, name, expected_names) -> None:
    pois = seed.parse_pois(OVERPASS)
    found = seed.poi_candidates(kind, name, pois)
    assert sorted(c["osm_name"] for c in found) == sorted(expected_names)
    assert all(c["title_matches"] == len(expected_names) for c in found)
    assert all(c["source"] == "osm_poi" for c in found)


@pytest.mark.parametrize(
    ("parent", "label", "expected_names"),
    [
        ('ДГ№4 "Теменужка"', "", ['ДГ-4 "Теменужка" Филиал 1']),
        ('ДГ№17 "Петър Берон"', "Жирафче", ['Детска градина "Жирафче"']),
        ('ДГ№17 "Петър Берон"', "Другарче", []),
        ('ДГ№13 "Мир"', "", []),
        ('ДГ№7 "А.С.Пушкин"', "", []),  # "ЦДГ Пушкин (филиал)" carries a different title
    ],
)
def test_poi_candidates_for_branch_by_label_or_parent_title_with_филиал(parent, label, expected_names) -> None:
    pois = seed.parse_pois(OVERPASS)
    found = seed.poi_candidates_for_branch("kindergarten", parent, label, pois)
    assert sorted(c["osm_name"] for c in found) == sorted(expected_names)
    # The parent's own building is never a branch candidate.
    assert "Теменужка" not in [c["osm_name"] for c in found]


def test_title_owner_counts_flag_titles_shared_between_institutions() -> None:
    institutions = [
        ("kindergarten", "81", 'ДГ№48 "Ран Босилек"'),
        ("kindergarten", "84", 'ДГ№51 "Ран Босилек"'),
        ("kindergarten", "56", 'ДГ№23 "Иглика"'),
        ("nursery", "10", 'ДЯ № 11 "ИГЛИКА"'),
        ("kindergarten", "46", 'ДГ№13 "Мир"'),
    ]
    counts = seed.title_owner_counts(institutions)
    assert counts["ран босилек"] == 2
    assert counts["иглика"] == 2
    assert counts["мир"] == 1


# --- address helpers -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("address", "query"),
    [
        ('гр. Варна, ул."Парижка комуна" №25', "Парижка комуна 25, Варна"),
        ('бул. "Чаталджа" 111', "Чаталджа 111, Варна"),
        ("с.Каменар", "Каменар, Варна"),
        ('с. Тополи, ул. "Здравец" №1', "Тополи, Здравец 1, Варна"),
        ('гр. Варна, ж.к."Владислав Варненчик" до блок 20', "Владислав Варненчик блок 20, Варна"),
        ('гр. Варна, кв. Виница, ул. "Лазур" №2', "Виница, Лазур 2, Варна"),
        ("кв. Трошево, до бл.20", "Трошево, бл.20, Варна"),
        ('гр. Варна, ул. "Никола Михайловски" №6', "Никола Михайловски 6, Варна"),
    ],
)
def test_build_query_strips_markers_the_geocoder_chokes_on(address: str, query: str) -> None:
    assert seed.build_query(address) == query


@pytest.mark.parametrize(
    ("address", "settlement"),
    [
        ("с.Каменар", "Каменар"),
        ('с. Тополи, ул. "Здравец" №1', "Тополи"),
        ("с. Звездица, ул. Феникс 47", "Звездица"),
        ("село Константиново, ул. Х 1", "Константиново"),
        ('гр. Варна, кв. Виница, ул. "Лазур" №2', VARNA),
        ("кв. Трошево, до бл.20", VARNA),
        ('ж.к."Владислав Варненчик" до бл.20', VARNA),
        ('ул. "Славянска" 21', VARNA),
        ("", VARNA),
    ],
)
def test_settlement_from_address(address: str, settlement: str) -> None:
    assert seed.settlement_from_address(address) == settlement


@pytest.mark.parametrize(
    ("fixture", "settlement"),
    [
        ("ДГ№13 Мир POI", VARNA),
        ("Игнатиево", "Игнатиево"),
        ("Константиново", "Константиново"),
        ("Аксаково", "Аксаково"),
        ("Каменар", "Каменар"),
    ],
)
def test_settlement_from_reverse_prefers_village_then_town_then_city(fixture, settlement) -> None:
    assert seed.settlement_from_reverse(NOMINATIM["reverse"][fixture]["response"]) == settlement


def test_settlement_from_reverse_without_a_settlement_is_none() -> None:
    assert seed.settlement_from_reverse({"address": {"road": "x"}}) is None
    assert seed.settlement_from_reverse({"error": "Unable to geocode"}) is None


def test_geocode_candidates_keep_only_rank_30() -> None:
    search = NOMINATIM["search"]
    assert seed.geocode_candidates(search['бул. "Чаталджа" 111']["response"]) == []
    assert seed.geocode_candidates(search["с.Каменар"]["response"]) == []
    (hit,) = seed.geocode_candidates(search['ул. "Никола Михайловски" №6']["response"])
    assert hit["source"] == "nominatim"
    assert hit["place_rank"] == 30
    assert hit["lat"] == pytest.approx(43.2096183)
    assert hit["lon"] == pytest.approx(27.9270345)
    assert hit["settlement"] == VARNA


def test_haversine_metres() -> None:
    assert seed.haversine_m(43.2096, 27.9270, 43.2096, 27.9270) == 0
    d = seed.haversine_m(43.2096183, 27.9270345, 43.2065, 27.9142)
    assert 1050 < d < 1150


# --- the auto-accept decision -----------------------------------------------------------------


def _decide(candidates, *, role="main", address='ул. "Х" 1', owners=1, address_settlement=VARNA):
    return seed.decide(
        role=role,
        address=address,
        address_settlement=address_settlement,
        candidates=candidates,
        title_owners=owners,
    )


def test_decide_auto_only_when_all_four_rules_hold() -> None:
    status, index, flags = _decide([_poi(), _geo()])
    assert (status, index, flags) == ("auto", 0, [])


def test_decide_auto_with_no_geocode_at_all() -> None:
    assert _decide([_poi()]) == ("auto", 0, [])


@pytest.mark.parametrize(
    ("candidates", "kwargs", "flag"),
    [
        ([], {}, "no_candidate"),
        ([_geo()], {}, "geocoder_only"),
        ([_poi(matches=2, osm="way/1"), _poi(matches=2, osm="way/2")], {}, "ambiguous_title"),
        ([_poi()], {"owners": 2}, "ambiguous_title"),
        ([_poi(inside=False)], {}, "outside_municipality"),
        ([_poi(settlement="Константиново")], {}, "settlement_mismatch"),
        ([_poi(settlement=None)], {}, "reverse_geocode_failed"),
        ([_poi(), _geo(lat=43.2136)], {}, "candidates_disagree"),
        ([_poi()], {"role": "branch"}, "branch"),
        ([], {"role": "branch", "address": ""}, "name_only_branch"),
    ],
    ids=[
        "no-candidate",
        "geocoder-only",
        "ambiguous-pois",
        "ambiguous-owners",
        "outside",
        "settlement-mismatch",
        "reverse-failed",
        "disagree",
        "branch",
        "name-only-branch",
    ],
)
def test_decide_each_rule_failing_alone_forces_pending(candidates, kwargs, flag) -> None:
    status, index, flags = _decide(candidates, **kwargs)
    assert status == "pending"
    assert index is None
    assert flag in flags
    assert set(flags) <= set(state.FLAGS)


def test_decide_out_of_polygon_geocode_is_kept_but_not_compared() -> None:
    far_outside = _geo(lat=43.2586, lon=27.8174, settlement="Аксаково", inside=False)
    status, index, flags = _decide([_poi(), far_outside])
    assert status == "pending"
    assert flags == ["outside_municipality"]  # rule 4 did not fire on the outside hit


def test_decide_out_of_polygon_poi_is_never_accepted_even_if_unique() -> None:
    status, _, flags = _decide([_poi(inside=False, settlement="Аксаково")], address_settlement=VARNA)
    assert status == "pending"
    assert "outside_municipality" in flags


def test_measured_failures_are_flagged_not_accepted() -> None:
    # Игнатиево and Аксаково: geocoder hits outside the polygon.
    for lat, lon, town in ((43.249555, 27.774731, "Игнатиево"), (43.258626, 27.817361, "Аксаково")):
        status, _, flags = _decide([_geo(lat, lon, settlement=town, inside=False)])
        assert status == "pending"
        assert "outside_municipality" in flags
    # Константиново: inside the municipality, so only the settlement rule catches it.
    status, _, flags = _decide(
        [_geo(43.161943, 27.782844, settlement="Константиново", inside=True)],
        address='гр. Варна, кв. Виница, ул. "Лазур" №2',
    )
    assert status == "pending"
    assert "settlement_mismatch" in flags


def test_name_only_branch_flags_are_exactly_branch_and_name_only() -> None:
    status, _, flags = _decide([], role="branch", address="")
    assert status == "pending"
    assert sorted(flags) == ["branch", "name_only_branch"]


# --- branch inventory -----------------------------------------------------------------------


def test_parse_branch_rows_from_the_free_places_table() -> None:
    rows = seed.parse_branch_rows(FREE_PLACES["free-places"]["SPR_SWOBODNI_MESTA"])
    assert len(rows) == 17
    by_parent: dict[int, list] = {}
    for row in rows:
        by_parent.setdefault(row.parent_number, []).append(row)
    assert {n: len(v) for n, v in by_parent.items()} == {
        1: 1, 2: 2, 4: 1, 5: 2, 12: 1, 13: 4, 17: 2, 18: 1, 39: 2, 44: 1
    }
    name_only = sorted((r.parent_number, r.label) for r in rows if not r.address)
    assert name_only == [(17, "Другарче"), (17, "Жирафче"), (18, "Бисерче")]
    assert all(r.label == "" for r in rows if r.address)
    addresses = {(r.parent_number, r.address) for r in rows}
    assert (13, "ул. Н. Михайловски 1А") in addresses
    assert (13, "ул. Тодор Икономов, 26") in addresses
    assert (13, "ул. Тодор Икономов 36") in addresses
    assert (13, "бул. Княз Борис I, 109") in addresses
    assert (1, 'ул."Жолио Кюри"№51,вх.Г,ет.1.ап.3') in addresses
    assert (2, 'ул."Батак"№6') in addresses
    assert (2, 'ул."Батак"№8') in addresses
    assert (12, '"Добруджа"№1') in addresses
    assert (44, "ул. Кишинев № 11") in addresses
    assert (4, 'ул. "Кап. Райчо"') in addresses
    assert (39, "ж.к. „Владислав Варненчик втори микро район \" бл.209") in addresses
    assert (39, "ж.к. „Владислав Варненчик втори микро район\" бл.210") in addresses
    assert not any("яслена" in r.address for r in rows)


def test_dg_number_reads_the_kindergarten_number() -> None:
    assert seed.dg_number('ДГ№13 "Мир"') == 13
    assert seed.dg_number('ДГ№52 "Бялата лястовица"') == 52
    assert seed.dg_number('ДЯ № 4 "Приказен свят"') is None
    assert seed.dg_number('ОУ "Отец Паисий"') is None


def test_branch_entries_attach_to_the_parent_institution() -> None:
    institutions = {
        ("kindergarten", "46"): {"name": 'ДГ№13 "Мир"', "address": 'ул. "Никола Михайловски" №6'},
        ("kindergarten", "50"): {"name": 'ДГ№17 "Петър Берон"', "address": 'ул. "Роза" №27'},
    }
    rows = [
        seed.BranchRow(parent_number=13, label="", address="ул. Н. Михайловски 1А", raw="…"),
        seed.BranchRow(parent_number=17, label="Жирафче", address="", raw="…"),
        seed.BranchRow(parent_number=99, label="", address="nowhere", raw="…"),
    ]
    entries, orphans = seed.branch_entries(rows, institutions)
    assert [e["key"] for e in entries] == [
        {"kind": "kindergarten", "external_id": "46", "role": "branch", "label": "",
         "address": "ул. Н. Михайловски 1А"},
        {"kind": "kindergarten", "external_id": "50", "role": "branch", "label": "Жирафче",
         "address": ""},
    ]
    assert entries[0]["name"] == 'ДГ№13 "Мир"'
    assert orphans == [rows[2]]


# --- shared state: decision -> CSV row, lineage --------------------------------------------


def _entry(status, *, role="main", label="", address='гр. Варна, ул. "Никола Михайловски" №6',
           candidates=None, flags=None, **decision):
    candidates = [_poi(), _geo()] if candidates is None else candidates
    return {
        "key": {"kind": "kindergarten", "external_id": "46", "role": role, "label": label,
                "address": address},
        "name": 'ДГ№13 "Мир"',
        "address_settlement": VARNA,
        "candidates": candidates,
        "flags": flags or [],
        "decision": state.make_decision(status, decided_at="2026-09-15", **decision),
    }


def test_render_csv_rows_maps_each_status_and_omits_pending() -> None:
    entries = [
        _entry("auto", candidate=0),
        _entry("accepted", role="branch", address="ул. Батак 6", candidate=1),
        _entry("pinned", role="branch", address="ул. Батак 8", lat=43.21, lon=27.92,
               precision="approximate"),
        _entry("no_pin", role="branch", label="Жирафче", address="", candidates=[]),
        _entry("pending", role="branch", address="ул. Батак 10", candidates=[]),
    ]
    rows, provenance = state.render_csv_rows(entries)
    by_addr = {r["address"]: r for r in rows}
    assert set(by_addr) == {'гр. Варна, ул. "Никола Михайловски" №6', "ул. Батак 6", "ул. Батак 8", ""}
    auto = by_addr['гр. Варна, ул. "Никола Михайловски" №6']
    assert (auto["source"], auto["precision"], auto["verification"]) == ("osm_poi", "building", "auto")
    assert (auto["lat"], auto["lon"]) == (43.2096, 27.9270)
    accepted = by_addr["ул. Батак 6"]
    assert (accepted["source"], accepted["precision"], accepted["verification"]) == (
        "nominatim", "building", "human")
    assert (accepted["lat"], accepted["lon"]) == (43.2097, 27.9271)
    pinned = by_addr["ул. Батак 8"]
    assert (pinned["source"], pinned["precision"], pinned["verification"]) == (
        "manual", "approximate", "human")
    assert (pinned["lat"], pinned["lon"]) == (43.21, 27.92)
    no_pin = by_addr[""]
    assert (no_pin["source"], no_pin["precision"], no_pin["verification"]) == ("manual", "none", "human")
    assert (no_pin["lat"], no_pin["lon"], no_pin["label"]) == (None, None, "Жирафче")
    assert all(r["verified_at"] == "2026-09-15" for r in rows)

    assert set(provenance) == {"kindergarten/46"}
    entry = provenance["kindergarten/46"]
    assert entry["osm"] == "way/1"
    assert entry["amenity"] == "kindergarten"
    assert entry["title_matches"] == 1
    assert entry["in_municipality"] is True
    assert entry["settlement"] == VARNA
    assert entry["address_settlement"] == VARNA
    assert 0 < entry["geocode_distance_m"] < 20
    assert entry["seeded_at"] == "2026-09-15"


def test_render_csv_rows_output_passes_the_parser() -> None:
    rows, provenance = state.render_csv_rows([_entry("auto", candidate=0)])
    from yasli.ingest.institution_locations_loader import render_csv

    parsed = list(parse_rows(csv.DictReader(io.StringIO(render_csv(rows))), provenance))
    assert len(parsed) == 1 and parsed[0]["verification"] == "auto"


def test_render_csv_rows_auto_without_geocode_records_null_distance() -> None:
    rows, provenance = state.render_csv_rows([_entry("auto", candidate=0, candidates=[_poi()])])
    assert provenance["kindergarten/46"]["geocode_distance_m"] is None


def test_decisions_from_files_rebuilds_each_decision_kind() -> None:
    csv_text = "\n".join([
        "kind,external_id,role,label,address,lat,lon,precision,source,verification,verified_at",
        'kindergarten,46,main,,"ул. ""Никола Михайловски"" №6",43.209618,27.927035,building,osm_poi,auto,2026-09-14',
        "kindergarten,46,branch,,ул. Батак 6,43.209700,27.927100,building,nominatim,human,2026-09-14",
        "kindergarten,46,branch,,ул. Батак 8,43.210000,27.920000,approximate,manual,human,2026-09-14",
        "kindergarten,17,branch,Жирафче,,,,none,manual,human,2026-09-14",
        "",
    ])
    provenance = {"kindergarten/46": {"lat": 43.209618, "lon": 27.927035, "osm": "way/1",
                                      "amenity": "kindergarten", "title_matches": 1,
                                      "in_municipality": True, "settlement": VARNA,
                                      "address_settlement": VARNA, "geocode_distance_m": 8,
                                      "seeded_at": "2026-09-14"}}
    rows = list(parse_rows(csv.DictReader(io.StringIO(csv_text)), provenance))
    decisions = state.decisions_from_files(rows, provenance)
    auto = decisions[("kindergarten", "46", "main", "", 'ул. "Никола Михайловски" №6')]
    assert auto["status"] == "auto"
    assert (auto["lat"], auto["lon"], auto["source"], auto["precision"]) == (
        43.209618, 27.927035, "osm_poi", "building")
    assert auto["provenance"] == provenance["kindergarten/46"]
    assert auto["decided_at"] == "2026-09-14"
    accepted = decisions[("kindergarten", "46", "branch", "", "ул. Батак 6")]
    assert (accepted["status"], accepted["source"], accepted["precision"]) == (
        "accepted", "nominatim", "building")
    pinned = decisions[("kindergarten", "46", "branch", "", "ул. Батак 8")]
    assert (pinned["status"], pinned["source"], pinned["precision"], pinned["lat"]) == (
        "pinned", "manual", "approximate", 43.21)
    no_pin = decisions[("kindergarten", "17", "branch", "Жирафче", "")]
    assert (no_pin["status"], no_pin["lat"], no_pin["precision"]) == ("no_pin", None, "none")


def test_resolve_candidate_index_matches_by_coordinate_and_source() -> None:
    candidates = [_poi(), _geo()]
    assert state.resolve_candidate_index(
        state.make_decision("accepted", lat=43.2097, lon=27.9271, source="nominatim"), candidates
    ) == 1
    assert state.resolve_candidate_index(
        state.make_decision("accepted", lat=43.2097, lon=27.9271, source="osm_poi"), candidates
    ) is None
    assert state.resolve_candidate_index(
        state.make_decision("pinned", lat=43.21, lon=27.92, source="manual"), candidates
    ) is None


def test_source_hash_is_stable_and_none_without_files(tmp_path: Path) -> None:
    csv_path = tmp_path / "institution_locations.csv"
    prov_path = tmp_path / "institution_locations.provenance.json"
    assert state.committed_hash(csv_path, prov_path) is None
    csv_path.write_text("a", encoding="utf-8")
    prov_path.write_text("{}", encoding="utf-8")
    first = state.committed_hash(csv_path, prov_path)
    assert first == state.committed_hash(csv_path, prov_path)
    assert len(first) == 64
    prov_path.write_text("{ }", encoding="utf-8")
    assert state.committed_hash(csv_path, prov_path) != first


def _doc(entries, source_hash):
    return {"source_hash": source_hash, "entries": entries}


def test_reconcile_with_no_candidates_file_rebuilds_from_committed_files() -> None:
    committed_rows, committed_prov = state.render_csv_rows([_entry("auto", candidate=0)])
    entries, rebuilt = state.reconcile(None, committed_rows, committed_prov, "h1")
    assert rebuilt is True
    (entry,) = entries.values()
    assert entry["decision"]["status"] == "auto"
    assert entry["candidates"] == []  # nothing local to keep
    assert entry["flags"] == []


def test_reconcile_with_matching_hash_keeps_local_decisions() -> None:
    committed_rows, committed_prov = state.render_csv_rows([_entry("auto", candidate=0)])
    local = _entry("pinned", lat=43.21, lon=27.92, precision="building")  # ahead of the CSV
    entries, rebuilt = state.reconcile(_doc([local], "h1"), committed_rows, committed_prov, "h1")
    assert rebuilt is False
    (entry,) = entries.values()
    assert entry["decision"]["status"] == "pinned"


def test_reconcile_with_stale_hash_rebuilds_decisions_but_keeps_candidates_and_flags() -> None:
    committed_rows, committed_prov = state.render_csv_rows(
        [_entry("pinned", lat=43.21, lon=27.92, precision="building")]
    )
    local = _entry("auto", candidate=0, flags=["branch"])
    entries, rebuilt = state.reconcile(_doc([local], "old"), committed_rows, committed_prov, "new")
    assert rebuilt is True
    (entry,) = entries.values()
    assert entry["decision"]["status"] == "pinned"
    assert (entry["decision"]["lat"], entry["decision"]["lon"]) == (43.21, 27.92)
    assert entry["candidates"] == local["candidates"]
    assert entry["flags"] == ["branch"]
    # Re-rendering yields exactly the committed rows again.
    rows, prov = state.render_csv_rows(list(entries.values()))
    assert (rows, prov) == (committed_rows, committed_prov)


def test_reconcile_stale_hash_drops_local_pending_and_keeps_undecided_as_pending() -> None:
    local = _entry("pending", candidates=[_geo()], flags=["geocoder_only"])
    entries, rebuilt = state.reconcile(_doc([local], "old"), [], {}, None)
    assert rebuilt is True
    (entry,) = entries.values()
    assert entry["decision"]["status"] == "pending"
    assert entry["flags"] == ["geocoder_only"]


# --- resumability ---------------------------------------------------------------------------


def test_plan_refresh_keeps_human_decisions_and_refreshes_the_rest() -> None:
    institutions = {
        ("kindergarten", "46"): {"name": 'ДГ№13 "Мир"',
                                 "address": 'гр. Варна, ул. "Никола Михайловски" №6'},
    }
    kept = _entry("accepted", candidate=0)
    stale = _entry("auto", role="branch", address="ул. Батак 6", candidate=0)
    pending = _entry("pending", role="branch", address="ул. Батак 8", candidates=[])
    existing = {state.entry_key(e): e for e in (kept, stale, pending)}
    to_gather, kept_entries = seed.plan_refresh(existing, institutions)
    assert [e["key"]["address"] for e in kept_entries] == ['гр. Варна, ул. "Никола Михайловски" №6']
    assert sorted(k[4] for k in to_gather) == ["ул. Батак 6", "ул. Батак 8"]


def test_plan_refresh_resets_a_moved_institution_to_pending_with_address_changed() -> None:
    institutions = {
        ("kindergarten", "46"): {"name": 'ДГ№13 "Мир"', "address": 'ул. "Тодор Икономов" №26'},
    }
    kept = _entry("accepted", candidate=0)  # decided against the old address
    existing = {state.entry_key(kept): kept}
    to_gather, kept_entries = seed.plan_refresh(existing, institutions)
    assert kept_entries == []
    ((key, seeded),) = to_gather.items()
    assert key == ("kindergarten", "46", "main", "", 'ул. "Тодор Икономов" №26')
    assert seeded["flags"] == ["address_changed"]
    assert seeded["decision"]["status"] == "pending"
    assert seeded["previous"]["key"]["address"] == 'гр. Варна, ул. "Никола Михайловски" №6'
    assert seeded["previous"]["decision"]["status"] == "accepted"


def test_plan_refresh_flags_address_changed_whichever_entry_is_visited_first() -> None:
    """Both the old-address and the new-address entry can be present (a
    rebuild from a committed file that still has the old row). Dict order
    must not decide whether the moved institution goes to review."""
    new_address = 'ул. "Тодор Икономов" №26'
    institutions = {("kindergarten", "46"): {"name": 'ДГ№13 "Мир"', "address": new_address}}
    old = _entry("accepted", candidate=0)  # decided against the old address
    new = _entry("pending", address=new_address, candidates=[_geo()], flags=[])
    for order in ((old, new), (new, old)):
        existing = {state.entry_key(e): e for e in order}
        to_gather, kept_entries = seed.plan_refresh(existing, institutions)
        assert kept_entries == []
        ((key, seeded),) = to_gather.items()
        assert key[4] == new_address
        assert seeded["flags"] == ["address_changed"]
        assert seeded["decision"]["status"] == "pending"
        assert seeded["previous"]["decision"]["status"] == "accepted"
    # A person's decision on the new address stands alone in either order.
    decided = _entry("pinned", address=new_address, lat=43.21, lon=27.92, precision="building")
    for order in ((old, decided), (decided, old)):
        existing = {state.entry_key(e): e for e in order}
        to_gather, kept_entries = seed.plan_refresh(existing, institutions)
        assert to_gather == {}
        assert [e["decision"]["status"] for e in kept_entries] == ["pinned"]


def test_plan_refresh_strips_the_institution_address_before_keying() -> None:
    """The snapshot contract does not strip and the loader's parser does, so
    a trailing space in institutions.address must never reach a key — it
    would parse back as a different building."""
    institutions = {
        ("kindergarten", "46"): {"name": 'ДГ№13 "Мир"', "address": ' ул. "Тодор Икономов" №26 '},
    }
    existing = {state.entry_key(_entry("accepted", candidate=0)): _entry("accepted", candidate=0)}
    to_gather, _kept = seed.plan_refresh(existing, institutions)
    ((key, _seeded),) = to_gather.items()
    assert key[4] == 'ул. "Тодор Икономов" №26'


def test_plan_refresh_quote_style_change_is_not_a_move() -> None:
    institutions = {
        ("kindergarten", "46"): {"name": 'ДГ№13 "Мир"',
                                 "address": 'ГР. ВАРНА, УЛ. „Никола Михайловски“ № 6'},
    }
    kept = _entry("accepted", candidate=0)
    existing = {state.entry_key(kept): kept}
    to_gather, kept_entries = seed.plan_refresh(existing, institutions)
    assert to_gather == {}
    assert len(kept_entries) == 1


def test_prune_stale_branches_drops_only_branches_missing_from_the_inventory() -> None:
    main_entry = _entry("accepted", candidate=0)
    current = _entry("pinned", role="branch", address="ул. Батак 6", lat=43.21, lon=27.92,
                     precision="building")
    stale = _entry("pinned", role="branch", address="ул. Батак 8 (стар адрес)", lat=43.21,
                   lon=27.92, precision="building")
    entries = {state.entry_key(e): e for e in (main_entry, current, stale)}
    inventory = [state.entry_key(current)]
    kept, dropped = seed.prune_stale_branches(entries, inventory)
    assert dropped == [state.entry_key(stale)]
    assert set(kept) == {state.entry_key(main_entry), state.entry_key(current)}


def test_seed_script_never_imported_by_the_package() -> None:
    src = Path(__file__).resolve().parents[1] / "src" / "yasli"
    offenders = [p for p in src.rglob("*.py") if "scripts" in p.read_text(encoding="utf-8")]
    assert offenders == []


# --- shared state: persist and crash recovery ---------------------------------------------


def _paths(tmp_path: Path) -> dict[str, Path]:
    return {
        "candidates": tmp_path / "institution_locations.candidates.json",
        "csv": tmp_path / "institution_locations.csv",
        "provenance": tmp_path / "institution_locations.provenance.json",
    }


def _persist(entries, paths: dict[str, Path]):
    return state.persist(entries, candidates_path=paths["candidates"], csv_path=paths["csv"],
                         provenance_path=paths["provenance"])


def _reload(paths: dict[str, Path]):
    """What the seed script does on startup: load the candidates file and the
    committed pair, then apply the lineage rule."""
    doc = state.load_candidates(paths["candidates"])
    rows, prov, hash_value, torn = state.load_committed(paths["csv"], paths["provenance"], doc)
    return state.reconcile(doc, rows, prov, hash_value, torn=torn)


def _candidates_doc(paths: dict[str, Path]) -> dict:
    return json.loads(paths["candidates"].read_text(encoding="utf-8"))


def _snapshot(paths: dict[str, Path]) -> dict[str, bytes]:
    return {name: path.read_bytes() for name, path in paths.items()}


def _by_key(row):
    return tuple(row[column] for column in state.KEY_FIELDS)


def _pending_branch():
    return _entry("pending", role="branch", address="ул. Батак 6", candidates=[_geo()],
                  flags=["branch"])


def test_persist_writes_all_three_files_and_clears_the_journal(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    rows, provenance = _persist([_entry("auto", candidate=0), _pending_branch()], paths)
    assert len(rows) == 1 and len(provenance) == 1  # the pending branch is not written
    (parsed,) = parse_file(paths["csv"], provenance_path=paths["provenance"])
    assert parsed["verification"] == "auto"
    doc = _candidates_doc(paths)
    assert len(doc["entries"]) == 2
    assert doc["source_hash"] == state.committed_hash(paths["csv"], paths["provenance"])
    assert doc["pending_write"] is None


def test_crash_between_the_candidates_write_and_the_derived_writes_is_repaired_on_the_next_run(
    tmp_path: Path, monkeypatch
) -> None:
    from yasli.ingest import institution_locations_loader as loader

    paths = _paths(tmp_path)
    _persist([_entry("auto", candidate=0), _pending_branch()], paths)
    csv_before = paths["csv"].read_bytes()
    decided = [_entry("auto", candidate=0),
               _entry("no_pin", role="branch", address="ул. Батак 6", candidates=[_geo()],
                      flags=["branch"], source="manual", precision="none")]

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(loader, "write_file", boom)
    with pytest.raises(OSError, match="disk full"):
        _persist(decided, paths)
    monkeypatch.undo()
    assert paths["csv"].read_bytes() == csv_before  # the decision is only in the candidates file
    doc = _candidates_doc(paths)
    assert doc["source_hash"] == state.committed_hash(paths["csv"], paths["provenance"])
    assert any(e["decision"]["status"] == "no_pin" for e in doc["entries"])

    entries, rebuilt = _reload(paths)  # matching hash: the local decision stands
    assert rebuilt is False
    _persist(entries.values(), paths)
    rows = {r["address"]: r for r in parse_file(paths["csv"], provenance_path=paths["provenance"])}
    assert rows["ул. Батак 6"]["precision"] == "none"


def _tear_the_pair(paths: dict[str, Path], monkeypatch) -> None:
    """Crash persist between its two renames — the provenance rename fails —
    after a decision that must delete a provenance entry (the one ``auto``
    row confirmed by a person becomes ``osm_poi`` + ``human``). Leaves the
    candidates file (old hash, journal stamped) and the CSV carrying the new
    decision, and the provenance file from the previous save."""
    import os

    _persist([_entry("auto", candidate=0)], paths)
    accepted = [_entry("accepted", candidate=0, lat=43.2096, lon=27.9270, source="osm_poi",
                       precision="building")]
    real_replace = os.replace

    def power_cut(src, dst):
        if Path(dst) == paths["provenance"]:
            raise OSError("power cut")
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", power_cut)
    with pytest.raises(OSError, match="power cut"):
        _persist(accepted, paths)
    monkeypatch.undo()
    with pytest.raises(LocationRowError, match="stale provenance"):
        list(parse_file(paths["csv"], provenance_path=paths["provenance"]))
    doc = _candidates_doc(paths)
    assert doc["pending_write"] is not None
    assert doc["source_hash"] != state.committed_hash(paths["csv"], paths["provenance"])


def test_crash_between_the_csv_and_provenance_renames_is_repaired_on_the_next_run(
    tmp_path: Path, monkeypatch
) -> None:
    paths = _paths(tmp_path)
    _tear_the_pair(paths, monkeypatch)
    doc = state.load_candidates(paths["candidates"])
    rows, prov, hash_value, torn = state.load_committed(paths["csv"], paths["provenance"], doc)
    assert torn and rows == [] and prov == {} and hash_value is None
    entries, rebuilt = state.reconcile(doc, rows, prov, hash_value, torn=torn)
    assert rebuilt is False  # the local decisions stand and regenerate both files
    _persist(entries.values(), paths)
    parsed = {(r["kind"], r["external_id"], r["role"]): r
              for r in parse_file(paths["csv"], provenance_path=paths["provenance"])}
    assert parsed[("kindergarten", "46", "main")]["verification"] == "human"
    assert json.loads(paths["provenance"].read_text(encoding="utf-8")) == {}
    doc = _candidates_doc(paths)
    assert doc["source_hash"] == state.committed_hash(paths["csv"], paths["provenance"])
    assert doc["pending_write"] is None  # the journal is cleared once both renames land


def test_load_committed_reports_a_torn_pair_only_on_the_journal(tmp_path: Path, monkeypatch) -> None:
    paths = _paths(tmp_path)
    _tear_the_pair(paths, monkeypatch)
    doc = _candidates_doc(paths)
    # Without the journal (the last save completed) the same pair is a
    # corrupted committed file, and propagates; so does no candidates doc.
    with pytest.raises(LocationRowError, match="stale provenance"):
        state.load_committed(paths["csv"], paths["provenance"], {**doc, "pending_write": None})
    with pytest.raises(LocationRowError, match="stale provenance"):
        state.load_committed(paths["csv"], paths["provenance"], None)
    # A CSV edited by hand after the crash is not the journalled one either.
    with paths["csv"].open("a", encoding="utf-8") as fh:
        fh.write("kindergarten,17,branch,Бисерче,,,,none,manual,human,2026-09-15\n")
    with pytest.raises(LocationRowError, match="stale provenance"):
        state.load_committed(paths["csv"], paths["provenance"], doc)


@pytest.mark.parametrize("corruption", ["not json {", None])
def test_a_hand_corrupted_provenance_file_aborts_the_run_before_anything_is_written(
    tmp_path: Path, corruption
) -> None:
    """In steady state the CSV always matches local state; that must not
    make a broken provenance file look like an interrupted save."""
    paths = _paths(tmp_path)
    _persist([_entry("auto", candidate=0)], paths)
    if corruption is None:  # a valid file whose entry no longer passes rule 1
        doc = json.loads(paths["provenance"].read_text(encoding="utf-8"))
        (entry,) = doc.values()
        entry["title_matches"] = 2
        corruption = json.dumps(doc, ensure_ascii=False)
    paths["provenance"].write_text(corruption, encoding="utf-8")
    before = _snapshot(paths)
    with pytest.raises(LocationRowError):
        _reload(paths)
    assert _snapshot(paths) == before


def test_a_hand_corrupted_committed_file_aborts_the_run(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _persist([_entry("auto", candidate=0)], paths)
    with paths["csv"].open("a", encoding="utf-8") as fh:
        fh.write("school,1,main,,x,43.2,27.9,building,manual,human,2026-09-15\n")
    before = _snapshot(paths)
    with pytest.raises(LocationRowError, match="kind 'school'"):
        _reload(paths)
    assert _snapshot(paths) == before


def test_a_row_written_into_the_csv_by_hand_becomes_a_decision_on_the_next_run(
    tmp_path: Path,
) -> None:
    """The hand-resolution loop in OPERATIONS.md: the seed script leaves a
    row pending, a person writes it into the CSV, and the next run picks it
    up as that person's decision — never reverting it — while keeping the
    candidates and flags from local state."""
    paths = _paths(tmp_path)
    _persist([_entry("auto", candidate=0), _pending_branch()], paths)
    with paths["csv"].open("a", encoding="utf-8") as fh:
        fh.write("kindergarten,46,branch,,ул. Батак 6,43.210000,27.920000,approximate,manual,human,2026-09-16\n")
    committed_rows = list(parse_file(paths["csv"], provenance_path=paths["provenance"]))
    assert _candidates_doc(paths)["source_hash"] != state.committed_hash(paths["csv"], paths["provenance"])

    entries, rebuilt = _reload(paths)
    assert rebuilt is True
    entry = entries[("kindergarten", "46", "branch", "", "ул. Батак 6")]
    assert entry["decision"]["status"] == "pinned"
    assert (entry["decision"]["lat"], entry["decision"]["lon"]) == (43.21, 27.92)
    assert entry["decision"]["precision"] == "approximate"
    assert entry["decision"]["decided_at"] == "2026-09-16"
    assert entry["candidates"] == [_geo()]  # kept from local state
    assert entry["flags"] == ["branch"]
    _persist(entries.values(), paths)  # re-rendered in canonical order: the same rows
    rewritten = parse_file(paths["csv"], provenance_path=paths["provenance"])
    assert sorted(rewritten, key=_by_key) == sorted(committed_rows, key=_by_key)
    assert _candidates_doc(paths)["source_hash"] == state.committed_hash(paths["csv"], paths["provenance"])
