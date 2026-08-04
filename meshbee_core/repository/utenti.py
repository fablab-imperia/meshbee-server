"""Queries on `utenti`."""
from typing import Any, Dict, List, Optional

# The public projection: `password_hash` is deliberately absent, so a response
# built straight from these rows cannot leak it.
COLUMNS = """id_utente, email, nome, cognome, ruolo,
                       data_creazione, data_attivazione, data_disattivazione,
                       ultimo_accesso, attivo"""

# Columns `update` will accept. Anything else is a programming error, not user
# input — the SET clause is assembled by name, so this is what keeps it safe.
UPDATABLE = ("email", "nome", "cognome", "ruolo", "attivo")


def get_credentials_by_email(cursor, email: str) -> Optional[Dict[str, Any]]:
    """The login projection: includes password_hash, unlike `COLUMNS`."""
    cursor.execute(
        """
        SELECT id_utente, email, password_hash, nome, cognome, ruolo, attivo
        FROM utenti
        WHERE email = %s
        """,
        (email,)
    )
    return cursor.fetchone()


def get_by_email(cursor, email: str) -> Optional[Dict[str, Any]]:
    cursor.execute(
        f"""
        SELECT {COLUMNS}
        FROM utenti
        WHERE email = %s
        """,
        (email,)
    )
    return cursor.fetchone()


def touch_ultimo_accesso(cursor, id_utente: int) -> None:
    cursor.execute(
        """
        UPDATE utenti
        SET ultimo_accesso = CURRENT_TIMESTAMP
        WHERE id_utente = %s
        """,
        (id_utente,)
    )


def get_ruolo(cursor, id_utente: int) -> Optional[Dict[str, Any]]:
    cursor.execute("SELECT ruolo FROM utenti WHERE id_utente = %s", (id_utente,))
    return cursor.fetchone()


def list_all(cursor) -> List[Dict[str, Any]]:
    cursor.execute(
        f"""
        SELECT {COLUMNS}
        FROM utenti
        ORDER BY id_utente
        """
    )
    return cursor.fetchall()


def find_id_by_email(cursor, email: str) -> Optional[Dict[str, Any]]:
    cursor.execute("SELECT id_utente FROM utenti WHERE email = %s", (email,))
    return cursor.fetchone()


def insert(cursor, *, email: str, password_hash: str, nome: str, cognome: str,
           ruolo: str) -> Dict[str, Any]:
    cursor.execute(
        f"""
        INSERT INTO utenti (email, password_hash, nome, cognome, ruolo, data_attivazione, attivo)
        VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP, true)
        RETURNING {COLUMNS}
        """,
        (email, password_hash, nome, cognome, ruolo)
    )
    return cursor.fetchone()


def update(cursor, id_utente: int, updates: Dict[str, Any], *,
           stamp_disattivazione: bool = False) -> Optional[Dict[str, Any]]:
    """
    Apply the named columns and return the updated row, or None if absent.

    `stamp_disattivazione` adds the data_disattivazione side effect; whether it
    applies is the service's call, not this layer's.
    """
    unknown = set(updates) - set(UPDATABLE)
    if unknown:
        raise ValueError(f"Colonne non aggiornabili: {sorted(unknown)}")

    assignments = [f"{column} = %s" for column in updates]
    params = list(updates.values())
    if stamp_disattivazione:
        assignments.append("data_disattivazione = CURRENT_TIMESTAMP")
    params.append(id_utente)

    cursor.execute(
        f"""
        UPDATE utenti
        SET {', '.join(assignments)}
        WHERE id_utente = %s
        RETURNING {COLUMNS}
        """,
        params
    )
    return cursor.fetchone()


def deactivate(cursor, id_utente: int) -> Optional[Dict[str, Any]]:
    cursor.execute(
        """
        UPDATE utenti
        SET attivo = false, data_disattivazione = CURRENT_TIMESTAMP
        WHERE id_utente = %s
        RETURNING id_utente
        """,
        (id_utente,)
    )
    return cursor.fetchone()


def get_password_hash(cursor, id_utente: int) -> Optional[Dict[str, Any]]:
    cursor.execute(
        "SELECT password_hash FROM utenti WHERE id_utente = %s",
        (id_utente,)
    )
    return cursor.fetchone()


def set_password_hash(cursor, id_utente: int, password_hash: str) -> Optional[Dict[str, Any]]:
    cursor.execute(
        "UPDATE utenti SET password_hash = %s WHERE id_utente = %s RETURNING id_utente",
        (password_hash, id_utente)
    )
    return cursor.fetchone()
