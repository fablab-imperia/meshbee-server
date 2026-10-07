"""Shared fixtures for the API test-suite."""

import os
from contextlib import contextmanager

import psycopg2
import pytest
from psycopg2.extras import RealDictCursor
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.pool import NullPool
from sqlmodel import Session

from api.config import Settings, get_settings
from meshbee_core.config import CoreSettings, get_core_settings

# Connection to the throwaway database defined as `postgres-test` in
# docker-compose.yml. Defaults match that service, so nothing needs configuring
# locally; CI can point them elsewhere.
TEST_DB_PARAMS = {
    "host": os.getenv("TEST_DB_HOST", "postgres-test"),
    "port": int(os.getenv("TEST_DB_PORT", "5432")),
    "dbname": os.getenv("TEST_DB_NAME", "beehive_test"),
    "user": os.getenv("TEST_DB_USER", "beehive_user"),
    "password": os.getenv("TEST_DB_PASSWORD", "test"),
}
# The same connection as a SQLAlchemy URL, for Alembic.
TEST_DB_URL = URL.create(
    "postgresql",
    username=TEST_DB_PARAMS["user"],
    password=TEST_DB_PARAMS["password"],
    host=TEST_DB_PARAMS["host"],
    port=TEST_DB_PARAMS["port"],
    database=TEST_DB_PARAMS["dbname"],
).render_as_string(hide_password=False)


@pytest.fixture
def anyio_backend():
    """
    Run `@pytest.mark.anyio` tests on asyncio.

    The anyio pytest plugin ships with fastapi, so async dependencies can be
    awaited directly without pulling in pytest-asyncio.
    """
    return "asyncio"


# The only settings without a default: every instance needs them. CoreSettings
# requires just the database password; the API adds the JWT signing key.
CORE_REQUIRED_ENV = {"DB_PASSWORD": "test-db-password"}
REQUIRED_ENV = {**CORE_REQUIRED_ENV, "JWT_SECRET_KEY": "test-jwt-secret"}


@pytest.fixture(autouse=True)
def isolated_settings_env(monkeypatch):
    """
    Give every test a pristine environment and an empty settings cache.

    The api container is started by docker-compose with DB_HOST=postgres,
    DB_PASSWORD, JWT_SECRET_KEY... already exported, so without this the tests
    would assert against the compose values instead of the declared defaults.
    Both `get_settings` helpers are lru_cached, so the caches are dropped on
    both sides of the test to keep results independent of execution order.

    `Settings` subclasses `CoreSettings`, so its model_fields is the superset
    and stripping it covers the database variables too.
    """
    for field_name in Settings.model_fields:
        monkeypatch.delenv(field_name, raising=False)
    get_settings.cache_clear()
    get_core_settings.cache_clear()
    yield
    get_settings.cache_clear()
    get_core_settings.cache_clear()


@pytest.fixture
def required_env(monkeypatch):
    """Export only the settings that have no default."""
    for name, value in REQUIRED_ENV.items():
        monkeypatch.setenv(name, value)
    return dict(REQUIRED_ENV)


@pytest.fixture
def build_settings():
    """
    Build a Settings instance from explicit keyword arguments.

    `_env_file=None` disables the dotenv source: the result must not depend on
    whether a `.env` file happens to sit in the current working directory.
    """

    def _build(**overrides):
        return Settings(_env_file=None, **{**REQUIRED_ENV, **overrides})

    return _build


@pytest.fixture
def build_core_settings():
    """Build a CoreSettings instance — the database half, without the API extras."""

    def _build(**overrides):
        return CoreSettings(_env_file=None, **{**CORE_REQUIRED_ENV, **overrides})

    return _build


class FakeResult:
    """What `FakeSession.exec` returns: hands out the session's canned rows."""

    def __init__(self, session):
        self.session = session

    def first(self):
        return self.session.next_row()

    one = first

    def all(self):
        rows, self.session.rows = self.session.rows, []
        return rows


class FakeSession:
    """
    Stand-in for the SQLModel session yielded by `meshbee_core.db.get_session`.

    Only the surface the repositories use is implemented. Every `exec` and `get`
    is recorded in `queries` and answered from `rows`, in order — so a function
    running two reads gets `rows[0]` then `rows[1]`, and None once they run out
    ("no row found"). Objects passed to `add` land in `added`: that is the
    INSERT a unit test can inspect without a database.
    """

    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.queries = []
        self.added = []

    def next_row(self):
        return self.rows.pop(0) if self.rows else None

    def exec(self, statement):
        self.queries.append(statement)
        return FakeResult(self)

    def get(self, model, key):
        self.queries.append(("get", model, key))
        return self.next_row()

    def add(self, obj):
        self.added.append(obj)

    def delete(self, obj):
        self.queries.append(("delete", obj))

    def flush(self):
        pass


