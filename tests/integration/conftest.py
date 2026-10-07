"""Fixtures for tests that run against the real postgres-test database.

Every test in this package is marked `integration` automatically, so
`pytest -m "not integration"` runs the rest of the suite without a database.
"""
import pytest
from fastapi.testclient import TestClient

INTEGRATION_DIR = "integration"

KNOWN_PASSWORD = "correct-horse-battery-staple"


@pytest.fixture(scope="session")
def known_password():
    """The plaintext behind `password_hash`."""
    return KNOWN_PASSWORD


@pytest.fixture(scope="session")
def password_hash():
    """A real bcrypt hash of KNOWN_PASSWORD, computed once (12 rounds is slow)."""
    from meshbee_core.security import get_password_hash

    return get_password_hash(KNOWN_PASSWORD)


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
    (CHECK constraint built from meshbee_core.limits).
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
def make_lettura(db):
    """Insert a reading for an arnia at a given time."""
    def _make(arnia, timestamp=None, temperatura=None, umidita=None, peso=None,
              batteria=None):
        db.execute(
            """
            INSERT INTO letture
                (id_arnia, id_nodo, timestamp, temperatura, umidita, peso, batteria)
            VALUES (%s, %s, COALESCE(%s, CURRENT_TIMESTAMP), %s, %s, %s, %s)
            RETURNING *
            """,
            (arnia["id_arnia"], arnia["id_nodo"], timestamp, temperatura, umidita, peso,
             batteria),
        )
        return dict(db.fetchone())

    return _make


@pytest.fixture
def make_attivita(db):
    """Insert an activity log row for an arnia, optionally authored by a user."""
    def _make(arnia, utente=None, tipo_attivita="ispezione", descrizione=None, timestamp=None):
        db.execute(
            """
            INSERT INTO log_attivita (id_utente, id_arnia, timestamp, tipo_attivita, descrizione)
            VALUES (%s, %s, COALESCE(%s, CURRENT_TIMESTAMP), %s, %s)
            RETURNING *
            """,
            (
                utente["id_utente"] if utente else None,
                arnia["id_arnia"],
                timestamp,
                tipo_attivita,
                descrizione,
            ),
        )
        return dict(db.fetchone())

    return _make


@pytest.fixture
def client(use_db):
    """
    A TestClient whose requests run inside the rolled-back test transaction.

    Deliberately not used as a context manager: entering one runs the app
    lifespan, which would call init_db_pool() and open a real pool against the
    *dev* database. `use_db` is installed on both modules because a request can
    reach the database through main's own queries and through the auth helpers
    (`check_user_arnia_access`, `authenticate_user`) it calls.
    """
    from api import auth
    from api import main

    use_db(main)
    use_db(auth)
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()


@pytest.fixture
def as_user(client):
    """
    Authenticate subsequent requests as the given user row.

    Only `get_current_active_user` is overridden, so `get_current_admin_user`
    still runs for real on admin endpoints — the role gate is genuinely
    exercised rather than bypassed.
    """
    from api import main
    from api.auth import get_current_active_user

    def _as(user):
        main.app.dependency_overrides[get_current_active_user] = lambda: user
        return client

    return _as


@pytest.fixture
def utente_con_arnia(make_utente, make_arnia, grant_access):
    """A user, an arnia, and an active association at the given permission level."""
    def _make(permessi="read", ruolo="user"):
        utente = make_utente(ruolo=ruolo)
        arnia = make_arnia()
        grant_access(utente["id_utente"], arnia["id_arnia"], permessi)
        return utente, arnia

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
