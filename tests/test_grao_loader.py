"""Unit + integration tests for the ГРАО KADS loader.

The unit tests exercise the parser against an in-tree fixture file
(`fixtures/kads_minimal.txt`, encoded as windows-1251). The
``load_inserts_rows`` integration test uses an in-memory SQLite to confirm
that the bulk-insert path lands rows on the typed ORM.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from yasli.ingest import grao_loader
from yasli.models import Base, GraoAddress

FIXTURE = Path(__file__).parent / "ingest" / "fixtures" / "kads_minimal.txt"


@pytest.fixture
def sqlite_session():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s
    engine.dispose()


def test_parse_number_token_simple() -> None:
    assert grao_loader.parse_number_token("003") == (3, "", "")


def test_parse_number_token_with_suffix() -> None:
    assert grao_loader.parse_number_token("019А") == (19, "А", "")


def test_parse_number_token_with_entrance() -> None:
    assert grao_loader.parse_number_token("007 А") == (7, "", "А")


def test_parse_number_token_with_numeric_entrance() -> None:
    assert grao_loader.parse_number_token("041 12") == (41, "", "12")


def test_parse_number_token_unparseable_returns_none() -> None:
    assert grao_loader.parse_number_token("abc") is None
    assert grao_loader.parse_number_token("") is None


def test_parse_file_yields_rows() -> None:
    rows = list(grao_loader.parse_file(FIXTURE))
    assert rows, "fixture should produce at least one row"


def test_parse_file_district_codes_match_section_blocks() -> None:
    rows = list(grao_loader.parse_file(FIXTURE))
    # Streets under район 01 should all be district_code='01'; under 02
    # all '02'; etc.
    by_street: dict[str, set[str]] = {}
    for row in rows:
        by_street.setdefault(row["street_raw"], set()).add(row["district_code"])
    # Each street belongs to one район in the fixture, so the set is 1.
    for street, codes in by_street.items():
        assert len(codes) == 1, (street, codes)


def test_parse_file_recognises_vapcarov_entrance_A() -> None:
    """Task 2.11: ул. Н.Й. Вапцаров №7 entrance А resolves to '02'."""
    rows = list(grao_loader.parse_file(FIXTURE))
    matches = [
        r
        for r in rows
        if "ВАПЦАРОВ" in r["street_raw"]
        and r["number_int"] == 7
        and r["entrance"] == "А"
    ]
    assert len(matches) == 1
    assert matches[0]["district_code"] == "02"
    assert matches[0]["district_name"] == "ПРИМОРСКИ"
    assert matches[0]["settlement_code"] == "10135"
    assert matches[0]["number_suffix"] == ""


def test_parse_file_continuation_line_attributes_to_previous_street() -> None:
    rows = list(grao_loader.parse_file(FIXTURE))
    # ВАПЦАРОВ's row list spans two physical lines: the second carries
    # entrance Д. Confirm 007 Д appears (continuation line worked).
    matches = [
        r
        for r in rows
        if "ВАПЦАРОВ" in r["street_raw"]
        and r["number_int"] == 7
        and r["entrance"] == "Д"
    ]
    assert len(matches) == 1
    assert matches[0]["district_code"] == "02"


def test_parse_file_multi_entrance_building_expands() -> None:
    rows = list(grao_loader.parse_file(FIXTURE))
    # ВАПЦАРОВ #007 has entrances А–Д (5 rows for number=7 expected).
    seven = [
        r
        for r in rows
        if "ВАПЦАРОВ" in r["street_raw"] and r["number_int"] == 7
    ]
    assert {r["entrance"] for r in seven} == {"А", "Б", "В", "Г", "Д"}


def test_parse_file_search_norm_matches_dg_format() -> None:
    """search_norm composes settlement + street_raw before ICAO
    transliteration so the column joins directly against
    ``streets.search_norm``, which DG-side ``parse_street()`` computes
    from the same verbatim ``<SETTLEMENT> <STREET>`` form.
    """
    rows = list(grao_loader.parse_file(FIXTURE))
    vapcarov = next(r for r in rows if "ВАПЦАРОВ" in r["street_raw"])
    assert vapcarov["search_norm"] == "gr.varna ul.n.y.vaptsarov"


def test_parse_file_recognises_kads_specific_locality_marker() -> None:
    """М-СТ locality marker (KADS-specific) does not break parsing."""
    rows = list(grao_loader.parse_file(FIXTURE))
    gornita = [r for r in rows if "ГОРНА ТРАКА" in r["street_raw"]]
    assert gornita, "М-СТ ГОРНА ТРАКА should parse"
    # search_norm includes the locality + raw street form.
    assert gornita[0]["search_norm"].startswith("gr.varna ")


def test_parse_file_handles_number_with_suffix() -> None:
    rows = list(grao_loader.parse_file(FIXTURE))
    gornita_2 = [
        r
        for r in rows
        if "ГОРНА ТРАКА" in r["street_raw"]
        and r["number_int"] == 2
        and r["number_suffix"] in {"А", "Б"}
    ]
    assert {r["number_suffix"] for r in gornita_2} == {"А", "Б"}


def test_parse_file_handles_three_disjoint_districts() -> None:
    rows = list(grao_loader.parse_file(FIXTURE))
    districts = {r["district_code"] for r in rows}
    assert districts == {"01", "02", "03"}


def test_parse_lines_handles_single_space_before_number_column() -> None:
    """Long street names can fill the fixed street-name column, leaving only
    one space before the number list starts at column 38.
    """
    rows = list(
        grao_loader.parse_lines(
            [
                "област 03 ВАРНА               община 06 ВАРНА               район 05_АСПАРУХОВО       10135 ГР.ВАРНА       секция 374",
                " 00330 УЛ.КАПИТАН I РАНГ СТ.ДИМИТРИЕВ 001,002",
            ]
        )
    )
    assert [row["number_int"] for row in rows] == [1, 2]
    assert rows[0]["street_code"] == "00330"
    assert rows[0]["street_raw"] == "УЛ.КАПИТАН I РАНГ СТ.ДИМИТРИЕВ"
    assert rows[0]["district_code"] == "05"


def test_parse_lines_handles_trailing_comma_continuation() -> None:
    rows = list(
        grao_loader.parse_lines(
            [
                "област 03 ВАРНА               община 06 ВАРНА               район 05_АСПАРУХОВО       10135 ГР.ВАРНА       секция 374",
                " 00076 УЛ.АДМИРАЛ ГРЕЙГ               002,003,",
                "                                      004,005,",
                "                                      006",
            ]
        )
    )
    assert [row["number_int"] for row in rows] == [2, 3, 4, 5, 6]
    assert {row["street_raw"] for row in rows} == {"УЛ.АДМИРАЛ ГРЕЙГ"}


def test_parse_file_entrance_empty_string_not_none() -> None:
    """Number cells without an entrance store '' to satisfy PK NOT NULL."""
    rows = list(grao_loader.parse_file(FIXTURE))
    plain = next(r for r in rows if r["number_int"] == 1 and r["street_raw"].startswith("УЛ.МОРСКА"))
    assert plain["entrance"] == ""
    assert plain["number_suffix"] == ""


def test_load_inserts_rows_and_is_idempotent(sqlite_session: Session) -> None:
    summary1 = grao_loader.load(FIXTURE, sqlite_session)
    sqlite_session.commit()
    assert summary1.rows_loaded > 0

    count_after_first = sqlite_session.scalar(
        select(GraoAddress.number_int).where(GraoAddress.number_int.is_not(None))
    )
    assert count_after_first is not None

    total1 = sqlite_session.query(GraoAddress).count()  # type: ignore[attr-defined]

    summary2 = grao_loader.load(FIXTURE, sqlite_session)
    sqlite_session.commit()
    total2 = sqlite_session.query(GraoAddress).count()  # type: ignore[attr-defined]
    assert summary1.rows_loaded == summary2.rows_loaded
    assert total1 == total2  # TRUNCATE + reinsert is idempotent


def test_load_truncate_clears_previous_data(sqlite_session: Session) -> None:
    """Reloading replaces existing rows even if the underlying file is empty."""
    grao_loader.load(FIXTURE, sqlite_session)
    sqlite_session.commit()

    # Re-load against an empty file → expect 0 rows after.
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
        tmp.write(b"")  # zero bytes, valid windows-1251
        empty_path = Path(tmp.name)
    try:
        summary = grao_loader.load(empty_path, sqlite_session)
        sqlite_session.commit()
        assert summary.rows_loaded == 0
        assert sqlite_session.query(GraoAddress).count() == 0  # type: ignore[attr-defined]
    finally:
        empty_path.unlink()
