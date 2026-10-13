"""Pending apiary invitations (#40).

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-13

Sharing an apiary with an email that has no account used to answer 404, which
told any user which addresses are registered. Such a share is now stored in
`inviti_apiari` (apiary, email, role) and becomes a row of `utenti_apiari` when
an account with that email is created.

The `ruolo` CHECK is frozen at the values `limits.py` held when this was
written, as every revision's are.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "inviti_apiari",
        sa.Column("id_apiario", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column(
            "ruolo",
            sa.String(length=20),
            server_default=sa.text("'viewer'"),
            nullable=False,
        ),
        sa.Column(
            "data_invito",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("id_invito", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "ruolo IN ('viewer', 'collaborator', 'manager')",
            name="inviti_apiari_ruolo_check",
        ),
        sa.ForeignKeyConstraint(
            ["id_apiario"], ["apiari.id_apiario"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id_invito"),
        sa.UniqueConstraint(
            "email", "id_apiario", name="inviti_apiari_email_id_apiario_key"
        ),
        comment="Apiari condivisi con email che non hanno ancora un account",
    )


def downgrade() -> None:
    op.drop_table("inviti_apiari")
