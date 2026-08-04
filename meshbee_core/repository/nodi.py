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


def upsert_seen(cursor, id_nodo: str, nome_nodo: str) -> None:
    """
    Register the node if new, otherwise just refresh `ultimo_messaggio`.

    Used by the ingest path, where a node may start transmitting before anyone
    has registered it through the admin API.
    """
    cursor.execute(
        """
        INSERT INTO nodi (id_nodo, nome_nodo, ultimo_messaggio, attivo)
        VALUES (%s, %s, CURRENT_TIMESTAMP, true)
        ON CONFLICT (id_nodo) DO UPDATE
        SET ultimo_messaggio = CURRENT_TIMESTAMP
        """,
        (id_nodo, nome_nodo)
    )
