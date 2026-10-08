"""Add apiari: each user's own grouping of the hives they can see.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-08

Apiaries are personal (#2). Membership is on the association,
`utenti_arnie.id_apiario`, so a hive shared by two users sits in an apiary of
each. A composite foreign key to `apiari (id_apiario, id_utente_proprietario)`
keeps a hive out of an apiary its user does not own.

Every user starts with one default apiary, named "Default". This revision
creates it for every existing account and puts all of that account's
associations in it — revoked ones included, since the column is NOT NULL and a
re-grant revives the row as it was.

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

# Frozen here rather than imported: replaying history must not change when the
# service's constant does.
DEFAULT_NAME = "Default"


def upgrade() -> None:
    op.create_table(
        "apiari",
        sa.Column("nome_apiario", sa.String(length=100), nullable=False),
        sa.Column("descrizione", sa.Text(), nullable=True),
        sa.Column("posizione", sa.String(length=255), nullable=True),
        sa.Column("latitudine", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("longitudine", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("id_apiario", sa.Integer(), nullable=False),
        sa.Column("id_utente_proprietario", sa.Integer(), nullable=False),
        sa.Column(
            "predefinito", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "data_creazione",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
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
            ["id_utente_proprietario"], ["utenti.id_utente"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id_apiario"),
        sa.UniqueConstraint(
            "id_apiario",
            "id_utente_proprietario",
            name="apiari_id_apiario_id_utente_proprietario_key",
        ),
        comment="Apiari: raggruppamenti personali delle arnie di un utente",
    )
    op.create_index("idx_apiari_proprietario", "apiari", ["id_utente_proprietario"])
    op.create_index(
        "uq_apiari_predefinito",
        "apiari",
        ["id_utente_proprietario"],
        unique=True,
        postgresql_where=sa.text("predefinito"),
    )

    bind = op.get_bind()
    bind.execute(
        sa.text(
            "INSERT INTO apiari (nome_apiario, id_utente_proprietario, predefinito)"
            " SELECT :name, id_utente, true FROM utenti ORDER BY id_utente"
        ),
        {"name": DEFAULT_NAME},
    )

    op.add_column("utenti_arnie", sa.Column("id_apiario", sa.Integer(), nullable=True))
    bind.exec_driver_sql(
        "UPDATE utenti_arnie ua SET id_apiario = a.id_apiario"
        " FROM apiari a"
        " WHERE a.id_utente_proprietario = ua.id_utente AND a.predefinito"
    )
    op.alter_column("utenti_arnie", "id_apiario", nullable=False)
    op.create_index("idx_utenti_arnie_apiario", "utenti_arnie", ["id_apiario"])
    op.create_foreign_key(
        "utenti_arnie_id_apiario_fkey",
        "utenti_arnie",
        "apiari",
        ["id_apiario", "id_utente"],
        ["id_apiario", "id_utente_proprietario"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "utenti_arnie_id_apiario_fkey", "utenti_arnie", type_="foreignkey"
    )
    op.drop_index("idx_utenti_arnie_apiario", table_name="utenti_arnie")
    op.drop_column("utenti_arnie", "id_apiario")
    op.drop_table("apiari")
