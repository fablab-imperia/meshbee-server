"""Hive ownership, apiaries, and sharing per apiary.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-08

Every hive belongs to an apiary (#2), and every apiary to a user (#36):
- `apiari`, with one "Default" apiary per user, created here for every
  existing account;
- `nodi.id_proprietario`, null while no admin has assigned the node;
- `arnie.id_apiario`, null while the hive's node is unassigned;
- `utenti_apiari`, the roles an owner grants others on an apiary. It replaces
  `utenti_arnie`, which granted access per hive and is dropped.

Existing access becomes ownership:
- a hive's candidate owner is the user with the highest level on it among
  active associations (admin > write > read), the earliest association
  breaking ties;
- a node's owner is the candidate owning most of its hives (lowest user id on
  a tie), and every hive of the node goes in that owner's Default — a node's
  hives always share its owner;
- every other active association becomes a role on that Default
  (read → viewer, write → collaborator, admin → manager), the highest per
  user. Access is now per apiary, so this can widen it to the owner's other
  hives there; it never removes any.
Hives that nobody had active access to stay unassigned, with their node.

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

LEVEL = "CASE ua.permessi WHEN 'admin' THEN 3 WHEN 'write' THEN 2 ELSE 1 END"

# The best-placed active association of each hive: its candidate owner.
CANDIDATES = f"""
    SELECT id_arnia, id_utente FROM (
        SELECT ua.id_arnia, ua.id_utente,
               row_number() OVER (
                   PARTITION BY ua.id_arnia
                   ORDER BY {LEVEL} DESC, ua.data_associazione, ua.id
               ) AS rank
        FROM utenti_arnie ua
        WHERE ua.attivo
    ) ranked
    WHERE rank = 1
"""

OWN_NODES = f"""
    UPDATE nodi n SET id_proprietario = chosen.id_utente
    FROM (
        SELECT DISTINCT ON (a.id_nodo) a.id_nodo, c.id_utente
        FROM ({CANDIDATES}) c
        JOIN arnie a ON a.id_arnia = c.id_arnia
        GROUP BY a.id_nodo, c.id_utente
        ORDER BY a.id_nodo, count(*) DESC, c.id_utente
    ) chosen
    WHERE n.id_nodo = chosen.id_nodo
"""

PLACE_HIVES = """
    UPDATE arnie a SET id_apiario = ap.id_apiario
    FROM nodi n
    JOIN apiari ap ON ap.id_utente_proprietario = n.id_proprietario AND ap.predefinito
    WHERE a.id_nodo = n.id_nodo
"""

SHARE_THE_REST = f"""
    INSERT INTO utenti_apiari (id_utente, id_apiario, ruolo)
    SELECT ua.id_utente, a.id_apiario,
           CASE max({LEVEL})
               WHEN 3 THEN 'manager' WHEN 2 THEN 'collaborator' ELSE 'viewer'
           END
    FROM utenti_arnie ua
    JOIN arnie a ON a.id_arnia = ua.id_arnia
    JOIN apiari ap ON ap.id_apiario = a.id_apiario
    WHERE ua.attivo AND ua.id_utente <> ap.id_utente_proprietario
    GROUP BY ua.id_utente, a.id_apiario
"""

# The table as revision 0002 left it, for downgrade.
UTENTI_ARNIE = """
    CREATE TABLE utenti_arnie (
        id SERIAL PRIMARY KEY,
        id_utente INTEGER NOT NULL REFERENCES utenti(id_utente) ON DELETE CASCADE,
        id_arnia INTEGER NOT NULL REFERENCES arnie(id_arnia) ON DELETE CASCADE,
        data_associazione TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        data_disassociazione TIMESTAMP,
        permessi VARCHAR(20) NOT NULL DEFAULT 'read'
            CHECK (permessi IN ('read', 'write', 'admin')),
        attivo BOOLEAN NOT NULL DEFAULT true,
        UNIQUE(id_utente, id_arnia),
        CONSTRAINT valid_association_dates CHECK (
            data_disassociazione IS NULL OR data_disassociazione >= data_associazione
        )
    );
    CREATE INDEX idx_utenti_arnie_utente ON utenti_arnie(id_utente);
    CREATE INDEX idx_utenti_arnie_arnia ON utenti_arnie(id_arnia);
    CREATE INDEX idx_utenti_arnie_attivo ON utenti_arnie(attivo);
