"""`institutions` table — one row per (external_id, kind) bucket from the
`snapshot.v1.json` contract."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from yasli.models import Base
from yasli.models.types import KIND_VALUES, Kind


class Institution(Base):
    __tablename__ = "institutions"
    __table_args__ = (
        UniqueConstraint("external_id", "kind", name="uq_institutions_external_id_kind"),
        CheckConstraint(
            "kind IN ('" + "','".join(KIND_VALUES) + "')",
            name="ck_institutions_kind",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    external_id: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    kind: Mapped[Kind] = mapped_column(String(16), nullable=False)
    source_url: Mapped[str] = mapped_column(String(512), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
