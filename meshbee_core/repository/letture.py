"""Queries on `letture`."""
import json
from typing import Any, Dict, List, Optional

COLUMNS = """id_lettura, id_arnia, id_nodo, timestamp,
                       temperatura, umidita, peso, batteria, dati_raw"""

# The measurement columns exposed as chart series. Whitelist, not decoration:
# `series` interpolates the name into the statement.
SERIES_FIELDS = ("temperatura", "umidita", "peso", "batteria")


def insert(cursor, *, id_arnia: int, id_nodo: str, timestamp, temperatura,
           umidita, peso, dati_raw: Optional[dict],
           batteria=None) -> Dict[str, Any]:
    """
    Persist one reading. A null timestamp defaults to now, in the database.

    This is the single INSERT both entry points reach: the API's manual-insert
    endpoint and the MQTT ingest path.
    """
    cursor.execute(
        f"""
        INSERT INTO letture
            (id_arnia, id_nodo, timestamp, temperatura, umidita, peso,
             batteria, dati_raw)
        VALUES (%s, %s, COALESCE(%s, CURRENT_TIMESTAMP), %s, %s, %s, %s, %s)
        RETURNING {COLUMNS}
        """,
        (
            id_arnia, id_nodo, timestamp, temperatura, umidita, peso, batteria,
            json.dumps(dati_raw) if dati_raw else None
        )
    )
    return cursor.fetchone()


def list_by_arnia(cursor, id_arnia: int, data_inizio, data_fine,
                  limit: int) -> List[Dict[str, Any]]:
    cursor.execute(
        f"""
        SELECT {COLUMNS}
        FROM letture
        WHERE id_arnia = %s
          AND timestamp >= %s
          AND timestamp <= %s
        ORDER BY timestamp DESC
        LIMIT %s
        """,
        (id_arnia, data_inizio, data_fine, limit)
    )
    return cursor.fetchall()


def list_all(cursor, limit: int) -> List[Dict[str, Any]]:
    cursor.execute(
        f"""
        SELECT {COLUMNS}
        FROM letture
        ORDER BY timestamp DESC
        LIMIT %s
        """,
        (limit,)
    )
    return cursor.fetchall()


def series(cursor, id_arnia: int, field: str, data_inizio, data_fine,
           limit: int) -> List[Dict[str, Any]]:
    """
    Timestamp plus one measurement, skipping rows where it is null.

    Rows with a null measurement are dropped rather than returned as gaps: the
    series feeds a chart, and a null point is not a data point.
    """
    if field not in SERIES_FIELDS:
        raise ValueError(f"Campo serie sconosciuto: {field!r}")

    cursor.execute(
        f"""
        SELECT timestamp, {field}
        FROM letture
        WHERE id_arnia = %s
          AND timestamp BETWEEN %s AND %s
          AND {field} IS NOT NULL
        ORDER BY timestamp DESC
        LIMIT %s
        """,
        (id_arnia, data_inizio, data_fine, limit)
    )
    return cursor.fetchall()
