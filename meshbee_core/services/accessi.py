"""Granting and revoking a user's access to an arnia."""

from typing import Any

from meshbee_core.db import integrity_errors
from meshbee_core.errors import NotFound
from meshbee_core.repository import accessi
from meshbee_core.services import apiari


def grant(session, associazione) -> None:
    """
    Associate a user with an arnia, or re-level an existing association.

    A new association goes in the apiary named, which must be one of that
    user's, or else in their default one. An existing association keeps the
    apiary the user had put the hive in.

    Raises:
        NotFound: se l'utente o l'arnia non esistono.
        InvalidData: if the apiary is not one of the user's.
    """
    if associazione.id_apiario is not None:
        apiario = apiari.owned_by(
            session, associazione.id_apiario, associazione.id_utente
        )
    else:
        apiario = apiari.ensure_predefinito(session, associazione.id_utente)
    with integrity_errors(foreign_key=NotFound("Utente o arnia non trovati")):
        accessi.upsert(
            session,
            associazione.id_utente,
            associazione.id_arnia,
            associazione.permessi,
            apiario["id_apiario"],
        )


def grant_if_absent(session, id_utente: int, id_arnia: int, permessi: str) -> None:
    """
    Grant access without touching an association that already exists.

    See `repository.accessi.insert_if_absent` for why bootstrapping must not use
    the reviving upsert.
    """
    apiario = apiari.ensure_predefinito(session, id_utente)
    accessi.insert_if_absent(
        session, id_utente, id_arnia, permessi, apiario["id_apiario"]
    )


def revoke(session, id_utente: int, id_arnia: int) -> None:
    """
    Raises:
        NotFound: se l'associazione non esiste o è già stata rimossa.
    """
    if not accessi.deactivate(session, id_utente, id_arnia):
        raise NotFound("Associazione non trovata o già rimossa")


def move(session, id_utente: int, id_arnia: int, id_apiario: int) -> dict[str, Any]:
    """
    Put a hive in another of the user's own apiaries. Only their view changes:
    anyone else sharing the hive keeps it where they put it.

    Raises:
        InvalidData: if the apiary is not one of the user's.
        NotFound: if the user has no active association with the arnia.
    """
    apiari.owned_by(session, id_apiario, id_utente)
    if not accessi.move(session, id_utente, id_arnia, id_apiario):
        raise NotFound("Nessuna associazione attiva con questa arnia")
    return {"message": "Arnia spostata"}
