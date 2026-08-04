"""Fixtures for tests that run against the real postgres-test database.

Every test in this package is marked `integration` automatically, so
`pytest -m "not integration"` runs the rest of the suite without a database.
"""
import pytest

INTEGRATION_DIR = "integration"


def pytest_collection_modifyitems(items):
    """
    Mark everything collected under tests/integration/ as `integration`.

    The hook receives *every* collected item, not just this package's, so the
    path check is what keeps the unit tests unmarked.
    """
    for item in items:
        if INTEGRATION_DIR in item.path.parts:
            item.add_marker(pytest.mark.integration)


@pytest.fixture
def make_utente(db):
    """
    Insert a row in `utenti` and return it.

    Defaults produce a valid active user; `ruolo` accepts only 'user' or 'admin'
    (CHECK constraint in init.sql).
    """
    counter = iter(range(1, 1000))

    def _make(password_hash="x", ruolo="user", attivo=True, email=None, **overrides):
        email = email or f"utente{next(counter)}@example.org"
        db.execute(
            """
            INSERT INTO utenti (email, password_hash, nome, cognome, ruolo, attivo)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                email,
                password_hash,
                overrides.get("nome", "Giulia"),
                overrides.get("cognome", "Rossi"),
                ruolo,
                attivo,
            ),
        )
        return dict(db.fetchone())

    return _make


@pytest.fixture
def make_arnia(db):
    """Insert a `nodi` row (once) plus an `arnie` row, and return the arnia."""
    counter = iter(range(1, 1000))

    def _make(id_nodo="NODE-TEST"):
        db.execute(
            "INSERT INTO nodi (id_nodo, nome_nodo) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (id_nodo, "Nodo di test"),
        )
        db.execute(
            """
            INSERT INTO arnie (id_nodo, id_sensore_fisico, nome_arnia)
            VALUES (%s, %s, %s)
            RETURNING *
            """,
            (id_nodo, f"SENSOR{next(counter):02d}", "Arnia di test"),
        )
        return dict(db.fetchone())

    return _make


@pytest.fixture
def grant_access(db):
    """Associate a user with an arnia at the given permission level."""
    def _grant(id_utente, id_arnia, permessi="read", attivo=True):
        db.execute(
            """
            INSERT INTO utenti_arnie (id_utente, id_arnia, permessi, attivo)
            VALUES (%s, %s, %s, %s)
            RETURNING *
            """,
            (id_utente, id_arnia, permessi, attivo),
        )
        return dict(db.fetchone())

    return _grant
