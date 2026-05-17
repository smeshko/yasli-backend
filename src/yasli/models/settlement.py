"""`settlements` reference table for Varna municipality locality context."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, String, text
from sqlalchemy.orm import Mapped, mapped_column

from yasli.models import Base
from yasli.models.types import LOCALITY_TYPE_VALUES, LocalityType


class Settlement(Base):
    __tablename__ = "settlements"
    __table_args__ = (
        CheckConstraint(
            "locality_type IN ('" + "','".join(LOCALITY_TYPE_VALUES) + "')",
            name="ck_settlements_locality_type",
        ),
    )

    code: Mapped[str] = mapped_column(String(5), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    locality_type: Mapped[LocalityType] = mapped_column(String(16), nullable=False)
    municipality_code: Mapped[str] = mapped_column(
        String(2),
        nullable=False,
        default="06",
        server_default=text("'06'"),
    )
    municipality_name: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="ВАРНА",
        server_default=text("'ВАРНА'"),
    )
    source: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="grao_kads",
        server_default=text("'grao_kads'"),
    )
