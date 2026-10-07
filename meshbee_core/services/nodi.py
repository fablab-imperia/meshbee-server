"""Transmitter nodes."""

from typing import Any

from meshbee_core.errors import Conflict, NotFound
from meshbee_core.repository import nodi


def list_nodi(session) -> list[dict[str, Any]]:
    return [dict(row) for row in nodi.list_all(session)]


def get_nodo(session, id_nodo: str) -> dict[str, Any]:
    """
    Raises:
        NotFound: se il nodo non esiste.
    """
    row = nodi.get(session, id_nodo)
    if not row:
        raise NotFound(f"Nodo '{id_nodo}' non trovato")
    return dict(row)


def create_nodo(session, nodo) -> dict[str, Any]:
    """
    Raises:
        Conflict: se il nodo è già registrato.
    """
    if nodi.find_id(session, nodo.id_nodo):
        raise Conflict(f"Nodo '{nodo.id_nodo}' già esistente")

    return dict(
        nodi.insert(
            session,
            id_nodo=nodo.id_nodo,
            nome_nodo=nodo.nome_nodo,
            descrizione=nodo.descrizione,
            posizione=nodo.posizione,
            configurazione=nodo.configurazione,
        )
    )


def update_nodo(session, id_nodo: str, nodo) -> dict[str, Any]:
    """
    Raises:
        NotFound: se il nodo non esiste.
    """
    row = nodi.update(
        session,
        id_nodo,
        nome_nodo=nodo.nome_nodo,
        descrizione=nodo.descrizione,
        posizione=nodo.posizione,
        configurazione=nodo.configurazione,
    )
    if not row:
        raise NotFound(f"Nodo '{id_nodo}' non trovato")
    return dict(row)


def deactivate_nodo(session, id_nodo: str) -> None:
    """
    Soft delete: the arnie and readings behind it are kept.

    Raises:
        NotFound: se il nodo non esiste.
    """
    if not nodi.deactivate(session, id_nodo):
        raise NotFound(f"Nodo '{id_nodo}' non trovato")
