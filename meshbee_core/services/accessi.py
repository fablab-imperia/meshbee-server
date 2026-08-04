"""Granting and revoking a user's access to an arnia."""
import psycopg2

from meshbee_core.errors import NotFound
from meshbee_core.repository import accessi


def grant(cursor, associazione) -> None:
    """
    Associate a user with an arnia, or re-level an existing association.

    Raises:
        NotFound: se l'utente o l'arnia non esistono.
    """
    try:
        accessi.upsert(
            cursor,
            associazione.id_utente,
            associazione.id_arnia,
            associazione.permessi,
        )
    except psycopg2.errors.ForeignKeyViolation as exc:
        raise NotFound("Utente o arnia non trovati") from exc


def revoke(cursor, id_utente: int, id_arnia: int) -> None:
    """
    Raises:
        NotFound: se l'associazione non esiste o è già stata rimossa.
    """
    if not accessi.deactivate(cursor, id_utente, id_arnia):
        raise NotFound("Associazione non trovata o già rimossa")