"""

# Back to per-hive access: the owner as 'admin', each share on every hive of
# its apiary.
UNSHARE = """
    INSERT INTO utenti_arnie (id_utente, id_arnia, permessi)
    SELECT ap.id_utente_proprietario, a.id_arnia, 'admin'
    FROM arnie a JOIN apiari ap ON ap.id_apiario = a.id_apiario;

    INSERT INTO utenti_arnie (id_utente, id_arnia, permessi)
    SELECT s.id_utente, a.id_arnia,
           CASE s.ruolo WHEN 'manager' THEN 'admin'
                        WHEN 'collaborator' THEN 'write' ELSE 'read' END
    FROM utenti_apiari s JOIN arnie a ON a.id_apiario = s.id_apiario;
"""


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
        comment="Apiari: luoghi che raggruppano le arnie di un proprietario",
    )
    op.create_index("idx_apiari_proprietario", "apiari", ["id_utente_proprietario"])
    op.create_index(
        "uq_apiari_predefinito",
        "apiari",
        ["id_utente_proprietario"],
        unique=True,
        postgresql_where=sa.text("predefinito"),
    )

    op.add_column("nodi", sa.Column("id_proprietario", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "nodi_id_proprietario_fkey",
        "nodi",
        "utenti",
        ["id_proprietario"],
        ["id_utente"],
        ondelete="SET NULL",
    )
    op.create_index("idx_nodi_proprietario", "nodi", ["id_proprietario"])

    op.add_column("arnie", sa.Column("id_apiario", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "arnie_id_apiario_fkey", "arnie", "apiari", ["id_apiario"], ["id_apiario"]
    )
    op.create_index("idx_arnie_apiario", "arnie", ["id_apiario"])

    op.create_table(
        "utenti_apiari",
        sa.Column("id_utente", sa.Integer(), nullable=False),
        sa.Column("id_apiario", sa.Integer(), nullable=False),
        sa.Column(
            "ruolo",
            sa.String(length=20),
            server_default=sa.text("'viewer'"),
            nullable=False,
        ),
        sa.Column(
            "data_condivisione",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "ruolo IN ('viewer', 'collaborator', 'manager')",
            name="utenti_apiari_ruolo_check",
        ),
        sa.ForeignKeyConstraint(
            ["id_apiario"], ["apiari.id_apiario"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["id_utente"], ["utenti.id_utente"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id_utente", "id_apiario", name="utenti_apiari_id_utente_id_apiario_key"
        ),
        comment="Apiari condivisi dal proprietario con altri utenti",
    )
    op.create_index("idx_utenti_apiari_utente", "utenti_apiari", ["id_utente"])
    op.create_index("idx_utenti_apiari_apiario", "utenti_apiari", ["id_apiario"])

    bind = op.get_bind()
    bind.execute(
        sa.text(
            "INSERT INTO apiari (nome_apiario, id_utente_proprietario, predefinito)"
            " SELECT :name, id_utente, true FROM utenti ORDER BY id_utente"
        ),
        {"name": DEFAULT_NAME},
    )
    bind.exec_driver_sql(OWN_NODES)
    bind.exec_driver_sql(PLACE_HIVES)
    bind.exec_driver_sql(SHARE_THE_REST)

    op.drop_table("utenti_arnie")


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(UTENTI_ARNIE)
    bind.exec_driver_sql(UNSHARE)

    op.drop_table("utenti_apiari")
    op.drop_index("idx_arnie_apiario", table_name="arnie")
    op.drop_constraint("arnie_id_apiario_fkey", "arnie", type_="foreignkey")
    op.drop_column("arnie", "id_apiario")
    op.drop_index("idx_nodi_proprietario", table_name="nodi")
    op.drop_constraint("nodi_id_proprietario_fkey", "nodi", type_="foreignkey")
    op.drop_column("nodi", "id_proprietario")
    op.drop_table("apiari")
