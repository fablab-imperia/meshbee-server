"""Transmitter nodes."""
from typing import Any, Dict, List

from meshbee_core.errors import Conflict, NotFound
from meshbee_core.repository import nodi


def list_nodi(cursor) -> List[Dict[str, Any]]:
    return [dict(row) for row in nodi.list_all(cursor)]


def get_nodo(cursor, id_nodo: str) -> Dict[str, Any]:
    """
    Raises:
        NotFound: se il nodo non esiste.
    """
    row = nodi.get(cursor, id_nodo)
    if not row:
        raise NotFound(f"Nodo '{id_nodo}' non trovato")
    return dict(row)


def create_nodo(cursor, nodo) -> Dict[str, Any]:
    """
    Raises:
        Conflict: se il nodo è già registrato.
    """
    if nodi.find_id(cursor, nodo.id_nodo):
        raise Conflict(f"Nodo '{nodo.id_nodo}' già esistente")

    return dict(nodi.insert(
        cursor,
        id_nodo=nodo.id_nodo,
        nome_nodo=nodo.nome_nodo,
        descrizione=nodo.descrizione,
        posizione=nodo.posizione,
        configurazione=nodo.configurazione,
    ))


def update_nodo(cursor, id_nodo: str, nodo) -> Dict[str, Any]:
    """
    Raises:
        NotFound: se il nodo non esiste.
    """
    row = nodi.update(
        cursor, id_nodo,
        nome_nodo=nodo.nome_nodo,
        descrizione=nodo.descrizione,
        posizione=nodo.posizione,
        configurazione=nodo.configurazione,
    )
    if not row:
        raise NotFound(f"Nodo '{id_nodo}' non trovato")
    return dict(row)


def deactivate_nodo(cursor, id_nodo: str) -> None:
    """
    Soft delete: the arnie and readings behind it are kept.

    Raises:
        NotFound: se il nodo non esiste.
    """
    if not nodi.deactivate(cursor, id_nodo):
        raise NotFound(f"Nodo '{id_nodo}' non trovato")
