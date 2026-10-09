"""Hives, and the state that carries their latest readings."""

from typing import Any

from meshbee_core.db import integrity_errors
from meshbee_core.errors import Conflict, InvalidData, NotFound
from meshbee_core.paging import EVERYTHING, Page, Paging
from meshbee_core.repository import arnie, nodi
from meshbee_core.services import apiari


def list_for_utente(
    session, current_user, id_apiario: int | None = None, paging: Paging = EVERYTHING
) -> Page:
    """
    Every active arnia for an admin, only the associated ones for a user.

    The admin branch is not a shortcut around the association table: an admin
    is expected to see hives nobody has been granted access to yet.

    A user sees the hives in the apiaries they own or have been shared, each
    with `accesso`: "owner" or the role shared. `id_apiario` narrows the list
    to one apiary, and opens nothing the user could not already see.
    """
    if current_user["ruolo"] == "admin":
        return arnie.list_stato_attive(
            session, current_user["id_utente"], id_apiario, paging
        )
    return arnie.list_stato_for_utente(
        session, current_user["id_utente"], id_apiario, paging
    )


def list_all(
    session, id_apiario: int | None = None, paging: Paging = EVERYTHING
) -> Page:
    """Every arnia including the retired ones — the admin inventory."""
    return arnie.list_stato(session, id_apiario, paging)


def list_ids(session) -> list[int]:
    """Every arnia id, oldest first — for callers that only need to iterate."""
    return [row["id_arnia"] for row in arnie.list_ids(session)]


def get_arnia(session, id_arnia: int, id_utente: int | None = None) -> dict[str, Any]:
    """
    With `id_utente`, the hive carries what that user may do on it.

    Raises:
        NotFound: se l'arnia non esiste.
    """
    row = arnie.get_stato(session, id_arnia, id_utente)
    if not row:
        raise NotFound("Arnia non trovata")
    return dict(row)


def create_arnia(session, arnia) -> dict[str, Any]:
    """
    The hive belongs to its node's owner: it goes in the apiary named, which
    must be that owner's, or else in their default one. A hive of an
    unassigned node is unassigned too, until an admin assigns the node.

    Raises:
        Conflict: se il sensore è già registrato per quel nodo.
        NotFound: se il nodo non esiste.
        InvalidData: if the apiary is not the node owner's, or the node is
            unassigned and an apiary was named.
    """
    id_apiario = placement(session, arnia.id_nodo, arnia.id_apiario)
    conflict = Conflict(
        f"Sensore '{arnia.id_sensore_fisico}' già registrato per il nodo '{arnia.id_nodo}'"
    )
    with integrity_errors(
        unique=conflict, foreign_key=NotFound(f"Nodo '{arnia.id_nodo}' non trovato")
    ):
        return dict(
            arnie.insert(
                session,
                id_nodo=arnia.id_nodo,
                id_sensore_fisico=arnia.id_sensore_fisico,
                # Same default the ingest path uses, so a hive created either way
                # is named identically.
                nome_arnia=arnia.nome_arnia
                or f"Arnia {arnia.id_nodo}-{arnia.id_sensore_fisico}",
                descrizione=arnia.descrizione,
                posizione=arnia.posizione,
                latitudine=arnia.latitudine,
                longitudine=arnia.longitudine,
                metadati=arnia.metadati,
                id_apiario=id_apiario,
            )
        )


def update_arnia(
    session, id_arnia: int, arnia, *, allow_attiva: bool = False
) -> dict[str, Any]:
    """
    Apply the supplied fields; unmentioned ones keep their stored value.

    `allow_attiva` is what separates the two update endpoints: a user with write
    permission may edit a hive's details but not retire or revive it.

    Raises:
        NotFound: se l'arnia non esiste.
    """
    optional = {"attiva": arnia.attiva} if allow_attiva else {}

    row = arnie.update(
        session,
        id_arnia,
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


def deactivate_arnia(session, id_arnia: int) -> None:
    """
    Soft delete: historical readings are kept.

    Raises:
        NotFound: se l'arnia non esiste.
    """
    if not arnie.deactivate(session, id_arnia):
        raise NotFound("Arnia non trovata")


def move_arnia(session, id_arnia: int, id_apiario: int) -> dict[str, Any]:
    """
    Move a hive into another apiary of its owner.

    Raises:
        NotFound: if the hive does not exist.
        InvalidData: if the hive is unassigned, or the apiary is not its owner's.
    """
    found = arnie.get_proprietario(session, id_arnia)
    if not found:
        raise NotFound("Arnia non trovata")
    if found["id_utente_proprietario"] is None:
        raise InvalidData("L'arnia non è assegnata: assegna prima il suo nodo")
    apiari.owned_by(session, id_apiario, found["id_utente_proprietario"])
    return arnie.set_apiario(session, id_arnia, id_apiario)


def placement(session, id_nodo: str, id_apiario: int | None) -> int | None:
    """
    The apiary a new hive of this node goes in.

    Raises:
        NotFound: if the node does not exist.
        InvalidData: if the apiary is not the node owner's, or the node is
            unassigned and an apiary was named.
    """
    nodo = nodi.get(session, id_nodo)
    if not nodo:
        raise NotFound(f"Nodo '{id_nodo}' non trovato")
    owner = nodo["id_proprietario"]
    if owner is None:
        if id_apiario is not None:
            raise InvalidData("Il nodo non è assegnato: assegnalo prima a un utente")
        return None
    if id_apiario is None:
        return apiari.ensure_predefinito(session, owner)["id_apiario"]
    return apiari.owned_by(session, id_apiario, owner)["id_apiario"]
