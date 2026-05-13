"""`grao_addresses` table — ГРАО (Главна Дирекция ГРАО) Address Classifier
reference rows for Varna.

Rows are loaded from the published KADS plaintext file (``kads-03-06.txt``)
by ``yasli.ingest.grao_loader``, not from the weekly DG snapshot. The
table is the ground truth for the (street, number, entrance) → район
mapping consumed by the district-stamping pass.

The table uses a surrogate primary key because real KADS files can contain
the same apparent street/number tuple in multiple sections or districts. The
loader preserves those rows; the stamping pass only accepts a lookup when the
matching rows agree on one district. The loader still substitutes the empty
string ``""`` for absent suffix/entrance so ``COALESCE`` joins line up.
"""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from yasli.models import Base
from yasli.models.types import DistrictCode


class GraoAddress(Base):
    __tablename__ = "grao_addresses"
    __table_args__ = (
        PrimaryKeyConstraint(
            "id",
            name="grao_addresses_pkey",
        ),
        CheckConstraint(
            "district_code IN ('01','02','03','04','05')",
            name="ck_grao_addresses_district_code",
        ),
        Index(
            "ix_grao_addresses_search_norm_number_int",
            "search_norm",
            "number_int",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, autoincrement=True, nullable=False)
    street_code: Mapped[str] = mapped_column(
        String(5), nullable=False
    )
    street_raw: Mapped[str] = mapped_column(String(256), nullable=False)
    search_norm: Mapped[str] = mapped_column(String(256), nullable=False)
    number_int: Mapped[int] = mapped_column(
        SmallInteger, nullable=False
    )
    number_suffix: Mapped[str] = mapped_column(
        String(2), nullable=False
    )
    entrance: Mapped[str] = mapped_column(
        String(4), nullable=False
    )
    district_code: Mapped[DistrictCode] = mapped_column(String(2), nullable=False)
    district_name: Mapped[str] = mapped_column(String(64), nullable=False)
    settlement_code: Mapped[str] = mapped_column(String(5), nullable=False)
    section_no: Mapped[int] = mapped_column(SmallInteger, nullable=False)
