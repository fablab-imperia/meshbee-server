"""Drop the trigger and the view: their logic now lives in meshbee_core.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-07

- `trigger_aggiorna_nodo` / `aggiorna_ultimo_messaggio_nodo()` stamped
  `nodi.ultimo_messaggio` with each reading's *reported* time, one UPDATE per
  row (#17). `services/ingest.py` now stamps it with the time the message was
  received, once per message.
- `v_arnie_stato` is replaced by the query in `repository/arnie.py`, which
  takes each arnia's latest reading in one LATERAL subquery instead of five
  correlated ones.

The downgrade recreates both exactly as the baseline defined them.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TRIGGER = r"""
CREATE OR REPLACE FUNCTION aggiorna_ultimo_messaggio_nodo()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE nodi
    SET ultimo_messaggio = NEW.timestamp
    WHERE id_nodo = NEW.id_nodo;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_aggiorna_nodo
AFTER INSERT ON letture
FOR EACH ROW
EXECUTE FUNCTION aggiorna_ultimo_messaggio_nodo();
"""

VIEW = r"""
CREATE OR REPLACE VIEW v_arnie_stato AS
SELECT
    a.id_arnia,
    a.id_nodo,
    a.id_sensore_fisico,
    a.nome_arnia,
    n.nome_nodo,
    a.posizione,
    a.latitudine,
    a.longitudine,
    a.data_installazione,
    a.data_rimozione,
    a.attiva,
    a.metadati,
    (SELECT temperatura FROM letture WHERE id_arnia = a.id_arnia ORDER BY timestamp DESC LIMIT 1) as ultima_temperatura,
    (SELECT umidita   FROM letture WHERE id_arnia = a.id_arnia ORDER BY timestamp DESC LIMIT 1) as ultima_umidita,
    (SELECT peso      FROM letture WHERE id_arnia = a.id_arnia ORDER BY timestamp DESC LIMIT 1) as ultimo_peso,
    (SELECT timestamp FROM letture WHERE id_arnia = a.id_arnia ORDER BY timestamp DESC LIMIT 1) as ultimo_aggiornamento,
    -- Appended last so migrate_v5.sql can CREATE OR REPLACE without a DROP.
    (SELECT batteria  FROM letture WHERE id_arnia = a.id_arnia ORDER BY timestamp DESC LIMIT 1) as ultima_batteria
FROM arnie a
LEFT JOIN nodi n ON a.id_nodo = n.id_nodo;
"""


def upgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql("DROP VIEW IF EXISTS v_arnie_stato")
    bind.exec_driver_sql("DROP TRIGGER IF EXISTS trigger_aggiorna_nodo ON letture")
    bind.exec_driver_sql("DROP FUNCTION IF EXISTS aggiorna_ultimo_messaggio_nodo()")


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(TRIGGER)
    bind.exec_driver_sql(VIEW)
