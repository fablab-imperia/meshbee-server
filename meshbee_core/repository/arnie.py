"""Queries on `arnie` and the `v_arnie_stato` view."""
import json
from typing import Any, Dict, List, Optional

COLUMNS = """id_arnia, id_nodo, id_sensore_fisico, nome_arnia, descrizione,
                          posizione, latitudine, longitudine, data_installazione, data_rimozione,
                          attiva, metadati"""

# Sentinel for "leave this column out of the statement entirely", which is not
# the same as passing None (COALESCE keeps the stored value).
UNSET = object()


def list_stato(cursor) -> List[Dict[str, Any]]:
    cursor.execute("SELECT * FROM v_arnie_stato ORDER BY id_arnia")
    return cursor.fetchall()


def list_stato_attive(cursor) -> List[Dict[str, Any]]:
    cursor.execute(
        """
        SELECT * FROM v_arnie_stato
        WHERE attiva = true
        ORDER BY nome_arnia
        """
    )
    return cursor.fetchall()


def list_stato_for_utente(cursor, id_utente: int) -> List[Dict[str, Any]]:
    cursor.execute(
        """
        SELECT vs.*
        FROM v_arnie_stato vs
        JOIN utenti_arnie ua ON vs.id_arnia = ua.id_arnia
        WHERE ua.id_utente = %s AND ua.attivo = true AND vs.attiva = true
        ORDER BY vs.nome_arnia
        """,
        (id_utente,)
    )
    return cursor.fetchall()


def get_stato(cursor, id_arnia: int) -> Optional[Dict[str, Any]]:
    cursor.execute("SELECT * FROM v_arnie_stato WHERE id_arnia = %s", (id_arnia,))
    return cursor.fetchone()


def list_ids(cursor) -> List[Dict[str, Any]]:
    """
    Just the identifiers, for callers that only need to iterate.

    Distinct from `list_stato` on purpose: that view runs four correlated
    subqueries per row to attach the latest readings, which is wasted work when
    nobody is going to look at them.
    """
    cursor.execute("SELECT id_arnia FROM arnie ORDER BY id_arnia")
    return cursor.fetchall()


def insert(cursor, *, id_nodo: str, id_sensore_fisico: str, nome_arnia: str,
           descrizione: Optional[str] = None, posizione: Optional[str] = None,
           latitudine=None, longitudine=None,
           metadati: Optional[dict] = None) -> Dict[str, Any]:
    cursor.execute(
        f"""
        INSERT INTO arnie
        (id_nodo, id_sensore_fisico, nome_arnia, descrizione, posizione, latitudine, longitudine, attiva, metadati)
        VALUES (%s, %s, %s, %s, %s, %s, %s, true, %s)
        RETURNING {COLUMNS}
        """,
        (
            id_nodo, id_sensore_fisico, nome_arnia, descrizione, posizione,
            latitudine, longitudine,
            json.dumps(metadati) if metadati else None
        )
    )
    return cursor.fetchone()


def update(cursor, id_arnia: int, *, nome_arnia=None, descrizione=None, posizione=None,
           latitudine=None, longitudine=None, metadati=None,
           attiva=UNSET) -> Optional[Dict[str, Any]]:
    """
    COALESCE partial update: a None argument leaves the column untouched.

    `attiva` is omitted from the statement unless explicitly passed — the user
    endpoint must not be able to reactivate or retire an arnia, only the admin
    one can.
    """
    assignments = [
        "nome_arnia  = COALESCE(%s, nome_arnia)",
        "descrizione = COALESCE(%s, descrizione)",
        "posizione   = COALESCE(%s, posizione)",
        "latitudine  = COALESCE(%s, latitudine)",
        "longitudine = COALESCE(%s, longitudine)",
    ]
    params = [nome_arnia, descrizione, posizione, latitudine, longitudine]

    if attiva is not UNSET:
        assignments.append("attiva      = COALESCE(%s, attiva)")
        params.append(attiva)

    assignments.append("metadati    = COALESCE(%s, metadati)")
    params.append(json.dumps(metadati) if metadati else None)
    params.append(id_arnia)

    set_clause = ",\n            ".join(assignments)
    cursor.execute(
        f"""
        UPDATE arnie
        SET {set_clause}
        WHERE id_arnia = %s
        RETURNING {COLUMNS}
        """,
        params
    )
    return cursor.fetchone()


def deactivate(cursor, id_arnia: int) -> Optional[Dict[str, Any]]:
    cursor.execute(
        """
        UPDATE arnie
        SET attiva = false, data_rimozione = CURRENT_TIMESTAMP
        WHERE id_arnia = %s
        RETURNING id_arnia
        """,
        (id_arnia,)
    )
    return cursor.fetchone()


def find_id_by_nodo_sensore(cursor, id_nodo: str, id_sensore: str) -> Optional[Dict[str, Any]]:
    cursor.execute(
        """
        SELECT id_arnia FROM arnie
        WHERE id_nodo = %s AND id_sensore_fisico = %s
        """,
        (id_nodo, id_sensore)
    )
    return cursor.fetchone()


def find_first_id_by_nodo(cursor, id_nodo: str) -> Optional[Dict[str, Any]]:
    """Fallback for readings that carry no sensor id: the node's lowest arnia."""
    cursor.execute(
        """
        SELECT id_arnia FROM arnie
        WHERE id_nodo = %s
        ORDER BY id_arnia
        LIMIT 1
        """,
        (id_nodo,)
    )
    return cursor.fetchone()
