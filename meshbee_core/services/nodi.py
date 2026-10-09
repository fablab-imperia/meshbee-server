"""Transmitter nodes."""

from typing import Any

from meshbee_core.errors import Conflict, NotFound
from meshbee_core.paging import EVERYTHING, Page, Paging
from meshbee_core.repository import arnie, nodi
from meshbee_core.services import apiari


def list_nodi(session, paging: Paging = EVERYTHING) -> Page:
    return nodi.list_all(session, paging)


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


def assign_proprietario(session, id_nodo: str, id_utente: int | None) -> dict[str, Any]:
    """
    Assign a node to a user, transfer it to another, or (None) unassign it.

    The node's hives follow: into the new owner's default apiary, or into no
    apiary at all. Shares on the previous owner's apiaries do not follow them.
    Re-assigning the current owner changes nothing, so it never undoes how the
    owner has arranged their hives.

    Raises:
        NotFound: if the node or the user does not exist.
    """
    nodo = nodi.get(session, id_nodo)
    if not nodo:
        raise NotFound(f"Nodo '{id_nodo}' non trovato")
    if nodo["id_proprietario"] == id_utente:
        return nodo

    target = None
    if id_utente is not None:
        target = apiari.ensure_predefinito(session, id_utente)["id_apiario"]
    arnie.place_nodo(session, id_nodo, target)
    return nodi.set_proprietario(session, id_nodo, id_utente)
