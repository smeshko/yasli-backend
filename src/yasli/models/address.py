"""`addresses` table — one row per distinct physical address.

A surrogate `id` primary key is used because the natural key
`(street_id, number_int, number_suffix, entrance)` includes nullable
columns and Postgres `PRIMARY KEY` columns are implicitly NOT NULL.
The composite UNIQUE constraint enforces "one row per natural address"
under Postgres' standard NULL-as-distinct semantics; ingest collapses
near-duplicates before insert.

The address ↔ institution coverage edge lives on the `address_institutions`
junction table (no ORM class — it has no business identity beyond the
composite key). It is exposed here as a SQLAlchemy `Table` and wired
into `Address.institutions` / `Institution.addresses` as a many-to-many
relationship with `lazy="raise"` to keep ingest explicit about its joins.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    ForeignKey,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from yasli.models import Base
from yasli.models.types import DistrictCode

if TYPE_CHECKING:
    from yasli.models.institution import Institution


address_institutions = Table(
    "address_institutions",
    Base.metadata,
    Column(
        "address_id",
        BigInteger,
        ForeignKey("addresses.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "institution_id",
        BigInteger,
        ForeignKey("institutions.id", ondelete="CASCADE"),
        nullable=False,
    ),
    PrimaryKeyConstraint(
        "address_id",
        "institution_id",
        name="address_institutions_pkey",
    ),
)


class Address(Base):
    __tablename__ = "addresses"
    __table_args__ = (
        UniqueConstraint(
            "street_id",
            "number_int",
            "number_suffix",
            "entrance",
            name="uq_addresses_natural",
        ),
        CheckConstraint(
            "district_code IS NULL OR district_code IN ('01','02','03','04','05')",
            name="ck_addresses_district_code",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    street_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("streets.id", ondelete="CASCADE"),
        nullable=False,
    )
    number_int: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    number_suffix: Mapped[str | None] = mapped_column(String(2), nullable=True)
    entrance: Mapped[str | None] = mapped_column(String(4), nullable=True)
    district_code: Mapped[DistrictCode | None] = mapped_column(
        String(2), nullable=True
    )

    institutions: Mapped[list["Institution"]] = relationship(
        "Institution",
        secondary=address_institutions,
        back_populates="addresses",
        lazy="raise",
    )
