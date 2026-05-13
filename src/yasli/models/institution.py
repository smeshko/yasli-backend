"""`institutions` table — one row per (external_id, kind) bucket from the
`snapshot.v2.json` contract."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    String,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from yasli.models import Base
from yasli.models.types import KIND_VALUES, Kind

if TYPE_CHECKING:
    from yasli.models.address import Address


class Institution(Base):
    __tablename__ = "institutions"
    __table_args__ = (
        UniqueConstraint("external_id", "kind", name="uq_institutions_external_id_kind"),
        CheckConstraint(
            "kind IN ('" + "','".join(KIND_VALUES) + "')",
            name="ck_institutions_kind",
        ),
        CheckConstraint(
            "district_code IS NULL OR district_code IN ('01','02','03','04','05')",
            name="ck_institutions_district_code",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    external_id: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    kind: Mapped[Kind] = mapped_column(String(16), nullable=False)
    source_url: Mapped[str] = mapped_column(String(512), nullable=False)
    address: Mapped[str | None] = mapped_column(String(256), nullable=True)
    district_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    has_infant_group: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    addresses: Mapped[list["Address"]] = relationship(
        "Address",
        secondary="address_institutions",
        back_populates="institutions",
        lazy="raise",
    )
