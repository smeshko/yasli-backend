"""institution_contact_fields

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-14 12:00:00.000000

Adds optional source contact metadata to institutions: phone, e-mail,
director and website. All nullable with no default and no backfill — rows
stay NULL until the scraper starts emitting the fields.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: Union[str, Sequence[str], None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "institutions",
        sa.Column("phone", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "institutions",
        sa.Column("email", sa.String(length=256), nullable=True),
    )
    op.add_column(
        "institutions",
        sa.Column("director", sa.String(length=256), nullable=True),
    )
    op.add_column(
        "institutions",
        sa.Column("website", sa.String(length=256), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("institutions", "website")
    op.drop_column("institutions", "director")
    op.drop_column("institutions", "email")
    op.drop_column("institutions", "phone")
