"""Single-use tokens sent by email: password reset (#54), invitations (#55).

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-13

`token_monouso` holds one row per emailed token: where the link went (`email`),
the account it acts on (`id_utente`, empty for an invitation to someone with no
account yet), who caused it (`id_mittente`), what it is for (`scopo`), when it
expires and when it was spent. Only the token's SHA-256 is stored.
`token_sessione` (refresh tokens, #16) is left as it is.

The `scopo` CHECK is frozen at the values `limits.py` held when this was
written, as every revision's are.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "token_monouso",
        sa.Column("id_token", sa.Integer(), nullable=False),
        sa.Column("id_utente", sa.Integer(), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("id_mittente", sa.Integer(), nullable=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("scopo", sa.String(length=20), nullable=False),
        sa.Column(
            "data_creazione",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("data_scadenza", sa.DateTime(), nullable=False),
        sa.Column("data_utilizzo", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "id_utente IS NOT NULL OR scopo = 'invite'",
            name="token_monouso_utente_check",
        ),
        sa.CheckConstraint(
            "scopo IN ('password_reset', 'invite')", name="token_monouso_scopo_check"
        ),
        sa.ForeignKeyConstraint(
            ["id_mittente"], ["utenti.id_utente"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["id_utente"], ["utenti.id_utente"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id_token"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        "idx_token_monouso_email_scopo",
        "token_monouso",
        ["email", "scopo"],
        unique=False,
    )
    op.create_index(
        "idx_token_monouso_mittente", "token_monouso", ["id_mittente"], unique=False
    )
    op.create_index(
        "idx_token_monouso_utente_scopo",
        "token_monouso",
        ["id_utente", "scopo"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_token_monouso_utente_scopo", table_name="token_monouso")
    op.drop_index("idx_token_monouso_mittente", table_name="token_monouso")
    op.drop_index("idx_token_monouso_email_scopo", table_name="token_monouso")
    op.drop_table("token_monouso")
