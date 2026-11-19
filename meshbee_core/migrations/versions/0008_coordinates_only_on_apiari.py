"""Coordinates belong to the apiary (#84).

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-19

Since 0005 an apiary has its own coordinates, and hives kept theirs from
before. The apiary is the place the map shows, so `arnie.latitudine` and
`arnie.longitudine` go, with their CHECKs. `arnie.posizione` stays: it is a
free-text note on how to find the hive, not a position.

Before dropping them, an apiary with neither coordinate gets the average of its
hives' coordinates (hives with both set, retired ones included), rounded to the
column's 6 decimals. An apiary that already has coordinates keeps them, and a
hive with no apiary has nowhere to give its own to.

The CHECKs restored on downgrade are frozen at the values `limits.py` held when
this was written, as every revision's are.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FILL_APIARI = """
    UPDATE apiari ap
    SET latitudine = c.latitudine, longitudine = c.longitudine
    FROM (
        SELECT id_apiario,
               round(avg(latitudine), 6) AS latitudine,
               round(avg(longitudine), 6) AS longitudine
        FROM arnie
        WHERE id_apiario IS NOT NULL
          AND latitudine IS NOT NULL AND longitudine IS NOT NULL
        GROUP BY id_apiario
    ) c
    WHERE ap.id_apiario = c.id_apiario
      AND ap.latitudine IS NULL AND ap.longitudine IS NULL
"""

# Back to per-hive coordinates: each hive takes its apiary's.
FILL_ARNIE = """
    UPDATE arnie a
    SET latitudine = ap.latitudine, longitudine = ap.longitudine
    FROM apiari ap
    WHERE ap.id_apiario = a.id_apiario
"""


def upgrade() -> None:
    op.execute(FILL_APIARI)
    op.drop_constraint("valid_latitudine", "arnie", type_="check")
    op.drop_constraint("valid_longitudine", "arnie", type_="check")
    op.drop_column("arnie", "latitudine")
    op.drop_column("arnie", "longitudine")


def downgrade() -> None:
    op.add_column(
        "arnie",
        sa.Column("latitudine", sa.Numeric(precision=9, scale=6), nullable=True),
    )
    op.add_column(
        "arnie",
        sa.Column("longitudine", sa.Numeric(precision=9, scale=6), nullable=True),
    )
    op.create_check_constraint(
        "valid_latitudine",
        "arnie",
        "latitudine IS NULL OR (latitudine >= -90 AND latitudine <= 90)",
    )
    op.create_check_constraint(
        "valid_longitudine",
        "arnie",
        "longitudine IS NULL OR (longitudine >= -180 AND longitudine <= 180)",
    )
    op.execute(FILL_ARNIE)
