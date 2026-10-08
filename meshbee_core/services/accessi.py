"""Sharing an apiary: the roles its owner grants other users on it."""

from typing import Any

from meshbee_core.errors import InvalidData, NotFound
from meshbee_core.repository import accessi, apiari, utenti


def list_condivisioni(session, id_apiario: int) -> list[dict[str, Any]]:
    """
    Raises:
        NotFound: if the apiary does not exist.
    """
    _require_apiario(session, id_apiario)
    return accessi.list_for_apiario(session, id_apiario)


def share(session, id_apiario: int, condivisione) -> dict[str, Any]:
    """
    Share the apiary with the user behind an email, or change their role.

    Raises:
        NotFound: if the apiary, or a user with that email, does not exist.
        InvalidData: if that user is the owner, who already has full access.
    """
    apiario = _require_apiario(session, id_apiario)
    found = utenti.find_id_by_email(session, condivisione.email)
    if not found:
        raise NotFound("Utente non trovato")
    if found["id_utente"] == apiario["id_utente_proprietario"]:
        raise InvalidData("Il proprietario ha già accesso completo all'apiario")

    accessi.upsert(session, found["id_utente"], id_apiario, condivisione.ruolo)
    return accessi.get(session, found["id_utente"], id_apiario)


def change_ruolo(
    session, id_apiario: int, id_utente: int, ruolo: str
) -> dict[str, Any]:
    """
    Raises:
        NotFound: if the apiary is not shared with that user.
    """
    if not accessi.update_ruolo(session, id_utente, id_apiario, ruolo):
        raise NotFound("Condivisione non trovata")
    return accessi.get(session, id_utente, id_apiario)


def revoke(session, id_apiario: int, id_utente: int) -> None:
    """
    Raises:
        NotFound: if the apiary is not shared with that user.
    """
    if not accessi.delete_share(session, id_utente, id_apiario):
        raise NotFound("Condivisione non trovata")


def _require_apiario(session, id_apiario: int) -> dict[str, Any]:
    apiario = apiari.get(session, id_apiario)
    if not apiario:
        raise NotFound("Apiario non trovato")
    return apiario
