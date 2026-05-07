"""ORM smoke tests — no database required.

Asserts the v1 tables are registered on `Base.metadata` and that
`Institution.kind` is annotated with the closed `Literal` set that matches
the database CHECK constraint.
"""

from __future__ import annotations

import typing

from yasli.models import Address, Base, Institution, Street, address_institutions
from yasli.models.types import KIND_VALUES


def test_metadata_registers_v1_tables() -> None:
    tables = set(Base.metadata.tables.keys())
    assert {
        "institutions",
        "streets",
        "addresses",
        "address_institutions",
    }.issubset(tables)
    assert "address_entries" not in tables


def test_orm_classes_resolve() -> None:
    assert Institution.__tablename__ == "institutions"
    assert Street.__tablename__ == "streets"
    assert Address.__tablename__ == "addresses"
    assert address_institutions.name == "address_institutions"


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
