"""Tests for the addresses + institutions district-stamping passes.

Uses an in-memory SQLite. Both Postgres and SQLite execute the
correlated-subquery UPDATE shape the same way, so behavior is comparable
without testcontainers.

The ``streets`` rows use the same ``search_norm`` form ГРАО stores
(stripped type marker, lowercase ICAO transliteration). Tests build
``grao_addresses`` rows by hand to set up the join conditions explicitly.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, insert, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from yasli.geo.settlements import VARNA_SETTLEMENTS
from yasli.ingest import district_stamp
from yasli.models import (
    Address,
    Base,
    GraoAddress,
    Institution,
    Street,
    address_institutions,
)


@pytest.fixture
def session():
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


def _add_street(session: Session, *, id: int, search_norm: str, raw: str) -> None:
    session.add(
        Street(
            id=id,
            city="ГР.ВАРНА",
            raw_name=raw,
            street_part=raw,
            type_marker="ул.",
            search_norm=search_norm,
        )
    )


def _add_address(
    session: Session,
    *,
    id: int,
    street_id: int,
    number_int: int,
    number_suffix: str | None = None,
    entrance: str | None = None,
    district_code: str | None = None,
    settlement_code: str | None = None,
) -> None:
    session.add(
        Address(
            id=id,
            street_id=street_id,
            number_int=number_int,
            number_suffix=number_suffix,
            entrance=entrance,
            district_code=district_code,
            settlement_code=settlement_code,
        )
    )


def _add_grao(
    session: Session,
    *,
    street_code: str,
    search_norm: str,
    raw: str,
    number_int: int,
    number_suffix: str = "",
    entrance: str = "",
    district_code: str,
    district_name: str = "X",
    settlement_code: str = "10135",
    section_no: int = 1,
) -> None:
    session.add(
        GraoAddress(
            street_code=street_code,
            street_raw=raw,
            search_norm=search_norm,
            number_int=number_int,
            number_suffix=number_suffix,
            entrance=entrance,
            district_code=district_code,
            district_name=district_name,
            settlement_code=settlement_code,
            section_no=section_no,
        )
    )


# ---------------------------------------------------------------------------
# Addresses pass
# ---------------------------------------------------------------------------


def test_primary_join_stamps_exact_match(session: Session) -> None:
    _add_street(session, id=1, search_norm="vapcarov", raw="ул. Вапцаров")
    _add_address(session, id=10, street_id=1, number_int=7, entrance="А")
    _add_grao(
        session,
        street_code="06598",
        search_norm="vapcarov",
        raw="УЛ.ВАПЦАРОВ",
        number_int=7,
        entrance="А",
        district_code="02",
    )
    session.commit()

    summary = district_stamp.stamp_addresses_unmatched(session)
    session.commit()

    assert summary.primary_stamped == 1
    a = session.execute(select(Address).where(Address.id == 10)).scalar_one()
    assert a.district_code == "02"


def test_primary_join_handles_null_suffix_and_entrance_via_coalesce(
    session: Session,
) -> None:
    _add_street(session, id=1, search_norm="morska", raw="ул. Морска")
    _add_address(session, id=10, street_id=1, number_int=5)
    _add_grao(
        session,
        street_code="00100",
        search_norm="morska",
        raw="УЛ.МОРСКА",
        number_int=5,
        number_suffix="",
        entrance="",
        district_code="01",
    )
    session.commit()
    district_stamp.stamp_addresses_unmatched(session)
    session.commit()
    a = session.execute(select(Address).where(Address.id == 10)).scalar_one()
    assert a.district_code == "01"


def test_primary_join_declines_when_exact_kads_rows_disagree(
    session: Session,
) -> None:
    """Real KADS files can repeat an apparent street/number tuple across
    districts. Exact lookup must only stamp when all matching rows agree.
    """
    _add_street(session, id=1, search_norm="akatsiya", raw="ул. Акация")
    _add_address(session, id=10, street_id=1, number_int=2)
    _add_grao(
        session,
        street_code="00446",
        search_norm="akatsiya",
        raw="УЛ.АКАЦИЯ",
        number_int=2,
        district_code="02",
        section_no=96,
    )
    _add_grao(
        session,
        street_code="02751",
        search_norm="akatsiya",
        raw="УЛ.АКАЦИЯ",
        number_int=2,
        district_code="05",
        section_no=400,
    )
    session.commit()

    summary = district_stamp.stamp_addresses_unmatched(session)
    session.commit()

    assert summary.primary_stamped == 0
    assert summary.fallback1_stamped == 0
    assert summary.fallback2_stamped == 0
    a = session.execute(select(Address).where(Address.id == 10)).scalar_one()
    assert a.district_code is None


def test_fallback1_entrance_less_resolves(session: Session) -> None:
    """When the exact entrance does not match but every match for that
    (search_norm, number_int, number_suffix) tuple shares one district,
    fallback 1 fills it in.
    """
    _add_street(session, id=1, search_norm="x", raw="ул. Х")
    _add_address(session, id=10, street_id=1, number_int=5, number_suffix="А", entrance="1")
    # ГРАО has the same number but with empty entrance.
    _add_grao(
        session,
        street_code="00001",
        search_norm="x",
        raw="УЛ.Х",
        number_int=5,
        number_suffix="А",
        entrance="",
        district_code="04",
    )
    session.commit()
    summary = district_stamp.stamp_addresses_unmatched(session)
    session.commit()
    assert summary.primary_stamped == 0
    assert summary.fallback1_stamped == 1
    a = session.execute(select(Address).where(Address.id == 10)).scalar_one()
    assert a.district_code == "04"


def test_fallback1_entrance_less_declines_on_split_district(
    session: Session,
) -> None:
    """Multiple matches with different district_codes → leave NULL."""
    _add_street(session, id=1, search_norm="y", raw="ул. Y")
    _add_address(session, id=10, street_id=1, number_int=5, number_suffix="А", entrance="1")
    _add_grao(
        session,
        street_code="00001",
        search_norm="y",
        raw="УЛ.Y",
        number_int=5,
        number_suffix="А",
        entrance="А",
        district_code="01",
    )
    _add_grao(
        session,
        street_code="00001",
        search_norm="y",
        raw="УЛ.Y",
        number_int=5,
        number_suffix="А",
        entrance="Б",
        district_code="02",
    )
    session.commit()
    summary = district_stamp.stamp_addresses_unmatched(session)
    session.commit()
    assert summary.fallback1_stamped == 0
    a = session.execute(select(Address).where(Address.id == 10)).scalar_one()
    assert a.district_code is None


def test_fallback2_street_majority_resolves(session: Session) -> None:
    """A number absent from ГРАО for that street, but all of the street's
    ГРАО rows share one district → stamp via street-majority.
    """
    _add_street(session, id=1, search_norm="javor", raw="ул. Явор")
    _add_address(session, id=10, street_id=1, number_int=99)
    _add_grao(
        session,
        street_code="00300",
        search_norm="javor",
        raw="УЛ.ЯВОР",
        number_int=2,
        district_code="03",
    )
    _add_grao(
        session,
        street_code="00300",
        search_norm="javor",
        raw="УЛ.ЯВОР",
        number_int=4,
        district_code="03",
    )
    session.commit()
    summary = district_stamp.stamp_addresses_unmatched(session)
    session.commit()
    assert summary.fallback2_stamped == 1
    a = session.execute(select(Address).where(Address.id == 10)).scalar_one()
    assert a.district_code == "03"


def test_fallback2_declines_on_cross_district_street(session: Session) -> None:
    """A boulevard that straddles районs → fallback declines; stays NULL."""
    _add_street(session, id=1, search_norm="primorski", raw="бул. Приморски")
    _add_address(session, id=10, street_id=1, number_int=999)
    _add_grao(
        session,
        street_code="00400",
        search_norm="primorski",
        raw="БУЛ.ПРИМОРСКИ",
        number_int=10,
        district_code="01",
    )
    _add_grao(
        session,
        street_code="00400",
        search_norm="primorski",
        raw="БУЛ.ПРИМОРСКИ",
        number_int=20,
        district_code="02",
    )
    session.commit()
    summary = district_stamp.stamp_addresses_unmatched(session)
    session.commit()
    assert summary.fallback2_stamped == 0
    a = session.execute(select(Address).where(Address.id == 10)).scalar_one()
    assert a.district_code is None
    assert summary.remaining_null == 1
    assert summary.null_sample  # populated


def test_re_running_gated_pass_on_fully_stamped_db_is_noop(
    session: Session,
) -> None:
    """Task 3.7: when every row is already stamped, the gated pass updates
    zero rows on the second run.
    """
    _add_street(session, id=1, search_norm="x", raw="ул. Х")
    _add_address(session, id=10, street_id=1, number_int=5, district_code="04")
    _add_grao(
        session,
        street_code="00001",
        search_norm="x",
        raw="УЛ.Х",
        number_int=5,
        district_code="04",
    )
    session.commit()
    summary = district_stamp.stamp_addresses_unmatched(session)
    session.commit()
    assert summary.primary_stamped == 0
    assert summary.fallback1_stamped == 0
    assert summary.fallback2_stamped == 0


def test_non_gated_restamp_overwrites_existing_stamp(session: Session) -> None:
    """Task 3.8: restamp_addresses_all() overrides a previously-stamped
    value when ГРАО reference data is changed.
    """
    _add_street(session, id=1, search_norm="x", raw="ул. Х")
    _add_address(session, id=10, street_id=1, number_int=5, district_code="04")
    # New ГРАО record reassigns the address to '03'.
    _add_grao(
        session,
        street_code="00001",
        search_norm="x",
        raw="УЛ.Х",
        number_int=5,
        district_code="03",
    )
    session.commit()
    summary = district_stamp.restamp_addresses_all(session)
    session.commit()
    assert summary.primary_stamped == 1
    a = session.execute(select(Address).where(Address.id == 10)).scalar_one()
    assert a.district_code == "03"


def test_settlement_case_sql_covers_configured_reference_data() -> None:
    sql = district_stamp._settlement_case_sql()

    assert sql.startswith("CASE ")
    assert sql.endswith(" ELSE NULL END")
    assert sql.count("WHEN ") == len(VARNA_SETTLEMENTS)
    for settlement in VARNA_SETTLEMENTS:
        for pattern in settlement.raw_name_patterns:
            assert f"s.raw_name LIKE '{pattern}'" in sql
        assert f"THEN '{settlement.code}'" in sql


def test_gated_settlement_pass_only_fills_null_settlement_code(
    session: Session,
) -> None:
    _add_street(session, id=1, search_norm="kamenar", raw="С.КАМЕНАР УЛ. Х")
    _add_address(session, id=10, street_id=1, number_int=1)
    _add_address(
        session,
        id=11,
        street_id=1,
        number_int=2,
        settlement_code="99999",
    )
    session.commit()

    summary = district_stamp.stamp_addresses_unmatched(session)
    session.commit()

    assert summary.settlement_stamped == 1
    rows = session.execute(select(Address).order_by(Address.id)).scalars().all()
    assert [row.settlement_code for row in rows] == ["35701", "99999"]


def test_non_gated_settlement_pass_recomputes_all_settlement_codes(
    session: Session,
) -> None:
    _add_street(session, id=1, search_norm="kamenar", raw="С. КАМЕНАР УЛ. Х")
    _add_address(
        session,
        id=10,
        street_id=1,
        number_int=1,
        settlement_code="99999",
    )
    session.commit()

    summary = district_stamp.restamp_addresses_all(session)
    session.commit()

    assert summary.settlement_stamped == 1
    address = session.execute(select(Address).where(Address.id == 10)).scalar_one()
    assert address.settlement_code == "35701"


# ---------------------------------------------------------------------------
# Institutions pass — catchment-majority primary + address-parse fallback
# ---------------------------------------------------------------------------


def _add_institution(
    session: Session,
    *,
    id: int,
    external_id: str,
    kind: str,
    name: str = "X",
    address: str | None = None,
    district_code: str | None = None,
) -> None:
    session.add(
        Institution(
            id=id,
            external_id=external_id,
            name=name,
            kind=kind,
            source_url="https://example.test/x",
            address=address,
            district_code=district_code,
            last_seen_at=datetime(2026, 5, 13, tzinfo=UTC),
        )
    )


def _add_edge(session: Session, *, address_id: int, institution_id: int) -> None:
    session.execute(
        insert(address_institutions),
        [{"address_id": address_id, "institution_id": institution_id}],
    )


def test_institutions_catchment_majority_unanimous(session: Session) -> None:
    _add_street(session, id=1, search_norm="x", raw="ул. Х")
    _add_address(session, id=10, street_id=1, number_int=1, district_code="04")
    _add_address(session, id=11, street_id=1, number_int=2, district_code="04")
    _add_address(session, id=12, street_id=1, number_int=3, district_code="04")
    _add_institution(session, id=100, external_id="K1", kind="kindergarten")
    _add_edge(session, address_id=10, institution_id=100)
    _add_edge(session, address_id=11, institution_id=100)
    _add_edge(session, address_id=12, institution_id=100)
    session.commit()

    summary = district_stamp.stamp_institutions_unmatched(session)
    session.commit()
    assert summary.primary_stamped == 1
    inst = session.execute(
        select(Institution).where(Institution.id == 100)
    ).scalar_one()
    assert inst.district_code == "04"


def test_institutions_catchment_plurality_wins(session: Session) -> None:
    _add_street(session, id=1, search_norm="x", raw="ул. Х")
    # 3 addresses in '04', 1 in '05'.
    for i, dc in enumerate(["04", "04", "04", "05"], start=10):
        _add_address(session, id=i, street_id=1, number_int=i, district_code=dc)
    _add_institution(session, id=100, external_id="K1", kind="kindergarten")
    for addr_id in range(10, 14):
        _add_edge(session, address_id=addr_id, institution_id=100)
    session.commit()
    district_stamp.stamp_institutions_unmatched(session)
    session.commit()
    inst = session.execute(
        select(Institution).where(Institution.id == 100)
    ).scalar_one()
    assert inst.district_code == "04"


def test_institutions_catchment_tied_breaks_alphabetically(session: Session) -> None:
    _add_street(session, id=1, search_norm="x", raw="ул. Х")
    # 2 in '04', 2 in '02' → tied → alphabetical → '02' wins.
    for i, dc in enumerate(["04", "04", "02", "02"], start=10):
        _add_address(session, id=i, street_id=1, number_int=i, district_code=dc)
    _add_institution(session, id=100, external_id="K1", kind="kindergarten")
    for addr_id in range(10, 14):
        _add_edge(session, address_id=addr_id, institution_id=100)
    session.commit()
    district_stamp.stamp_institutions_unmatched(session)
    session.commit()
    inst = session.execute(
        select(Institution).where(Institution.id == 100)
    ).scalar_one()
    assert inst.district_code == "02"


def test_nurseries_never_touched_by_institutions_pass(session: Session) -> None:
    """Task 4.6: a nursery's district_code is never changed by the pass."""
    _add_street(session, id=1, search_norm="x", raw="ул. Х")
    _add_address(session, id=10, street_id=1, number_int=1, district_code="03")
    _add_institution(
        session,
        id=100,
        external_id="N1",
        kind="nursery",
        district_code="02",
    )
    _add_edge(session, address_id=10, institution_id=100)
    session.commit()

    district_stamp.restamp_institutions_all(session)  # non-gated, would normally overwrite
    session.commit()

    inst = session.execute(
        select(Institution).where(Institution.id == 100)
    ).scalar_one()
    assert inst.district_code == "02"  # nursery's API-sourced value untouched


