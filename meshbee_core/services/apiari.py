"""Apiaries: each user's own grouping of the hives they can see.

Every user has one default apiary, created with the account, which new grants
land in and which cannot be deleted. Beyond it a user may create, edit and
delete as many as they like; which apiary a hive is in is stored per user on
the association (`utenti_arnie.id_apiario`), never on the hive.
"""

from typing import Any

from meshbee_core.db import integrity_errors
from meshbee_core.errors import Conflict, InvalidData, NotFound
from meshbee_core.repository import accessi, apiari

DEFAULT_NOME = "Default"


def ensure_predefinito(session, id_utente: int) -> dict[str, Any]:
    """
    The user's default apiary, created if they have none yet.

    Raises:
        NotFound: if the user does not exist.
    """
    found = apiari.get_predefinito(session, id_utente)
    if found:
        return found
    with integrity_errors(foreign_key=NotFound(f"Utente {id_utente} non trovato")):
        return apiari.insert(
            session,
            id_utente_proprietario=id_utente,
            nome_apiario=DEFAULT_NOME,
            predefinito=True,
        )


def list_for_utente(session, id_utente: int) -> list[dict[str, Any]]:
    """The user's own apiaries, the default first."""
    return apiari.list_all(session, id_utente)


def list_all(session, id_utente: int | None = None) -> list[dict[str, Any]]:
    """Everyone's apiaries, or one owner's — the admin view."""
    return apiari.list_all(session, id_utente)


def get_apiario(session, id_apiario: int) -> dict[str, Any]:
    """
    Raises:
        NotFound: if the apiary does not exist.
    """
    row = apiari.get(session, id_apiario)
    if not row:
        raise NotFound("Apiario non trovato")
    return row


def owned_by(session, id_apiario: int, id_utente: int) -> dict[str, Any]:
    """
    The apiary, if it is one of the user's own.

    A missing apiary and someone else's get the same answer, so the check
    reveals nothing about other people's apiaries.

    Raises:
        InvalidData: if the user does not own it, or it does not exist.
    """
    row = apiari.get(session, id_apiario)
    if not row or row["id_utente_proprietario"] != id_utente:
        raise InvalidData("Apiario non accessibile")
    return row


def create_apiario(session, id_utente: int, apiario) -> dict[str, Any]:
    """
    A new, non-default apiary owned by `id_utente`.

    Raises:
        NotFound: if the owner is not a user.
    """
    with integrity_errors(foreign_key=NotFound(f"Utente {id_utente} non trovato")):
        return apiari.insert(
            session,
            id_utente_proprietario=id_utente,
            nome_apiario=apiario.nome_apiario,
            descrizione=apiario.descrizione,
            posizione=apiario.posizione,
            latitudine=apiario.latitudine,
            longitudine=apiario.longitudine,
            metadati=apiario.metadati,
        )


def update_apiario(session, id_apiario: int, apiario) -> dict[str, Any]:
    """
    Apply the supplied fields; unmentioned ones keep their stored value.

    Raises:
        NotFound: if the apiary does not exist.
    """
    row = apiari.update(
        session,
        id_apiario,
        nome_apiario=apiario.nome_apiario,
        descrizione=apiario.descrizione,
        posizione=apiario.posizione,
        latitudine=apiario.latitudine,
        longitudine=apiario.longitudine,
        metadati=apiario.metadati,
    )
    if not row:
        raise NotFound("Apiario non trovato")
    return row


def delete_apiario(session, id_apiario: int) -> None:
    """
    Delete an apiary its owner has emptied.

    Refused for the default apiary, and while active hives are still in it:
    where each hive goes is the owner's decision. Revoked associations, which
    the owner cannot see, are moved to their default apiary first.

    Raises:
        NotFound: if the apiary does not exist.
        Conflict: if it is the default, or still holds active hives.
    """
    apiario = get_apiario(session, id_apiario)
    if apiario["predefinito"]:
        raise Conflict("L'apiario predefinito non può essere eliminato")
    count = apiari.count_arnie_attive(session, id_apiario)
    if count:
        raise Conflict(
            f"L'apiario contiene ancora {count} arnie: spostale prima di eliminarlo"
        )

    predefinito = ensure_predefinito(session, apiario["id_utente_proprietario"])
    accessi.move_all(session, id_apiario, predefinito["id_apiario"])
    apiari.delete(session, id_apiario)
