"""address_centric_schema

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-07 09:00:00.000000

Replaces the institution-centric `address_entries` table with an
address-centric pair: `addresses` (one row per distinct physical address)
plus `address_institutions` (junction table for the many-to-many coverage
relationship).

The why is documented in
`openspec/changes/address-centric-schema/` (proposal, design, specs).
The drop-and-recreate is justified because no production data exists yet;
`downgrade()` recreates `address_entries` empty so the round-trip lands at
the revision-`0002` shape.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_index("address_entries_lookup", table_name="address_entries")
    op.drop_table("address_entries")

    op.create_table(
        "addresses",
        sa.Column(
            "id",
            sa.BigInteger(),
            sa.Identity(always=False),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "street_id",
            sa.BigInteger(),
            sa.ForeignKey("streets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("number_int", sa.SmallInteger(), nullable=False),
        sa.Column("number_suffix", sa.String(length=2), nullable=True),
        sa.Column("entrance", sa.String(length=4), nullable=True),
        sa.UniqueConstraint(
            "street_id",
            "number_int",
            "number_suffix",
            "entrance",
            name="uq_addresses_natural",
        ),
    )

    op.create_table(
        "address_institutions",
        sa.Column(
            "address_id",
            sa.BigInteger(),
            sa.ForeignKey("addresses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "institution_id",
            sa.BigInteger(),
            sa.ForeignKey("institutions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "address_id",
            "institution_id",
            name="address_institutions_pkey",
        ),
    )

    op.create_index(
        "ix_address_institutions_address_id",
        "address_institutions",
        ["address_id"],
    )


def downgrade() -> None:
    """Downgrade schema.

    Drops the new tables and recreates `address_entries` empty with the
    columns, constraints, and lookup index defined in revision `0002`.
    """
    op.drop_index(
        "ix_address_institutions_address_id",
        table_name="address_institutions",
    )
    op.drop_table("address_institutions")
    op.drop_table("addresses")

    op.create_table(
        "address_entries",
        sa.Column(
            "id",
            sa.BigInteger(),
            sa.Identity(always=False),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "institution_id",
            sa.BigInteger(),
            sa.ForeignKey("institutions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "street_id",
            sa.BigInteger(),
            sa.ForeignKey("streets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("number_int", sa.SmallInteger(), nullable=False),
        sa.Column("number_suffix", sa.String(length=2), nullable=True),
        sa.Column("entrance", sa.String(length=4), nullable=True),
        sa.UniqueConstraint(
            "institution_id",
            "street_id",
            "number_int",
            "number_suffix",
            "entrance",
            name="uq_address_entries_full",
        ),
    )

    op.create_index(
        "address_entries_lookup",
        "address_entries",
        ["street_id", "number_int"],
    )