def test_institutions_fallback_address_parse_when_no_catchment(
    session: Session,
) -> None:
    """Task 4.8: no catchment rows → fallback to parsing institutions.address.

    The lookup goes through ``parse_street("ГР.ВАРНА БУЛ.ВЛАДИСЛАВ ВАРНЕНЧИК")``,
    which yields ``search_norm = "gr.varna bul.vladislav varnenchik"`` — the
    same form ``streets.search_norm`` carries. The fixture's GRAO row uses
    the same value so the lookup hits exactly.
    """
    composed = "gr.varna bul.vladislav varnenchik"
    _add_street(session, id=1, search_norm=composed, raw="бул. Владислав Варненчик")
    _add_grao(
        session,
        street_code="00001",
        search_norm=composed,
        raw="БУЛ.ВЛАДИСЛАВ ВАРНЕНЧИК",
        number_int=19,
        district_code="04",
    )
    _add_institution(
        session,
        id=100,
        external_id="K1",
        kind="kindergarten",
        address="ГР.ВАРНА БУЛ.ВЛАДИСЛАВ ВАРНЕНЧИК 19",
    )
    session.commit()
    summary = district_stamp.stamp_institutions_unmatched(session)
    session.commit()
    assert summary.fallback_stamped == 1
    inst = session.execute(
        select(Institution).where(Institution.id == 100)
    ).scalar_one()
    assert inst.district_code == "04"


