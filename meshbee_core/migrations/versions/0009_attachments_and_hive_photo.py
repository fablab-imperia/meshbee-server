"""Attachments, and a photo per hive (#3).

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-24

`allegati` records the uploaded files; the bytes live in the storage directory
(`meshbee_core/storage.py`), under `chiave`. The table does not say what a file
belongs to: `arnie.id_foto` points at a hive's photo, and the next kind of
attachment will be another such column. Deleting an attachment empties the
column that pointed at it.

Constraint names are the ones Postgres would generate, spelled out so the
downgrade can name them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "allegati",
        sa.Column("id_allegato", sa.Integer(), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("dimensione", sa.Integer(), nullable=False),
        sa.Column("larghezza", sa.Integer(), nullable=True),
        sa.Column("altezza", sa.Integer(), nullable=True),
        sa.Column(
            "data_caricamento",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("id_utente_caricamento", sa.Integer(), nullable=True),
        sa.Column("chiave", sa.String(length=255), nullable=False),
        sa.CheckConstraint("dimensione > 0", name="allegati_dimensione_check"),
        sa.ForeignKeyConstraint(
            ["id_utente_caricamento"],
            ["utenti.id_utente"],
            name="allegati_id_utente_caricamento_fkey",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id_allegato"),
        sa.UniqueConstraint("chiave", name="allegati_chiave_key"),
        comment="File caricati: foto delle arnie",
    )
    op.add_column("arnie", sa.Column("id_foto", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "arnie_id_foto_fkey",
        "arnie",
        "allegati",
        ["id_foto"],
        ["id_allegato"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("arnie_id_foto_fkey", "arnie", type_="foreignkey")
    op.drop_column("arnie", "id_foto")
    op.drop_table("allegati")
