"""nursery_metadata

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-13 08:30:00.000000

Adds snapshot v2 institution metadata: physical address, district code, and
kindergarten infant-group flag.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "institutions",
        sa.Column("address", sa.String(length=256), nullable=True),
    )
    op.add_column(
        "institutions",
        sa.Column("district_code", sa.String(length=2), nullable=True),
    )
    op.add_column(
        "institutions",
        sa.Column(
            "has_infant_group",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_check_constraint(
        "ck_institutions_district_code",
        "institutions",
        "district_code IS NULL OR district_code IN ('01','02','03','04','05')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "ck_institutions_district_code",
        "institutions",
        type_="check",
    )
    op.drop_column("institutions", "has_infant_group")
    op.drop_column("institutions", "district_code")
    op.drop_column("institutions", "address")
