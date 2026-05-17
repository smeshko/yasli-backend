"""settlement_code

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-17 09:00:00.000000

Adds a nullable ``addresses.settlement_code`` (VARCHAR(5)) column that
mirrors ``grao_addresses.settlement_code``. The column powers a
settlement-level fallback in ``/api/match`` for addresses outside
ГР.ВАРНА (e.g. с. Каменар, с. Тополи). Villages sit directly under
община Варна with no район designation so their ``district_code`` is
always NULL, but their ``settlement_code`` is enough to confirm they're
in Varna municipality and route a request for nurseries to the
city-wide list. Kindergartens and the one village preschool already
work via the address_institutions junction, so no parallel column is
needed on ``institutions``.

No CHECK constraint: settlement codes are free-form 5-char strings
inherited from ГРАО, not a closed enum like ``district_code``.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0006"
down_revision: Union[str, Sequence[str], None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "addresses",
        sa.Column("settlement_code", sa.String(length=5), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("addresses", "settlement_code")
