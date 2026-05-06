"""`streets` table — one row per distinct verbatim street string from the
snapshot, with the normalised form ingest computes for fuzzy lookup."""

from __future__ import annotations

from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from yasli.models import Base


class Street(Base):
    __tablename__ = "streets"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    city: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_name: Mapped[str] = mapped_column(String(256), nullable=False, unique=True)
    street_part: Mapped[str] = mapped_column(String(256), nullable=False)
    type_marker: Mapped[str | None] = mapped_column(String(8), nullable=True)
    search_norm: Mapped[str] = mapped_column(String(256), nullable=False)
