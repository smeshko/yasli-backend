"""address_institutions_institution_id_index

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-19 12:00:00.000000

Adds an index on ``address_institutions.institution_id``. Revision
``0003`` only indexed the ``address_id`` side of the junction table,
leaving queries that filter by ``institution_id`` (institution coverage
fetch, catchment-majority lookups) scanning the unindexed side.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0008"
down_revision: Union[str, Sequence[str], None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_address_institutions_institution_id",
        "address_institutions",
        ["institution_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_address_institutions_institution_id",
        table_name="address_institutions",
    )
