"""Sharing an apiary: the roles its owner grants other users on it.

An apiary is shared by email. If the email has an account, that is a share
(`utenti_apiari`); if not, a pending invitation (`inviti_apiari`, #40) that
becomes a share when an account with that email is created. The caller is
told the same either way, so sharing cannot be used to find out which
addresses are registered.
"""

from typing import Any

from meshbee_core.errors import InvalidData, NotFound
from meshbee_core.paging import EVERYTHING, Page, Paging
from meshbee_core.repository import accessi, apiari, inviti, utenti

ATTIVA, IN_ATTESA = "attiva", "in_attesa"
INVITO_NOT_FOUND = "Invito non trovato"


def list_condivisioni(session, id_apiario: int, paging: Paging = EVERYTHING) -> Page:
    """
    Raises:
        NotFound: if the apiary does not exist.
    """
    _require_apiario(session, id_apiario)
    return accessi.list_for_apiario(session, id_apiario, paging)


def share(session, id_apiario: int, condivisione) -> dict[str, Any]:
    """
    Share the apiary with an email, or change the role it was given.

    Returns `id_apiario`, `email`, `ruolo` and `stato`: `attiva` with the
    `id_utente` of the account, or `in_attesa` with the `id_invito` of the
    invitation. Only the first three are for the person sharing (#40); the rest
    is for whoever acts on it, such as sending an email.

    Raises:
        NotFound: if the apiary does not exist.
        InvalidData: if the email is the owner's, who already has full access.
    """
    apiario = _require_apiario(session, id_apiario)
    email, ruolo = condivisione.email, condivisione.ruolo
    result = {"id_apiario": id_apiario, "email": email, "ruolo": ruolo}

    found = utenti.find_id_by_email(session, email)
    if found is None:
        invito = inviti.upsert(session, email, id_apiario, ruolo)
        return {**result, "stato": IN_ATTESA, "id_invito": invito["id_invito"]}

    if found["id_utente"] == apiario["id_utente_proprietario"]:
        raise InvalidData("Il proprietario ha già accesso completo all'apiario")
    accessi.upsert(session, found["id_utente"], id_apiario, ruolo)
    return {**result, "stato": ATTIVA, "id_utente": found["id_utente"]}


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


def change_invito_ruolo(
    session, id_apiario: int, id_invito: int, ruolo: str
) -> dict[str, Any]:
    """
    Raises:
        NotFound: if the apiary has no such pending invitation.
    """
    invito = inviti.update_ruolo(session, id_invito, id_apiario, ruolo)
    if invito is None:
        raise NotFound(INVITO_NOT_FOUND)
    return invito


def revoke_invito(session, id_apiario: int, id_invito: int) -> dict[str, Any]:
    """
    Withdraw a pending invitation; return what it was.

    Raises:
        NotFound: if the apiary has no such pending invitation.
    """
    invito = inviti.delete_one(session, id_invito, id_apiario)
    if invito is None:
        raise NotFound(INVITO_NOT_FOUND)
    return invito


def accept_invitations(session, id_utente: int, email: str) -> int:
    """
    Turn every pending invitation to `email` into a share for the new account.

    Called when an account is created with that email, or takes it on. An
    invitation to an apiary the account already owns is dropped: owning allows
    everything. Returns how many apiaries it now shares.
    """
    shared = 0
    for invito in inviti.take_for_email(session, email):
        apiario = apiari.get(session, invito["id_apiario"])
        if apiario["id_utente_proprietario"] != id_utente:
            accessi.upsert(session, id_utente, invito["id_apiario"], invito["ruolo"])
            shared += 1
    return shared


def _require_apiario(session, id_apiario: int) -> dict[str, Any]:
    apiario = apiari.get(session, id_apiario)
    if not apiario:
        raise NotFound("Apiario non trovato")
    return apiario
