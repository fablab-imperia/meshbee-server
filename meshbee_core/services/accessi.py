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


def grant_if_absent(cursor, id_utente: int, id_arnia: int, permessi: str) -> None:
    """
    Grant access without touching an association that already exists.

    See `repository.accessi.insert_if_absent` for why bootstrapping must not use
    the reviving upsert.
    """
    accessi.insert_if_absent(cursor, id_utente, id_arnia, permessi)


def revoke(cursor, id_utente: int, id_arnia: int) -> None:
    """
    Raises:
        NotFound: se l'associazione non esiste o è già stata rimossa.
    """
    if not accessi.deactivate(cursor, id_utente, id_arnia):
        raise NotFound("Associazione non trovata o già rimossa")