@pytest.fixture
def fake_session():
    """
    A bare FakeSession to hand to a repository or service function.

    Those take the session as an argument rather than opening one, so unlike
    the entry points they need no patching — just something to pass in.
    """

    def _make(rows=None):
        return FakeSession(rows)

    return _make


@pytest.fixture
def fake_db(monkeypatch):
    """
    Replace `get_session` in the module under test with an in-memory fake.

    Patching targets the *importing* module (`auth`, `main`), not
    `meshbee_core.db`, because both do `from meshbee_core.db import
    get_session` and hold their own reference. The session then flows on into
    the repository and service functions they call, so this one seam still
    covers the whole request. Pass `error=` to simulate the database being
    unreachable.

        session = fake_db(auth, rows=["admin"])
        assert session.queries == []
    """

    def _install(module, rows=None, error=None):
        session = FakeSession(rows)

        @contextmanager
        def _fake_get_session():
            if error is not None:
                raise error
            yield session

        monkeypatch.setattr(module, "get_session", _fake_get_session)
        return session

    return _install


# ============================================
# Real-database fixtures (integration tests)
# ============================================


@pytest.fixture(scope="session")
def test_schema():
    """
    Rebuild the test database from the migration chain, once per pytest run.

    Dropping the schema and running every revision from scratch, rather than
    relying on the container being fresh, means the flush happens on every run,
    identically on a long-running local stack and on a throwaway CI container.

    Building it with `upgrade head` — the path a fresh install takes — also
    keeps the migrations honest: a revision that fails, or that never made it
    into the chain, fails the suite here. That the result matches
    `meshbee_core.models` is `tests/integration/test_migrations.py`'s job.
    """
    from meshbee_core.migrations import upgrade

    try:
        connection = psycopg2.connect(**TEST_DB_PARAMS)
    except psycopg2.OperationalError as exc:
        raise RuntimeError(
            f"Test database unreachable at {TEST_DB_PARAMS['host']}:{TEST_DB_PARAMS['port']} "
            f"({exc.__class__.__name__}). Start it with:\n"
            "    docker-compose --profile test up -d postgres-test\n"
            'Or run the DB-less tests only:  pytest -m "not integration"'
        ) from exc

    connection.autocommit = True
    with connection, connection.cursor() as cursor:
        cursor.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    connection.close()

    upgrade(TEST_DB_URL)


@pytest.fixture(scope="session")
def test_engine(test_schema):
    engine = create_engine(TEST_DB_URL, poolclass=NullPool)
    yield engine
    engine.dispose()


@pytest.fixture
def db_connection(test_engine):
    """
    One connection, inside a transaction that is rolled back when the test ends.

    Isolation without re-seeding: every test sees the empty schema, writes what
    it needs, and leaves nothing behind. Both `db` and `session` run on it, so
    rows one writes are visible to the other.
    """
    connection = test_engine.connect()
    transaction = connection.begin()
    try:
        yield connection
    finally:
        transaction.rollback()
        connection.close()


@pytest.fixture
def db(db_connection):
    """
    A raw RealDictCursor on the test transaction, for setup and assertions.

    Tests state their fixtures and expectations in SQL on purpose: it checks
    the code under test against the database, not against itself.
    """
    cursor = db_connection.connection.dbapi_connection.cursor(
        cursor_factory=RealDictCursor
    )
    try:
        yield cursor
    finally:
        cursor.close()


def savepoint_session(connection) -> Session:
    """
    A session inside the test transaction, using SAVEPOINTs for its own.

    Its commit releases a savepoint and its rollback returns to one, so the
    code under test behaves as in production — a failed block undoes only its
    own work — while the outer transaction still discards everything.
    """
    return Session(
        bind=connection,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
    )


@pytest.fixture
def session(db_connection):
    """A session to pass to repository and service functions directly."""
    session = savepoint_session(db_connection)
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def use_db(monkeypatch, db_connection, db):
    """
    Point the module under test at the rolled-back test transaction.

    Same seam as `fake_db`, real SQL underneath: `use_db(auth)` makes
    `auth.authenticate_user` run its queries against postgres-test. Each
    `with get_session()` block gets a fresh session, as in production, so no
    identity map carries stale rows from one block to the next.
    """

    def _install(module):
        @contextmanager
        def _test_get_session():
            session = savepoint_session(db_connection)
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        monkeypatch.setattr(module, "get_session", _test_get_session)
        return db

    return _install
