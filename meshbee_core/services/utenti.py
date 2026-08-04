"""User accounts: creation, updates, deactivation and passwords."""
from typing import Any, Dict, List

import psycopg2

from meshbee_core.errors import Conflict, InvalidData, NotFound
from meshbee_core.repository import utenti
from meshbee_core.security import get_password_hash, verify_password


def list_utenti(cursor) -> List[Dict[str, Any]]:
    return [dict(row) for row in utenti.list_all(cursor)]


def create_utente(cursor, user) -> Dict[str, Any]:
    """
    Raises:
        Conflict: se l'email è già registrata.
    """
    if utenti.find_id_by_email(cursor, user.email):
        raise Conflict("Email già registrata")

    return dict(utenti.insert(
        cursor,
        email=user.email,
        password_hash=get_password_hash(user.password),
        nome=user.nome,
        cognome=user.cognome,
        ruolo=user.ruolo,
    ))


def update_utente(cursor, id_utente: int, user_update) -> Dict[str, Any]:
    """
    Apply the fields that were actually supplied.

    Raises:
        InvalidData: se non è stato indicato alcun campo.
        NotFound: se l'utente non esiste.
        Conflict: se la nuova email è già registrata.
    """
    updates = {
        field: value
        for field, value in (
            ("email", user_update.email),
            ("nome", user_update.nome),
            ("cognome", user_update.cognome),
            ("ruolo", user_update.ruolo),
            ("attivo", user_update.attivo),
        )
        if value is not None
    }

    if not updates:
        raise InvalidData("Nessun campo da aggiornare")

    # Deactivating an account records when it happened.
    stamp = user_update.attivo is False

    try:
        updated = utenti.update(cursor, id_utente, updates, stamp_disattivazione=stamp)
    except psycopg2.errors.UniqueViolation as exc:
        raise Conflict("Email già registrata") from exc

    if not updated:
        raise NotFound("Utente non trovato")

    return dict(updated)


def deactivate_utente(cursor, id_utente: int, *, acting_user_id: int) -> None:
    """
    Soft-delete an account.

    Raises:
        InvalidData: se l'utente prova a disattivare se stesso.
        NotFound: se l'utente non esiste.
    """
    # Locking yourself out would need another admin to undo it.
    if id_utente == acting_user_id:
        raise InvalidData("Non puoi disattivare te stesso")

    if not utenti.deactivate(cursor, id_utente):
        raise NotFound("Utente non trovato")


def reset_password(cursor, id_utente: int, new_password: str) -> None:
    """
    Set a password without knowing the old one (admin only).

    Raises:
        NotFound: se l'utente non esiste.
    """
    if not utenti.set_password_hash(cursor, id_utente, get_password_hash(new_password)):
        raise NotFound("Utente non trovato")


def change_own_password(cursor, id_utente: int, current_password, new_password: str) -> None:
    """
    Replace a password, proving knowledge of the current one.

    Raises:
        InvalidData: se la password attuale manca o non è corretta.
    """
    if not current_password:
        raise InvalidData("Inserire la password attuale")

    row = utenti.get_password_hash(cursor, id_utente)
    if not verify_password(current_password, row["password_hash"]):
        raise InvalidData("Password attuale non corretta")

    utenti.set_password_hash(cursor, id_utente, get_password_hash(new_password))
