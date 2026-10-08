"""Apiaries: the places hives are grouped by.

Access is never granted on an apiary itself. A user sees an apiary because they
are associated with a hive in it (see `repository/apiari.py`), and inside it
only those hives; admins see everything.
"""

from typing import Any

from meshbee_core.db import integrity_errors
from meshbee_core.errors import Conflict, NotFound
from meshbee_core.repository import apiari


def owner_not_found(id_utente: int | None) -> NotFound:
    return NotFound(f"Utente {id_utente} non trovato")


def list_for_utente(session, current_user) -> list[dict[str, Any]]:
    """Every active apiary for an admin, those holding the user's hives otherwise."""
    if current_user["ruolo"] == "admin":
        return apiari.list_attivi(session)
    return apiari.list_for_utente(session, current_user["id_utente"])


def list_all(session) -> list[dict[str, Any]]:
    """Every apiary including the retired ones — the admin inventory."""
    return apiari.list_all(session)


def get_apiario(session, id_apiario: int) -> dict[str, Any]:
    """
    Raises:
        NotFound: if the apiary does not exist.
    """
    row = apiari.get(session, id_apiario)
    if not row:
        raise NotFound("Apiario non trovato")
    return row


def create_apiario(session, apiario) -> dict[str, Any]:
    """
    Raises:
        NotFound: if the owner is not a user.
    """
    with integrity_errors(foreign_key=owner_not_found(apiario.id_utente_proprietario)):
        return apiari.insert(
            session,
            nome_apiario=apiario.nome_apiario,
            descrizione=apiario.descrizione,
            posizione=apiario.posizione,
            latitudine=apiario.latitudine,
            longitudine=apiario.longitudine,
            id_utente_proprietario=apiario.id_utente_proprietario,
            metadati=apiario.metadati,
        )


def update_apiario(session, id_apiario: int, apiario) -> dict[str, Any]:
    """
    Apply the supplied fields; unmentioned ones keep their stored value.

    Switching `attivo` off goes through the same rule as deleting.

    Raises:
        NotFound: if the apiary or the new owner does not exist.
        Conflict: if it is being retired while active hives are still in it.
    """
    if apiario.attivo is False:
        refuse_if_occupied(session, id_apiario)

    with integrity_errors(foreign_key=owner_not_found(apiario.id_utente_proprietario)):
        row = apiari.update(
            session,
            id_apiario,
            nome_apiario=apiario.nome_apiario,
            descrizione=apiario.descrizione,
            posizione=apiario.posizione,
            latitudine=apiario.latitudine,
            longitudine=apiario.longitudine,
            id_utente_proprietario=apiario.id_utente_proprietario,
            attivo=apiario.attivo,
            metadati=apiario.metadati,
        )
    if not row:
        raise NotFound("Apiario non trovato")
    return row


def deactivate_apiario(session, id_apiario: int) -> None:
    """
    Soft delete, refused while active hives are still in the apiary.

    Refusing rather than detaching them: emptying an apiary is a decision about
    each hive, and an apiary retired silently would leave them pointing at a
    place that no longer shows up anywhere.

    Raises:
        NotFound: if the apiary does not exist.
        Conflict: if active hives are still in it.
    """
    refuse_if_occupied(session, id_apiario)
    if not apiari.deactivate(session, id_apiario):
        raise NotFound("Apiario non trovato")


def refuse_if_occupied(session, id_apiario: int) -> None:
    count = apiari.count_arnie_attive(session, id_apiario)
    if count:
        raise Conflict(
            f"L'apiario contiene ancora {count} arnie attive: spostale prima di disattivarlo"
        )
