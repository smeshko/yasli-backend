"""`address_entries` table — one row per (institution, street, number)
observed in the snapshot. No `priority_class` column per s02 Decision 8.

A synthetic `id` primary key is used so that `number_suffix` and `entrance`
can remain nullable (Postgres `PRIMARY KEY` columns are implicitly NOT
NULL); composite uniqueness is enforced by a separate `UNIQUE` constraint
which honours Postgres' "NULL ≠ NULL" treatment.
"""

from __future__ import annotations

from sqlalchemy import BigInteger, ForeignKey, SmallInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from yasli.models import Base


class AddressEntry(Base):
    __tablename__ = "address_entries"
    __table_args__ = (
        UniqueConstraint(
            "institution_id",
            "street_id",
            "number_int",
            "number_suffix",
            "entrance",
            name="uq_address_entries_full",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    institution_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("institutions.id", ondelete="CASCADE"),
        nullable=False,
    )
    street_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("streets.id", ondelete="CASCADE"),
        nullable=False,
    )
    number_int: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    number_suffix: Mapped[str | None] = mapped_column(String(2), nullable=True)
    entrance: Mapped[str | None] = mapped_column(String(4), nullable=True)
