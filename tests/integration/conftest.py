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

    Like `create_utente`, it also gives the user their default apiary, whose id
    the returned row carries as `id_apiario_predefinito`.
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
        utente = dict(db.fetchone())
        db.execute(
            """
            INSERT INTO apiari (nome_apiario, id_utente_proprietario, predefinito)
            VALUES ('Default', %s, true)
            RETURNING id_apiario
            """,
            (utente["id_utente"],),
        )
        utente["id_apiario_predefinito"] = db.fetchone()["id_apiario"]
        return utente

    return _make


@pytest.fixture
def make_arnia(db):
    """
    Insert an `arnie` row (and its `nodi` row, once), and return the arnia.

    With `apiario` (a `make_apiario` or `make_utente` row), the hive is in it,
    and its node — one per owner unless named — belongs to that apiary's
    owner, as the services keep it. Without, both are unassigned.
    """
    counter = iter(range(1, 1000))

    def _make(id_nodo=None, apiario=None):
        id_apiario = owner = None
        if apiario is not None:
            id_apiario = apiario.get(
                "id_apiario", apiario.get("id_apiario_predefinito")
            )
            owner = apiario.get("id_utente_proprietario", apiario.get("id_utente"))
        id_nodo = id_nodo or (f"NODE-U{owner}" if owner else "NODE-TEST")
        db.execute(
            "INSERT INTO nodi (id_nodo, nome_nodo, id_proprietario) VALUES (%s, %s, %s)"
            " ON CONFLICT DO NOTHING",
            (id_nodo, "Nodo di test", owner),
        )
        db.execute(
            """
            INSERT INTO arnie (id_nodo, id_sensore_fisico, nome_arnia, id_apiario)
            VALUES (%s, %s, %s, %s)
            RETURNING *
            """,
            (id_nodo, f"SENSOR{next(counter):02d}", "Arnia di test", id_apiario),
        )
        return dict(db.fetchone())

    return _make


@pytest.fixture
def make_apiario(db):
    """Insert a non-default apiary owned by a `make_utente` row, and return it."""
    counter = iter(range(1, 1000))

    def _make(proprietario, nome_apiario=None):
        db.execute(
            """
            INSERT INTO apiari (nome_apiario, id_utente_proprietario)
            VALUES (%s, %s)
            RETURNING *
            """,
            (
                nome_apiario or f"Apiario {next(counter):02d}",
                proprietario["id_utente"],
            ),
        )
        return dict(db.fetchone())

    return _make


@pytest.fixture
def make_lettura(db):
    """Insert a reading for an arnia at a given time."""

    def _make(
        arnia, timestamp=None, temperatura=None, umidita=None, peso=None, batteria=None
    ):
        db.execute(
            """
            INSERT INTO letture
                (id_arnia, id_nodo, timestamp, temperatura, umidita, peso, batteria)
            VALUES (%s, %s, COALESCE(%s, CURRENT_TIMESTAMP), %s, %s, %s, %s)
            RETURNING *
            """,
            (
                arnia["id_arnia"],
                arnia["id_nodo"],
                timestamp,
                temperatura,
                umidita,
                peso,
                batteria,
            ),
        )
        return dict(db.fetchone())

    return _make


@pytest.fixture
def make_attivita(db):
    """Insert an activity log row for an arnia, optionally authored by a user."""

    def _make(
        arnia, utente=None, tipo_attivita="ispezione", descrizione=None, timestamp=None
    ):
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
    from api import auth, main

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
def utente_con_arnia(make_utente, make_arnia, share):
    """
    A user and an arnia they reach as `ruolo`: "owner" (it is in their default
    apiary), or a role shared on its owner's default apiary.
    """

    def _make(ruolo="owner", ruolo_utente="user"):
        utente = make_utente(ruolo=ruolo_utente)
        if ruolo == "owner":
            return utente, make_arnia(apiario=utente)
        owner = make_utente()
        arnia = make_arnia(apiario=owner)
        share(utente["id_utente"], arnia["id_apiario"], ruolo)
        return utente, arnia

    return _make


@pytest.fixture
def share(db):
    """Share an apiary with a user as the given role."""

    def _share(id_utente, id_apiario, ruolo="viewer"):
        db.execute(
            """
            INSERT INTO utenti_apiari (id_utente, id_apiario, ruolo)
            VALUES (%s, %s, %s)
            RETURNING *
            """,
            (id_utente, id_apiario, ruolo),
        )
        return dict(db.fetchone())

    return _share
