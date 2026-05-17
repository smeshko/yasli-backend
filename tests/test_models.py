"""ORM smoke tests — no database required.

Asserts the v2 tables are registered on `Base.metadata` and that
`Institution.kind` is annotated with the closed `Literal` set that matches
the database CHECK constraint.
"""

from __future__ import annotations

import typing

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from yasli.models import (
    Address,
    Base,
    GraoAddress,
    Institution,
    Settlement,
    Street,
    address_institutions,
)
from yasli.models.types import DISTRICT_CODE_VALUES, KIND_VALUES, LOCALITY_TYPE_VALUES


def test_metadata_registers_v2_tables() -> None:
    tables = set(Base.metadata.tables.keys())
    assert {
        "institutions",
        "streets",
        "addresses",
        "address_institutions",
        "grao_addresses",
        "settlements",
    }.issubset(tables)
    assert "address_entries" not in tables


def test_orm_classes_resolve() -> None:
    assert Institution.__tablename__ == "institutions"
    assert Street.__tablename__ == "streets"
    assert Address.__tablename__ == "addresses"
    assert address_institutions.name == "address_institutions"
    assert GraoAddress.__tablename__ == "grao_addresses"
    assert Settlement.__tablename__ == "settlements"


def test_institution_kind_literal_matches_check_constraint() -> None:
    hints = typing.get_type_hints(
        Institution,
        localns={"Address": Address},
        include_extras=False,
    )
    kind_type = hints["kind"]
    # `Mapped[Kind]` resolves to `Mapped[Literal[...]]`; unwrap once to get
    # at the underlying Literal so `typing.get_args` returns its values.
    inner_args = typing.get_args(kind_type)
    assert len(inner_args) == 1, kind_type
    literal_args = typing.get_args(inner_args[0])
    assert set(literal_args) == set(KIND_VALUES)


def test_institution_metadata_columns_registered() -> None:
    columns = Institution.__table__.c
    assert columns.address.nullable is True
    assert columns.district_code.nullable is True
    assert columns.has_infant_group.nullable is False


def test_institution_district_code_literal_matches_check_constraint() -> None:
    hints = typing.get_type_hints(
        Institution,
        localns={"Address": Address},
        include_extras=False,
    )
    dc_type = hints["district_code"]
    # Mapped[Optional[DistrictCode]] → typing.get_args returns the Optional-
    # wrapped Literal. Unwrap one layer for the Literal, then collect args.
    inner_args = typing.get_args(dc_type)
    assert len(inner_args) == 1, dc_type
    optional_type = inner_args[0]
    # typing.get_args on Optional[X] returns (X, NoneType).
    optional_args = typing.get_args(optional_type)
    literal_type = next(a for a in optional_args if a is not type(None))
    literal_args = typing.get_args(literal_type)
    assert set(literal_args) == set(DISTRICT_CODE_VALUES)


def test_address_district_code_literal_matches_check_constraint() -> None:
    hints = typing.get_type_hints(
        Address,
        localns={"Institution": Institution},
        include_extras=False,
    )
    dc_type = hints["district_code"]
    inner_args = typing.get_args(dc_type)
    assert len(inner_args) == 1, dc_type
    optional_type = inner_args[0]
    optional_args = typing.get_args(optional_type)
    literal_type = next(a for a in optional_args if a is not type(None))
    literal_args = typing.get_args(literal_type)
    assert set(literal_args) == set(DISTRICT_CODE_VALUES)


def test_address_district_code_column_is_nullable() -> None:
    assert Address.__table__.c.district_code.nullable is True


def test_settlement_locality_type_literal_matches_check_constraint() -> None:
    hints = typing.get_type_hints(
        Settlement,
        include_extras=False,
    )
    locality_type = hints["locality_type"]
    inner_args = typing.get_args(locality_type)
    assert len(inner_args) == 1, locality_type
    literal_args = typing.get_args(inner_args[0])
    assert set(literal_args) == set(LOCALITY_TYPE_VALUES)


def test_settlement_columns_registered() -> None:
    cols = Settlement.__table__.c
    expected = {
        "code",
        "name",
        "locality_type",
        "municipality_code",
        "municipality_name",
        "source",
    }
    actual_cols = {c.name for c in cols}
    assert expected.issubset(actual_cols)
    assert cols.code.primary_key is True
    assert cols.code.nullable is False
    assert cols.name.nullable is False
    assert cols.locality_type.nullable is False
    assert cols.municipality_code.nullable is False
    assert cols.municipality_name.nullable is False
    assert cols.source.nullable is False
    assert cols.code.type.length == 5
    assert cols.name.type.length == 64
    assert cols.locality_type.type.length == 16
    assert cols.municipality_code.type.length == 2
    assert cols.municipality_name.type.length == 64
    assert cols.source.type.length == 32


def test_grao_address_columns_registered() -> None:
    cols = GraoAddress.__table__.c
    expected_non_null = {
        "id",
        "street_code",
        "street_raw",
        "search_norm",
        "number_int",
        "number_suffix",
        "entrance",
        "district_code",
        "district_name",
        "settlement_code",
        "section_no",
    }
    actual_cols = {c.name for c in cols}
    assert expected_non_null.issubset(actual_cols)
    for name in expected_non_null:
        assert cols[name].nullable is False, name


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


def test_address_district_code_round_trips(session_factory) -> None:
    """Insert an address with district_code, reload it, assert the value
    survives through the typed column (task 1.8)."""
    with Session(session_factory) as s:
        s.add(
            Street(
                id=1,
                city="ГР.ВАРНА",
                raw_name="ул. Round",
                street_part="Round",
                type_marker="ул.",
                search_norm="round",
            )
        )
        s.add(Address(id=10, street_id=1, number_int=7, district_code="02"))
        s.add(Address(id=11, street_id=1, number_int=8, district_code=None))
        s.commit()

    with Session(session_factory) as s:
        stamped = s.execute(select(Address).where(Address.id == 10)).scalar_one()
        unstamped = s.execute(select(Address).where(Address.id == 11)).scalar_one()
        assert stamped.district_code == "02"
        assert unstamped.district_code is None


def test_grao_address_round_trips(session_factory) -> None:
    with Session(session_factory) as s:
        s.add(
            GraoAddress(
                street_code="06598",
                street_raw="УЛ.Н.Й.ВАПЦАРОВ",
                search_norm="n.y.vaptsarov",
                number_int=7,
                number_suffix="",
                entrance="А",
                district_code="02",
                district_name="ПРИМОРСКИ",
                settlement_code="10135",
                section_no=42,
            )
        )
        s.commit()

    with Session(session_factory) as s:
        row = s.execute(select(GraoAddress)).scalar_one()
        assert row.district_code == "02"
        assert row.district_name == "ПРИМОРСКИ"
        assert row.entrance == "А"
        assert row.number_suffix == ""


def test_settlement_round_trips(session_factory) -> None:
    with Session(session_factory) as s:
        s.add(
            Settlement(
                code="99999",
                name="ТЕСТ",
                locality_type="city",
            )
        )
        s.commit()

    with Session(session_factory) as s:
        row = s.execute(select(Settlement)).scalar_one()
        assert row.code == "99999"
        assert row.name == "ТЕСТ"
        assert row.locality_type == "city"
        assert row.municipality_code == "06"
        assert row.municipality_name == "ВАРНА"
        assert row.source == "grao_kads"
