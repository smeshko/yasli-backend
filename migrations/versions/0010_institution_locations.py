"""institution_locations

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-15 12:00:00.000000

Adds the ``institution_locations`` reference table: one row per building an
institution occupies (its ``main`` building or a ``branch``), keyed to
``institutions`` by the natural key ``(external_id, kind)``, with a
coordinate and mandatory provenance columns (``precision``, ``source``,
``verification``, ``verified_at``). Rows are loaded from the committed
``data/institution_locations.csv`` by
``yasli.ingest.institution_locations_loader``, never by the weekly ingest.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: Union[str, Sequence[str], None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "institution_locations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("external_id", sa.String(length=16), nullable=False),
        sa.Column("role", sa.String(length=8), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column("address", sa.String(length=256), nullable=False),
        sa.Column("lat", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("lon", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("precision", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("verification", sa.String(length=8), nullable=False),
        sa.Column("verified_at", sa.Date(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="institution_locations_pkey"),
        sa.UniqueConstraint(
            "kind",
            "external_id",
            "role",
            "label",
            "address",
            name="uq_institution_locations_building",
        ),
        sa.ForeignKeyConstraint(
            ["external_id", "kind"],
            ["institutions.external_id", "institutions.kind"],
            ondelete="RESTRICT",
            onupdate="CASCADE",
            name="fk_institution_locations_institution",
        ),
        sa.CheckConstraint(
            "kind IN ('nursery','kindergarten','preschool')",
            name="ck_institution_locations_kind",
        ),
        sa.CheckConstraint(
            "role IN ('main','branch')",
            name="ck_institution_locations_role",
        ),
        sa.CheckConstraint(
            "precision IN ('building','approximate','none')",
            name="ck_institution_locations_precision",
        ),
        sa.CheckConstraint(
            "source IN ('osm_poi','nominatim','manual')",
            name="ck_institution_locations_source",
        ),
        sa.CheckConstraint(
            "verification IN ('auto','human')",
            name="ck_institution_locations_verification",
        ),
        sa.CheckConstraint(
            "(lat IS NULL) = (lon IS NULL)",
            name="ck_institution_locations_coordinate_pair",
        ),
        sa.CheckConstraint(
            "(precision = 'none') = (lat IS NULL)",
            name="ck_institution_locations_precision_none",
        ),
        sa.CheckConstraint(
            "NOT (source = 'manual' AND verification = 'auto')",
            name="ck_institution_locations_manual_not_auto",
        ),
        sa.CheckConstraint(
            "verification <> 'auto' OR "
            "(source = 'osm_poi' AND role = 'main' AND precision = 'building')",
            name="ck_institution_locations_auto_shape",
        ),
    )
    # Exactly one `main` row per institution; also the (kind, external_id)
    # lookup index for the detail endpoint.
    op.create_index(
        "uq_institution_locations_main",
        "institution_locations",
        ["kind", "external_id"],
        unique=True,
        postgresql_where=sa.text("role = 'main'"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("uq_institution_locations_main", table_name="institution_locations")
    op.drop_table("institution_locations")
