"""Add apiari and the optional apiary of each hive.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-08

An apiary groups hives by the place they stand in (#2). `arnie.id_apiario` is
nullable and nothing is backfilled: hives provisioned over MQTT, and every hive
that predates this revision, simply belong to no apiary until someone assigns
one. The hive keeps its own `posizione` and coordinates.

The coordinate CHECKs are frozen at the values `limits.py` held when this was
written, as every revision's are.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Spelled out so downgrade can name it; it is the name Postgres would generate.
ARNIE_APIARIO_FK = "arnie_id_apiario_fkey"


def upgrade() -> None:
    op.create_table(
        "apiari",
        sa.Column("nome_apiario", sa.String(length=100), nullable=False),
        sa.Column("descrizione", sa.Text(), nullable=True),
        sa.Column("posizione", sa.String(length=255), nullable=True),
        sa.Column("latitudine", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("longitudine", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("id_utente_proprietario", sa.Integer(), nullable=True),
        sa.Column("id_apiario", sa.Integer(), nullable=False),
        sa.Column(
            "data_creazione",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("data_disattivazione", sa.DateTime(), nullable=True),
        sa.Column(
            "attivo", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column("metadati", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.CheckConstraint(
            "latitudine IS NULL OR (latitudine >= -90 AND latitudine <= 90)",
            name="apiari_valid_latitudine",
        ),
        sa.CheckConstraint(
            "longitudine IS NULL OR (longitudine >= -180 AND longitudine <= 180)",
            name="apiari_valid_longitudine",
        ),
        sa.ForeignKeyConstraint(
            ["id_utente_proprietario"], ["utenti.id_utente"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id_apiario"),
        comment="Apiari: luoghi fisici che raggruppano le arnie",
    )
    op.create_index("idx_apiari_attivo", "apiari", ["attivo"])
    op.create_index("idx_apiari_proprietario", "apiari", ["id_utente_proprietario"])

    op.add_column("arnie", sa.Column("id_apiario", sa.Integer(), nullable=True))
    op.create_index("idx_arnie_apiario", "arnie", ["id_apiario"])
    op.create_foreign_key(
        ARNIE_APIARIO_FK,
        "arnie",
        "apiari",
        ["id_apiario"],
        ["id_apiario"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(ARNIE_APIARIO_FK, "arnie", type_="foreignkey")
    op.drop_index("idx_arnie_apiario", table_name="arnie")
    op.drop_column("arnie", "id_apiario")
    op.drop_table("apiari")
