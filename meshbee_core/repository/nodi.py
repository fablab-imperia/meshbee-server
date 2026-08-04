"""Queries on `nodi`."""
import json
from typing import Any, Dict, List, Optional

COLUMNS = """id_nodo, nome_nodo, descrizione, posizione,
                       data_registrazione, ultimo_messaggio, attivo, configurazione"""


def list_all(cursor) -> List[Dict[str, Any]]:
    cursor.execute(
        f"""
        SELECT {COLUMNS}
        FROM nodi
        ORDER BY id_nodo
        """
    )
    return cursor.fetchall()


def get(cursor, id_nodo: str) -> Optional[Dict[str, Any]]:
    cursor.execute(
        f"""
        SELECT {COLUMNS}
        FROM nodi WHERE id_nodo = %s
        """,
        (id_nodo,)
    )
    return cursor.fetchone()


def find_id(cursor, id_nodo: str) -> Optional[Dict[str, Any]]:
    cursor.execute("SELECT id_nodo FROM nodi WHERE id_nodo = %s", (id_nodo,))
    return cursor.fetchone()


def insert(cursor, *, id_nodo: str, nome_nodo: Optional[str], descrizione: Optional[str],
           posizione: Optional[str], configurazione: Optional[dict]) -> Dict[str, Any]:
    cursor.execute(
        f"""
        INSERT INTO nodi (id_nodo, nome_nodo, descrizione, posizione, attivo, configurazione)
        VALUES (%s, %s, %s, %s, true, %s)
        RETURNING {COLUMNS}
        """,
        (
            id_nodo, nome_nodo, descrizione, posizione,
            json.dumps(configurazione) if configurazione else None
        )
    )
    return cursor.fetchone()


def update(cursor, id_nodo: str, *, nome_nodo: Optional[str], descrizione: Optional[str],
           posizione: Optional[str], configurazione: Optional[dict]) -> Optional[Dict[str, Any]]:
    """COALESCE partial update: a None argument leaves the column untouched."""
    cursor.execute(
        f"""
        UPDATE nodi
        SET nome_nodo    = COALESCE(%s, nome_nodo),
            descrizione  = COALESCE(%s, descrizione),
            posizione    = COALESCE(%s, posizione),
            configurazione = COALESCE(%s, configurazione)
        WHERE id_nodo = %s
        RETURNING {COLUMNS}
        """,
        (
            nome_nodo, descrizione, posizione,
            json.dumps(configurazione) if configurazione else None,
            id_nodo
        )
    )
    return cursor.fetchone()


def deactivate(cursor, id_nodo: str) -> Optional[Dict[str, Any]]:
    cursor.execute(
        "UPDATE nodi SET attivo = false WHERE id_nodo = %s RETURNING id_nodo",
        (id_nodo,)
    )
    return cursor.fetchone()


def register_if_absent(cursor, id_nodo: str, nome_nodo: str) -> None:
    """
    Make sure the node exists, leaving an already-registered one untouched.

    Used by the ingest path, where a node may start transmitting before anyone
    has registered it through the admin API.

    Deliberately does *not* write `ultimo_messaggio`: that column is owned by
    the `trigger_aggiorna_nodo` trigger on `letture`, which fires immediately
    after and overwrites whatever we put there. Setting it here cost every
    message a second UPDATE of the same row for a value that never survived.
    """
    cursor.execute(
        """
        INSERT INTO nodi (id_nodo, nome_nodo, attivo)
        VALUES (%s, %s, true)
        ON CONFLICT (id_nodo) DO NOTHING
        """,
        (id_nodo, nome_nodo)
    )