def test_institutions_fallback_when_all_catchment_districts_null(
    session: Session,
) -> None:
    """Catchment exists but every address has NULL district_code → fallback.

    Cyrillic ``Х`` (ha) transliterates to Latin ``h`` per the ICAO table,
    so ``to_search_norm("ГР.ВАРНА УЛ.Х") == "gr.varna ul.h"``.
    """
    composed = "gr.varna ul.h"
    _add_street(session, id=1, search_norm=composed, raw="ул. Х")
    _add_address(session, id=10, street_id=1, number_int=1)  # district_code IS NULL
    _add_address(session, id=11, street_id=1, number_int=2)  # district_code IS NULL
    _add_grao(
        session,
        street_code="00001",
        search_norm=composed,
        raw="УЛ.Х",
        number_int=99,
        district_code="03",
    )
    _add_institution(
        session,
        id=100,
        external_id="K1",
        kind="kindergarten",
        address="ГР.ВАРНА УЛ.Х 99",
    )
    _add_edge(session, address_id=10, institution_id=100)
    _add_edge(session, address_id=11, institution_id=100)
    session.commit()
    summary = district_stamp.stamp_institutions_unmatched(session)
    session.commit()
    assert summary.fallback_stamped == 1
    inst = session.execute(
        select(Institution).where(Institution.id == 100)
    ).scalar_one()
    assert inst.district_code == "03"


