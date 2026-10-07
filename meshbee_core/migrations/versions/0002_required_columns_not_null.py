"""Make NOT NULL the columns the API already treats as required.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-07

The API's response models and the tables now share one declaration
(meshbee_core/models.py), so a column the API returns as required is NOT NULL
in the database too. Until now a NULL in any of them reached the response model
and failed it: a 500 for whoever listed that row.

Existing NULLs are filled first, choosing values that keep what the
application did with the row before, rather than the column's default:

- booleans (`attivo`, `attiva`) become **false**. Every reader treats NULL as
  "not true" — such an account cannot log in, such an association grants no
  access, such an arnia is not listed — so true would silently revive them;
- `utenti.ruolo` becomes 'user', the least privileged role;
- `utenti_arnie.permessi` becomes 'read' and the association is deactivated:
  a NULL there made the permission check fail, so it never granted anything;
- timestamps take the best evidence the row has — activation or last login for
  an account, the first reading for a node or an arnia — and the time of the
  migration otherwise.

Foreign keys have nothing to be filled with: an arnia without a node, or a
reading without an arnia, cannot be repaired by guessing. Rather than delete
data, the migration stops and reports how many such rows there are; deal with
them by hand and run it again. Everything happens in one transaction, so a
stop leaves the database exactly as it was.

The values are literals on purpose: a revision is history and must not change
when `limits.py` does.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Rows a NOT NULL foreign key would reject and nothing can fill.
ORPHANS = {
    "arnie without id_nodo": "SELECT count(*) FROM arnie WHERE id_nodo IS NULL",
    "letture without id_arnia": "SELECT count(*) FROM letture WHERE id_arnia IS NULL",
    "log_attivita without id_arnia": "SELECT count(*) FROM log_attivita WHERE id_arnia IS NULL",
    "utenti_arnie without id_utente or id_arnia": "SELECT count(*) FROM utenti_arnie WHERE id_utente IS NULL OR id_arnia IS NULL",
}

FILLS = (
    # Deactivate first, while permessi still tells us which rows were broken.
    "UPDATE utenti_arnie SET attivo = false, "
    "data_disassociazione = COALESCE(data_disassociazione, CURRENT_TIMESTAMP) "
    "WHERE permessi IS NULL",
    "UPDATE utenti_arnie SET permessi = 'read' WHERE permessi IS NULL",
    "UPDATE utenti_arnie SET attivo = false WHERE attivo IS NULL",
    "UPDATE utenti_arnie SET data_associazione = CURRENT_TIMESTAMP "
    "WHERE data_associazione IS NULL",
    # valid_association_dates: a filled start must not follow an existing end.
    "UPDATE utenti_arnie SET data_associazione = data_disassociazione "
    "WHERE data_disassociazione IS NOT NULL AND data_associazione > data_disassociazione",
    "UPDATE utenti SET ruolo = 'user' WHERE ruolo IS NULL",
    "UPDATE utenti SET attivo = false WHERE attivo IS NULL",
    "UPDATE utenti SET data_creazione = COALESCE(data_attivazione, ultimo_accesso, CURRENT_TIMESTAMP) "
    "WHERE data_creazione IS NULL",
    "UPDATE nodi SET attivo = false WHERE attivo IS NULL",
    "UPDATE nodi SET data_registrazione = COALESCE("
    "(SELECT min(l.timestamp) FROM letture l WHERE l.id_nodo = nodi.id_nodo), CURRENT_TIMESTAMP) "
    "WHERE data_registrazione IS NULL",
    "UPDATE arnie SET attiva = false WHERE attiva IS NULL",
    "UPDATE arnie SET data_installazione = COALESCE("
    "(SELECT min(l.timestamp) FROM letture l WHERE l.id_arnia = arnie.id_arnia), CURRENT_TIMESTAMP) "
    "WHERE data_installazione IS NULL",
    "UPDATE log_attivita SET timestamp = CURRENT_TIMESTAMP WHERE timestamp IS NULL",
)

REQUIRED = {
    "utenti": ("ruolo", "data_creazione", "attivo"),
    "nodi": ("data_registrazione", "attivo"),
    "arnie": ("id_nodo", "data_installazione", "attiva"),
    "letture": ("id_arnia",),
    "log_attivita": ("id_arnia", "timestamp"),
    "utenti_arnie": (
        "id_utente",
        "id_arnia",
        "data_associazione",
        "permessi",
        "attivo",
    ),
}


def upgrade() -> None:
    bind = op.get_bind()

    orphans = {
        what: count
        for what, query in ORPHANS.items()
        if (count := bind.exec_driver_sql(query).scalar())
    }
    if orphans:
        found = ", ".join(f"{count} {what}" for what, count in orphans.items())
        raise RuntimeError(
            f"Cannot make the foreign keys NOT NULL: found {found}. These rows have "
            "no owner to fill in; fix or delete them by hand, then run the migration "
            "again. Nothing has been changed."
        )

    for statement in FILLS:
        bind.exec_driver_sql(statement)

    for table, columns in REQUIRED.items():
        for column in columns:
            op.alter_column(table, column, nullable=False)


def downgrade() -> None:
    # The filled values stay: there is no telling them apart from real ones.
    for table, columns in REQUIRED.items():
        for column in columns:
            op.alter_column(table, column, nullable=True)
