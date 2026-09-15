"""`institution_locations` table — one row per building an institution
occupies, keyed to `institutions` by its natural key `(external_id, kind)`.

Rows are loaded from the committed reference file
``data/institution_locations.csv`` by ``yasli.ingest.institution_locations_loader``,
never from the weekly snapshot. Every row carries how precise the pin is
(``precision``), where the coordinate came from (``source``) and how the row
was decided (``verification``): ``auto`` for a unique OSM POI match that
passed the seed script's four rules, ``human`` for a decision made in the
review tool.

``label`` and ``address`` are stored as the empty string when absent (the
``grao_addresses`` convention) so the UNIQUE tuple actually constrains —
Postgres treats NULLs as distinct.

The surrogate ``id`` is ``BigInteger().with_variant(Integer, "sqlite")``:
Postgres gets ``BIGINT``, while SQLite (the loader tests) gets a plain
``INTEGER PRIMARY KEY`` that autoincrements when rows are inserted without
an ``id``. The loader truncates, so ``id`` is never a join key.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from yasli.models import Base
from yasli.models.types import (
    KIND_VALUES,
    PRECISION_VALUES,
    ROLE_VALUES,
    SOURCE_VALUES,
    VERIFICATION_VALUES,
    Kind,
    LocationPrecision,
    LocationRole,
    LocationSource,
    LocationVerification,
)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ('" + "','".join(values) + "')"


class InstitutionLocation(Base):
    __tablename__ = "institution_locations"
    __table_args__ = (
        UniqueConstraint(
            "kind",
            "external_id",
            "role",
            "label",
            "address",
            name="uq_institution_locations_building",
        ),
        ForeignKeyConstraint(
            ["external_id", "kind"],
            ["institutions.external_id", "institutions.kind"],
            ondelete="RESTRICT",
            onupdate="CASCADE",
            name="fk_institution_locations_institution",
        ),
        CheckConstraint(_in("kind", KIND_VALUES), name="ck_institution_locations_kind"),
        CheckConstraint(_in("role", ROLE_VALUES), name="ck_institution_locations_role"),
        CheckConstraint(
            _in("precision", PRECISION_VALUES), name="ck_institution_locations_precision"
        ),
        CheckConstraint(_in("source", SOURCE_VALUES), name="ck_institution_locations_source"),
        CheckConstraint(
            _in("verification", VERIFICATION_VALUES),
            name="ck_institution_locations_verification",
        ),
        # A half-coordinate is always a bug.
        CheckConstraint(
            "(lat IS NULL) = (lon IS NULL)",
            name="ck_institution_locations_coordinate_pair",
        ),
        # Provenance and data agree: no pin <=> precision 'none'.
        CheckConstraint(
            "(precision = 'none') = (lat IS NULL)",
            name="ck_institution_locations_precision_none",
        ),
        # A hand-placed pin cannot have been auto-accepted.
        CheckConstraint(
            "NOT (source = 'manual' AND verification = 'auto')",
            name="ck_institution_locations_manual_not_auto",
        ),
        # The part of the auto-accept rules the database can enforce: an
        # auto-accepted row is always a unique POI match on a main building.
        CheckConstraint(
            "verification <> 'auto' OR "
            "(source = 'osm_poi' AND role = 'main' AND precision = 'building')",
            name="ck_institution_locations_auto_shape",
        ),
        # Exactly one `main` row per institution. Doubles as the
        # `(kind, external_id)` lookup index for the detail endpoint.
        Index(
            "uq_institution_locations_main",
            "kind",
            "external_id",
            unique=True,
            postgresql_where=text("role = 'main'"),
            sqlite_where=text("role = 'main'"),
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    kind: Mapped[Kind] = mapped_column(String(16), nullable=False)
    external_id: Mapped[str] = mapped_column(String(16), nullable=False)
    role: Mapped[LocationRole] = mapped_column(String(8), nullable=False)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    address: Mapped[str] = mapped_column(String(256), nullable=False)
    lat: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    lon: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    precision: Mapped[LocationPrecision] = mapped_column(String(16), nullable=False)
    source: Mapped[LocationSource] = mapped_column(String(16), nullable=False)
    verification: Mapped[LocationVerification] = mapped_column(String(8), nullable=False)
    verified_at: Mapped[date] = mapped_column(Date, nullable=False)
