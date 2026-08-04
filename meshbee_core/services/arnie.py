"""Hives, and the state view that carries their latest readings."""
from typing import Any, Dict, List

import psycopg2

from meshbee_core.errors import Conflict, NotFound
from meshbee_core.repository import arnie


def list_for_utente(cursor, current_user) -> List[Dict[str, Any]]:
    """
    Every active arnia for an admin, only the associated ones for a user.

    The admin branch is not a shortcut around the association table: an admin
    is expected to see hives nobody has been granted access to yet.
    """
    if current_user['ruolo'] == 'admin':
        rows = arnie.list_stato_attive(cursor)
    else:
        rows = arnie.list_stato_for_utente(cursor, current_user['id_utente'])
    return [dict(row) for row in rows]


def list_all(cursor) -> List[Dict[str, Any]]:
    """Every arnia including the retired ones — the admin inventory."""
    return [dict(row) for row in arnie.list_stato(cursor)]


def get_arnia(cursor, id_arnia: int) -> Dict[str, Any]:
    """
    Raises:
        NotFound: se l'arnia non esiste.
    """
    row = arnie.get_stato(cursor, id_arnia)
    if not row:
        raise NotFound("Arnia non trovata")
    return dict(row)


def create_arnia(cursor, arnia) -> Dict[str, Any]:
    """
    Raises:
        Conflict: se il sensore è già registrato per quel nodo.
        NotFound: se il nodo non esiste.
    """
    try:
        return dict(arnie.insert(
            cursor,
            id_nodo=arnia.id_nodo,
            id_sensore_fisico=arnia.id_sensore_fisico,
            # Same default the ingest path uses, so a hive created either way
            # is named identically.
            nome_arnia=arnia.nome_arnia or f"Arnia {arnia.id_nodo}-{arnia.id_sensore_fisico}",
            descrizione=arnia.descrizione,
            posizione=arnia.posizione,
            latitudine=arnia.latitudine,
            longitudine=arnia.longitudine,
            metadati=arnia.metadati,
        ))
    except psycopg2.errors.UniqueViolation as exc:
        raise Conflict(
            f"Sensore '{arnia.id_sensore_fisico}' già registrato per il nodo '{arnia.id_nodo}'"
        ) from exc
    except psycopg2.errors.ForeignKeyViolation as exc:
        raise NotFound(f"Nodo '{arnia.id_nodo}' non trovato") from exc


def update_arnia(cursor, id_arnia: int, arnia, *, allow_attiva: bool = False) -> Dict[str, Any]:
    """
    Apply the supplied fields; unmentioned ones keep their stored value.

    `allow_attiva` is what separates the two update endpoints: a user with write
    permission may edit a hive's details but not retire or revive it.

    Raises:
        NotFound: se l'arnia non esiste.
    """
    optional = {"attiva": arnia.attiva} if allow_attiva else {}

    row = arnie.update(
        cursor, id_arnia,
        nome_arnia=arnia.nome_arnia,
        descrizione=arnia.descrizione,
        posizione=arnia.posizione,
        latitudine=arnia.latitudine,
        longitudine=arnia.longitudine,
        metadati=arnia.metadati,
        **optional,
    )
    if not row:
        raise NotFound("Arnia non trovata")
    return dict(row)


def deactivate_arnia(cursor, id_arnia: int) -> None:
    """
    Soft delete: historical readings are kept.

    Raises:
        NotFound: se l'arnia non esiste.
    """
    if not arnie.deactivate(cursor, id_arnia):
        raise NotFound("Arnia non trovata")
