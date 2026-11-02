"""retire legacy infant-group nursery rows

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-02 12:00:00.000000

Data-only migration (YAS-35). The 18 ``nursery/<kindergarten id>`` rows named
``ДГ№X … / с яслена група/`` came from a frozen fixture, not from any snapshot,
so nothing refreshes them: they are months stale, have no район and no
``main`` location. The migration hard-deletes them, scoped to
``kind = 'nursery'``, the 18 external ids and ``name LIKE 'ДГ%'``. Their
``institution_locations`` rows go first (the foreign key is RESTRICT); the
``address_institutions`` edges cascade. On a database without the rows it
does nothing.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: Union[str, Sequence[str], None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


LEGACY_EXTERNAL_IDS = (
    "39",
    "47",
    "52",
    "56",
    "63",
    "66",
    "67",
    "68",
    "69",
    "71",
    "72",
    "73",
    "74",
    "75",
    "80",
    "81",
    "82",
    "83",
)


def upgrade() -> None:
    """Delete the legacy infant-group nursery rows."""
    bind = op.get_bind()
    params = {"ids": list(LEGACY_EXTERNAL_IDS)}
    bind.execute(
        sa.text(
            "DELETE FROM institution_locations il USING institutions i "
            "WHERE il.kind = i.kind AND il.external_id = i.external_id "
            "AND i.kind = 'nursery' AND i.external_id = ANY(:ids) "
            "AND i.name LIKE 'ДГ%'"
        ),
        params,
    )
    bind.execute(
        sa.text(
            "DELETE FROM institutions "
            "WHERE kind = 'nursery' AND external_id = ANY(:ids) "
            "AND name LIKE 'ДГ%'"
        ),
        params,
    )


def downgrade() -> None:
    """Deliberate no-op.

    The rows live in git history (``data/seed/legacy_institutions.json``
    before YAS-35); restoring months-stale rows would bring the defect back.
    """
