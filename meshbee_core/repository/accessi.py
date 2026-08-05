"""Queries on `utenti_arnie`, the user-to-arnia association."""
from typing import Any, Dict, Optional


def get_permesso(cursor, id_utente: int, id_arnia: int) -> Optional[Dict[str, Any]]:
    """The permission level of an *active* association, or None if there is none."""
    cursor.execute(
        """
        SELECT permessi FROM utenti_arnie
        WHERE id_utente = %s AND id_arnia = %s AND attivo = true
        """,
        (id_utente, id_arnia)
    )
    return cursor.fetchone()


def upsert(cursor, id_utente: int, id_arnia: int, permessi: str) -> None:
    """Grant access, reviving and re-levelling a previously removed association."""
    cursor.execute(
        """
        INSERT INTO utenti_arnie (id_utente, id_arnia, permessi, attivo)
        VALUES (%s, %s, %s, true)
        ON CONFLICT (id_utente, id_arnia)
        DO UPDATE SET
            permessi = EXCLUDED.permessi,
            attivo = true,
            data_disassociazione = NULL
        """,
        (id_utente, id_arnia, permessi)
    )


def insert_if_absent(cursor, id_utente: int, id_arnia: int, permessi: str) -> None:
    """
    Grant access only where none was ever recorded, leaving existing rows alone.

    Deliberately not `upsert`: this is for bootstrapping, which re-runs on every
    `docker-compose up`. Reviving an association an admin had revoked, on every
    restart, would be a silent authorization change.
    """
    cursor.execute(
        """
        INSERT INTO utenti_arnie (id_utente, id_arnia, permessi, attivo)
        VALUES (%s, %s, %s, true)
        ON CONFLICT (id_utente, id_arnia) DO NOTHING
        """,
        (id_utente, id_arnia, permessi)
    )


def deactivate(cursor, id_utente: int, id_arnia: int) -> Optional[Dict[str, Any]]:
    cursor.execute(
        """
        UPDATE utenti_arnie
        SET attivo = false, data_disassociazione = CURRENT_TIMESTAMP
        WHERE id_utente = %s AND id_arnia = %s AND attivo = true
        RETURNING id
        """,
        (id_utente, id_arnia)
    )
    return cursor.fetchone()
