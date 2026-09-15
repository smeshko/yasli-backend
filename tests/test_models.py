"""ORM smoke tests — no database required.

Asserts the v2 tables are registered on `Base.metadata` and that
`Institution.kind` is annotated with the closed `Literal` set that matches
the database CHECK constraint.
"""

from __future__ import annotations

import typing
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from yasli.models import (
    Address,
    Base,
    GraoAddress,
    Institution,
    InstitutionLocation,
    Settlement,
    Street,
    address_institutions,
)
from yasli.models.types import (
    DISTRICT_CODE_VALUES,
    KIND_VALUES,
    LOCALITY_TYPE_VALUES,
    PRECISION_VALUES,
    ROLE_VALUES,
    SOURCE_VALUES,
    VERIFICATION_VALUES,
)


def test_metadata_registers_v2_tables() -> None:
    tables = set(Base.metadata.tables.keys())
    assert {
        "institutions",
        "streets",
        "addresses",
        "address_institutions",
        "grao_addresses",
        "settlements",
        "institution_locations",
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


CONTACT_COLUMNS = {"phone": 128, "email": 256, "director": 256, "website": 256}


def test_institution_contact_columns_registered() -> None:
    columns = Institution.__table__.c
    for name, length in CONTACT_COLUMNS.items():
        assert columns[name].nullable is True, name
        assert columns[name].type.length == length, name
        assert columns[name].server_default is None, name


def test_institution_contacts_default_to_none() -> None:
    inst = Institution(external_id="1", name="ДГ 1", kind="kindergarten")
    for name in CONTACT_COLUMNS:
        assert getattr(inst, name) is None


def test_institution_contacts_round_trip(session_factory) -> None:
    from datetime import datetime, timezone

    seen = datetime(2026, 9, 13, tzinfo=timezone.utc)
    contacts = {
        "phone": "052 123 456 / 0888 123 456",
        "email": "dg1@varna.bg",
        "director": "Мария Петрова",
        "website": "https://dg1.example.bg",
    }
    with Session(session_factory) as s:
        s.add(
            Institution(
                id=1,
                external_id="1",
                name="ДГ 1",
                kind="kindergarten",
                source_url="https://x",
                last_seen_at=seen,
                **contacts,
            )
        )
        s.add(
            Institution(
                id=2,
                external_id="2",
                name="ДГ 2",
                kind="kindergarten",
                source_url="https://x",
                last_seen_at=seen,
            )
        )
        s.commit()
    with Session(session_factory) as s:
        with_contacts = s.get(Institution, 1)
        without = s.get(Institution, 2)
        for name, value in contacts.items():
            assert getattr(with_contacts, name) == value
            assert getattr(without, name) is None


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


# --- institution_locations (revision 0010) ---------------------------------


LOCATION_ROW = {
    "kind": "kindergarten",
    "external_id": "46",
    "role": "main",
    "label": "",
    "address": 'ул. "Никола Михайловски" №6',
    "lat": Decimal("43.206500"),
    "lon": Decimal("27.914200"),
    "precision": "building",
    "source": "osm_poi",
    "verification": "auto",
    "verified_at": date(2026, 9, 14),
}


def _location(**overrides):
    row = dict(LOCATION_ROW)
    row.update(overrides)
    return row


def test_metadata_registers_institution_locations() -> None:
    assert "institution_locations" in Base.metadata.tables
    assert InstitutionLocation.__tablename__ == "institution_locations"


def test_institution_location_columns_registered() -> None:
    cols = InstitutionLocation.__table__.c
    not_null = {
        "id",
        "kind",
        "external_id",
        "role",
        "label",
        "address",
        "precision",
        "source",
        "verification",
        "verified_at",
    }
    assert not_null | {"lat", "lon"} == {c.name for c in cols}
    for name in not_null:
        assert cols[name].nullable is False, name
    assert cols.lat.nullable is True
    assert cols.lon.nullable is True
    assert cols.kind.type.length == 16
    assert cols.external_id.type.length == 16
    assert cols.role.type.length == 8
    assert cols.label.type.length == 128
    assert cols.address.type.length == 256
    assert cols.precision.type.length == 16
    assert cols.source.type.length == 16
    assert cols.verification.type.length == 8
    assert (cols.lat.type.precision, cols.lat.type.scale) == (9, 6)
    assert (cols.lon.type.precision, cols.lon.type.scale) == (9, 6)


def _literal_values(cls, field: str) -> set[str]:
    hints = typing.get_type_hints(cls, include_extras=False)
    inner_args = typing.get_args(hints[field])
    assert len(inner_args) == 1, hints[field]
    return set(typing.get_args(inner_args[0]))


def test_institution_location_literals_match_value_tuples() -> None:
    assert _literal_values(InstitutionLocation, "kind") == set(KIND_VALUES)
    assert _literal_values(InstitutionLocation, "role") == set(ROLE_VALUES)
    assert _literal_values(InstitutionLocation, "precision") == set(PRECISION_VALUES)
    assert _literal_values(InstitutionLocation, "source") == set(SOURCE_VALUES)
    assert _literal_values(InstitutionLocation, "verification") == set(VERIFICATION_VALUES)


def test_institution_location_value_tuples() -> None:
    assert ROLE_VALUES == ("main", "branch")
    assert PRECISION_VALUES == ("building", "approximate", "none")
    assert SOURCE_VALUES == ("osm_poi", "nominatim", "manual")
    assert VERIFICATION_VALUES == ("auto", "human")


def test_institution_location_bulk_insert_without_id_on_sqlite(session_factory) -> None:
    """The loader inserts row dicts with no ``id``; SQLite must autoincrement."""
    rows = [
        _location(),
        _location(role="branch", address="ул. Н. Михайловски 1А", source="manual",
                  verification="human"),
        _location(external_id="17", role="branch", label="Жирафче", address="",
                  lat=None, lon=None, precision="none", source="manual",
                  verification="human"),
    ]
    with Session(session_factory) as s:
        s.execute(insert(InstitutionLocation), rows)
        s.commit()
    with Session(session_factory) as s:
        loaded = s.execute(
            select(InstitutionLocation).order_by(InstitutionLocation.id)
        ).scalars().all()
    assert [r.id for r in loaded] == [1, 2, 3]
    assert loaded[0].lat == Decimal("43.206500")
    assert loaded[2].lat is None
    assert loaded[2].label == "Жирафче"


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"lon": None}, id="lat-without-lon"),
        pytest.param({"lat": None}, id="lon-without-lat"),
        pytest.param({"precision": "none"}, id="precision-none-with-coordinate"),
        pytest.param(
            {"lat": None, "lon": None, "precision": "building", "source": "manual",
             "verification": "human"},
            id="precision-building-without-coordinate",
        ),
        pytest.param({"role": "satellite"}, id="unknown-role"),
        pytest.param({"source": "guess"}, id="unknown-source"),
        pytest.param({"precision": "street"}, id="unknown-precision"),
        pytest.param({"verification": "maybe"}, id="unknown-verification"),
        pytest.param({"kind": "infant"}, id="unknown-kind"),
        pytest.param({"source": "manual", "verification": "auto"}, id="manual-auto"),
        pytest.param({"source": "nominatim", "verification": "auto"}, id="auto-nominatim"),
        pytest.param({"role": "branch", "verification": "auto"}, id="auto-branch"),
        pytest.param(
            {"precision": "approximate", "verification": "auto"}, id="auto-approximate"
        ),
    ],
)
def test_institution_location_check_constraints_reject(session_factory, overrides) -> None:
    with Session(session_factory) as s, pytest.raises(IntegrityError):
        s.execute(insert(InstitutionLocation), [_location(**overrides)])
        s.commit()


