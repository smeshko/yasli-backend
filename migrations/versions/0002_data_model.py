"""data_model

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-06 19:00:00.000000

Creates the v1 data-model schema: `pg_trgm`, the three core tables
(`institutions`, `streets`, `address_entries`), and the two non-PK indexes
(`streets_search_norm_trgm`, `address_entries_lookup`).

The why and the column semantics are documented in
`openspec/changes/s05-backend-data-model/` (proposal, design, specs). The
column names and `kind` vocabulary mirror the s02 `snapshot.v1.json`
contract verbatim.

`downgrade()` drops the indexes and tables in reverse FK order but does
NOT drop the `pg_trgm` extension — other tables can depend on it and
removing it on rollback would risk an extension-cascade surprise. See
design.md Decision 9.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


KIND_VALUES = ("nursery", "kindergarten", "preschool")


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "institutions",
        sa.Column(
            "id",
            sa.BigInteger(),
            sa.Identity(always=False),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("external_id", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("source_url", sa.String(length=512), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "external_id", "kind", name="uq_institutions_external_id_kind"
        ),
        sa.CheckConstraint(
            "kind IN ('" + "','".join(KIND_VALUES) + "')",
            name="ck_institutions_kind",
        ),
    )

    op.create_table(
        "streets",
        sa.Column(
            "id",
            sa.BigInteger(),
            sa.Identity(always=False),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("city", sa.String(length=64), nullable=False),
        sa.Column("raw_name", sa.String(length=256), nullable=False, unique=True),
        sa.Column("street_part", sa.String(length=256), nullable=False),
        sa.Column("type_marker", sa.String(length=8), nullable=True),
        sa.Column("search_norm", sa.String(length=256), nullable=False),
    )

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
        "streets_search_norm_trgm",
        "streets",
        ["search_norm"],
        postgresql_using="gin",
        postgresql_ops={"search_norm": "gin_trgm_ops"},
    )

    op.create_index(
        "address_entries_lookup",
        "address_entries",
        ["street_id", "number_int"],
    )


def downgrade() -> None:
    """Downgrade schema.

    Indexes and tables are dropped in reverse FK order. The `pg_trgm`
    extension is intentionally NOT dropped — see module docstring.
    """
    op.drop_index("address_entries_lookup", table_name="address_entries")
    op.drop_index("streets_search_norm_trgm", table_name="streets")
    op.drop_table("address_entries")
    op.drop_table("streets")
    op.drop_table("institutions")