def test_institutions_unstampable_remains_null_with_reason(session: Session) -> None:
    """No catchment AND no parsable address → NULL with reason logged."""
    _add_institution(
        session,
        id=100,
        external_id="K1",
        kind="kindergarten",
        address=None,
    )
    session.commit()
    summary = district_stamp.stamp_institutions_unmatched(session)
    session.commit()
    assert summary.remaining_null == 1
    inst = session.execute(
        select(Institution).where(Institution.id == 100)
    ).scalar_one()
    assert inst.district_code is None
    assert len(summary.null_sample) == 1
    assert summary.null_sample[0].external_id == "K1"
    assert summary.null_sample[0].reason in {
        "no_catchment",
        "all_catchment_null",
        "address_parse_failed",
    }


def test_cli_restamp_districts_touches_only_addresses_and_institutions(
    session: Session,
) -> None:
    """Task 5.3: ``python -m yasli.ingest restamp-districts`` is allowed to
    modify ``addresses.district_code`` and ``institutions.district_code``,
    but must leave every other table untouched (streets, junction edges,
    grao_addresses).
    """
    from yasli.ingest.__main__ import restamp_districts_in_session

    _add_street(session, id=1, search_norm="x", raw="ул. Х")
    _add_address(session, id=10, street_id=1, number_int=1)
    _add_address(session, id=11, street_id=1, number_int=2)
    _add_grao(
        session,
        street_code="00001",
        search_norm="x",
        raw="УЛ.Х",
        number_int=1,
        district_code="03",
    )
    _add_grao(
        session,
        street_code="00001",
        search_norm="x",
        raw="УЛ.Х",
        number_int=2,
        district_code="03",
    )
    _add_institution(session, id=100, external_id="K1", kind="kindergarten")
    _add_edge(session, address_id=10, institution_id=100)
    session.commit()

    # Snapshot tables that MUST NOT change.
    streets_before = sorted(
        (s.id, s.raw_name, s.search_norm)
        for s in session.execute(select(Street)).scalars()
    )
    edges_before = sorted(
        (row.address_id, row.institution_id)
        for row in session.execute(
            select(
                address_institutions.c.address_id,
                address_institutions.c.institution_id,
            )
        )
    )
    grao_before = sorted(
        (g.street_code, g.number_int, g.district_code)
        for g in session.execute(select(GraoAddress)).scalars()
    )

    addresses_summary, institutions_summary = restamp_districts_in_session(session)
    session.commit()

    # The stamping passes did do work…
    assert addresses_summary.primary_stamped >= 1
    # …on addresses and institutions.
    a = session.execute(select(Address).where(Address.id == 10)).scalar_one()
    assert a.district_code == "03"

    # …but nothing else moved.
    streets_after = sorted(
        (s.id, s.raw_name, s.search_norm)
        for s in session.execute(select(Street)).scalars()
    )
    edges_after = sorted(
        (row.address_id, row.institution_id)
        for row in session.execute(
            select(
                address_institutions.c.address_id,
                address_institutions.c.institution_id,
            )
        )
    )
    grao_after = sorted(
        (g.street_code, g.number_int, g.district_code)
        for g in session.execute(select(GraoAddress)).scalars()
    )
    assert streets_before == streets_after
    assert edges_before == edges_after
    assert grao_before == grao_after


