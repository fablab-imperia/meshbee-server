"""Queries on `log_attivita`."""
import json
from typing import Any, Dict, List, Optional

COLUMNS = """id_log, id_utente, id_arnia, timestamp,
                       tipo_attivita, descrizione, dati"""

# Columns `update` will accept; the SET clause is assembled by name.
UPDATABLE = ("timestamp", "tipo_attivita", "descrizione", "dati")


def list_by_arnia(cursor, id_arnia: int, data_inizio, data_fine, limit: int,
                  tipo_attivita: Optional[str] = None) -> List[Dict[str, Any]]:
    query = f"""
                SELECT {COLUMNS}
                FROM log_attivita
                WHERE id_arnia = %s
                  AND timestamp >= %s
                  AND timestamp <= %s
            """
    params = [id_arnia, data_inizio, data_fine]

    if tipo_attivita:
        query += " AND tipo_attivita = %s"
        params.append(tipo_attivita)

    query += " ORDER BY timestamp DESC LIMIT %s"
    params.append(limit)

    cursor.execute(query, params)
    return cursor.fetchall()


def list_all(cursor, limit: int) -> List[Dict[str, Any]]:
    cursor.execute(
        f"""
        SELECT {COLUMNS}
        FROM log_attivita
        ORDER BY timestamp DESC
        LIMIT %s
        """,
        (limit,)
    )
    return cursor.fetchall()


def count_for_arnia(cursor, id_arnia: int) -> int:
    cursor.execute(
        "SELECT COUNT(*) AS n FROM log_attivita WHERE id_arnia = %s", (id_arnia,)
    )
    return cursor.fetchone()["n"]


def insert(cursor, *, id_utente: Optional[int], id_arnia: int, timestamp,
           tipo_attivita: str, descrizione: Optional[str],
           dati: Optional[dict]) -> Dict[str, Any]:
    cursor.execute(
        f"""
        INSERT INTO log_attivita
        (id_utente, id_arnia, timestamp, tipo_attivita, descrizione, dati)
        VALUES (%s, %s, COALESCE(%s, CURRENT_TIMESTAMP), %s, %s, %s)
        RETURNING {COLUMNS}
        """,
        (
            id_utente, id_arnia, timestamp, tipo_attivita, descrizione,
            json.dumps(dati) if dati else None
        )
    )
    return cursor.fetchone()


def find_owned(cursor, id_log: int, id_arnia: int, id_utente: int) -> Optional[Dict[str, Any]]:
    """Ownership probe: the activity must belong to both this arnia and this user."""
    cursor.execute(
        "SELECT id_log FROM log_attivita WHERE id_log = %s AND id_arnia = %s AND id_utente = %s",
        (id_log, id_arnia, id_utente)
    )
    return cursor.fetchone()


def get_all_columns(cursor, id_log: int) -> Optional[Dict[str, Any]]:
    """Every column, for the empty-patch path that returns the row unchanged."""
    cursor.execute("SELECT * FROM log_attivita WHERE id_log = %s", (id_log,))
    return cursor.fetchone()


def update(cursor, id_log: int, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    unknown = set(updates) - set(UPDATABLE)
    if unknown:
        raise ValueError(f"Colonne non aggiornabili: {sorted(unknown)}")

    assignments = []
    params = []
    for field, value in updates.items():
        assignments.append(f"{field} = %s")
        params.append(json.dumps(value) if field == "dati" and value is not None else value)
    params.append(id_log)

    cursor.execute(
        f"UPDATE log_attivita SET {', '.join(assignments)} WHERE id_log = %s RETURNING *",
        tuple(params)
    )
    return cursor.fetchone()


def delete_owned(cursor, id_log: int, id_arnia: int, id_utente: int) -> Optional[Dict[str, Any]]:
    cursor.execute(
        "DELETE FROM log_attivita WHERE id_log = %s AND id_arnia = %s AND id_utente = %s RETURNING id_log",
        (id_log, id_arnia, id_utente)
    )
    return cursor.fetchone()
