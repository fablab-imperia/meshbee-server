"""Turning a message from a node into a stored reading.

This sits on top of `services.letture.record_reading` rather than beside it,
because provisioning is where the two write paths legitimately differ: a node
may start transmitting before anyone registered it, so the ingest path creates
what it needs. The API's manual-insert endpoint refuses an unknown arnia
instead, and that difference is intentional.
"""
import logging
from typing import Any, Dict

from meshbee_core.errors import NotFound
from meshbee_core.repository import arnie, nodi
from meshbee_core.services import letture

logger = logging.getLogger(__name__)


def register_node_and_resolve_arnia(session, id_nodo: str, id_sensore) -> int:
    """
    Record that the node was heard from, and find the arnia the reading is for.

    Creates the arnia when the node reports a sensor id we have never seen.
    Without a sensor id there is nothing to create *from*, so it falls back to
    the node's first arnia.

    Raises:
        NotFound: se non è possibile determinare l'arnia.
    """
    # Registration only — `nodi.ultimo_messaggio` is maintained by the
    # trigger on `letture`, so recording the sighting is the reading's job.
    nodi.register_if_absent(session, id_nodo, f"Nodo {id_nodo}")

    if id_sensore:
        found = arnie.find_id_by_nodo_sensore(session, id_nodo, id_sensore)
        if found:
            return found['id_arnia']

        created = arnie.insert(
            session,
            id_nodo=id_nodo,
            id_sensore_fisico=id_sensore,
            nome_arnia=f"Arnia {id_nodo}-{id_sensore}",
        )
        logger.info(f"Creata nuova arnia: {created['id_arnia']}")
        return created['id_arnia']

    found = arnie.find_first_id_by_nodo(session, id_nodo)
    if found:
        return found['id_arnia']

    # Raising rather than returning None matters: the caller's session commits on
    # a clean exit, so a quiet return would persist the node upsert above. The
    # handler used to roll back by hand here.
    raise NotFound(f"Impossibile determinare id_arnia per nodo {id_nodo}")


def record_node_reading(session, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Store one reading from a node, provisioning the nodo and arnia as needed.

    Raises:
        NotFound: se l'arnia non è determinabile.
        InvalidData: se le misure non rispettano i limiti dichiarati.
    """
    id_nodo = payload['id_nodo']
    id_arnia = register_node_and_resolve_arnia(session, id_nodo, payload.get('id_sensore'))

    return letture.record_reading(session, {
        'id_arnia': id_arnia,
        'id_nodo': id_nodo,
        'timestamp': payload.get('timestamp'),
        'temperatura': payload.get('temperatura'),
        'umidita': payload.get('umidita'),
        'peso': payload.get('peso'),
        # The wire key is `bat`; everything past this point calls it batteria.
        'batteria': payload.get('bat'),
        'dati_raw': payload.get('dati_raw'),
    })
