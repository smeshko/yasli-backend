"""grao_district_routing

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-13 12:00:00.000000

Adds the ГРАО (Bulgarian civil registry) address-classifier reference table
``grao_addresses`` and the nullable ``addresses.district_code`` column
populated post-ingest by the district-stamping pass. ``institutions.district_code``
(owned by revision 0004) is untouched.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: Union[str, Sequence[str], None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "grao_addresses",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("street_code", sa.String(length=5), nullable=False),
        sa.Column("street_raw", sa.String(length=256), nullable=False),
        sa.Column("search_norm", sa.String(length=256), nullable=False),
        sa.Column("number_int", sa.SmallInteger(), nullable=False),
        sa.Column("number_suffix", sa.String(length=2), nullable=False),
        sa.Column("entrance", sa.String(length=4), nullable=False),
        sa.Column("district_code", sa.String(length=2), nullable=False),
        sa.Column("district_name", sa.String(length=64), nullable=False),
        sa.Column("settlement_code", sa.String(length=5), nullable=False),
        sa.Column("section_no", sa.SmallInteger(), nullable=False),
        sa.PrimaryKeyConstraint(
            "id",
            name="grao_addresses_pkey",
        ),
        sa.CheckConstraint(
            "district_code IN ('01','02','03','04','05')",
            name="ck_grao_addresses_district_code",
        ),
    )
    op.create_index(
        "ix_grao_addresses_search_norm_number_int",
        "grao_addresses",
        ["search_norm", "number_int"],
    )

    op.add_column(
        "addresses",
        sa.Column("district_code", sa.String(length=2), nullable=True),
    )
    op.create_check_constraint(
        "ck_addresses_district_code",
        "addresses",
        "district_code IS NULL OR district_code IN ('01','02','03','04','05')",
    )


def downgrade() -> None:
    """Downgrade schema. institutions.district_code (revision 0004) is untouched."""
    op.drop_constraint("ck_addresses_district_code", "addresses", type_="check")
    op.drop_column("addresses", "district_code")
    op.drop_index(
        "ix_grao_addresses_search_norm_number_int",
        table_name="grao_addresses",
    )
    op.drop_table("grao_addresses")