def test_pass_ordering_addresses_first_then_institutions(session: Session) -> None:
    """Task 4.9: running addresses pass first lets the institutions pass
    consume freshly-stamped values.
    """
    _add_street(session, id=1, search_norm="x", raw="ул. Х")
    # Addresses start NULL.
    _add_address(session, id=10, street_id=1, number_int=1)
    _add_address(session, id=11, street_id=1, number_int=2)
    _add_grao(
        session,
        street_code="00001",
        search_norm="x",
        raw="УЛ.Х",
        number_int=1,
        district_code="03",
    )
    _add_grao(
        session,
        street_code="00001",
        search_norm="x",
        raw="УЛ.Х",
        number_int=2,
        district_code="03",
    )
    _add_institution(session, id=100, external_id="K1", kind="kindergarten")
    _add_edge(session, address_id=10, institution_id=100)
    _add_edge(session, address_id=11, institution_id=100)
    session.commit()

    # Step 1: addresses pass first.
    district_stamp.stamp_addresses_unmatched(session)
    session.commit()
    addrs = session.execute(select(Address).order_by(Address.id)).scalars().all()
    assert [a.district_code for a in addrs] == ["03", "03"]

    # Step 2: institutions pass now sees the stamped catchment.
    district_stamp.stamp_institutions_unmatched(session)
    session.commit()
    inst = session.execute(
        select(Institution).where(Institution.id == 100)
    ).scalar_one()
    assert inst.district_code == "03"
