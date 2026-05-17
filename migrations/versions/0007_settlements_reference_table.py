"""settlements_reference_table

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-17 12:00:00.000000

Adds a small ``settlements`` reference table keyed by the existing
ГРАО/KADS settlement code. The table gives backend code normalized
city/village context for ``addresses.settlement_code`` without changing
ingest output, route behavior, or frontend behavior.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0007"
down_revision: Union[str, Sequence[str], None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SETTLEMENTS = (
    {
        "code": "10135",
        "name": "ГР.ВАРНА",
        "locality_type": "city",
        "municipality_code": "06",
        "municipality_name": "ВАРНА",
        "source": "grao_kads",
    },
    {
        "code": "35701",
        "name": "С.КАМЕНАР",
        "locality_type": "village",
        "municipality_code": "06",
        "municipality_name": "ВАРНА",
        "source": "grao_kads",
    },
    {
        "code": "72709",
        "name": "С.ТОПОЛИ",
        "locality_type": "village",
        "municipality_code": "06",
        "municipality_name": "ВАРНА",
        "source": "grao_kads",
    },
    {
        "code": "30497",
        "name": "С.ЗВЕЗДИЦА",
        "locality_type": "village",
        "municipality_code": "06",
        "municipality_name": "ВАРНА",
        "source": "grao_kads",
    },
    {
        "code": "38354",
        "name": "С.КОНСТАНТИНОВО",
        "locality_type": "village",
        "municipality_code": "06",
        "municipality_name": "ВАРНА",
        "source": "grao_kads",
    },
    {
        "code": "35211",
        "name": "С.КАЗАШКО",
        "locality_type": "village",
        "municipality_code": "06",
        "municipality_name": "ВАРНА",
        "source": "grao_kads",
    },
)


def upgrade() -> None:
    op.create_table(
        "settlements",
        sa.Column("code", sa.String(length=5), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("locality_type", sa.String(length=16), nullable=False),
        sa.Column(
            "municipality_code",
            sa.String(length=2),
            nullable=False,
            server_default=sa.text("'06'"),
        ),
        sa.Column(
            "municipality_name",
            sa.String(length=64),
            nullable=False,
            server_default=sa.text("'ВАРНА'"),
        ),
        sa.Column(
            "source",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'grao_kads'"),
        ),
        sa.PrimaryKeyConstraint("code", name="settlements_pkey"),
        sa.CheckConstraint(
            "locality_type IN ('city','village')",
            name="ck_settlements_locality_type",
        ),
    )

    settlements_table = sa.table(
        "settlements",
        sa.column("code", sa.String(length=5)),
        sa.column("name", sa.String(length=64)),
        sa.column("locality_type", sa.String(length=16)),
        sa.column("municipality_code", sa.String(length=2)),
        sa.column("municipality_name", sa.String(length=64)),
        sa.column("source", sa.String(length=32)),
    )
    op.bulk_insert(settlements_table, list(SETTLEMENTS))


def downgrade() -> None:
    op.drop_table("settlements")
