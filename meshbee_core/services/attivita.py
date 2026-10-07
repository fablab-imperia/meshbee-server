"""The beekeeper's activity log."""
from typing import Any, Dict, List

from meshbee_core.errors import NotFound
from meshbee_core.repository import attivita
from meshbee_core.services.letture import default_window


def list_for_arnia(session, id_arnia: int, data_inizio, data_fine, limit: int,
                   tipo_attivita=None) -> List[Dict[str, Any]]:
    data_inizio, data_fine = default_window(data_inizio, data_fine)
    rows = attivita.list_by_arnia(session, id_arnia, data_inizio, data_fine, limit, tipo_attivita)
    return [dict(row) for row in rows]


def list_all(session, limit: int) -> List[Dict[str, Any]]:
    return [dict(row) for row in attivita.list_all(session, limit)]


def count_for_arnia(session, id_arnia: int) -> int:
    """How many entries an arnia already has — used to keep seeding idempotent."""
    return attivita.count_for_arnia(session, id_arnia)


def create_attivita(session, id_utente: int, id_arnia: int, nuova) -> Dict[str, Any]:
    """
    Record an activity against an arnia.

    The arnia comes from the path, not the body: a user with write access to one
    hive must not be able to file an entry against another by editing the JSON.
    """
    return dict(attivita.insert(
        session,
        id_utente=id_utente,
        id_arnia=id_arnia,
        timestamp=nuova.timestamp,
        tipo_attivita=nuova.tipo_attivita,
        descrizione=nuova.descrizione,
        dati=nuova.dati,
    ))


def update_attivita(session, id_log: int, id_arnia: int, id_utente: int,
                    changes) -> Dict[str, Any]:
    """
    Edit one's own activity entry.

    Raises:
        NotFound: se l'attività non esiste, o non appartiene a utente e arnia.
    """
    if not attivita.find_owned(session, id_log, id_arnia, id_utente):
        raise NotFound("Attività non trovata")

    updates = changes.model_dump(exclude_unset=True)
    if not updates:
        # Nothing to change: hand back the row as it stands.
        return dict(attivita.get_all_columns(session, id_log))

    return dict(attivita.update(session, id_log, updates))


def delete_attivita(session, id_log: int, id_arnia: int, id_utente: int) -> None:
    """
    Raises:
        NotFound: se l'attività non esiste, o non appartiene a utente e arnia.
    """
    if not attivita.delete_owned(session, id_log, id_arnia, id_utente):
        raise NotFound("Attività non trovata o non appartenente all'utente")