def test_institution_location_unique_tuple(session_factory) -> None:
    with Session(session_factory) as s:
        s.execute(
            insert(InstitutionLocation),
            [
                _location(role="branch", source="manual", verification="human"),
                _location(role="branch", label="Б", source="manual", verification="human"),
            ],
        )
        s.commit()
    with Session(session_factory) as s, pytest.raises(IntegrityError):
        s.execute(
            insert(InstitutionLocation),
            [_location(role="branch", source="manual", verification="human")],
        )
        s.commit()


def test_institution_location_one_main_per_institution(session_factory) -> None:
    with Session(session_factory) as s:
        s.execute(insert(InstitutionLocation), [_location()])
        s.commit()
    with Session(session_factory) as s, pytest.raises(IntegrityError):
        s.execute(
            insert(InstitutionLocation),
            [_location(address="другаде 1", source="manual", verification="human")],
        )
        s.commit()
    with Session(session_factory) as s:
        s.execute(
            insert(InstitutionLocation),
            [
                _location(role="branch", address="ул. Батак 6", source="manual",
                          verification="human"),
                _location(role="branch", address="ул. Батак 8", source="manual",
                          verification="human"),
            ],
        )
        s.commit()
        count = s.execute(select(InstitutionLocation)).scalars().all()
    assert len(count) == 3
