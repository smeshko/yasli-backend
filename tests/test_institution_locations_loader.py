"""Parser tests for the institution locations reference file.

Pure, network-free: every case is an inline CSV string so the fixture is
readable in the test body, and every rejection asserts on the line number
in the error. The municipality polygon is the committed one in ``data/``.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from yasli.ingest.institution_locations_loader import (
    COLUMNS,
    DEFAULT_CSV,
    DEFAULT_PROVENANCE,
    LocationRowError,
    load_provenance,
    normalise_address,
    parse_file,
    parse_rows,
    write_file,
)

HEADER = ",".join(COLUMNS)

# ДГ№13 "Мир": a main row auto-accepted from a unique OSM POI match.
MAIN_AUTO = (
    'kindergarten,46,main,,"ул. ""Никола Михайловски"" №6",'
    "43.206500,27.914200,building,osm_poi,auto,2026-09-14"
)
MAIN_AUTO_PROVENANCE = {
    "kindergarten/46": {
        "lat": 43.2065,
        "lon": 27.9142,
        "osm": "way/123",
        "amenity": "kindergarten",
        "title_matches": 1,
        "in_municipality": True,
        "settlement": "Варна",
        "address_settlement": "Варна",
        "geocode_distance_m": 18,
        "seeded_at": "2026-09-14",
    }
}
# A branch a person pinned by hand.
BRANCH_HUMAN = (
    "kindergarten,46,branch,,ул. Н. Михайловски 1А,"
    "43.207100,27.913800,building,manual,human,2026-09-14"
)
# A name-only branch, deliberately left without a pin.
BRANCH_NO_PIN = "kindergarten,17,branch,Жирафче,,,,none,manual,human,2026-09-14"

# Measured geocoder failures (research §3.2): OSM place nodes.
IGNATIEVO = ("43.249555", "27.774731")
AKSAKOVO = ("43.258626", "27.817361")


def _csv(*rows: str, header: str = HEADER) -> str:
    return "\n".join([header, *rows]) + "\n"


def _parse(text: str, provenance: dict | None = None) -> list[dict]:
    reader = csv.DictReader(io.StringIO(text))
    return list(parse_rows(reader, provenance or {}))


def _error(text: str, provenance: dict | None = None) -> LocationRowError:
    with pytest.raises(LocationRowError) as info:
        _parse(text, provenance)
    return info.value


# --- well-formed --------------------------------------------------------------


def test_well_formed_file_parses_to_orm_row_dicts() -> None:
    rows = _parse(_csv(MAIN_AUTO, BRANCH_HUMAN, BRANCH_NO_PIN), MAIN_AUTO_PROVENANCE)
    assert [r["role"] for r in rows] == ["main", "branch", "branch"]
    main = rows[0]
    assert set(main) == set(COLUMNS)
    assert main["kind"] == "kindergarten"
    assert main["external_id"] == "46"
    assert main["label"] == ""
    assert main["address"] == 'ул. "Никола Михайловски" №6'
    assert main["lat"] == Decimal("43.206500")
    assert main["lon"] == Decimal("27.914200")
    assert main["precision"] == "building"
    assert main["source"] == "osm_poi"
    assert main["verification"] == "auto"
    assert main["verified_at"] == date(2026, 9, 14)
    no_pin = rows[2]
    assert no_pin["label"] == "Жирафче"
    assert no_pin["address"] == ""
    assert no_pin["lat"] is None
    assert no_pin["lon"] is None
    assert no_pin["precision"] == "none"


def test_address_with_comma_and_doubled_quotes_round_trips() -> None:
    row = (
        'preschool,7,main,,"ж.к. ""Владислав Варненчик"" II м.р., бл.209",'
        "43.230000,27.870000,approximate,manual,human,2026-09-14"
    )
    (parsed,) = _parse(_csv(row))
    assert parsed["address"] == 'ж.к. "Владислав Варненчик" II м.р., бл.209'


def test_file_with_no_auto_rows_parses_with_empty_provenance() -> None:
    rows = _parse(_csv(BRANCH_HUMAN, BRANCH_NO_PIN), {})
    assert len(rows) == 2


# --- header ------------------------------------------------------------------------


def test_missing_header_column_rejected_before_any_row() -> None:
    header = ",".join(c for c in COLUMNS if c != "source")
    bad_row = "kindergarten,46,main,,x,43.2065,27.9142,building,human,2026-09-14"
    err = _error(_csv(bad_row, header=header))
    assert err.line_no == 1
    assert "source" in str(err)


def test_extra_header_column_rejected_before_any_row() -> None:
    err = _error(_csv(MAIN_AUTO + ",extra", header=HEADER + ",notes"))
    assert err.line_no == 1
    assert "notes" in str(err)


# --- coordinates -----------------------------------------------------------------------


def test_lat_without_lon_rejected_with_line_number() -> None:
    row = "kindergarten,46,main,,x,43.206500,,building,manual,human,2026-09-14"
    err = _error(_csv(BRANCH_NO_PIN, row))
    assert err.line_no == 3
    assert "lon" in str(err)


def test_lon_without_lat_rejected_with_line_number() -> None:
    row = "kindergarten,46,main,,x,,27.914200,building,manual,human,2026-09-14"
    err = _error(_csv(row))
    assert err.line_no == 2


def test_precision_none_with_coordinate_rejected() -> None:
    row = "kindergarten,46,main,,x,43.206500,27.914200,none,manual,human,2026-09-14"
    err = _error(_csv(row))
    assert err.line_no == 2
    assert "precision" in str(err)


def test_precision_building_without_coordinate_rejected() -> None:
    row = "kindergarten,46,main,,x,,,building,manual,human,2026-09-14"
    err = _error(_csv(row))
    assert err.line_no == 2
    assert "precision" in str(err)


def test_precision_street_rejected_as_unknown_value() -> None:
    row = "kindergarten,46,main,,x,43.206500,27.914200,street,manual,human,2026-09-14"
    err = _error(_csv(row))
    assert err.line_no == 2
    assert "street" in str(err)


def test_non_numeric_coordinate_rejected() -> None:
    row = "kindergarten,46,main,,x,north,27.914200,building,manual,human,2026-09-14"
    err = _error(_csv(row))
    assert err.line_no == 2
    assert "north" in str(err)


@pytest.mark.parametrize(
    ("name", "point"),
    [("Игнатиево", IGNATIEVO), ("Аксаково", AKSAKOVO)],
)
def test_coordinate_outside_municipality_rejected_naming_line_and_value(name, point) -> None:
    lat, lon = point
    row = f"kindergarten,46,main,,x,{lat},{lon},building,manual,human,2026-09-14"
    err = _error(_csv(BRANCH_NO_PIN, row))
    assert err.line_no == 3
    assert lat in str(err) and lon in str(err)
    assert "municipality" in str(err)


# --- value sets --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("row", "needle"),
    [
        ("infant,46,main,,x,43.206500,27.914200,building,manual,human,2026-09-14", "infant"),
        ("kindergarten,46,annex,,x,43.206500,27.914200,building,manual,human,2026-09-14", "annex"),
        ("kindergarten,46,main,,x,43.206500,27.914200,building,guess,human,2026-09-14", "guess"),
        ("kindergarten,46,main,,x,43.206500,27.914200,building,manual,maybe,2026-09-14", "maybe"),
        ("kindergarten,,main,,x,43.206500,27.914200,building,manual,human,2026-09-14", "external_id"),
    ],
    ids=["kind", "role", "source", "verification", "empty-external-id"],
)
def test_unknown_values_rejected(row: str, needle: str) -> None:
    err = _error(_csv(row))
    assert err.line_no == 2
    assert needle in str(err)


def test_manual_with_auto_rejected() -> None:
    row = "kindergarten,46,main,,x,43.206500,27.914200,building,manual,auto,2026-09-14"
    err = _error(_csv(row))
    assert err.line_no == 2
    assert "manual" in str(err) and "auto" in str(err)


@pytest.mark.parametrize(
    "row",
    [
        "kindergarten,46,main,,x,43.206500,27.914200,building,nominatim,auto,2026-09-14",
        "kindergarten,46,branch,,x,43.206500,27.914200,building,osm_poi,auto,2026-09-14",
        "kindergarten,46,main,,x,43.206500,27.914200,approximate,osm_poi,auto,2026-09-14",
    ],
    ids=["auto-nominatim", "auto-branch", "auto-approximate"],
)
def test_auto_row_shape_rejected(row: str) -> None:
    err = _error(_csv(row), MAIN_AUTO_PROVENANCE)
    assert err.line_no == 2
    assert "auto" in str(err)


def test_verified_at_must_be_iso_date() -> None:
    for bad in ("14.09.2026", "2026-9-14", "20260914", "yesterday"):
        row = f"kindergarten,46,main,,x,43.206500,27.914200,building,manual,human,{bad}"
        err = _error(_csv(row))
        assert err.line_no == 2, bad
        assert "verified_at" in str(err), bad


# --- uniqueness ----------------------------------------------------------------------------


def test_duplicate_building_tuple_rejected_by_parser() -> None:
    err = _error(_csv(BRANCH_HUMAN, BRANCH_NO_PIN, BRANCH_HUMAN))
    assert err.line_no == 4
    assert "duplicate" in str(err)
    assert "line 2" in str(err)


def test_rows_differing_only_by_label_are_distinct() -> None:
    other = BRANCH_NO_PIN.replace("Жирафче", "Другарче")
    assert len(_parse(_csv(BRANCH_NO_PIN, other))) == 2


def test_second_main_row_for_institution_rejected_even_with_other_address() -> None:
    first = "kindergarten,46,main,,x,43.206500,27.914200,building,manual,human,2026-09-14"
    second = "kindergarten,46,main,,y,43.207100,27.913800,building,manual,human,2026-09-14"
    err = _error(_csv(BRANCH_NO_PIN, first, second))
    assert err.line_no == 4
    assert "main" in str(err)
    assert "kindergarten/46" in str(err)
    assert "line 3" in str(err)


def test_main_rows_for_different_kinds_are_independent() -> None:
    a = "kindergarten,46,main,,x,43.206500,27.914200,building,manual,human,2026-09-14"
    b = "nursery,46,main,,y,43.207100,27.913800,building,manual,human,2026-09-14"
    assert len(_parse(_csv(a, b))) == 2


# --- provenance ----------------------------------------------------------------------------


def test_over_long_cells_are_rejected_with_the_table_limit_and_line_number() -> None:
    """Parser/table parity for the free-text columns: an over-long cell
    must fail here with a line number, not at INSERT after the TRUNCATE."""
    from yasli.ingest.institution_locations_loader import MAX_LENGTHS
    from yasli.models import InstitutionLocation

    assert MAX_LENGTHS == {
        c: InstitutionLocation.__table__.c[c].type.length for c in ("external_id", "label", "address")
    }
    long_address = "ул. " + "Б" * 253  # 257 characters
    err = _error(_csv(BRANCH_HUMAN, f"kindergarten,46,branch,,{long_address},43.207100,27.913800,"
                                    "building,manual,human,2026-09-14"))
    assert err.line_no == 3
    assert "address is 257 characters" in str(err) and "256" in str(err)
    err = _error(_csv(f"kindergarten,17,branch,{'Ж' * 129},,,,none,manual,human,2026-09-14"))
    assert err.line_no == 2 and "label is 129 characters" in str(err)
    err = _error(_csv("kindergarten,12345678901234567,main,,x,,,none,manual,human,2026-09-14"))
    assert err.line_no == 2 and "external_id is 17 characters" in str(err)


def test_auto_row_without_provenance_entry_rejected() -> None:
    err = _error(_csv(MAIN_AUTO), {})
    assert err.line_no == 2
    assert "provenance" in str(err)
    assert "kindergarten/46" in str(err)


def test_auto_row_with_provenance_coordinate_mismatch_rejected() -> None:
    entry = {**MAIN_AUTO_PROVENANCE["kindergarten/46"], "lat": 43.2066}
    err = _error(_csv(MAIN_AUTO), {"kindergarten/46": entry})
    assert err.line_no == 2
    assert "coordinate" in str(err)


@pytest.mark.parametrize(
    ("override", "needle"),
    [
        ({"title_matches": 2}, "title_matches"),
        ({"title_matches": 0}, "title_matches"),
        ({"in_municipality": False}, "in_municipality"),
        ({"settlement": "Константиново"}, "settlement"),
        ({"geocode_distance_m": 151}, "geocode_distance_m"),
    ],
    ids=["ambiguous", "no-match", "outside", "settlement-mismatch", "geocode-far"],
)
def test_auto_row_with_failed_rule_rejected(override: dict, needle: str) -> None:
    entry = {**MAIN_AUTO_PROVENANCE["kindergarten/46"], **override}
    err = _error(_csv(MAIN_AUTO), {"kindergarten/46": entry})
    assert err.line_no == 2
    assert needle in str(err)


def test_auto_row_with_no_geocode_passes() -> None:
    entry = {**MAIN_AUTO_PROVENANCE["kindergarten/46"], "geocode_distance_m": None}
    (row,) = _parse(_csv(MAIN_AUTO), {"kindergarten/46": entry})
    assert row["verification"] == "auto"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("title_matches", True, "title_matches is True, not 1"),
        ("title_matches", "1", "title_matches is '1', not 1"),
        ("geocode_distance_m", "999", "geocode_distance_m '999' is not a number"),
        ("geocode_distance_m", True, "geocode_distance_m True is not a number"),
        ("settlement", 1, "settlement 1 does not agree"),
    ],
)
def test_provenance_fields_are_type_checked_not_just_compared(field, value, message) -> None:
    """A hand-edited entry with the wrong JSON type fails with a line
    number, never with a TypeError — and ``true`` is not ``1``."""
    bad = {"kindergarten/46": {**MAIN_AUTO_PROVENANCE["kindergarten/46"], field: value}}
    err = _error(_csv(MAIN_AUTO), bad)
    assert err.line_no == 2
    assert message in str(err)


def test_stale_provenance_entry_rejected() -> None:
    provenance = {**MAIN_AUTO_PROVENANCE, "nursery/1": MAIN_AUTO_PROVENANCE["kindergarten/46"]}
    err = _error(_csv(MAIN_AUTO), provenance)
    assert err.line_no is None
    assert "nursery/1" in str(err)
    assert "stale" in str(err)


def test_provenance_for_a_human_row_is_stale() -> None:
    err = _error(_csv(BRANCH_HUMAN), MAIN_AUTO_PROVENANCE)
    assert "kindergarten/46" in str(err)


def test_load_provenance_missing_file_is_empty(tmp_path: Path) -> None:
    assert load_provenance(tmp_path / "nope.json") == {}


def test_load_provenance_rejects_non_object(tmp_path: Path) -> None:
    path = tmp_path / "p.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(LocationRowError):
        load_provenance(path)


# --- normalise_address ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "variant",
    [
        'ул. "Никола Михайловски" №6',
        'ул. “Никола Михайловски” №6',
        'ул. „Никола Михайловски“ №6',
        'ул. «Никола Михайловски» №6',
        'ул. "Никола Михайловски" № 6',
        'УЛ. "НИКОЛА МИХАЙЛОВСКИ" №6',
        '  ул.  "Никола   Михайловски"  №6  ',
        'ул . "Никола Михайловски" №6',
    ],
)
def test_normalise_address_treats_research_variants_as_equal(variant: str) -> None:
    assert normalise_address(variant) == normalise_address('ул. "Никола Михайловски" №6')


def test_normalise_address_keeps_real_differences() -> None:
    base = normalise_address('ул. "Никола Михайловски" №6')
    assert normalise_address('ул. "Никола Михайловски" №8') != base
    assert normalise_address('ул. "Никола Михайловски" 1А') != base
    assert normalise_address('ул. "Тодор Икономов" №6') != base


def test_normalise_address_collapses_comma_spacing() -> None:
    assert normalise_address("ж.к. Младост , бл.127") == normalise_address("ж.к. Младост,бл.127")


# --- parse_file / write_file ---------------------------------------------------------------


def test_defaults_are_anchored_to_the_repo_data_dir() -> None:
    assert DEFAULT_CSV.name == "institution_locations.csv"
    assert DEFAULT_PROVENANCE.name == "institution_locations.provenance.json"
    assert DEFAULT_CSV.parent == DEFAULT_PROVENANCE.parent
    assert DEFAULT_CSV.parent.name == "data"
    assert (DEFAULT_CSV.parent / "varna_municipality.geojson").exists()


def test_parse_file_reads_utf8_and_sibling_provenance(tmp_path: Path) -> None:
    csv_path = tmp_path / "institution_locations.csv"
    csv_path.write_text(_csv(MAIN_AUTO, BRANCH_HUMAN), encoding="utf-8")
    (tmp_path / "institution_locations.provenance.json").write_text(
        json.dumps(MAIN_AUTO_PROVENANCE), encoding="utf-8"
    )
    rows = list(parse_file(csv_path))
    assert [r["role"] for r in rows] == ["main", "branch"]


def test_parse_file_missing_provenance_rejects_auto_rows(tmp_path: Path) -> None:
    csv_path = tmp_path / "institution_locations.csv"
    csv_path.write_text(_csv(MAIN_AUTO), encoding="utf-8")
    with pytest.raises(LocationRowError) as info:
        list(parse_file(csv_path))
    assert info.value.line_no == 2


def test_parse_file_explicit_provenance_path(tmp_path: Path) -> None:
    csv_path = tmp_path / "rows.csv"
    csv_path.write_text(_csv(MAIN_AUTO), encoding="utf-8")
    prov = tmp_path / "elsewhere.json"
    prov.write_text(json.dumps(MAIN_AUTO_PROVENANCE), encoding="utf-8")
    assert len(list(parse_file(csv_path, provenance_path=prov))) == 1


def test_write_file_round_trips_rows_and_provenance(tmp_path: Path) -> None:
    csv_path = tmp_path / "institution_locations.csv"
    rows = _parse(_csv(BRANCH_NO_PIN, BRANCH_HUMAN, MAIN_AUTO), MAIN_AUTO_PROVENANCE)
    tricky = {
        **rows[0],
        "external_id": "39",
        "label": "",
        "address": 'ж.к. "Владислав Варненчик" II м.р., бл.209',
        "lat": Decimal("43.23"),
        "lon": Decimal("27.87"),
        "precision": "approximate",
    }
    write_file(csv_path, [*rows, tricky], MAIN_AUTO_PROVENANCE)

    text = csv_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert lines[0] == HEADER
    # Stable order: kind, external_id, role, label, address — main before branch
    # only because 'branch' < 'main' is false; the sort is by the tuple.
    assert [line.split(",")[1:3] for line in lines[1:]] == [
        ["17", "branch"],
        ["39", "branch"],
        ["46", "branch"],
        ["46", "main"],
    ]
    assert '"ж.к. ""Владислав Варненчик"" II м.р., бл.209"' in text
    assert ",43.230000,27.870000," in text

    reparsed = list(parse_file(csv_path))
    assert reparsed == sorted(
        [*rows, tricky],
        key=lambda r: (r["kind"], r["external_id"], r["role"], r["label"], r["address"]),
    )
    prov_path = tmp_path / "institution_locations.provenance.json"
    assert json.loads(prov_path.read_text(encoding="utf-8")) == MAIN_AUTO_PROVENANCE
    assert prov_path.read_text(encoding="utf-8").endswith("\n")


def test_write_file_refuses_invalid_rows_without_touching_either_file(tmp_path: Path) -> None:
    csv_path = tmp_path / "institution_locations.csv"
    prov_path = tmp_path / "institution_locations.provenance.json"
    csv_path.write_text("old csv", encoding="utf-8")
    prov_path.write_text("old provenance", encoding="utf-8")

    (bad,) = _parse(_csv(BRANCH_HUMAN))
    bad = {**bad, "lat": Decimal(AKSAKOVO[0]), "lon": Decimal(AKSAKOVO[1])}
    with pytest.raises(LocationRowError) as info:
        write_file(csv_path, [bad], {})
    assert "municipality" in str(info.value)
    assert csv_path.read_text(encoding="utf-8") == "old csv"
    assert prov_path.read_text(encoding="utf-8") == "old provenance"
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "institution_locations.csv",
        "institution_locations.provenance.json",
    ]


def test_write_file_refuses_auto_row_without_provenance(tmp_path: Path) -> None:
    csv_path = tmp_path / "institution_locations.csv"
    rows = _parse(_csv(MAIN_AUTO), MAIN_AUTO_PROVENANCE)
    with pytest.raises(LocationRowError):
        write_file(csv_path, rows, {})
    assert not csv_path.exists()


def test_write_file_accepts_string_and_float_inputs(tmp_path: Path) -> None:
    csv_path = tmp_path / "institution_locations.csv"
    row = {
        "kind": "nursery",
        "external_id": "3",
        "role": "main",
        "label": "",
        "address": "ул. Батак 6",
        "lat": 43.2065,
        "lon": "27.9142",
        "precision": "building",
        "source": "nominatim",
        "verification": "human",
        "verified_at": "2026-09-14",
    }
    write_file(csv_path, [row], {})
    (parsed,) = parse_file(csv_path)
    assert parsed["lat"] == Decimal("43.206500")
    assert parsed["lon"] == Decimal("27.914200")
    assert parsed["verified_at"] == date(2026, 9, 14)


# --- loader (TASK-003) ----------------------------------------------------------------------
#
# SQLite in-memory session, copied from tests/test_grao_loader.py — there is
# no shared fixture in tests/conftest.py. SQLite does not enforce the FK, which
# is one reason the loader keeps its own pre-TRUNCATE checks.

import os  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

from sqlalchemy import create_engine, select, text as sa_text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from yasli.ingest import institution_locations_loader as loader  # noqa: E402
from yasli.models import Base, Institution, InstitutionLocation  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]

INSTITUTIONS = [
    ("kindergarten", "46", 'ДГ№13 "Мир"', 'ул. "Никола Михайловски" №6'),
    ("kindergarten", "17", 'ДГ№17 "Петър Берон"', 'ул. "Роза" №27'),
    ("nursery", "3", 'ДЯ №3 "Зайо Байо"', None),
]

MAIN_17_NO_PIN = "kindergarten,17,main,,\"ул. \"\"Роза\"\" №27\",,,none,manual,human,2026-09-14"
MAIN_3_HUMAN = "nursery,3,main,,ул. Батак 6,43.210000,27.920000,building,nominatim,human,2026-09-14"


@pytest.fixture
def sqlite_engine():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        # institutions.id is a bare BigInteger PK, which SQLite does not
        # autoincrement — pass explicit ids, as tests/test_models.py does.
        for i, (kind, external_id, name, address) in enumerate(INSTITUTIONS, start=1):
            s.add(
                Institution(
                    id=i,
                    kind=kind,
                    external_id=external_id,
                    name=name,
                    address=address,
                    source_url="https://example.test/x",
                    last_seen_at=datetime(2026, 9, 14, tzinfo=timezone.utc),
                )
            )
        s.commit()
    yield engine
    engine.dispose()


@pytest.fixture
def sqlite_session(sqlite_engine):
    with Session(sqlite_engine) as s:
        yield s


def _write_pair(tmp_path: Path, csv_text: str, provenance: dict | None = None) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    csv_path = tmp_path / "institution_locations.csv"
    csv_path.write_text(csv_text, encoding="utf-8")
    (tmp_path / "institution_locations.provenance.json").write_text(
        json.dumps(provenance or {}), encoding="utf-8"
    )
    return csv_path


def _complete_file(tmp_path: Path) -> Path:
    """Every institution in the fixture has a main row; ДГ№13 has branches."""
    return _write_pair(
        tmp_path,
        _csv(MAIN_AUTO, BRANCH_HUMAN, BRANCH_NO_PIN, MAIN_17_NO_PIN, MAIN_3_HUMAN),
        MAIN_AUTO_PROVENANCE,
    )


def _business_rows(session: Session) -> list[tuple]:
    """Every column except the surrogate ``id`` — the idempotence contract.
    Ends the autobegun read transaction so the next ``session.begin()`` works."""
    rows = session.execute(
        select(InstitutionLocation).order_by(
            InstitutionLocation.kind,
            InstitutionLocation.external_id,
            InstitutionLocation.role,
            InstitutionLocation.label,
            InstitutionLocation.address,
        )
    ).scalars()
    out = [tuple(getattr(r, c) for c in loader.COLUMNS) for r in rows]
    session.rollback()
    return out


def test_load_truncates_and_inserts_idempotently(tmp_path: Path, sqlite_session) -> None:
    path = _complete_file(tmp_path)
    with sqlite_session.begin():
        first = loader.load(path, sqlite_session)
    rows_after_first = _business_rows(sqlite_session)
    ids_after_first = [r.id for r in sqlite_session.execute(select(InstitutionLocation)).scalars()]
    sqlite_session.rollback()
    with sqlite_session.begin():
        second = loader.load(path, sqlite_session)
    rows_after_second = _business_rows(sqlite_session)

    assert first.rows_loaded == second.rows_loaded == 5
    assert rows_after_first == rows_after_second
    assert len(rows_after_first) == 5
    assert len(ids_after_first) == 5


def test_summary_counts_and_unresolved_main_names(tmp_path: Path, sqlite_session) -> None:
    path = _complete_file(tmp_path)
    with sqlite_session.begin():
        summary = loader.load(path, sqlite_session)
    assert summary.rows_loaded == 5
    assert summary.by_role == {"main": 3, "branch": 2}
    assert summary.by_verification == {"auto": 1, "human": 4}
    assert summary.missing_main == []
    assert summary.address_drift == []
    assert summary.unresolved_main == ['ДГ№17 "Петър Берон" (kindergarten/17)']
    assert summary.dry_run is False


def test_unmatched_pair_aborts_whole_load_naming_the_pair(tmp_path: Path, sqlite_session) -> None:
    with sqlite_session.begin():
        loader.load(_complete_file(tmp_path), sqlite_session)
    before = _business_rows(sqlite_session)

    stray = "preschool,99,main,,x,43.210000,27.920000,building,manual,human,2026-09-14"
    path = _write_pair(
        tmp_path / "bad",
        _csv(MAIN_AUTO, BRANCH_HUMAN, BRANCH_NO_PIN, MAIN_17_NO_PIN, MAIN_3_HUMAN, stray),
        MAIN_AUTO_PROVENANCE,
    )
    with pytest.raises(loader.UnmatchedInstitution) as info:
        with sqlite_session.begin():
            loader.load(path, sqlite_session)
    assert "preschool/99" in str(info.value)
    assert _business_rows(sqlite_session) == before


def test_unmatched_pair_aborts_even_with_allow_incomplete(tmp_path: Path, sqlite_session) -> None:
    stray = "preschool,99,main,,x,43.210000,27.920000,building,manual,human,2026-09-14"
    path = _write_pair(tmp_path, _csv(stray))
    with pytest.raises(loader.UnmatchedInstitution):
        with sqlite_session.begin():
            loader.load(path, sqlite_session, allow_incomplete=True)
    assert _business_rows(sqlite_session) == []


def test_missing_main_aborts_before_truncate_naming_institutions(
    tmp_path: Path, sqlite_session
) -> None:
    with sqlite_session.begin():
        loader.load(_complete_file(tmp_path), sqlite_session)
    before = _business_rows(sqlite_session)
    assert len(before) == 5

    partial = _write_pair(
        tmp_path / "partial", _csv(MAIN_AUTO, BRANCH_HUMAN, MAIN_3_HUMAN), MAIN_AUTO_PROVENANCE
    )
    with pytest.raises(loader.IncompleteFile) as info:
        with sqlite_session.begin():
            loader.load(partial, sqlite_session)
    assert 'ДГ№17 "Петър Берон" (kindergarten/17)' in str(info.value)
    assert _business_rows(sqlite_session) == before


def test_missing_main_loads_under_allow_incomplete_with_count(tmp_path: Path, sqlite_session) -> None:
    partial = _write_pair(tmp_path, _csv(MAIN_AUTO, BRANCH_HUMAN, MAIN_3_HUMAN), MAIN_AUTO_PROVENANCE)
    with sqlite_session.begin():
        summary = loader.load(partial, sqlite_session, allow_incomplete=True)
    assert summary.rows_loaded == 3
    assert summary.missing_main == ['ДГ№17 "Петър Берон" (kindergarten/17)']
    assert len(_business_rows(sqlite_session)) == 3


def test_explicit_no_pin_row_counts_as_present(tmp_path: Path, sqlite_session) -> None:
    path = _complete_file(tmp_path)
    with sqlite_session.begin():
        summary = loader.load(path, sqlite_session)
    assert summary.missing_main == []
    assert summary.unresolved_main == ['ДГ№17 "Петър Берон" (kindergarten/17)']


def test_address_drift_aborts_before_truncate_naming_both_addresses(
    tmp_path: Path, sqlite_session
) -> None:
    path = _complete_file(tmp_path)
    with sqlite_session.begin():
        loader.load(path, sqlite_session)
    before = _business_rows(sqlite_session)

    sqlite_session.execute(
        sa_text(
            "UPDATE institutions SET address = 'ул. \"Тодор Икономов\" №26' "
            "WHERE kind = 'kindergarten' AND external_id = '46'"
        )
    )
    sqlite_session.commit()
    with pytest.raises(loader.IncompleteFile) as info:
        with sqlite_session.begin():
            loader.load(path, sqlite_session)
    message = str(info.value)
    assert 'ДГ№13 "Мир" (kindergarten/46)' in message
    assert 'ул. "Никола Михайловски" №6' in message
    assert 'ул. "Тодор Икономов" №26' in message
    assert _business_rows(sqlite_session) == before


def test_quote_style_only_change_is_not_drift(tmp_path: Path, sqlite_session) -> None:
    sqlite_session.execute(
        sa_text(
            "UPDATE institutions SET address = 'УЛ. „Никола Михайловски“ № 6' "
            "WHERE kind = 'kindergarten' AND external_id = '46'"
        )
    )
    sqlite_session.commit()
    with sqlite_session.begin():
        summary = loader.load(_complete_file(tmp_path), sqlite_session)
    assert summary.address_drift == []
    assert summary.rows_loaded == 5


def test_null_institution_address_is_skipped_by_drift_guard(tmp_path: Path, sqlite_session) -> None:
    # nursery/3 has address NULL in the fixture; its main row still loads.
    with sqlite_session.begin():
        summary = loader.load(_complete_file(tmp_path), sqlite_session)
    assert summary.address_drift == []


def test_address_drift_loads_under_allow_incomplete_and_is_listed(
    tmp_path: Path, sqlite_session
) -> None:
    sqlite_session.execute(
        sa_text(
            "UPDATE institutions SET address = 'ул. \"Тодор Икономов\" №26' "
            "WHERE kind = 'kindergarten' AND external_id = '46'"
        )
    )
    sqlite_session.commit()
    with sqlite_session.begin():
        summary = loader.load(_complete_file(tmp_path), sqlite_session, allow_incomplete=True)
    assert summary.rows_loaded == 5
    assert summary.address_drift == [
        ('ДГ№13 "Мир" (kindergarten/46)', 'ул. "Никола Михайловски" №6', 'ул. "Тодор Икономов" №26')
    ]


def test_dry_run_runs_guards_without_touching_the_table(tmp_path: Path, sqlite_session) -> None:
    with sqlite_session.begin():
        loader.load(_complete_file(tmp_path), sqlite_session)
    before = _business_rows(sqlite_session)

    partial = _write_pair(
        tmp_path / "partial", _csv(MAIN_AUTO, BRANCH_HUMAN, MAIN_3_HUMAN), MAIN_AUTO_PROVENANCE
    )
    with pytest.raises(loader.IncompleteFile):
        with sqlite_session.begin():
            loader.load(partial, sqlite_session, dry_run=True)
    assert _business_rows(sqlite_session) == before

    with sqlite_session.begin():
        summary = loader.load(partial, sqlite_session, dry_run=True, allow_incomplete=True)
    assert summary.dry_run is True
    assert summary.rows_loaded == 3
    assert summary.missing_main == ['ДГ№17 "Петър Берон" (kindergarten/17)']
    assert _business_rows(sqlite_session) == before


def test_parser_error_surfaces_with_line_number(tmp_path: Path, sqlite_session) -> None:
    bad = "kindergarten,46,main,,x,43.206500,,building,manual,human,2026-09-14"
    path = _write_pair(tmp_path, _csv(MAIN_17_NO_PIN, bad))
    with pytest.raises(LocationRowError) as info:
        with sqlite_session.begin():
            loader.load(path, sqlite_session)
    assert info.value.line_no == 3


# --- CLI ------------------------------------------------------------------------------------


def _run_cli(args: list[str], cwd: Path, env_extra: dict[str, str] | None = None):
    env = os.environ.copy()
    env.pop("DATABASE_URL", None)
    env.update(env_extra or {})
    env["PYTHONPATH"] = str(REPO_ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "yasli.ingest.institution_locations_loader", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
    )


def test_cli_file_not_found_exits_2(tmp_path: Path) -> None:
    result = _run_cli([str(tmp_path / "missing.csv")], cwd=tmp_path)
    assert result.returncode == 2
    assert "not found" in result.stderr
    assert "missing.csv" in result.stderr


def test_cli_default_path_resolves_to_repo_data_dir_from_any_cwd(tmp_path: Path) -> None:
    """No path argument from a temp cwd: the default is the in-repo file,
    anchored to the package, never the cwd. Asked of the module from that
    cwd, and confirmed by the CLI getting past its file check there (it
    stops at the missing DATABASE_URL, never at a not-found file)."""
    expected = REPO_ROOT / "data" / "institution_locations.csv"
    assert expected.exists()  # the committed file
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    printed = subprocess.run(
        [sys.executable, "-c",
         "from yasli.ingest.institution_locations_loader import DEFAULT_CSV; print(DEFAULT_CSV)"],
        cwd=tmp_path, env=env, capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert Path(printed) == expected
    assert not Path(printed).is_relative_to(tmp_path)
    result = _run_cli(["--dry-run"], cwd=tmp_path)
    assert result.returncode == 2
    assert "not found" not in result.stderr
    assert "DATABASE_URL" in result.stderr


def test_cli_parse_failure_exits_3_with_line_number(tmp_path: Path) -> None:
    bad = "kindergarten,46,main,,x,43.206500,,building,manual,human,2026-09-14"
    path = _write_pair(tmp_path, _csv(bad))
    result = _run_cli([str(path)], cwd=tmp_path)
    assert result.returncode == 3
    assert "line 2" in result.stderr


def test_cli_missing_database_url_exits_2(tmp_path: Path) -> None:
    """From a cwd with no ../.env, Settings() cannot find DATABASE_URL."""
    path = _write_pair(tmp_path, _csv(MAIN_17_NO_PIN))
    result = _run_cli([str(path)], cwd=tmp_path)
    assert result.returncode == 2
    assert "DATABASE_URL" in result.stderr
    assert "Traceback" not in result.stderr


def test_cli_unknown_flag_shows_usage(tmp_path: Path) -> None:
    result = _run_cli(["--bogus"], cwd=tmp_path)
    assert result.returncode != 0
    assert "usage:" in result.stderr.lower()


def test_cli_referential_abort_exits_4(tmp_path: Path, sqlite_engine, monkeypatch, capsys) -> None:
    monkeypatch.setattr(loader, "get_engine", lambda: sqlite_engine)
    partial = _write_pair(tmp_path, _csv(MAIN_AUTO, MAIN_3_HUMAN), MAIN_AUTO_PROVENANCE)
    rc = loader.main([str(partial)])
    captured = capsys.readouterr()
    assert rc == 4
    assert 'ДГ№17 "Петър Берон" (kindergarten/17)' in captured.err
    assert "--allow-incomplete" in captured.err


def test_cli_success_summary_line(tmp_path: Path, sqlite_engine, monkeypatch, capsys) -> None:
    monkeypatch.setattr(loader, "get_engine", lambda: sqlite_engine)
    rc = loader.main([str(_complete_file(tmp_path))])
    captured = capsys.readouterr()
    assert rc == 0
    lines = captured.out.strip().splitlines()
    assert lines[0].startswith("institution_locations_loader done ")
    for field in (
        "rows=5",
        "main=3",
        "branch=2",
        "auto=1",
        "human=4",
        "missing_main=0",
        "address_drift=0",
        "unresolved_main=1",
        "dry_run=0",
    ):
        assert field in lines[0], field
    assert any('ДГ№17 "Петър Берон" (kindergarten/17)' in line for line in lines[1:])


def test_cli_allow_incomplete_and_dry_run_flags(
    tmp_path: Path, sqlite_engine, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(loader, "get_engine", lambda: sqlite_engine)
    partial = _write_pair(tmp_path, _csv(MAIN_AUTO, MAIN_3_HUMAN), MAIN_AUTO_PROVENANCE)
    rc = loader.main([str(partial), "--allow-incomplete", "--dry-run"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "missing_main=1" in captured.out
    assert "dry_run=1" in captured.out
    with Session(sqlite_engine) as s:
        assert _business_rows(s) == []


def test_render_csv_strips_string_cells_so_a_row_survives_the_round_trip() -> None:
    """The parser strips label and address; the renderer must too, or a
    trailing space in institutions.address becomes a second building."""
    import csv
    import io
    from datetime import date
    from decimal import Decimal

    from yasli.ingest.institution_locations_loader import parse_rows, render_csv

    row = {
        "kind": "kindergarten", "external_id": "46", "role": "branch", "label": " Жирафче ",
        "address": "ул. Батак 6 ", "lat": Decimal("43.209600"), "lon": Decimal("27.927000"),
        "precision": "building", "source": "manual", "verification": "human",
        "verified_at": date(2026, 9, 15),
    }
    text = render_csv([row])
    assert ",Жирафче,ул. Батак 6," in text
    (parsed,) = parse_rows(csv.DictReader(io.StringIO(text)), {})
    assert (parsed["label"], parsed["address"]) == ("Жирафче", "ул. Батак 6")
    assert render_csv([parsed]) == text
