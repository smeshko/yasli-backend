"""Pure-helper tests for the institution locations seed script and the
shared review state module. No network: every external response comes from
``scripts/fixtures/`` (captured 2026-09-15) or is inline.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest

from scripts import seed_institution_locations as seed
from scripts.location_review import state
from yasli.ingest.institution_locations_loader import parse_rows

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
